"""
Master OSS → client-facing PDF, via ReportLab.

Built natively rather than through the browser's print dialog for one reason:
pagination. A browser can avoid breaking inside a row, but it cannot label a
day that continues onto the next page, and its output changes with whoever's
printer settings happen to be. A document that goes to a client has to look
the same every time.

The look is the paper spec of 2026-09-07 (brand.py "Paper", and
claude/ADI_Print_Design_Spec_2026-09-07.md): Barlow, a light document header
— eyebrow, condensed title, a midnight rule — column headers as tracked
mineral capitals with a hairline, section bands on warm white, hairlines
between rows, gold condensed numerals for the codes. No navy band, no zebra,
no filled header rows: the page is paper, the ink is the information.

Reads from oss_export.build_master_items, so it cannot disagree with the
Master tab or the XLSX.
"""
import os
from datetime import datetime

from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

import brand
import paper_fonts
from oss_export import (build_master_items, count_label, department_style,
                        dept_label, group_by_day, group_by_department,
                        master_label, time_range_text)


MIDNIGHT = colors.HexColor(brand.MIDNIGHT)
INK = colors.HexColor(brand.INK)
STRIPE = colors.HexColor(brand.STRIPE)
MINERAL = colors.HexColor(brand.MINERAL)
LINE = colors.HexColor(brand.LINE)
CYAN_INK = colors.HexColor(brand.CYAN_INK)
GOLD_INK = colors.HexColor(brand.GOLD_INK)

PT = brand.PAPER_PT_BODY
LEAD = PT * brand.PAPER_LEADING
HAIR = brand.PAPER_HAIRLINE_PT

MARGIN_TOP = brand.PAPER_MARGIN_TOP_MM * mm
MARGIN_SIDE = brand.PAPER_MARGIN_SIDE_MM * mm
MARGIN_BOTTOM = brand.PAPER_MARGIN_BOTTOM_MM * mm
CONTENT_W = letter[0] - 2 * MARGIN_SIDE          # 7.476in
# The running header on body pages: one line of small capitals and a
# hairline. The frame starts below it.
RUNNING_HEAD_H = 7 * mm
FOOTER_H = 6 * mm

# Content split so the schedule reads left-to-right as
# when → who → what → how much → anything else. Proportions are those of
# the 6.5in layout, scaled to the wider paper margins; the code column is
# a fixed 0.36in because two condensed capitals at 10.5pt measure ~0.2in.
def _scaled(widths_in):
    fixed = 0.36
    rest = CONTENT_W / inch - fixed
    total = sum(widths_in)
    return [fixed * inch] + [w / total * rest * inch for w in widths_in]

COL_WIDTHS = _scaled([0.62, 0.70, 2.55, 0.85, 1.48])
COLUMNS = ["", "Time", "Dept", "Item", "Detail", "Notes"]

# A day header stranded at the foot of a page looks like a mistake, so it is
# bound to this many following rows and moves with them.
ORPHAN_GUARD_ROWS = 3


def _styles():
    f = paper_fonts.register()
    body = ParagraphStyle(
        "body", fontName=f["text"], fontSize=PT, leading=LEAD, textColor=INK)
    return {
        "fonts": f,
        "body": body,
        "cell": ParagraphStyle("cell", parent=body),
        "cell_medium": ParagraphStyle("cell_medium", parent=body,
                                      fontName=f["text_medium"]),
        "cell_dim": ParagraphStyle("cell_dim", parent=body, textColor=MINERAL),
        # Indent lives in the STYLE, so a crew name is never interpolated into
        # ReportLab markup. Names are user data and can contain & or < — the
        # PDF is the only export that parses its cell contents as XML.
        "cell_name": ParagraphStyle("cell_name", parent=body, leftIndent=8),
        # Column header: tracked mineral capitals, no fill.
        "head": ParagraphStyle(
            "head", parent=body, fontName=f["text_medium"],
            fontSize=brand.PAPER_PT_SMALL, leading=brand.PAPER_PT_SMALL * 1.3,
            textColor=MINERAL),
        # Section band: condensed bold capitals on warm white.
        "band": ParagraphStyle(
            "band", parent=body, fontName=f["display_bold"],
            fontSize=brand.PAPER_PT_GROUP, leading=brand.PAPER_PT_GROUP * 1.2,
            textColor=MIDNIGHT),
        # The two-letter row code: condensed bold gold, like the item numbers
        # on the Larry list.
        "code": ParagraphStyle(
            "code", parent=body, fontName=f["display_bold"],
            fontSize=PT * 1.15, leading=LEAD, textColor=GOLD_INK,
            alignment=TA_RIGHT),
        "label": ParagraphStyle(
            "label", parent=body, fontName=f["text_medium"],
            fontSize=brand.PAPER_PT_SMALL, leading=brand.PAPER_PT_SMALL * 1.3,
            textColor=MINERAL),
        "key_code": ParagraphStyle(
            "key_code", parent=body, fontName=f["text_bold"],
            fontSize=brand.PAPER_PT_SMALL, textColor=colors.white,
            alignment=1),
    }


def _caps(text):
    return (text or "").upper()


class _Tracked(Flowable):
    """One line of letterspaced capitals — the eyebrow voice — as a
    flowable, because Paragraph has no tracking and the cover header is
    laid out by the frame, not drawn on the canvas."""

    def __init__(self, text, font, size, color, track=0.12):
        Flowable.__init__(self)
        self.text, self.font, self.size = text.upper(), font, size
        self.color, self.track = color, track

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = self.size * 1.3
        return self.width, self.height

    def draw(self):
        c = self.canv
        t = c.beginText(0, self.size * 0.3)
        t.setFont(self.font, self.size)
        t.setFillColor(self.color)
        t.setCharSpace(self.size * self.track)
        t.textOut(self.text)
        t.setCharSpace(0)
        c.drawText(t)


def _mark_continued(part):
    """Append 'continued' to a split table's repeated day-header cell.

    This is the thing browser print-to-PDF cannot do: when a day runs past the
    foot of a page, the reader needs to know which day they are still in
    without flipping back.
    """
    try:
        row = part._cellvalues[0]
        cell = row[0]
        # ReportLab wraps flowable cell contents in an _ExpandedCellTuple, so
        # the Paragraph is one level in — reading `cell.text` gets you nothing.
        wrapped = isinstance(cell, (list, tuple))
        inner = cell[0] if wrapped and cell else cell
        text = getattr(inner, "text", None)
        if not text or "continued" in text:
            return
        marked = Paragraph(text + "  ·  continued", inner.style)
        # Replace the whole row rather than mutating in place: the repeated
        # header row is the SAME list object the preceding part holds, so an
        # in-place edit would retroactively label the page we came from.
        new_row = list(row)
        new_row[0] = type(cell)([marked]) if wrapped else marked
        part._cellvalues[0] = new_row
    except Exception:
        pass            # a labelling nicety must never break the document


class _DayTable(Table):
    """One day's rows. Rows 0–1 are the day label and column header, and
    repeat on continuation.

    Also refuses a split that would strand the day header with only a row or
    two at the foot of a page. Returning [] tells the layout engine "not
    here", so the whole day moves to the next page and splits somewhere
    sensible. The refusal happens at most once per table, so it cannot loop.
    """

    def split(self, availWidth, availHeight):
        parts = Table.split(self, availWidth, availHeight)
        if len(parts) == 2 and not getattr(self, "_refused_split", False):
            kept = len(getattr(parts[0], "_cellvalues", []) or [])
            if kept < 2 + ORPHAN_GUARD_ROWS:
                self._refused_split = True
                return []
        for part in parts[1:]:
            _mark_continued(part)
            # A continuation part must never refuse a split of its own.
            # Table.split() returns fresh objects, so without this each part
            # gets its own refusal — and a part that refuses at the TOP of an
            # empty frame has nowhere left to go, which ReportLab reports as
            # LayoutError rather than falling back. That is how MCDC26 died on
            # page 30. The orphan guard is a nicety; never let it hard-fail.
            part._refused_split = True
        return parts


class _Doc(BaseDocTemplate):
    """Letter portrait. The cover carries the document header (eyebrow,
    title, meta, rule); every page after carries a one-line running head.
    Both carry the footer."""

    def __init__(self, buf, show, agency, logo_file, doc_kind="Master Schedule",
                 **kw):
        self.show, self.agency, self.logo_file = show, agency, logo_file
        # What this document IS, in the running head on every page and in
        # the PDF's own title metadata (note 9). The cover says it once; the
        # running head is what a reader sees on page 14 of a section export,
        # and page 14 is exactly where somebody stops remembering which file
        # they opened.
        self.doc_kind = doc_kind
        self.fonts = paper_fonts.register()
        BaseDocTemplate.__init__(
            self, buf, pagesize=letter,
            leftMargin=MARGIN_SIDE, rightMargin=MARGIN_SIDE,
            topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM + FOOTER_H,
            title=f"{show.code or show.name or 'Show'} — {doc_kind}",
            author=getattr(agency, "name", None) or brand.SIGNATURE_FORMAL,
            **kw)
        cover = Frame(self.leftMargin, self.bottomMargin, self.width,
                      self.height, id="cover", leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        body = Frame(self.leftMargin, self.bottomMargin, self.width,
                     self.height - RUNNING_HEAD_H, id="body",
                     leftPadding=0, rightPadding=0, topPadding=0,
                     bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[cover], onPage=self._cover_chrome),
            PageTemplate(id="body", frames=[body], onPage=self._chrome),
        ])

    # ── chrome ──
    def _eyebrow_text(self):
        code = (self.show.code or self.show.name or "").strip()
        return "ADI WORKFLOW" + (f"  ·  {code.upper()}" if code else "")

    def _tracked(self, canvas, x, y, text, font, size, color, align="left",
                 track=0.12):
        """Uppercase, letterspaced small capitals — the eyebrow voice.
        Character spacing lives on a text object, not the canvas."""
        space = size * track
        if align == "right":
            x -= canvas.stringWidth(text, font, size) + space * (len(text) - 1)
        t = canvas.beginText(x, y)
        t.setFont(font, size)
        t.setFillColor(color)
        t.setCharSpace(space)
        t.textOut(text)
        t.setCharSpace(0)          # Tc is graphics state; never let it leak
        canvas.drawText(t)

    def _footer(self, canvas, doc):
        f = self.fonts
        y = MARGIN_BOTTOM * 0.75
        name = getattr(self.agency, "name", None) or brand.SIGNATURE_FORMAL
        bits = [name, self.show.name or "", self.doc_kind, str(doc.page)]
        canvas.setFont(f["text"], brand.PAPER_PT_SMALL)
        canvas.setFillColor(MINERAL)
        canvas.drawRightString(self.leftMargin + self.width, y,
                               "  ·  ".join(b for b in bits if b))
        # The legend for the code column, on every page. A two-letter code
        # is only useful if the key travels with the sheet — these get
        # photocopied and handed out a page at a time, so a key on page one
        # would be lost.
        canvas.drawString(self.leftMargin, y, brand.KIND_LEGEND)

    def _chrome(self, canvas, doc):
        """Body pages: eyebrow left, document kind right, hairline."""
        canvas.saveState()
        f = self.fonts
        top = letter[1] - MARGIN_TOP
        y = top - brand.PAPER_PT_SMALL
        self._tracked(canvas, self.leftMargin, y, self._eyebrow_text(),
                      f["display"], brand.PAPER_PT_SMALL, CYAN_INK)
        self._tracked(canvas, self.leftMargin + self.width, y,
                      self.doc_kind.upper(), f["display"],
                      brand.PAPER_PT_SMALL, MINERAL, align="right")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(HAIR)
        rule_y = top - RUNNING_HEAD_H + 2.5 * mm
        canvas.line(self.leftMargin, rule_y, self.leftMargin + self.width, rule_y)
        self._footer(canvas, doc)
        canvas.restoreState()

    def _cover_chrome(self, canvas, doc):
        canvas.saveState()
        self._footer(canvas, doc)
        canvas.restoreState()


# ── cover ──
def _doc_header(doc_kind, show, master_items, st, logo_file=None):
    """The document header, as a table so it flows: eyebrow + title on the
    left, dates and counts on the right, a midnight rule beneath."""
    f = st["fonts"]
    days = [d for d, _ in group_by_day(master_items) if d and d.date]
    span = ""
    if days:
        first, last = days[0].date, days[-1].date
        span = (brand.fmt_date(first, "full") if first == last else
                f"{brand.fmt_date(first)} – {brand.fmt_date(last, 'full')}")
    n_days = len(days)
    counts = " · ".join(b for b in [
        f"{n_days} day{'s' if n_days != 1 else ''}" if n_days else "",
        f"{len(master_items)} item{'s' if len(master_items) != 1 else ''}",
    ] if b)

    title = ParagraphStyle(
        "title", fontName=f["display_bold"], fontSize=brand.PAPER_PT_TITLE,
        leading=brand.PAPER_PT_TITLE * 1.0, textColor=MIDNIGHT,
        spaceBefore=2)
    meta_b = ParagraphStyle(
        "meta_b", fontName=f["text_semibold"], fontSize=brand.PAPER_PT_EYEBROW,
        leading=brand.PAPER_PT_EYEBROW * 1.35, textColor=INK,
        alignment=TA_RIGHT)
    meta = ParagraphStyle(
        "meta", parent=meta_b, fontName=f["text"], textColor=MINERAL)

    # The eyebrow: letterspaced capitals. _Tracked takes plain text, so
    # the show name (user data) is never parsed as markup.
    eb_text = "ADI WORKFLOW"
    show_name = (show.name or "").strip()
    if show_name:
        eb_text += "  ·  " + show_name
    left = [_Tracked(eb_text, f["display"], brand.PAPER_PT_EYEBROW, CYAN_INK),
            Paragraph(doc_kind, title)]
    right = [Paragraph(escape(span) or "&nbsp;", meta_b),
             Paragraph(escape(counts), meta)]

    logo = None
    if logo_file and os.path.exists(logo_file):
        try:
            from reportlab.platypus import Image
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(logo_file).getSize()
            w = 1.0 * inch
            logo = Image(logo_file, width=w, height=ih * w / iw)
            logo.hAlign = "RIGHT"
        except Exception:
            logo = None        # never fail a document over artwork

    right_cell = ([logo, Spacer(1, 3)] if logo else []) + right
    t = Table([[left, right_cell]],
              colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), brand.PAPER_RULE_PT, MIDNIGHT),
    ]))
    return [t, Spacer(1, 8)]


def _fact_table(rows, st):
    """The house pattern: a two-column table, never a bullet list. Labels
    are the column-header voice; values are body."""
    data = [[Paragraph(_caps(k), st["label"]),
             Paragraph(escape(v) if v else "—", st["cell"])] for k, v in rows]
    t = Table(data, colWidths=[1.45 * inch, CONTENT_W - 1.45 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -1), HAIR, LINE),
    ]))
    return t


def _band(text, st, widths=None):
    """A section band: condensed capitals on warm white, hairline below."""
    t = Table([[Paragraph(_caps(text), st["band"])]],
              colWidths=[CONTENT_W] if widths is None else widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), STRIPE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LINEBELOW", (0, 0), (-1, -1), HAIR, LINE),
    ]))
    return t


def _cover(show, agency, master_items, st, sections=None, logo_file=None):
    days = [d for d, _ in group_by_day(master_items) if d and d.date]
    span = ""
    if days:
        first, last = days[0].date, days[-1].date
        span = (brand.fmt_date(first, "full") if first == last else
                f"{brand.fmt_date(first)} – {brand.fmt_date(last, 'full')}")

    # Note 9 — a section PDF must not be mistakable for the master. It
    # carries the same header and the same key, so the TITLE is what has to
    # say which document this is. Somebody holding a Dock-only schedule and
    # believing it is the whole show is exactly the failure to design out.
    doc_kind = "Master Schedule" if not sections else "Section Schedule"
    flow = _doc_header(doc_kind, show, master_items, st, logo_file=logo_file)

    flow.append(_fact_table([
        ("Client", show.client.name if show.client else None),
        ("Venue", show.venue.name if show.venue else None),
        ("Room", show.room_name),
        ("Dates", span),
        ("Sections", ", ".join(sections) if sections else None),
        ("Schedule days", str(len(days)) if days else "0"),
        ("Total items", str(len(master_items))),
        ("Prepared by", getattr(agency, "name", None) or brand.SIGNATURE_FORMAL),
        ("Issued", datetime.now().strftime("%-d %b %Y, %H:%M")),
    ], st))

    # Department key. Colour is a convenience; the short text label is what
    # survives the black-and-white printer these documents meet constantly.
    flow += [Spacer(1, 14), _band("Department key", st)]
    cells, style = [], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), HAIR, LINE)]
    for i, (dept, _rows) in enumerate(group_by_department(master_items)):
        ds = department_style(dept)
        cells.append([Paragraph(escape(ds["short"] or dept[:5]), st["key_code"]),
                      Paragraph(escape(dept), st["cell"])])
        style.append(("BACKGROUND", (0, i), (0, i),
                      colors.HexColor("#" + ds["hex"])))
    if cells:
        key = Table(cells, colWidths=[0.62 * inch, 2.4 * inch], hAlign="LEFT")
        key.setStyle(TableStyle(style))
        flow += [Spacer(1, 4), key]
    return flow + [PageBreak()]


def _section_heading(text, st):
    return _band(text, st)


def _at_a_glance(master_items, st):
    """The week in one view, so a client sees the shape before the detail."""
    groups = group_by_day(master_items)
    if len(groups) < 2:
        return []
    header = [Paragraph(_caps(h), st["head"])
              for h in ("Day", "Date", "First", "Last", "Items", "Departments")]
    rows, style = [header], [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ("LINEBELOW", (0, 0), (-1, -1), HAIR, LINE)]
    for i, (day, items) in enumerate(groups, start=1):
        timed = [it for it in items if it["time"]]
        depts = sorted({it["dept"] for it in items})
        rows.append([
            Paragraph(brand.fmt_date(day.date) if day and day.date
                      else "Unscheduled", st["cell_medium"]),
            Paragraph(brand.fmt_date(day.date, "short") if day and day.date
                      else "—", st["cell_dim"]),
            Paragraph(brand.fmt_time(timed[0]["time"]) if timed else "—", st["cell"]),
            Paragraph(brand.fmt_time(timed[-1]["time"]) if timed else "—", st["cell"]),
            Paragraph(str(len(items)), st["cell"]),
            Paragraph(escape(", ".join(department_style(d)["short"] or d
                                       for d in depts)), st["cell_dim"]),
        ])

    t = Table(rows, colWidths=_glance_widths(), repeatRows=1)
    t.setStyle(TableStyle(style))
    return [_section_heading("At a glance", st), Spacer(1, 2), t, PageBreak()]


def _glance_widths():
    parts = [1.25, 0.62, 0.62, 0.62, 0.55, 2.84]
    total = sum(parts)
    return [p / total * CONTENT_W for p in parts]


def _row_style_base():
    return [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        # Row 0: the section band.
        ("BACKGROUND", (0, 0), (-1, 0), STRIPE),
        ("SPAN", (0, 0), (-1, 0)),
        ("TOPPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5),
        ("LINEBELOW", (0, 0), (-1, 0), HAIR, LINE),
        # Row 1: the column header — no fill, hairline beneath.
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 2),
        ("LINEBELOW", (0, 1), (-1, 1), HAIR, LINE),
        # Every row after: a hairline.
        ("LINEBELOW", (0, 2), (-1, -1), HAIR, LINE),
        ("RIGHTPADDING", (0, 0), (0, -1), 3),
    ]


def _day_rows(day, items, st):
    """One day as a single table: header row 0, then one row per item.

    Keeping the day header inside the table (rather than as a separate
    paragraph) is what lets repeatRows carry it onto a continuation page.
    """
    label = brand.fmt_date(day.date, "full") if day and day.date else "Unscheduled"
    header = [Paragraph(escape(label), st["band"]), "", "", "", "", ""]
    cols = [Paragraph(_caps(c), st["head"]) for c in COLUMNS]
    rows = [header, cols]
    style = _row_style_base()
    i = 2
    for n, item in enumerate(items):
        ds = department_style(item["dept"])
        kind = item.get("kind") or "act"
        rows.append([
            Paragraph(brand.row_code(kind, item.get("dept")), st["code"]),
            Paragraph(time_range_text(item, brand.fmt_time) or "—", st["cell_medium"]),
            Paragraph(f"<b>{escape(ds['short'] or item['dept'][:5])}</b>", st["cell"]),
            Paragraph(master_label(item), st["cell"]),
            Paragraph(_detail(item), st["cell_dim"]),
            Paragraph(item["notes"] or "", st["cell_dim"]),
        ])
        style.append(("TEXTCOLOR", (2, i), (2, i), colors.HexColor("#" + ds["hex"])))
        # No zebra: it alternated by POSITION and carried no information. The
        # fill carries KIND — three tiers, from brand.KIND_FILL — while the
        # code column carries the seven-way distinction.
        fill = brand.KIND_FILL.get(kind)
        if fill:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(fill)))
        i += 1

        # Note 5 — one name per row beneath the headcount, matching the show
        # book's call sheet. Before this the PDF printed a comma list while the
        # XLSX printed a headcount: the two exports disagreed about the same
        # event, which is the drift oss_export exists to prevent.
        for who in item.get("crew_names") or []:
            rows.append([
                "", "", "", Paragraph(escape(who or ""), st["cell_name"]),
                "", "",
            ])
            i += 1

        # LOCAL LABOR. These used to be in `crew_names`, so "14 × Rigger"
        # printed as one more indented name with an empty code column —
        # identical on the page to one human. They carry LL and the
        # local-labor fill, and the headcount goes in the detail column
        # because the number is the whole point of the line.
        for line in item.get("local_lines") or []:
            rows.append([
                Paragraph(brand.KIND_CODE.get("local", ""), st["code"]),
                "", "",
                Paragraph(escape(line.get("label") or ""), st["cell_name"]),
                Paragraph(count_label("Crew", line.get("qty")) or "", st["cell_dim"]),
                "",
            ])
            local_fill = brand.KIND_FILL.get("local")
            if local_fill:
                style.append(("BACKGROUND", (0, i), (-1, i),
                              colors.HexColor(local_fill)))
            i += 1
    return rows, style


def _detail(item):
    bits = []
    if item.get("count") is not None:
        bits.append(count_label(item["dept"], item["count"])
                    or f"×{item['count']}")
    if item.get("duration_hrs") is not None:
        bits.append(f"{item['duration_hrs']:g} hr")
    return " · ".join(bits)


def _day_sections(master_items, st):
    flow = [_section_heading("Schedule by day", st), Spacer(1, 6)]
    for day, items in group_by_day(master_items):
        rows, style = _day_rows(day, items, st)
        # One table per day. repeatRows=2 carries the day label AND the column
        # header onto continuation pages; _DayTable refuses a split that would
        # leave an orphaned header. A short day is additionally wrapped so it
        # is never broken at all.
        table = _DayTable(rows, colWidths=COL_WIDTHS, repeatRows=2)
        table.setStyle(TableStyle(style))
        flow.append(KeepTogether(table) if len(items) <= ORPHAN_GUARD_ROWS
                    else table)
        flow.append(Spacer(1, 10))
    return flow


def _department_sections(master_items, st):
    """Each department's own schedule, so a head can find just their lines."""
    flow = [PageBreak(), _section_heading("Schedule by department", st),
            Spacer(1, 6)]
    widths = _scaled([1.20, 0.62, 2.55, 0.75, 1.08])
    for dept, items in group_by_department(master_items):
        ds = department_style(dept)
        header = [Paragraph(escape(dept), st["band"]), "", "", "", "", ""]
        cols = [Paragraph(_caps(c), st["head"])
                for c in ("", "Day", "Time", "Item", "Detail", "Notes")]
        rows = [header, cols]
        style = _row_style_base()
        # The department's colour as a rule down the left of its band —
        # the same swatch as the key on the cover, on paper that may be mono.
        style.append(("LINEBEFORE", (0, 0), (0, 0), 3,
                      colors.HexColor("#" + ds["hex"])))
        i = 2
        for item in items:
            day = item["day"]
            kind = item.get("kind") or "act"
            rows.append([
                Paragraph(brand.row_code(kind, item.get("dept")), st["code"]),
                Paragraph(brand.fmt_date(day.date) if day and day.date
                          else "Unscheduled", st["cell_medium"]),
                Paragraph(time_range_text(item, brand.fmt_time) or "—", st["cell"]),
                Paragraph(escape(master_label(item)), st["cell"]),
                Paragraph(_detail(item), st["cell_dim"]),
                Paragraph(escape(item["notes"] or ""), st["cell_dim"]),
            ])
            fill = brand.KIND_FILL.get(kind)
            if fill:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(fill)))
            i += 1
            # This is what blew up on MCDC26. The Crew department's rows put
            # every name for a call into ONE cell in a 2.55in column — 40 names
            # is a single row 263 points tall, and a table of those cannot fit
            # a 618-point frame however it is split. One name per row (note 5)
            # is both what Larry asked for and what makes this paginate at all.
            for who in item.get("crew_names") or []:
                rows.append(["", "", "",
                             Paragraph(escape(who or ""), st["cell_name"]),
                             "", ""])
                i += 1
            # Same split as the day sections: a count of a position is not a
            # name, and the Crew department section is exactly where a reader
            # goes to find out how many bodies are coming.
            for line in item.get("local_lines") or []:
                rows.append([Paragraph(brand.KIND_CODE.get("local", ""), st["code"]),
                             "", "",
                             Paragraph(escape(line.get("label") or ""),
                                       st["cell_name"]),
                             Paragraph(count_label("Crew", line.get("qty")) or "",
                                       st["cell_dim"]),
                             ""])
                local_fill = brand.KIND_FILL.get("local")
                if local_fill:
                    style.append(("BACKGROUND", (0, i), (-1, i),
                                  colors.HexColor(local_fill)))
                i += 1
        table = _DayTable(rows, colWidths=widths, repeatRows=2)
        table.setStyle(TableStyle(style))
        flow += [KeepTogether(table) if len(items) <= ORPHAN_GUARD_ROWS
                 else table, Spacer(1, 10)]
    return flow


def build_pdf(buf, show, entries, meal_services, agency=None, logo_file=None,
              departments=None):
    """Render the Master OSS into `buf`. Caller supplies the already-queried
    collections so this stays a pure presentation layer over oss_export.

    `departments` scopes the document to a subset of sections (note 9: "PDF an
    individual section — Dock, or Security — without having to PDF the whole
    thing"). It is applied to `master_items` and to NOTHING else, which is why
    it costs three lines: the cover, the department key, the at-a-glance
    table, the day sections and the department sections are every one of them
    derived from that list. Filter once and a Dock-only PDF is a genuine
    standalone document — its own header, its own key, its own day-by-day —
    rather than the master with pages torn out of it.

    Names are matched through `dept_label`, so a caller may pass either the
    stored type or the label a user sees. Three departments differ between the
    two (Hazer/Haze, House LX/House Lights, HVAC/HVAC / AC) and a section
    export that silently produced an empty PDF for one of them would be a very
    quiet way to hand somebody a blank schedule.
    """
    master_items, _hardcoded = build_master_items(show, entries, meal_services)

    sections = None
    if departments:
        wanted = {dept_label(d) for d in departments if d}
        master_items = [i for i in master_items
                        if dept_label(i.get("dept")) in wanted]
        # What was ASKED for, not what turned out to have rows. A section the
        # user picked that came back empty still belongs on the cover — the
        # reader needs to see that Security was included and had nothing in
        # it, rather than wonder whether it was left out.
        sections = sorted(wanted)

    st = _styles()

    doc = _Doc(buf, show, agency, logo_file,
               doc_kind="Section Schedule" if sections else "Master Schedule")
    # Page one uses the cover template; everything after switches to the body
    # template, which adds the running head. BaseDocTemplate decorates pages
    # through PageTemplate.onPage, not build() kwargs.
    flow = [NextPageTemplate("body")]
    flow += _cover(show, agency, master_items, st, sections=sections,
                   logo_file=logo_file)
    if master_items:
        flow += _at_a_glance(master_items, st)
        flow += _day_sections(master_items, st)
        flow += _department_sections(master_items, st)
    else:
        flow.append(Paragraph("No schedule items yet.", st["cell_dim"]))

    doc.build(flow)
    return buf

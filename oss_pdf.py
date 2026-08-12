"""
Master OSS → client-facing PDF, via ReportLab.

Built natively rather than through the browser's print dialog for one reason:
pagination. A browser can avoid breaking inside a row, but it cannot label a
day that continues onto the next page, and its output changes with whoever's
printer settings happen to be. A document that goes to a client has to look
the same every time.

Follows the ADI house geometry recovered from Larry's .docx templates (see
brand.py): US Letter portrait, 6.5in content width, navy header band, grey
eyebrow, pipe-delimited footer. Tables throughout — there is not a single
bullet list in any ADI document.

Reads from oss_export.build_master_items, so it cannot disagree with the
Master tab or the XLSX.
"""
import os
from datetime import datetime

from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

import brand
from oss_export import (build_master_items, count_label, department_style,
                        group_by_day, group_by_department, master_label,
                        time_range_text)


MIDNIGHT = colors.HexColor(brand.MIDNIGHT)
WARM_WHITE = colors.HexColor(brand.WARM_WHITE)
CYAN = colors.HexColor(brand.SIGNAL_CYAN)
MINERAL = colors.HexColor(brand.MINERAL)
HAIRLINE = colors.HexColor("#D7DCE3")
ZEBRA = colors.HexColor("#F7F6F2")   # warm-white derived, matches the screen

# 6.5in of content, split so the schedule reads left-to-right as
# when → who → what → how much → anything else.
COL_WIDTHS = [0.62 * inch, 0.70 * inch, 2.55 * inch, 0.85 * inch, 1.78 * inch]
COLUMNS = ["Time", "Dept", "Item", "Detail", "Notes"]

# A day header stranded at the foot of a page looks like a mistake, so it is
# bound to this many following rows and moves with them.
ORPHAN_GUARD_ROWS = 3


def _styles():
    body = ParagraphStyle(
        "body", fontName=brand.FONT_FALLBACK, fontSize=brand.PT_BODY,
        leading=brand.PT_BODY + 2.2, textColor=colors.HexColor("#16202E"))   # Midnight-biased, was an undocumented grey
    return {
        "body": body,
        "cell": ParagraphStyle("cell", parent=body),
        "cell_dim": ParagraphStyle("cell_dim", parent=body, textColor=MINERAL),
        # Indent lives in the STYLE, so a crew name is never interpolated into
        # ReportLab markup. Names are user data and can contain & or < — the
        # PDF is the only export that parses its cell contents as XML.
        "cell_name": ParagraphStyle("cell_name", parent=body, leftIndent=8),
        "head": ParagraphStyle(
            "head", parent=body, fontName=brand.FONT_FALLBACK + "-Bold",
            fontSize=brand.PT_SMALL, textColor=colors.white),
        "day": ParagraphStyle(
            "day", parent=body, fontName=brand.FONT_FALLBACK + "-Bold",
            fontSize=brand.PT_HEADING_3, textColor=colors.white),
    }


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
    """Letter portrait with the ADI header band and footer on every page."""

    def __init__(self, buf, show, agency, logo_file, **kw):
        self.show, self.agency, self.logo_file = show, agency, logo_file
        BaseDocTemplate.__init__(
            self, buf, pagesize=letter,
            leftMargin=brand.MARGIN_LEFT_IN * inch,
            rightMargin=brand.MARGIN_RIGHT_IN * inch,
            topMargin=(brand.MARGIN_TOP_IN + brand.LOGO_BAND_H_IN + 0.22) * inch,
            bottomMargin=brand.MARGIN_BOTTOM_IN * inch,
            title=f"{show.code or show.name or 'Show'} — Master Schedule",
            author=getattr(agency, "name", None) or brand.SIGNATURE_FORMAL,
            **kw)
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="body",
                      leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self._cover_chrome),
            PageTemplate(id="body", frames=[frame], onPage=self._chrome),
        ])

    def _band(self, canvas):
        """Full-bleed navy band with the agency mark, per the .docx header."""
        w, h = letter
        band_h = (brand.MARGIN_TOP_IN + brand.LOGO_BAND_H_IN) * inch
        canvas.setFillColor(MIDNIGHT)
        canvas.rect(0, h - band_h, w, band_h, stroke=0, fill=1)
        canvas.setStrokeColor(CYAN)          # the measured datum rule
        canvas.setLineWidth(1)
        canvas.line(self.leftMargin, h - band_h,
                    self.leftMargin + self.width, h - band_h)

        if self.logo_file and os.path.exists(self.logo_file):
            try:
                from reportlab.lib.utils import ImageReader
                img = ImageReader(self.logo_file)
                iw, ih = img.getSize()
                max_h = brand.LOGO_BAND_H_IN * inch * 0.62
                scale = min(max_h / ih, (2.2 * inch) / iw)
                canvas.drawImage(
                    img, self.leftMargin,
                    h - band_h + (band_h - ih * scale) / 2,
                    iw * scale, ih * scale, mask="auto")
            except Exception:
                pass        # never fail a document over artwork

    def _footer(self, canvas, doc):
        name = getattr(self.agency, "name", None) or brand.SIGNATURE_FORMAL
        bits = [name, self.show.name or "", "Master Schedule", str(doc.page)]
        canvas.setFont(brand.FONT_FALLBACK, brand.PT_FOOTER)
        canvas.setFillColor(MINERAL)
        canvas.drawRightString(
            self.leftMargin + self.width, brand.MARGIN_BOTTOM_IN * inch * 0.55,
            "  |  ".join(b for b in bits if b))

    def _chrome(self, canvas, doc):
        canvas.saveState(); self._band(canvas)
        canvas.setFont(brand.FONT_FALLBACK + "-Bold", brand.PT_EYEBROW)
        canvas.setFillColor(colors.HexColor(brand.MINERAL))   # "structure and secondary information"
        canvas.drawRightString(
            self.leftMargin + self.width,
            letter[1] - (brand.MARGIN_TOP_IN + brand.LOGO_BAND_H_IN) * inch + 8,
            (self.show.code or self.show.name or "").upper())
        self._footer(canvas, doc); canvas.restoreState()

    def _cover_chrome(self, canvas, doc):
        canvas.saveState(); self._band(canvas)
        self._footer(canvas, doc); canvas.restoreState()


def _fact_table(rows, st):
    """The house pattern: a two-column shaded table, never a bullet list."""
    data = [[Paragraph(f"<b>{k}</b>", st["cell_dim"]),
             Paragraph(v or "—", st["cell"])] for k, v in rows]
    t = Table(data, colWidths=[1.55 * inch, 4.95 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, HAIRLINE),
    ]))
    return t


def _cover(show, agency, master_items, st):
    days = [d for d, _ in group_by_day(master_items) if d and d.date]
    span = ""
    if days:
        first, last = days[0].date, days[-1].date
        span = (brand.fmt_date(first, "full") if first == last else
                f"{brand.fmt_date(first)} – {brand.fmt_date(last, 'full')}")

    flow = [Spacer(1, 0.55 * inch),
            Paragraph((show.name or "").upper(), ParagraphStyle(
                "cover_eyebrow", fontName=brand.FONT_FALLBACK + "-Bold",
                fontSize=brand.PT_EYEBROW, textColor=MINERAL, alignment=TA_LEFT)),
            Spacer(1, 6),
            Paragraph("Master Schedule", ParagraphStyle(
                "cover_title", fontName=brand.FONT_FALLBACK + "-Bold",
                fontSize=brand.PT_TITLE, leading=brand.PT_TITLE + 4,
                textColor=MIDNIGHT)),
            Spacer(1, 0.30 * inch)]

    flow.append(_fact_table([
        ("Client", show.client.name if show.client else None),
        ("Venue", show.venue.name if show.venue else None),
        ("Room", show.room_name),
        ("Dates", span),
        ("Schedule days", str(len(days)) if days else "0"),
        ("Total items", str(len(master_items))),
        ("Prepared by", getattr(agency, "name", None) or brand.SIGNATURE_FORMAL),
        ("Issued", datetime.now().strftime("%-d %b %Y, %H:%M")),
    ], st))

    # Department key. Colour is a convenience; the short text label is what
    # survives the black-and-white printer these documents meet constantly.
    flow += [Spacer(1, 0.30 * inch),
             Paragraph("DEPARTMENT KEY", ParagraphStyle(
                 "key", fontName=brand.FONT_FALLBACK + "-Bold",
                 fontSize=brand.PT_EYEBROW, textColor=MINERAL))]
    cells, style = [], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for i, (dept, _rows) in enumerate(group_by_department(master_items)):
        ds = department_style(dept)
        cells.append([Paragraph(f"<b>{ds['short'] or dept[:5]}</b>", st["head"]),
                      Paragraph(dept, st["cell"])])
        style.append(("BACKGROUND", (0, i), (0, i),
                      colors.HexColor("#" + ds["hex"])))
        style.append(("ALIGN", (0, i), (0, i), "CENTER"))
    if cells:
        key = Table(cells, colWidths=[0.62 * inch, 2.2 * inch])
        key.setStyle(TableStyle(style))
        flow += [Spacer(1, 5), key]
    return flow + [PageBreak()]


def _section_heading(text, st):
    return Paragraph(text, ParagraphStyle(
        "h1", fontName=brand.FONT_FALLBACK + "-Bold",
        fontSize=brand.PT_HEADING_2, leading=brand.PT_HEADING_2 + 3,
        textColor=MIDNIGHT, spaceBefore=10, spaceAfter=7))


def _at_a_glance(master_items, st):
    """The week in one view, so a client sees the shape before the detail."""
    groups = group_by_day(master_items)
    if len(groups) < 2:
        return []
    header = [Paragraph(f"<b>{h}</b>", st["head"])
              for h in ("Day", "Date", "First", "Last", "Items", "Departments")]
    rows, style = [header], [
        ("BACKGROUND", (0, 0), (-1, 0), MIDNIGHT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, HAIRLINE)]
    for i, (day, items) in enumerate(groups, start=1):
        timed = [it for it in items if it["time"]]
        depts = sorted({it["dept"] for it in items})
        rows.append([
            Paragraph(brand.fmt_date(day.date) if day and day.date
                      else "Unscheduled", st["cell"]),
            Paragraph(brand.fmt_date(day.date, "short") if day and day.date
                      else "—", st["cell_dim"]),
            Paragraph(brand.fmt_time(timed[0]["time"]) if timed else "—", st["cell"]),
            Paragraph(brand.fmt_time(timed[-1]["time"]) if timed else "—", st["cell"]),
            Paragraph(str(len(items)), st["cell"]),
            Paragraph(", ".join(department_style(d)["short"] or d
                                for d in depts), st["cell_dim"]),
        ])
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))

    t = Table(rows, colWidths=[1.25 * inch, 0.62 * inch, 0.62 * inch,
                               0.62 * inch, 0.55 * inch, 2.84 * inch],
              repeatRows=1)
    t.setStyle(TableStyle(style))
    return [_section_heading("At a glance", st), t, PageBreak()]


def _day_rows(day, items, st):
    """One day as a single table: header row 0, then one row per item.

    Keeping the day header inside the table (rather than as a separate
    paragraph) is what lets repeatRows carry it onto a continuation page.
    """
    label = brand.fmt_date(day.date, "full") if day and day.date else "Unscheduled"
    header = [Paragraph(label, st["day"]), "", "", "", ""]
    cols = [Paragraph(f"<b>{c}</b>", st["head"]) for c in COLUMNS]
    rows = [header, cols]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), MIDNIGHT),
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor(brand.MINERAL)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 2), (-1, -1), 0.4, HAIRLINE),
    ]
    i = 2
    for n, item in enumerate(items):
        ds = department_style(item["dept"])
        rows.append([
            Paragraph(time_range_text(item, brand.fmt_time) or "—", st["cell"]),
            Paragraph(f"<b>{ds['short'] or item['dept'][:5]}</b>", st["cell"]),
            Paragraph(master_label(item), st["cell"]),
            Paragraph(_detail(item), st["cell_dim"]),
            Paragraph(item["notes"] or "", st["cell_dim"]),
        ])
        style.append(("TEXTCOLOR", (1, i), (1, i), colors.HexColor("#" + ds["hex"])))
        if i % 2:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        i += 1

        # Note 5 — one name per row beneath the headcount, matching the show
        # book's call sheet. Before this the PDF printed a comma list while the
        # XLSX printed a headcount: the two exports disagreed about the same
        # event, which is the drift oss_export exists to prevent.
        for who in item.get("crew_names") or []:
            rows.append([
                "", "", Paragraph(escape(who or ""), st["cell_name"]), "", "",
            ])
            if i % 2:
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
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
    flow = [_section_heading("Schedule by day", st)]
    for day, items in group_by_day(master_items):
        rows, style = _day_rows(day, items, st)
        # repeatRows=2 carries BOTH the day label and the column header onto
        # any continuation page.
        # One table per day. repeatRows=2 carries the day label AND the column
        # header onto continuation pages; _DayTable refuses a split that would
        # leave an orphaned header. A short day is additionally wrapped so it
        # is never broken at all.
        table = _DayTable(rows, colWidths=COL_WIDTHS, repeatRows=2)
        table.setStyle(TableStyle(style))
        flow.append(KeepTogether(table) if len(items) <= ORPHAN_GUARD_ROWS
                    else table)
        flow.append(Spacer(1, 9))
    return flow


def _department_sections(master_items, st):
    """Each department's own schedule, so a head can find just their lines."""
    flow = [PageBreak(), _section_heading("Schedule by department", st)]
    widths = [1.20 * inch, 0.62 * inch, 2.55 * inch, 0.75 * inch, 1.38 * inch]
    for dept, items in group_by_department(master_items):
        ds = department_style(dept)
        header = [Paragraph(f"<b>{dept}</b>", st["day"]), "", "", "", ""]
        cols = [Paragraph(f"<b>{c}</b>", st["head"])
                for c in ("Day", "Time", "Item", "Detail", "Notes")]
        rows = [header, cols]
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + ds["hex"])),
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor(brand.MINERAL)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 2), (-1, -1), 0.4, HAIRLINE)]
        i = 2
        for item in items:
            day = item["day"]
            rows.append([
                Paragraph(brand.fmt_date(day.date) if day and day.date
                          else "Unscheduled", st["cell"]),
                Paragraph(time_range_text(item, brand.fmt_time) or "—", st["cell"]),
                Paragraph(escape(master_label(item)), st["cell"]),
                Paragraph(_detail(item), st["cell_dim"]),
                Paragraph(escape(item["notes"] or ""), st["cell_dim"]),
            ])
            if i % 2:
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
            i += 1
            # This is what blew up on MCDC26. The Crew department's rows put
            # every name for a call into ONE cell in a 2.55in column — 40 names
            # is a single row 263 points tall, and a table of those cannot fit
            # a 618-point frame however it is split. One name per row (note 5)
            # is both what Larry asked for and what makes this paginate at all.
            for who in item.get("crew_names") or []:
                rows.append(["", "",
                             Paragraph(escape(who or ""), st["cell_name"]),
                             "", ""])
                if i % 2:
                    style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
                i += 1
        table = _DayTable(rows, colWidths=widths, repeatRows=2)
        table.setStyle(TableStyle(style))
        flow += [KeepTogether(table) if len(items) <= ORPHAN_GUARD_ROWS
                 else table, Spacer(1, 9)]
    return flow


def build_pdf(buf, show, entries, meal_services, agency=None, logo_file=None):
    """Render the Master OSS into `buf`. Caller supplies the already-queried
    collections so this stays a pure presentation layer over oss_export."""
    master_items, _hardcoded = build_master_items(show, entries, meal_services)
    st = _styles()

    doc = _Doc(buf, show, agency, logo_file)
    # Page one uses the cover template; everything after switches to the body
    # template, which adds the running eyebrow. BaseDocTemplate decorates
    # pages through PageTemplate.onPage, not build() kwargs.
    flow = [NextPageTemplate("body")]
    flow += _cover(show, agency, master_items, st)
    if master_items:
        flow += _at_a_glance(master_items, st)
        flow += _day_sections(master_items, st)
        flow += _department_sections(master_items, st)
    else:
        flow.append(Paragraph("No schedule items yet.", st["cell_dim"]))

    doc.build(flow)
    return buf

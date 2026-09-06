"""Vendor RFQ workbooks from the local labor crew calls (capture log #12).

Jason, 2026-09-06: RFQ (not RFP), one per VENDOR per show, the columns
matching Larry's own `ADI Vendor RFQ — Discipline + Labor Master Template`
in Drive, and the GHC26 Local Labor RFQ he sent on 09-04 as the shape of the
finished document. This module reproduces the template's `00 RFQ Setup`,
`03 Labor Schedule` and `07 Lists` tabs, plus the GHC26 PDF's daily summary,
and fills every yellow (ADI) cell the app knows. Blue cells stay formulas.

Which vendor gets which line: the show's department -> vendor map (note 2;
`vendor_map_for_show`), resolved through the line's catalogue department —
the same department the crew call already groups it under. Lines whose
department has no vendor collect under "Unassigned" so nothing is silently
left out of every workbook.

Counts come from `qty` — the one place in the payroll stack where the line
count is the right shape. Hours per body split on the vendor's own terms
(`billing.thresholds_for(None, vendor)`), because that is how the template
itself lays them out (Regular / OT / DT hours per line).

Colours and fills are the template's: `FFF2CC` yellow = ADI fills in,
`EAF3F8` pale blue = formula or vendor, `0072CE` section heads on white,
`0A162E` title bands.
"""
import datetime as dt
import io
from collections import OrderedDict

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import billing
from local_labor import DEPARTMENT_ORDER, group_rows_by_department

UNASSIGNED = "Unassigned"

FONT = "Arial"
Y_FILL = PatternFill("solid", fgColor="FFF2CC")     # ADI input
B_FILL = PatternFill("solid", fgColor="EAF3F8")     # formula / vendor
H_FILL = PatternFill("solid", fgColor="0072CE")     # section head
T_FILL = PatternFill("solid", fgColor="0A162E")     # title band
THIN = Side(style="thin", color="C9D2DD")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

LABOR_HEADERS = ["Day #", "Scheduled Date", "Date Override", "Effective Work Date",
                 "Call Time", "End Time", "Department", "Position / Classification",
                 "Scope / Activity", "Qty", "Regular Hours", "OT Hours", "DT Hours",
                 "Regular Rate", "OT Rate", "DT Rate", "Extended Price"]
LABOR_WIDTHS = [7, 14, 13, 16, 10, 10, 16, 30, 28, 6, 12, 10, 10, 12, 10, 10, 14]

UNITS = ["lot", "system", "day", "week", "month", "each", "pair", "set", "foot",
         "square foot", "hour", "10-hour day", "allowance", "service"]


# ── data ─────────────────────────────────────────────────────────────────────

def _parse_clock(value):
    return billing._parse_clock(value)


def _end_time(call, hours):
    t = _parse_clock(call)
    if t is None:
        return None
    end = dt.datetime.combine(dt.date(2000, 1, 1), t) + dt.timedelta(hours=float(hours or 0))
    return end.time()


def _fmt_time(t):
    if t is None:
        return ""
    return t.strftime("%-I:%M %p")


def lines_by_vendor(show):
    """``OrderedDict(vendor_key -> {"vendor": Company|None, "lines": [...]})``.

    A line is ``{day, activity, row, department, position, qty, hours}`` in
    schedule order (day, call time, catalogue order). ``vendor_key`` is the
    company id, or ``UNASSIGNED``.
    """
    from models import vendor_map_for_show
    vmap = vendor_map_for_show(show.id)
    out = OrderedDict()
    for day in show.days:
        acts = sorted(day.activities, key=lambda a: ((a.time or "99:99"), a.sort_order or 0, a.id))
        for act in acts:
            rows = [r for r in act.crew_rows if r.is_local_labor]
            if not rows:
                continue
            for dept, dept_rows in group_rows_by_department(rows):
                sdv = vmap.get(dept)
                vendor = sdv.company if (sdv is not None and sdv.company_id) else None
                key = vendor.id if vendor is not None else UNASSIGNED
                bucket = out.setdefault(key, {"vendor": vendor, "job_number": None, "lines": []})
                if sdv is not None and sdv.job_number and not bucket["job_number"]:
                    bucket["job_number"] = sdv.job_number
                for row in dept_rows:
                    title = row.position or (row.position_ref.title if row.position_ref else "Crew")
                    bucket["lines"].append({
                        "day": day, "activity": act, "row": row,
                        "department": dept if dept != "Unassigned" else "General",
                        "position": title,
                        "task": (row.task or "").strip(),
                        "qty": int(row.qty or 1),
                        "hours": float(row.hours or 0),
                    })
    # vendors in name order, Unassigned last
    ordered = OrderedDict()
    for key, b in sorted(out.items(), key=lambda kv: (kv[0] == UNASSIGNED,
                                                       (kv[1]["vendor"].name.lower() if kv[1]["vendor"] else ""))):
        ordered[key] = b
    return ordered


def summary(bucket):
    """Counts the GHC26 cover states: lines, assignments (bodies), person-hours."""
    lines = bucket["lines"]
    return {
        "lines": len(lines),
        "assignments": sum(l["qty"] for l in lines),
        "person_hours": sum(l["qty"] * l["hours"] for l in lines),
        "days": len({l["day"].id for l in lines}),
    }


# ── workbook ────────────────────────────────────────────────────────────────

def _title(ws, text, width):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    c = ws.cell(row=1, column=1, value=text)
    c.font = Font(name=FONT, size=14, bold=True, color="FFFFFF")
    c.fill = T_FILL
    c.alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 26


def _note(ws, row, text, width):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(name=FONT, size=9, italic=True, color="FFFFFF")
    c.fill = H_FILL
    c.alignment = Alignment(vertical="center", indent=1)


def _section(ws, row, text, width):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
    c.fill = H_FILL


def _kv(ws, row, label, value, adi=True):
    a = ws.cell(row=row, column=1, value=label)
    a.font = Font(name=FONT, size=10, bold=True)
    a.fill = B_FILL
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    v = ws.cell(row=row, column=3, value=value)
    v.font = Font(name=FONT, size=10)
    v.fill = Y_FILL if adi else B_FILL
    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=6)
    if isinstance(value, (dt.date, dt.datetime)):
        v.number_format = "mmm d, yyyy"


def _header_row(ws, row, headers):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = Font(name=FONT, size=9, bold=True, color="FFFFFF")
        c.fill = H_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = BORDER
    ws.row_dimensions[row].height = 28


def _setup_sheet(wb, show, bucket, agency, issue_date):
    ws = wb.active
    ws.title = "00 RFQ Setup"
    _title(ws, "ADI VENDOR RFQ — DISCIPLINE + LABOR", 8)
    _note(ws, 2, "Complete the yellow fields once. The remaining tabs carry the RFQ information forward.", 8)
    vendor = bucket["vendor"]
    s = summary(bucket)
    lines = bucket["lines"]
    dates = sorted({l["day"].date for l in lines})
    vcode = (vendor.code or vendor.name if vendor else "UNASSIGNED").upper().replace(" ", "")
    rfq_id = f"RFQ-{(show.code or show.name or 'SHOW').replace(' ', '')}-{vcode}"
    venue = ""
    if show.venue:
        bits = [show.venue.name, ", ".join(b for b in (show.venue.city, show.venue.state) if b)]
        venue = " — ".join(b for b in bits if b)
    per_day = max((sum(1 for l in lines if l["day"].id == d) for d in {l["day"].id for l in lines}), default=0)

    r = 4
    _section(ws, r, "RFQ IDENTIFICATION", 8); r += 1
    for label, value in [
        ("RFQ ID", rfq_id),
        ("Opportunity / Show ID", show.code or ""),
        ("RFQ Discipline", "Local Labor"),
        ("Revision", "v1"),
        ("Issue Date", issue_date),
        ("Proposal Due", ""),
        ("Event / Program", show.name),
        ("City / Venue", venue),
        ("Event Dates", show.date_range() if callable(getattr(show, "date_range", None)) else ""),
        ("ADI Contact", getattr(agency, "contact_name", None) or "Larry Kargol"),
        ("Contact Email", getattr(agency, "contact_email", None) or "hello@adiexpgroup.com"),
    ]:
        _kv(ws, r, label, value); r += 1
    r += 1
    _section(ws, r, "VENDOR & COMMERCIAL INFORMATION", 8); r += 1
    for label, value in [
        ("Vendor Company", vendor.name if vendor else "(no vendor assigned — see Local Labor Vendors on the show page)"),
        ("Vendor Contact", (vendor.contact_name if vendor else "") or ""),
        ("Vendor Email", (vendor.email if vendor else "") or ""),
        ("Vendor Phone", (vendor.phone if vendor else "") or ""),
        ("Vendor Job Number", bucket.get("job_number") or ""),
        ("Quote Valid Through", ""),
        ("Payment Terms", "Net 30"),
        ("Tax Status", "Vendor to state"),
        ("Currency", "USD"),
        ("Requested Pricing Format", "Itemized"),
        ("Master Labor Window Start (Travel In)", dates[0] if dates else ""),
        ("Master Labor Window End (Travel Out)", dates[-1] if dates else ""),
        ("Labor Lines per Day", per_day),
    ]:
        _kv(ws, r, label, value); r += 1
    r += 1
    _section(ws, r, "TERMS & RESPONSE REQUIREMENTS", 8); r += 1
    for label in ("Delivery / Install Window", "Strike / Return Window", "Freight Included?",
                  "Travel Included?", "Labor Included?", "Alternates Requested?",
                  "Special Instructions"):
        _kv(ws, r, label, ""); r += 1
    r += 1
    _section(ws, r, "THIS REQUEST", 8); r += 1
    _kv(ws, r, "Dated call lines", s["lines"], adi=False); r += 1
    _kv(ws, r, "Assignments (bodies)", s["assignments"], adi=False); r += 1
    _kv(ws, r, "Planning person-hours", round(s["person_hours"], 1), adi=False); r += 1
    _kv(ws, r, "Vendor completion",
        "Confirm jurisdiction, classifications, minimum calls, regular/overtime/double-time "
        "allocation, applicable rates, meal and rest rules, supervision, travel, equipment, "
        "taxes, fees, exclusions, and availability. Return the completed schedule and "
        "itemized estimate.", adi=False)
    ws.row_dimensions[r].height = 58
    ws.cell(row=r, column=3).alignment = Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate([22, 14, 18, 14, 14, 14, 10, 10], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def _daily_summary_sheet(wb, bucket):
    ws = wb.create_sheet("02 Daily Summary")
    _title(ws, "DAILY LABOR SUMMARY", 5)
    _note(ws, 2, "One row per work date: assignments and planning person-hours, as the crew calls stand today.", 5)
    _header_row(ws, 4, ["Date", "Phase", "Assignments", "Person-Hours", "Primary Activity"])
    by_day = OrderedDict()
    for l in bucket["lines"]:
        d = by_day.setdefault(l["day"].id, {"day": l["day"], "assignments": 0, "hours": 0.0})
        d["assignments"] += l["qty"]
        d["hours"] += l["qty"] * l["hours"]
    r = 5
    for d in by_day.values():
        day = d["day"]
        vals = [day.date, day.phase or "", d["assignments"], round(d["hours"], 1), day.label or ""]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.font = Font(name=FONT, size=10)
            c.border = BORDER
            c.fill = B_FILL
            if i == 1:
                c.number_format = "ddd mm.dd"
        r += 1
    t = ws.cell(row=r, column=1, value="Total")
    t.font = Font(name=FONT, size=10, bold=True)
    ws.cell(row=r, column=3, value=f"=SUM(C5:C{max(r - 1, 5)})").font = Font(name=FONT, bold=True)
    ws.cell(row=r, column=4, value=f"=SUM(D5:D{max(r - 1, 5)})").font = Font(name=FONT, bold=True)
    for i, w in enumerate([14, 22, 13, 14, 44], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"
    return ws


def _labor_sheet(wb, show, bucket):
    ws = wb.create_sheet("03 Labor Schedule")
    _title(ws, "ADI RFQ LABOR SCHEDULE — DATE DRIVEN", len(LABOR_HEADERS))
    _note(ws, 2, "One row per date, call, department and classification. Yellow is ADI's ask; "
                 "vendor enters Regular Rate; OT, DT and Extended Price calculate.", len(LABOR_HEADERS))
    vendor = bucket["vendor"]
    ws.cell(row=4, column=1, value="RFQ ID").font = Font(name=FONT, bold=True, size=9)
    ws.cell(row=4, column=2, value="='00 RFQ Setup'!C5").font = Font(name=FONT, size=9)
    ws.cell(row=4, column=3, value="Discipline").font = Font(name=FONT, bold=True, size=9)
    ws.cell(row=4, column=4, value="='00 RFQ Setup'!C7").font = Font(name=FONT, size=9)
    ws.cell(row=4, column=5, value="Vendor").font = Font(name=FONT, bold=True, size=9)
    ws.cell(row=4, column=6, value="='00 RFQ Setup'!C18").font = Font(name=FONT, size=9)
    ws.cell(row=5, column=1, value=("Vendor: " + vendor.name) if vendor else
            "Vendor: Not yet assigned").font = Font(name=FONT, size=9, italic=True)
    _header_row(ws, 6, LABOR_HEADERS)

    ot_after, dt_after = billing.thresholds_for(None, vendor)
    dates = sorted({l["day"].date for l in bucket["lines"]})
    day_no = {d: i + 1 for i, d in enumerate(dates)}
    r = 7
    for l in bucket["lines"]:
        day = l["day"]
        st, ot, dtm = billing.split_day(l["hours"], ot_after, dt_after)
        end = _end_time(l["activity"].time, l["hours"])
        activity = day.label or day.phase or ""
        if l["task"]:
            activity = f"{activity} — {l['task']}" if activity else l["task"]
        vals = [
            day_no[day.date], day.date, None, f"=IF(C{r}<>\"\",C{r},B{r})",
            _fmt_time(_parse_clock(l["activity"].time)), _fmt_time(end),
            l["department"], l["position"], activity, l["qty"],
            st or None, ot or None, dtm or None,
            None, f"=IF(N{r}=\"\",\"\",N{r}*1.5)", f"=IF(N{r}=\"\",\"\",N{r}*2)",
            (f"=IF(OR(J{r}=\"\",N{r}=\"\"),\"\",J{r}*(IF(K{r}=\"\",0,K{r}*N{r})"
             f"+IF(L{r}=\"\",0,L{r}*O{r})+IF(M{r}=\"\",0,M{r}*P{r})))"),
        ]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.font = Font(name=FONT, size=9)
            c.border = BORDER
            # A (day #), D (effective), O/P/Q (formulas) are blue; the rest ADI yellow
            c.fill = B_FILL if i in (1, 4, 15, 16, 17) else Y_FILL
            if i in (2, 4):
                c.number_format = "ddd mm.dd"
            if i in (15, 16, 17):
                c.number_format = '"$"#,##0.00'
            if i == 14:
                c.number_format = '"$"#,##0.00'
        r += 1
    last = max(r - 1, 7)
    tot = ws.cell(row=r + 1, column=9, value="Totals")
    tot.font = Font(name=FONT, bold=True, size=9)
    for col in (10, 11, 12, 13, 17):
        letter = get_column_letter(col)
        c = ws.cell(row=r + 1, column=col, value=f"=SUM({letter}7:{letter}{last})")
        c.font = Font(name=FONT, bold=True, size=9)
        if col == 17:
            c.number_format = '"$"#,##0.00'
    # pull-downs from 07 Lists, like the template
    for col, rng in (("G", "$A$5:$A$40"), ("H", "$B$5:$B$200"), ("I", "$C$5:$C$60")):
        dv = DataValidation(type="list", formula1=f"'07 Lists'!{rng}", allow_blank=True)
        dv.add(f"{col}7:{col}{max(last, 1006)}")
        ws.add_data_validation(dv)
    for i, w in enumerate(LABOR_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A7"
    ws.print_title_rows = "6:6"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws


def _lists_sheet(wb, positions, activities):
    ws = wb.create_sheet("07 Lists")
    _title(ws, "ADI RFQ CONTROLLED LISTS", 4)
    _note(ws, 2, "Edit these lists to expand the pull-downs on 03 Labor Schedule.", 4)
    _header_row(ws, 4, ["Department / Discipline", "Position / Classification",
                        "Scope / Activity", "Unit"])
    depts = list(DEPARTMENT_ORDER) + ["Other"]
    cols = [depts, positions, activities, UNITS]
    for ci, values in enumerate(cols, start=1):
        for ri, v in enumerate(values, start=5):
            ws.cell(row=ri, column=ci, value=v).font = Font(name=FONT, size=9)
    for i, w in enumerate([24, 34, 30, 14], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def build_workbook(show, bucket, agency=None, issue_date=None):
    """One vendor's RFQ workbook. Returns an ``openpyxl.Workbook``."""
    from models import Position, PhaseType
    issue_date = issue_date or dt.date.today()
    wb = openpyxl.Workbook()
    _setup_sheet(wb, show, bucket, agency, issue_date)
    _daily_summary_sheet(wb, bucket)
    _labor_sheet(wb, show, bucket)
    positions = [p.title for p in Position.query.filter_by(is_local_labor=True)
                 .order_by(Position.department, Position.title).all()]
    activities = [t.name for t in PhaseType.query.order_by(PhaseType.sort_order).all()]
    _lists_sheet(wb, positions, activities)
    return wb


def workbook_bytes(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename_for(show, bucket, issue_date=None):
    issue_date = issue_date or dt.date.today()
    vendor = bucket["vendor"]
    v = (vendor.code or vendor.name) if vendor else "Unassigned"
    v = "".join(ch if ch.isalnum() else "_" for ch in v).strip("_") or "Vendor"
    code = "".join(ch if ch.isalnum() else "_" for ch in (show.code or show.name or "Show")).strip("_")
    return f"{code}_Local_Labor_RFQ_{v}_{issue_date.strftime('%Y%m%d')}.xlsx"

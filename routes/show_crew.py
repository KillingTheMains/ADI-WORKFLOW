"""
show_crew.py — routes for assigning crew members to a specific show.

URL prefix: /shows/<show_id>/crew
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from extensions import db
from models import Show, CrewMember, ShowCrewAssignment, Company, Position, \
    ScheduleActivity, CrewRow, ShowOpenSlot
from datetime import date as date_cls
from crew_ordering import crew_order_by, crew_sort_key

show_crew_bp = Blueprint("show_crew", __name__)


# ── Show crew roster page ─────────────────────────────────────────────────────
#
# (Removed a dead `_get_show_or_404` helper that raised a bare Exception
# instead of a real 404. Every route uses `Show.query.get_or_404` directly.)

@show_crew_bp.route("/<int:show_id>/crew")
def show_crew(show_id):
    show = Show.query.get_or_404(show_id)

    # All active crew, grouped by company
    all_crew = (
        db.session.query(CrewMember)
        .filter_by(active=True)
        .outerjoin(Position, CrewMember.position_id == Position.id)
        .order_by(*crew_order_by())
        .all()
    )

    # Set of crew_member_ids already assigned to this show
    assigned_ids = {a.crew_member_id for a in show.crew_assignments}

    # Group crew by company for display
    companies = {}
    for cm in all_crew:
        co_name = cm.company.name if cm.company else "No Company"
        co_id   = cm.company_id or 0
        if co_id not in companies:
            companies[co_id] = {"name": co_name, "crew": []}
        companies[co_id]["crew"].append(cm)

    # Sort companies alphabetically
    sorted_companies = sorted(companies.values(), key=lambda c: c["name"])

    # ── Phase A: booked crew + open slots, grouped by booking_task ──────────
    assignments = (ShowCrewAssignment.query
                   .filter_by(show_id=show_id)
                   .all())
    open_slots  = (ShowOpenSlot.query
                   .filter_by(show_id=show_id)
                   .all())

    # ── #29 Phase 2: roster grouped by COMPANY; open/TBD slots collect in
    # their own group at the end (Option A). Within a company, manual drag
    # (assignment.sort_order) wins, else the canonical Crew Database order.
    roster_map = {}
    for a in assignments:
        cm = a.crew_member
        co_id = (cm.company_id if cm else None) or 0
        co_name = cm.company.name if cm and cm.company else "No Company"
        g = roster_map.setdefault(co_id, {"name": co_name, "assignments": [],
                                          "slots": [], "rows": []})
        g["assignments"].append(a)
        g["rows"].append({
            "kind": "a", "obj": a,
            "_sort": ((a.sort_order if a.sort_order is not None else 10**9,)
                      + (crew_sort_key(cm) if cm else (10**9,))),
        })
    for g in roster_map.values():
        g["rows"].sort(key=lambda r: r["_sort"])
    roster_groups = [g for _, g in sorted(roster_map.items(),
                                          key=lambda kv: kv[1]["name"].lower())]

    # Open/TBD slots have no company → one group at the end of the roster.
    if open_slots:
        tbd = {"name": "Open Positions (TBD)", "assignments": [],
               "slots": [], "rows": []}
        for s in sorted(open_slots, key=lambda s: (
                s.sort_order if s.sort_order is not None else 10**9, s.id)):
            tbd["slots"].append(s)
            tbd["rows"].append({"kind": "s", "obj": s, "_sort": ()})
        roster_groups.append(tbd)

    # Position list for the "+ TBD slot" picker
    all_positions = Position.query.order_by(Position.department, Position.title).all()

    return render_template(
        "shows/show_crew.html",
        show=show,
        sorted_companies=sorted_companies,
        assigned_ids=assigned_ids,
        roster_groups=roster_groups,
        all_positions=all_positions,
        all_companies=Company.query.order_by(Company.name).all(),
    )


# ── Assign / unassign a single crew member ────────────────────────────────────

def _autofill_travel_window(assignment, show):
    """#31 — fill Travel In/Out from the show's designated travel window, but
    ONLY when blank. Additive: never overwrites a date already set."""
    if show.travel_window_start and not assignment.travel_in_date:
        assignment.travel_in_date = show.travel_window_start
    if show.travel_window_end and not assignment.travel_out_date:
        assignment.travel_out_date = show.travel_window_end
    return assignment


@show_crew_bp.route("/<int:show_id>/crew/assign", methods=["POST"])
def assign_crew(show_id):
    show = Show.query.get_or_404(show_id)
    crew_member_id = int(request.form["crew_member_id"])
    action = request.form.get("action", "assign")  # "assign" or "unassign"

    if action == "assign":
        existing = ShowCrewAssignment.query.filter_by(
            show_id=show_id, crew_member_id=crew_member_id).first()
        if not existing:
            a = ShowCrewAssignment(show_id=show_id, crew_member_id=crew_member_id)
            _autofill_travel_window(a, show)
            db.session.add(a)
            db.session.commit()
    else:
        ShowCrewAssignment.query.filter_by(
            show_id=show_id, crew_member_id=crew_member_id).delete()
        db.session.commit()

    return redirect(url_for("show_crew.show_crew", show_id=show_id))


# ── Assign / unassign an entire company in one click ─────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/assign-company", methods=["POST"])
def assign_company(show_id):
    show = Show.query.get_or_404(show_id)
    company_id = int(request.form["company_id"])
    action = request.form.get("action", "assign")

    company_crew = CrewMember.query.filter_by(
        company_id=company_id, active=True).all()

    if action == "assign":
        for cm in company_crew:
            exists = ShowCrewAssignment.query.filter_by(
                show_id=show_id, crew_member_id=cm.id).first()
            if not exists:
                a = ShowCrewAssignment(show_id=show_id, crew_member_id=cm.id)
                _autofill_travel_window(a, show)
                db.session.add(a)
        db.session.commit()
        co = Company.query.get(company_id)
        flash(f"Added all {co.name} crew to {show.name}.", "success")
    else:
        crew_ids = [cm.id for cm in company_crew]
        ShowCrewAssignment.query.filter(
            ShowCrewAssignment.show_id == show_id,
            ShowCrewAssignment.crew_member_id.in_(crew_ids)
        ).delete(synchronize_session=False)
        db.session.commit()
        co = Company.query.get(company_id)
        flash(f"Removed all {co.name} crew from {show.name}.", "info")

    return redirect(url_for("show_crew.show_crew", show_id=show_id))


# ── AJAX: Add all assigned crew from a company to a specific activity ─────────

@show_crew_bp.route(
    "/<int:show_id>/schedule/<int:day_id>/activities/<int:act_id>/add-company-crew",
    methods=["POST"])
def add_company_crew_to_activity(show_id, day_id, act_id):
    """
    Bulk-add every show-assigned crew member from a company to an activity.
    Called via AJAX from the day editor.
    """
    activity   = ScheduleActivity.query.get_or_404(act_id)
    company_id = int(request.json.get("company_id", 0))
    hours      = request.json.get("hours")          # float or None
    if hours is not None:
        try:
            hours = float(hours)
        except (TypeError, ValueError):
            hours = None

    # Crew assigned to this show AND belonging to this company
    assigned = (
        db.session.query(CrewMember)
        .join(ShowCrewAssignment,
              ShowCrewAssignment.crew_member_id == CrewMember.id)
        .filter(
            ShowCrewAssignment.show_id == show_id,
            CrewMember.company_id == company_id,
            CrewMember.active == True,
        )
        .outerjoin(Position, CrewMember.position_id == Position.id)
        .order_by(*crew_order_by())
        .all()
    )

    # Current max sort_order in this activity
    existing_max = db.session.query(
        db.func.max(CrewRow.sort_order)
    ).filter_by(activity_id=act_id).scalar() or 0

    added = []
    for i, cm in enumerate(assigned):
        # Skip if already on this activity
        already = CrewRow.query.filter_by(
            activity_id=act_id, crew_member_id=cm.id).first()
        if already:
            continue
        row = CrewRow(
            activity_id=act_id,
            crew_member_id=cm.id,
            position=cm.position.title if cm.position else "",
            sort_order=existing_max + i + 1,
            hours=hours,
        )
        db.session.add(row)
        added.append({
            "id": None,  # filled after commit
            "crew_member_id": cm.id,
            "name": cm.display_label,
            "position": cm.position.title if cm.position else "",
        })

    db.session.commit()

    # Fill in the real IDs
    for item in added:
        row = CrewRow.query.filter_by(
            activity_id=act_id,
            crew_member_id=item["crew_member_id"]
        ).first()
        if row:
            item["id"] = row.id

    return jsonify({"added": len(added), "rows": added})


# ── Crew contact sheet ────────────────────────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/contact-sheet")
def contact_sheet(show_id):
    """Printable contact sheet for all crew assigned to this show."""
    show = Show.query.get_or_404(show_id)

    # Pull assigned crew with their full relationships loaded
    assignments = (
        db.session.query(ShowCrewAssignment)
        .join(CrewMember, ShowCrewAssignment.crew_member_id == CrewMember.id)
        .outerjoin(Position, CrewMember.position_id == Position.id)
        .filter(ShowCrewAssignment.show_id == show_id, CrewMember.active == True)
        .order_by(*crew_order_by())
        .all()
    )

    # Group by company
    companies = {}
    for a in assignments:
        cm = a.crew_member
        co_name = cm.company.name if cm.company else "No Company"
        co_id   = cm.company_id or 0
        if co_id not in companies:
            companies[co_id] = {"name": co_name, "crew": []}
        companies[co_id]["crew"].append(cm)

    sorted_companies = sorted(companies.values(), key=lambda c: c["name"])

    return render_template(
        "shows/crew_contact_sheet.html",
        show=show,
        sorted_companies=sorted_companies,
        total=len(assignments),
    )


# ── Show hours report ─────────────────────────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/hours")
def hours_report(show_id):
    """Per-crew-member hours breakdown across all show days.

    Three populations, three tables (2026-09-05, capture log #7):

    * NAMED crew — one line per person, hours per day from their crew rows.
    * LOCAL LABOR — one line per (company, position); the count lives on the
      crew row, the actuals live on its bodies (`CrewRowBody`), so a line of
      six can leave at six different times and still be one line here.
    * TBD — rows with neither a person nor a local labor position.

    The billable split is per DAY and per BODY on each person's own terms:
    `billing.thresholds_for` resolves person -> company -> default. Where an
    actual is recorded it is what gets split; otherwise the estimate. Hours
    only — no rate is applied on this report (see billing.py).
    """
    from billing import (split_day, split_day_flagged, weighted_hours,
                         thresholds_for, short_turn_for, day_flags,
                         rates_for, rates_for_local, cost_of)
    from crew_sections import walk

    show = Show.query.get_or_404(show_id)
    # Money is behind a toggle (Jason, 2026-09-06): the report stays an hours
    # report by default; ?cost=1 prices every line it can.
    want_cost = request.args.get("cost") == "1"

    # Optional filters. Options are collected from the unfiltered data so a
    # filter can always be undone from the page it produced.
    want_dept    = (request.args.get("dept") or "").strip()
    want_company = (request.args.get("company") or "").strip()

    # Build a lookup: crew_member_id → {member, days: {day_id: hours}, total}
    crew_data  = {}   # keyed by crew_member_id (for named crew)
    local_data = {}   # keyed by (company, position) for local labor lines
    tbd_data   = []   # list of {name, day_id, hours, position, activity} for unnamed rows

    show_days = show.days  # already ordered by date

    for day in show_days:
        for act in day.activities:
            for row, l1, _l2 in walk(list(act.crew_rows)):
                qty     = row.qty or 1
                hrs     = (row.hours or 0) * qty
                actual  = (row.actual_hours or 0) * qty
                # Local labor FIRST. Show 3's local lines are linked to one
                # placeholder crew record per position ("<Company> Lighting
                # Hand"), so testing crew_member_id first claimed them as
                # named people — a line of 8 hands x 10 hrs became one person
                # working 80 hours in a day, split 10 ST + 2 OT + 68 DT. A row
                # that IS local labor is a count, whatever it is linked to;
                # the call sheet's conflict check applies the same rule.
                if row.is_local_labor:
                    section = (l1.group_label if l1 is not None else "") or ""
                    company = l1.company if (l1 is not None and l1.company_id) else None
                    if company is None and row.crew_member is not None:
                        company = row.crew_member.company
                    co_name = company.name if company else (section or "")
                    position = row.position or (row.position_ref.title if row.position_ref else "Local labor")
                    key = (co_name, position)
                    if key not in local_data:
                        local_data[key] = {
                            "company":  co_name,
                            "_company": company,
                            "_position": row.position_ref,
                            "section":  section,
                            "position": position,
                            "dept":     (row.position_ref.department if row.position_ref else "") or "",
                            "thresholds": thresholds_for(None, company),
                            "days":     {},     # day_id -> {"qty","est","actual","recorded"}
                            "total":    0.0,
                            "total_actual": 0.0,
                            "bodies":   0,
                            "recorded": 0,
                            "actual_recorded": False,
                            "st_hours": 0.0, "ot_hours": 0.0, "dt_hours": 0.0,
                        }
                    entry = local_data[key]
                    d = entry["days"].setdefault(day.id, {"qty": 0, "est": 0.0,
                                                          "actual": 0.0, "recorded": 0})
                    d["qty"] += qty
                    d["est"] += hrs
                    entry["total"] += hrs
                    entry["bodies"] += qty
                    # Per body: its own actual where recorded, else the line's
                    # estimate; each body's day is split on its own.
                    have = {b.index: b for b in row.bodies}
                    ot_after, dt_after = entry["thresholds"]
                    for n in range(1, qty + 1):
                        b = have.get(n)
                        a = b.actual_hours if b is not None else None
                        if a is not None:
                            d["actual"] += a
                            d["recorded"] += 1
                            entry["total_actual"] += a
                            entry["recorded"] += 1
                            entry["actual_recorded"] = True
                        st, ot, dt = split_day(a if a is not None else (row.hours or 0),
                                               ot_after, dt_after)
                        entry["st_hours"] += st
                        entry["ot_hours"] += ot
                        entry["dt_hours"] += dt
                elif row.crew_member_id:
                    if row.crew_member_id not in crew_data:
                        cm = row.crew_member
                        crew_data[row.crew_member_id] = {
                            "member":   cm,
                            "position": row.position or (cm.position.title if cm.position else ""),
                            "dept":     (cm.position.department if cm.position else "") or "",
                            "company":  cm.company.name if cm.company else "",
                            "type":     row.crew_type or "",
                            "days":     {},
                            "days_billable": {},   # actual where recorded, else estimate
                            "cells":    {},        # day_id -> {"rows","est","actual","multi"}
                            "day_dates": {},
                            "shifts":   [],        # (date, call time, billable hrs) per row
                            "total":    0.0,
                            "total_actual": 0.0,
                            "est_recorded": 0.0,   # estimate of the days with an actual
                            "actual_recorded": False,
                        }
                    entry = crew_data[row.crew_member_id]
                    entry["days"][day.id] = entry["days"].get(day.id, 0.0) + hrs
                    billable = actual if row.actual_hours is not None else hrs
                    entry["days_billable"][day.id] = entry["days_billable"].get(day.id, 0.0) + billable
                    entry["day_dates"][day.id] = day.date
                    entry["shifts"].append((day.date, act.time, billable))
                    entry["total"] += hrs
                    entry["total_actual"] += actual
                    if row.actual_hours is not None:
                        entry["actual_recorded"] = True
                        # Δ compares like with like: the actual against the
                        # estimate of the days that HAVE an actual, so two
                        # recorded days out of seven read +1.5, not -48.5.
                        entry["est_recorded"] += hrs
                    # The cell (Jason, 09-07): the actual is typed on this
                    # report. One row on the day -> the cell edits that row;
                    # two calls on one day -> read-only, the actual belongs
                    # to a shift and is typed on the day page.
                    cell = entry["cells"].setdefault(day.id, {
                        "rows": [], "est": 0.0, "actual": None, "multi": False})
                    cell["rows"].append(row.id)
                    cell["est"] += hrs
                    if row.actual_hours is not None:
                        cell["actual"] = (cell["actual"] or 0.0) + actual
                    cell["multi"] = len(cell["rows"]) > 1
                else:
                    # TBD / unnamed row — track separately
                    tbd_data.append({
                        "name":     row.display_name,
                        "position": row.position or "",
                        "type":     row.crew_type or "",
                        "day_id":   day.id,
                        "hours":    hrs,
                        "actual":   actual if row.actual_hours is not None else None,
                        "activity": act.description,
                    })

    # Filter options, from everything, before anything is dropped
    dept_options = sorted({e["dept"] for e in crew_data.values() if e["dept"]}
                          | {e["dept"] for e in local_data.values() if e["dept"]})
    company_options = sorted({e["company"] for e in crew_data.values() if e["company"]}
                             | {e["company"] for e in local_data.values() if e["company"]})

    def keep(e):
        if want_dept and e["dept"] != want_dept:
            return False
        if want_company and e["company"] != want_company:
            return False
        return True

    # Sort named crew: by company, then the canonical Crew Database order (#29)
    sorted_crew = sorted(
        (e for e in crew_data.values() if keep(e)),
        key=lambda x: (x["company"], crew_sort_key(x["member"]))
    )
    sorted_local = sorted(
        (e for e in local_data.values() if keep(e)),
        key=lambda x: (x["company"], x["dept"], x["position"])
    )

    # Day totals (sum of all named crew hours per day). Estimates, as the
    # stat cards are; the per-day figures Larry reads in the table are the
    # BILLABLE ones below (actual where recorded, else estimate), each
    # marked when any estimate is inside it — the "*" convention (Jason,
    # 09-07: the estimate carries a star, the actual does not).
    day_totals = {}
    for entry in sorted_crew:
        for day_id, hrs in entry["days"].items():
            day_totals[day_id] = day_totals.get(day_id, 0.0) + hrs
    local_day_totals = {}
    for entry in sorted_local:
        for day_id, d in entry["days"].items():
            local_day_totals[day_id] = local_day_totals.get(day_id, 0.0) + d["est"]

    def _bucket(store, key, day_id):
        return store.setdefault(key, {}).setdefault(
            day_id, {"hours": 0.0, "est_in": False, "n": 0})

    # Named crew: per company per day, and the show per day.
    company_day = {}
    named_day = {}
    for entry in sorted_crew:
        for day_id, cell in entry["cells"].items():
            billable = cell["actual"] if cell["actual"] is not None else cell["est"]
            for b in (_bucket(company_day, entry["company"], day_id),
                      _bucket(named_day, "", day_id)):
                b["hours"] += billable
                b["n"] += 1
                if cell["actual"] is None:
                    b["est_in"] = True
    named_day = named_day.get("", {})
    # Local labor: per company per day (bodies x hours; actuals per body).
    local_company_day = {}
    for entry in sorted_local:
        for day_id, d in entry["days"].items():
            b = _bucket(local_company_day, entry["company"], day_id)
            # Recorded bodies count their actual; the rest their estimate.
            per_body_est = (d["est"] / d["qty"]) if d["qty"] else 0.0
            b["hours"] += d["actual"] + per_body_est * (d["qty"] - d["recorded"])
            b["n"] += d["qty"]
            if d["recorded"] < d["qty"]:
                b["est_in"] = True
    # Named + local, for the show-level figures (man-hours, hours by phase)
    all_day_totals = dict(day_totals)
    for day_id, h in local_day_totals.items():
        all_day_totals[day_id] = all_day_totals.get(day_id, 0.0) + h

    # Larry's billable day: 10 hours, OT 1.5x for 11-12, DT 2.0x from 13 —
    # unless the person, or their company, has other terms. Split PER DAY:
    # summing a person's show total and splitting that would invent overtime
    # for eight short days and hide it on one long one.
    # Short turnaround and 6th/7th day (Jason, 2026-09-06; the week resets
    # on Monday, 2026-09-07), NAMED CREW ONLY:
    # a body is per call, so neither rule can follow local labor across
    # days. A flagged day is all OT (DT still after the person's DT
    # threshold); an hour is ST, OT or DT, never two of them.
    short_turn_days = sixth_days = 0
    for entry in sorted_crew:
        member = entry["member"]
        ot_after, dt_after = thresholds_for(member)
        entry["thresholds"] = (ot_after, dt_after)
        entry["short_turn_after"] = short_turn_for(member)
        flags = day_flags(entry["shifts"], entry["short_turn_after"])
        entry["day_flags"] = {}
        st = ot = dt = 0.0
        for day_id, h in entry["days_billable"].items():
            f = flags.get(entry["day_dates"].get(day_id), {})
            all_ot = bool(f.get("short_turn") or f.get("sixth_day"))
            a, b, c = split_day_flagged(h, ot_after, dt_after, all_ot=all_ot)
            st += a; ot += b; dt += c
            if f.get("short_turn"):
                entry["day_flags"][day_id] = "short"
                short_turn_days += 1
            elif f.get("sixth_day"):
                entry["day_flags"][day_id] = "sixth"
                sixth_days += 1
        entry["st_hours"], entry["ot_hours"], entry["dt_hours"] = st, ot, dt
        entry["weighted_hours"] = weighted_hours(st, ot, dt)
        entry["rates"] = rates_for(member)
        entry["cost"] = cost_of((st, ot, dt), entry["rates"]) if want_cost else None
    for entry in sorted_local:
        entry["weighted_hours"] = weighted_hours(
            entry["st_hours"], entry["ot_hours"], entry["dt_hours"])
        entry["rates"] = rates_for_local(entry["_company"], entry["_position"])
        entry["cost"] = (cost_of((entry["st_hours"], entry["ot_hours"], entry["dt_hours"]),
                                 entry["rates"]) if want_cost else None)

    # Company subtotals for the named table (rendered after each group)
    company_totals = {}
    for entry in sorted_crew:
        ct = company_totals.setdefault(entry["company"], {
            "n": 0, "total": 0.0, "total_actual": 0.0, "est_recorded": 0.0,
            "st": 0.0, "ot": 0.0, "dt": 0.0, "actual_recorded": False,
            "cost": 0.0, "unpriced": 0})
        ct["n"] += 1
        if entry.get("cost") is not None:
            ct["cost"] += entry["cost"]
        elif want_cost:
            ct["unpriced"] += 1
        ct["total"] += entry["total"]
        ct["total_actual"] += entry["total_actual"]
        ct["est_recorded"] += entry["est_recorded"]
        ct["st"] += entry["st_hours"]; ct["ot"] += entry["ot_hours"]; ct["dt"] += entry["dt_hours"]
        ct["actual_recorded"] = ct["actual_recorded"] or entry["actual_recorded"]

    named_st = sum(e["st_hours"] for e in sorted_crew)
    named_ot = sum(e["ot_hours"] for e in sorted_crew)
    named_dt = sum(e["dt_hours"] for e in sorted_crew)
    local_st = sum(e["st_hours"] for e in sorted_local)
    local_ot = sum(e["ot_hours"] for e in sorted_local)
    local_dt = sum(e["dt_hours"] for e in sorted_local)
    totals_st, totals_ot, totals_dt = named_st + local_st, named_ot + local_ot, named_dt + local_dt

    # Anyone on terms other than the defaults gets a footnote on the banner.
    from billing import OT_AFTER_HOURS, DT_AFTER_HOURS
    own_terms = sorted({
        f"{e['member'].display_label} (OT after {e['thresholds'][0]:g}, DT after {e['thresholds'][1]:g})"
        for e in sorted_crew if e["thresholds"] != (OT_AFTER_HOURS, DT_AFTER_HOURS)
    } | {
        f"{e['company']} local labor (OT after {e['thresholds'][0]:g}, DT after {e['thresholds'][1]:g})"
        for e in sorted_local if e["thresholds"] != (OT_AFTER_HOURS, DT_AFTER_HOURS)
    })

    named_cost = sum(e["cost"] for e in sorted_crew if e.get("cost") is not None)
    named_unpriced = sum(1 for e in sorted_crew if want_cost and e.get("cost") is None)
    local_cost = sum(e["cost"] for e in sorted_local if e.get("cost") is not None)
    local_unpriced = sum(1 for e in sorted_local if want_cost and e.get("cost") is None)
    local_company_cost = {}
    for e in sorted_local:
        lc = local_company_cost.setdefault(e["company"], {"cost": 0.0, "unpriced": 0})
        if e.get("cost") is not None:
            lc["cost"] += e["cost"]
        elif want_cost:
            lc["unpriced"] += 1

    grand_total        = sum(e["total"] for e in sorted_crew)
    grand_total_actual = sum(e["total_actual"] for e in sorted_crew)
    grand_est_recorded = sum(e["est_recorded"] for e in sorted_crew)
    any_actual_recorded = any(e.get("actual_recorded") for e in sorted_crew)
    local_total        = sum(e["total"] for e in sorted_local)
    local_total_actual = sum(e["total_actual"] for e in sorted_local)
    local_any_recorded = any(e["actual_recorded"] for e in sorted_local)
    local_bodies       = sum(e["bodies"] for e in sorted_local)

    return render_template(
        "shows/hours_report.html",
        show=show,
        show_days=show_days,
        sorted_crew=sorted_crew,
        sorted_local=sorted_local,
        tbd_data=tbd_data,
        day_totals=day_totals,
        local_day_totals=local_day_totals,
        company_day=company_day, named_day=named_day,
        local_company_day=local_company_day,
        today=date_cls.today(),
        all_day_totals=all_day_totals,
        company_totals=company_totals,
        totals_st=totals_st, totals_ot=totals_ot, totals_dt=totals_dt,
        named_ot=named_ot, named_dt=named_dt, local_ot=local_ot, local_dt=local_dt,
        own_terms=own_terms,
        grand_total=grand_total,
        grand_total_actual=grand_total_actual,
        grand_est_recorded=grand_est_recorded,
        any_actual_recorded=any_actual_recorded,
        local_total=local_total,
        local_total_actual=local_total_actual,
        local_any_recorded=local_any_recorded,
        local_bodies=local_bodies,
        dept_options=dept_options, company_options=company_options,
        want_dept=want_dept, want_company=want_company,
        filtered=bool(want_dept or want_company),
        want_cost=want_cost,
        named_cost=named_cost, named_unpriced=named_unpriced,
        local_cost=local_cost, local_unpriced=local_unpriced,
        local_company_cost=local_company_cost,
        short_turn_days=short_turn_days, sixth_days=sixth_days,
    )



# ── Local labor hours, per body (capture log #5, 2026-09-05) ─────────────────

def _local_labor_lines(show, create=True):
    """Every local labor line on the show, in schedule order, with its bodies.

    Returns ``[{day, calls: [{activity, lines: [{row, section, company,
    bodies}]}]}]`` — only days and calls that have at least one local labor
    line. A line's company is its section header's company when the header
    is bound to one; that is what the hours report uses to resolve OT/DT
    terms for a nameless line.
    """
    from crew_sections import walk
    from models import bodies_for
    days = []
    created = False
    for day in show.days:
        calls = []
        for act in day.activities:
            lines = []
            for row, l1, _l2 in walk(list(act.crew_rows)):
                if not row.is_local_labor:
                    continue
                before = len(row.bodies)
                bodies = bodies_for(row, create=create)
                created = created or len(row.bodies) != before
                lines.append({
                    "row": row,
                    "section": (l1.group_label if l1 is not None else "") or "",
                    "company": l1.company if l1 is not None and l1.company_id else None,
                    "bodies": bodies,
                })
            if lines:
                calls.append({"activity": act, "lines": lines})
        if calls:
            days.append({"day": day, "calls": calls})
    if created:
        db.session.commit()
    return days


@show_crew_bp.route("/<int:show_id>/crew/local-labor-hours")
def local_labor_hours(show_id):
    """Actual hours for local labor, one figure per BODY.

    The crew call keeps "Qty 6 · Lighting Hand · 10 hrs" — six interchangeable
    slots and one estimate — because that is how they are booked. Payroll
    needs six actuals, because that is how they leave.

    Laid out as a table in the Hours Report's language (Jason, 2026-09-08):
    one row per LINE, with that line's bodies as a strip of boxes inside one
    cell. One row per BODY would be the more obvious table and is the wrong
    one — MCDC26 would be 344 rows, and the line is the unit the crew is
    actually booked and invoiced in.

    Filters, options and the company/department a line belongs to are
    resolved exactly as `hours_report` resolves them, so the same filter
    means the same thing on both pages.
    """
    show = Show.query.get_or_404(show_id)
    nested = _local_labor_lines(show)

    want_dept    = (request.args.get("dept") or "").strip()
    want_company = (request.args.get("company") or "").strip()

    days, opts_dept, opts_company = [], set(), set()
    n_lines = n_bodies = n_recorded = 0
    est_total = actual_total = delta_total = 0.0

    for entry in nested:
        day, lines = entry["day"], []
        d_est = d_actual = d_delta = 0.0
        d_bodies = d_recorded = 0
        for call in entry["calls"]:
            act = call["activity"]
            for line in call["lines"]:
                row = line["row"]
                company = line["company"]
                # Same resolution as the report: the section header's company,
                # else the section label — a line with neither is "Unassigned"
                # there and reads the same here.
                co_name = company.name if company else (line["section"] or "")
                dept = (row.position_ref.department if row.position_ref else "") or ""
                if dept:
                    opts_dept.add(dept)
                if co_name:
                    opts_company.add(co_name)
                if want_dept and dept != want_dept:
                    continue
                if want_company and co_name != want_company:
                    continue

                bodies = line["bodies"]
                est_each = row.hours
                recorded = [b for b in bodies if b.actual_hours is not None]
                line_est = (est_each or 0) * len(bodies)
                line_actual = sum(b.actual_hours for b in recorded)
                # Δ against the bodies that HAVE a figure, never the whole
                # line — the same rule the Hours Report's Δ column follows,
                # so two recorded out of six reads +1.5 and not −38.5.
                line_delta = (line_actual - (est_each or 0) * len(recorded)
                              if recorded and est_each is not None else None)

                lines.append({
                    "row": row, "activity": act, "bodies": bodies,
                    "section": line["section"], "company": co_name, "dept": dept,
                    "est_each": est_each, "qty": len(bodies),
                    "est_total": line_est, "actual_total": line_actual,
                    "recorded": len(recorded), "delta": line_delta,
                })
                d_est += line_est
                d_actual += line_actual
                d_delta += line_delta or 0
                d_bodies += len(bodies)
                d_recorded += len(recorded)

        if lines:
            days.append({"day": day, "lines": lines, "est_total": d_est,
                         "actual_total": d_actual, "bodies": d_bodies,
                         "recorded": d_recorded, "delta": d_delta,
                         "blank": d_bodies - d_recorded})
            n_lines += len(lines)
            n_bodies += d_bodies
            n_recorded += d_recorded
            est_total += d_est
            actual_total += d_actual
            delta_total += d_delta

    return render_template(
        "shows/local_labor_hours.html", show=show, days=days,
        n_lines=n_lines, n_bodies=n_bodies, n_recorded=n_recorded,
        n_blank=n_bodies - n_recorded,
        est_total=est_total, actual_total=actual_total, delta_total=delta_total,
        avg_recorded=(actual_total / n_recorded) if n_recorded else None,
        dept_options=sorted(opts_dept), company_options=sorted(opts_company),
        want_dept=want_dept, want_company=want_company,
        filtered=bool(want_dept or want_company))


@show_crew_bp.route("/<int:show_id>/crew/local-labor-hours/day/<int:day_id>/fill",
                    methods=["POST"])
def local_labor_fill_day(show_id, day_id):
    """Fill every BLANK body on one day with its own line's estimate.

    The per-line button was the only way to do this, and a load-in day is
    twenty lines. Blanks only, for the same reason the line button is blanks
    only: a typed figure is an exception somebody recorded on purpose.
    """
    from models import ScheduleDay, bodies_for
    day = ScheduleDay.query.get_or_404(day_id)
    if day.show_id != show_id:
        return ("", 404)
    filled, skipped = 0, 0
    for act in day.activities:
        for row in act.crew_rows:
            if not row.is_local_labor:
                continue
            if row.hours is None:
                skipped += 1
                continue
            for b in bodies_for(row):
                if b.actual_hours is None:
                    b.actual_hours = float(row.hours)
                    filled += 1
    db.session.commit()
    if filled:
        flash(f"{filled} filled from the estimate on "
              f"{day.date.strftime('%a %b %-d') if day.date else 'that day'}."
              + (f" {skipped} line(s) had no estimate to copy." if skipped else ""),
              "success")
    else:
        flash("Nothing to fill — every body on that day already has hours."
              if not skipped else
              f"{skipped} line(s) on that day have no estimate to copy.",
              "info" if not skipped else "warning")
    return redirect(url_for("show_crew.local_labor_hours", show_id=show_id,
                            dept=request.form.get("dept") or None,
                            company=request.form.get("company") or None)
                    + f"#day-{day.id}")


def _body_in_show(body, show_id):
    return (body.crew_row is not None and body.crew_row.activity is not None
            and body.crew_row.activity.day is not None
            and body.crew_row.activity.day.show_id == show_id)


@show_crew_bp.route("/<int:show_id>/crew/local-labor-hours/body/<int:body_id>",
                    methods=["POST"])
def local_labor_body(show_id, body_id):
    """Save one body's actual hours. Blank clears it."""
    from models import CrewRowBody
    body = CrewRowBody.query.get_or_404(body_id)
    if not _body_in_show(body, show_id):
        return ("", 404)
    body.actual_hours = _to_float(request.form.get("actual_hours"))
    db.session.commit()
    if request.headers.get("X-Autosave"):
        return ("", 204)
    return redirect(url_for("show_crew.local_labor_hours", show_id=show_id))


@show_crew_bp.route("/<int:show_id>/crew/local-labor-hours/row/<int:row_id>/fill",
                    methods=["POST"])
def local_labor_fill(show_id, row_id):
    """Fill every BLANK body on a line with the line's estimate.

    Only blanks: a body already typed is an exception someone recorded on
    purpose, and a convenience button must not undo it.
    """
    from models import CrewRow, bodies_for
    row = CrewRow.query.get_or_404(row_id)
    if row.activity is None or row.activity.day is None \
            or row.activity.day.show_id != show_id or not row.is_local_labor:
        return ("", 404)
    est = row.hours
    n = 0
    if est is not None:
        for b in bodies_for(row):
            if b.actual_hours is None:
                b.actual_hours = float(est)
                n += 1
    db.session.commit()
    if request.headers.get("X-Autosave"):
        return ("", 204)
    if est is None:
        flash("That line has no estimated hours to copy.", "warning")
    else:
        flash(f"{n} filled with {est:g} hrs." if n else "Every body on that line already had hours.",
              "success" if n else "info")
    return redirect(url_for("show_crew.local_labor_hours", show_id=show_id)
                    + f"#row-{row.id}")


# ── Named crew actuals, typed on the Hours Report (Jason, 2026-09-07) ────────
#
# The report showed estimates and had nowhere to type what happened. Each day
# cell of the named table is now the input; it edits the same
# CrewRow.actual_hours the day page edits, so the two never disagree.

def _named_row_in_show(row, show_id):
    return (row is not None and row.activity is not None
            and row.activity.day is not None
            and row.activity.day.show_id == show_id
            and bool(row.crew_member_id) and not row.is_local_labor)


@show_crew_bp.route("/<int:show_id>/crew/hours/row/<int:row_id>", methods=["POST"])
def hours_row_actual(show_id, row_id):
    """Save one named-crew row's actual hours from the report. Blank clears."""
    from models import CrewRow
    row = CrewRow.query.get_or_404(row_id)
    if not _named_row_in_show(row, show_id):
        return ("", 404)
    row.actual_hours = _to_float(request.form.get("actual_hours"))
    db.session.commit()
    if request.headers.get("X-Autosave"):
        return ("", 204)
    return redirect(url_for("show_crew.hours_report", show_id=show_id))


@show_crew_bp.route("/<int:show_id>/crew/hours/company/fill", methods=["POST"])
def hours_company_fill(show_id):
    """Fill every BLANK named-crew cell in one company with its estimate.

    Only blanks — a typed actual is an exception someone recorded on
    purpose. ``company`` is the name as the report groups it; "" is the
    people with no company.
    """
    from crew_sections import walk
    show = Show.query.get_or_404(show_id)
    want = (request.form.get("company") or "").strip()
    n = 0
    for day in show.days:
        for act in day.activities:
            for row, _l1, _l2 in walk(list(act.crew_rows)):
                if row.is_local_labor or not row.crew_member_id:
                    continue
                cm = row.crew_member
                co = cm.company.name if (cm is not None and cm.company) else ""
                if co != want or row.actual_hours is not None or row.hours is None:
                    continue
                row.actual_hours = float(row.hours)
                n += 1
    db.session.commit()
    if request.headers.get("X-Autosave"):
        return jsonify({"filled": n})
    flash(f"{n} filled from the estimate." if n else "Nothing to fill — every day already has an actual.",
          "success" if n else "info")
    return redirect(url_for("show_crew.hours_report", show_id=show_id))


# ── Phase A: edit booking info on an existing assignment ─────────────────────

def _parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date_cls.fromisoformat(s)
    except ValueError:
        return None


def _set_if_present(obj, attr, form, key, transform=None):
    """Only update attr if the form key is in the request — lets booking
    page and travel page each post their own slice of fields without
    blanking the other's data."""
    if key not in form:
        return
    raw = form.get(key) or ""
    val = transform(raw) if transform else (raw.strip() or None)
    setattr(obj, attr, val)


def _to_float(s):
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


@show_crew_bp.route("/<int:show_id>/crew/assignment/<int:aid>/edit", methods=["POST"])
def edit_assignment(show_id, aid):
    a = ShowCrewAssignment.query.get_or_404(aid)
    if a.show_id != show_id:
        flash("Assignment doesn't belong to this show.", "danger")
        return redirect(url_for("show_crew.show_crew", show_id=show_id))
    f = request.form
    next_url = (f.get("next") or "").strip()

    # Booking fields (Booking Sheet form)
    _set_if_present(a, "booking_task",   f, "booking_task")
    _set_if_present(a, "role_override",  f, "role_override")
    _set_if_present(a, "travel_in_date", f, "travel_in_date", _parse_date)
    _set_if_present(a, "start_date",     f, "start_date",     _parse_date)
    _set_if_present(a, "end_date",       f, "end_date",       _parse_date)
    _set_if_present(a, "travel_out_date",f, "travel_out_date",_parse_date)
    # Travel fields (Travel page form)
    _set_if_present(a, "hotel_name",         f, "hotel_name")
    _set_if_present(a, "hotel_check_in",     f, "hotel_check_in",  _parse_date)
    _set_if_present(a, "hotel_check_out",    f, "hotel_check_out", _parse_date)
    _set_if_present(a, "hotel_confirmation", f, "hotel_confirmation")
    _set_if_present(a, "hotel_cost",         f, "hotel_cost",      _to_float)
    _set_if_present(a, "arrival_flight",     f, "arrival_flight")
    _set_if_present(a, "arrival_time",       f, "arrival_time")
    _set_if_present(a, "departure_flight",   f, "departure_flight")
    _set_if_present(a, "departure_time",     f, "departure_time")
    _set_if_present(a, "itinerary_link",     f, "itinerary_link")

    db.session.commit()
    flash(f"Saved {a.crew_member.display_label}.", "success")
    # Respect a posted `next=` (Travel page submits it) so we land back
    # where the user came from.
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("show_crew.show_crew", show_id=show_id))


# ── Phase A: TBD / open-slot CRUD ────────────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/slot/add", methods=["POST"])
def add_slot(show_id):
    show = Show.query.get_or_404(show_id)
    f = request.form
    pos_id = (f.get("position_id") or "").strip()
    slot = ShowOpenSlot(
        show_id          = show_id,
        position_id      = int(pos_id) if pos_id.isdigit() else None,
        placeholder_label= (f.get("placeholder_label") or "").strip() or None,
        booking_task     = (f.get("booking_task") or "").strip() or None,
        travel_in_date   = _parse_date(f.get("travel_in_date")),
        start_date       = _parse_date(f.get("start_date")),
        end_date         = _parse_date(f.get("end_date")),
        travel_out_date  = _parse_date(f.get("travel_out_date")),
        notes            = (f.get("notes") or "").strip() or None,
    )
    if not slot.position_id and not slot.placeholder_label:
        flash("Pick a Position OR enter a label for the slot.", "danger")
        return redirect(url_for("show_crew.show_crew", show_id=show_id))
    db.session.add(slot)
    db.session.commit()
    flash(f"Added TBD slot: {slot.display_title}.", "success")
    return redirect(url_for("show_crew.show_crew", show_id=show_id))


@show_crew_bp.route("/<int:show_id>/crew/slot/<int:sid>/edit", methods=["POST"])
def edit_slot(show_id, sid):
    slot = ShowOpenSlot.query.get_or_404(sid)
    if slot.show_id != show_id:
        flash("Slot doesn't belong to this show.", "danger")
        return redirect(url_for("show_crew.show_crew", show_id=show_id))
    f = request.form
    pos_id = (f.get("position_id") or "").strip()
    slot.position_id      = int(pos_id) if pos_id.isdigit() else None
    slot.placeholder_label= (f.get("placeholder_label") or "").strip() or None
    slot.booking_task     = (f.get("booking_task") or "").strip() or None
    slot.travel_in_date   = _parse_date(f.get("travel_in_date"))
    slot.start_date       = _parse_date(f.get("start_date"))
    slot.end_date         = _parse_date(f.get("end_date"))
    slot.travel_out_date  = _parse_date(f.get("travel_out_date"))
    slot.notes            = (f.get("notes") or "").strip() or None
    db.session.commit()
    flash("Slot updated.", "success")
    return redirect(url_for("show_crew.show_crew", show_id=show_id))


@show_crew_bp.route("/<int:show_id>/crew/slot/<int:sid>/delete", methods=["POST"])
def delete_slot(show_id, sid):
    slot = ShowOpenSlot.query.get_or_404(sid)
    if slot.show_id != show_id:
        flash("Slot doesn't belong to this show.", "danger")
        return redirect(url_for("show_crew.show_crew", show_id=show_id))
    db.session.delete(slot)
    db.session.commit()
    flash("Slot removed.", "success")
    return redirect(url_for("show_crew.show_crew", show_id=show_id))


@show_crew_bp.route("/<int:show_id>/crew/slot/<int:sid>/fill", methods=["POST"])
def fill_slot(show_id, sid):
    """Convert a TBD slot into a real ShowCrewAssignment, carrying the
    slot's booking_task and date window over to the new assignment."""
    slot = ShowOpenSlot.query.get_or_404(sid)
    if slot.show_id != show_id:
        flash("Slot doesn't belong to this show.", "danger")
        return redirect(url_for("show_crew.show_crew", show_id=show_id))
    cm_id = (request.form.get("crew_member_id") or "").strip()
    if not cm_id.isdigit():
        flash("Pick a crew member to fill this slot.", "danger")
        return redirect(url_for("show_crew.show_crew", show_id=show_id))

    # Don't double-assign the same person to the same show
    existing = ShowCrewAssignment.query.filter_by(
        show_id=show_id, crew_member_id=int(cm_id)).first()
    if existing:
        # Just merge the slot's booking info into the existing assignment
        existing.booking_task    = existing.booking_task    or slot.booking_task
        existing.travel_in_date  = existing.travel_in_date  or slot.travel_in_date
        existing.start_date      = existing.start_date      or slot.start_date
        existing.end_date        = existing.end_date        or slot.end_date
        existing.travel_out_date = existing.travel_out_date or slot.travel_out_date
    else:
        db.session.add(ShowCrewAssignment(
            show_id          = show_id,
            crew_member_id   = int(cm_id),
            booking_task     = slot.booking_task,
            travel_in_date   = slot.travel_in_date,
            start_date       = slot.start_date,
            end_date         = slot.end_date,
            travel_out_date  = slot.travel_out_date,
        ))
    db.session.delete(slot)
    db.session.commit()
    flash("Slot filled.", "success")
    return redirect(url_for("show_crew.show_crew", show_id=show_id))



# ── Phase B: Travel page (per-crew hotel + flight detail) ────────────────────

def _travel_assignments_sorted(show_id, sort_by="check_in"):
    """Return this show's assignments in the given sort order."""
    items = ShowCrewAssignment.query.filter_by(show_id=show_id).all()

    def _name(a):
        return (a.crew_member.last_name or "").lower() if a.crew_member else ""
    def _company(a):
        cm = a.crew_member
        return (cm.company.name or "").lower() if cm and cm.company else "zzz"
    def _position(a):
        cm = a.crew_member
        return (cm.position.title or "").lower() if cm and cm.position else "zzz"
    def _order(a):   # canonical Crew Database order (#29)
        cm = a.crew_member
        return cm.sort_order if (cm and cm.sort_order is not None) else 10**9

    if sort_by == "company":
        items.sort(key=lambda a: (_company(a), _order(a), _name(a)))
    elif sort_by == "name":
        items.sort(key=_name)
    elif sort_by == "position":
        items.sort(key=lambda a: (_position(a), _name(a)))
    else:   # check_in — default (None → bottom, then by name)
        # Check-in now mirrors the shared Travel In date.
        items.sort(key=lambda a: (a.travel_in_date or date_cls.max, _name(a)))
    return items


def _company_name(a):
    """Display name of an assignment's company ('No Company' when unset)."""
    cm = a.crew_member
    return cm.company.name if cm and cm.company else "No Company"


def _company_counts(assignments):
    """{company_name: traveler_count} for the on-screen company banners."""
    counts = {}
    for a in assignments:
        name = _company_name(a)
        counts[name] = counts.get(name, 0) + 1
    return counts


@show_crew_bp.route("/<int:show_id>/crew/travel")
def travel(show_id):
    show = Show.query.get_or_404(show_id)
    sort_by = (request.args.get("sort") or "check_in").strip().lower()
    if sort_by not in ("check_in", "name", "company", "position"):
        sort_by = "check_in"
    assignments = _travel_assignments_sorted(show_id, sort_by)
    grand_total  = sum((a.hotel_cost or 0) for a in assignments)
    grand_nights = sum((a.stay_nights or 0) for a in assignments)
    return render_template("shows/show_crew_travel.html",
                           show=show,
                           assignments=assignments,
                           grand_total=grand_total,
                           grand_nights=grand_nights,
                           company_counts=_company_counts(assignments),
                           sort_by=sort_by)


@show_crew_bp.route("/<int:show_id>/crew/travel/bulk-dates", methods=["POST"])
def travel_bulk_dates(show_id):
    """Set Travel-In / Show-in (start) / Show-out (end) / Travel-Out on many
    crew at once. Larry's request: 'Select specific crew members or ALL, and
    set travel in, show, travel out dates for several or all crew at once.'

    Only the date fields that are actually filled in the toolbar are applied;
    blank fields leave each row's existing value alone (so you can push just a
    travel-in date to a group without wiping their return dates). Every write
    goes through the normal SQLAlchemy path, so the audit log captures it and
    it's undoable from Recent Activity."""
    Show.query.get_or_404(show_id)
    f = request.form

    # Which rows? Support checkbox lists posted as assignment_ids.
    raw_ids = f.getlist("assignment_ids")
    ids = set()
    for r in raw_ids:
        try:
            ids.add(int(r))
        except (TypeError, ValueError):
            continue

    # Map of model-attr → parsed date, keeping only non-empty values.
    field_map = {
        "travel_in_date":  _parse_date(f.get("travel_in_date")),
        "start_date":      _parse_date(f.get("start_date")),
        "end_date":        _parse_date(f.get("end_date")),
        "travel_out_date": _parse_date(f.get("travel_out_date")),
    }
    updates = {k: v for k, v in field_map.items() if v is not None}

    sort_by = (f.get("sort") or "check_in").strip().lower()
    if sort_by not in ("check_in", "name", "company", "position"):
        sort_by = "check_in"
    back = url_for("show_crew.travel", show_id=show_id, sort=sort_by)

    if not ids:
        flash("No crew selected — pick at least one row, then apply.", "warning")
        return redirect(back)
    if not updates:
        flash("No dates entered — fill at least one date field, then apply.", "warning")
        return redirect(back)

    # Only touch assignments that belong to THIS show (defensive).
    rows = (ShowCrewAssignment.query
            .filter(ShowCrewAssignment.show_id == show_id,
                    ShowCrewAssignment.id.in_(ids))
            .all())
    n = 0
    for a in rows:
        for attr, val in updates.items():
            setattr(a, attr, val)
        n += 1
    db.session.commit()

    which = ", ".join(k.replace("_date", "").replace("_", " ") for k in updates)
    flash(f"Updated {which} on {n} crew member{'' if n == 1 else 's'}. "
          f"Undo from Recent Activity if needed.", "success")
    return redirect(back)



# ── Drag-to-reorder on the Booking Sheet ─────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/reorder", methods=["POST"])
def reorder(show_id):
    """
    Bulk-update sort_order from a drag-and-drop reorder within a booking-task
    card. Accepts JSON:
       { "items": [{"type": "a"|"s", "id": <int>}, ...] }
    Assigns sort_order = idx * 10 to each item in the given order. Rows
    from a different show are ignored defensively.
    """
    from flask import jsonify
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not isinstance(items, list):
        return jsonify(ok=False, error="items must be a list"), 400
    n = 0
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        kind = it.get("type")
        try:
            rid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if kind == "a":
            obj = ShowCrewAssignment.query.get(rid)
        elif kind == "s":
            obj = ShowOpenSlot.query.get(rid)
        else:
            continue
        if obj and obj.show_id == show_id:
            obj.sort_order = idx * 10
            n += 1
    db.session.commit()
    return jsonify(ok=True, count=n)



# ── Contact sheet + Travel exports (XLSX / PDF) ──────────────────────────────
import io as _io
from flask import send_file


def _xlsx_response(wb, filename):
    """Serialize an openpyxl Workbook and stream it as a download."""
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _slugify(s):
    return "".join(c if c.isalnum() else "_" for c in (s or "")).strip("_")


@show_crew_bp.route("/<int:show_id>/crew/contact-sheet.xlsx")
def contact_sheet_xlsx(show_id):
    """Same data as the on-screen contact sheet, delivered as XLSX."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill

    show = Show.query.get_or_404(show_id)
    assignments = (
        db.session.query(ShowCrewAssignment)
        .join(CrewMember, ShowCrewAssignment.crew_member_id == CrewMember.id)
        .outerjoin(Position, CrewMember.position_id == Position.id)
        .filter(ShowCrewAssignment.show_id == show_id, CrewMember.active == True)
        .order_by(*crew_order_by())
        .all()
    )
    # Group by company (same as the HTML view)
    companies = {}
    for a in assignments:
        cm = a.crew_member
        co_name = cm.company.name if cm.company else "No Company"
        co_id   = cm.company_id or 0
        companies.setdefault(co_id, {"name": co_name, "crew": []})["crew"].append(cm)
    sorted_companies = sorted(companies.values(), key=lambda c: c["name"])

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contact Sheet"
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1A1A1A")
    company_fill = PatternFill("solid", fgColor="F5F5F5")

    # Title row
    ws.append([f"{show.code or ''}   {show.name}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Crew Contact Sheet   ·   "
               f"{show.venue.name + ' — ' + show.venue.city if show.venue else ''}"])
    ws.append([])

    headers = ["Name", "Position", "Department", "Phone", "Email"]
    for co in sorted_companies:
        # Company banner
        ws.append([f"{co['name']}   —   {len(co['crew'])} member(s)"])
        row = ws.max_row
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(headers))
        ws.cell(row=row, column=1).font = header_font
        ws.cell(row=row, column=1).fill = header_fill

        # Header row
        ws.append(headers)
        for c in range(1, len(headers) + 1):
            ws.cell(row=ws.max_row, column=c).font = Font(bold=True, size=9)
            ws.cell(row=ws.max_row, column=c).fill = company_fill

        # Data
        for cm in co["crew"]:
            ws.append([
                cm.display_label,
                cm.position.title if cm.position else "",
                cm.position.department if cm.position else "",
                cm.phone or "",
                cm.email or "",
            ])
        ws.append([])

    # Column widths
    widths = [22, 18, 14, 15, 34]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = w

    fname = f"{_slugify(show.code or show.name)}_contact_sheet.xlsx"
    return _xlsx_response(wb, fname)


@show_crew_bp.route("/<int:show_id>/crew/travel.xlsx")
def travel_xlsx(show_id):
    """Travel table as XLSX, respecting the ?sort= query param."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    show = Show.query.get_or_404(show_id)
    sort_by = (request.args.get("sort") or "check_in").strip().lower()
    if sort_by not in ("check_in", "name", "company", "position"):
        sort_by = "check_in"
    assignments = _travel_assignments_sorted(show_id, sort_by)
    company_counts = _company_counts(assignments)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Travel"

    ws.append([f"{show.code or ''}   {show.name}   —   Travel"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Sorted by: {sort_by.replace('_', ' ')}"])
    ws.append([])

    headers = ["Name", "Company", "Position", "Booking Task",
               "Hotel", "Check In", "Check Out", "Nights",
               "Conf #", "Cost",
               "Arr Flight #", "Arr Time", "Dep Flight #", "Dep Time",
               "Itinerary"]

    def _write_header_row():
        ws.append(headers)
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=ws.max_row, column=c)
            cell.font = Font(bold=True, color="FFFFFF", size=10)
            cell.fill = PatternFill("solid", fgColor="1A1A1A")

    company_banner = (sort_by == "company")
    company_fill = PatternFill("solid", fgColor="F5F5F5")

    if not company_banner:
        _write_header_row()

    cur_company = None
    for a in assignments:
        cm = a.crew_member
        # When sorted by company, emit a section banner + header row on change,
        # mirroring the Crew Contact Sheet layout.
        if company_banner:
            co_name = _company_name(a)
            if co_name != cur_company:
                cur_company = co_name
                n = company_counts.get(co_name, 0)
                ws.append([f"{co_name}   —   {n} traveler{'' if n == 1 else 's'}"])
                brow = ws.max_row
                ws.merge_cells(start_row=brow, start_column=1,
                               end_row=brow, end_column=len(headers))
                bcell = ws.cell(row=brow, column=1)
                bcell.font = Font(bold=True, color="FFFFFF")
                bcell.fill = PatternFill("solid", fgColor="1A1A1A")
                _write_header_row()
        ws.append([
            cm.display_label if cm else "",
            cm.company.name if cm and cm.company else "",
            cm.position.title if cm and cm.position else "",
            a.booking_task or "",
            a.hotel_name or "",
            a.travel_in_date.isoformat() if a.travel_in_date else "",
            a.travel_out_date.isoformat() if a.travel_out_date else "",
            a.stay_nights if a.stay_nights is not None else "",
            a.hotel_confirmation or "",
            a.hotel_cost if a.hotel_cost is not None else "",
            a.arrival_flight or "",
            a.arrival_time or "",
            a.departure_flight or "",
            a.departure_time or "",
            a.itinerary_link or "",
        ])

    # Grand total rows: hotel cost + hotel nights
    grand        = sum((a.hotel_cost or 0) for a in assignments)
    grand_nights = sum((a.stay_nights or 0) for a in assignments)
    ws.append([])
    cost_row = ws.max_row + 1
    ws.cell(row=cost_row, column=9, value="Grand-total hotel cost:").font = Font(bold=True)
    ws.cell(row=cost_row, column=10, value=grand).font = Font(bold=True)
    nights_row = cost_row + 1
    ws.cell(row=nights_row, column=7, value="Grand-total hotel nights:").font = Font(bold=True)
    ws.cell(row=nights_row, column=8, value=grand_nights).font = Font(bold=True)

    widths = [22, 18, 18, 14,   22, 12, 12, 8, 18, 12,   16, 10, 16, 10, 40]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = w

    fname = f"{_slugify(show.code or show.name)}_travel.xlsx"
    return _xlsx_response(wb, fname)


@show_crew_bp.route("/<int:show_id>/crew/travel/print")
def travel_print(show_id):
    """Print-friendly Travel view. Renders the same on-screen page with a
    print stylesheet that hides the sidebar/nav/buttons. Users hit Cmd+P
    (Ctrl+P on Windows) to save as PDF via their browser.

    Replaces the previous WeasyPrint route, which failed on PythonAnywhere
    because Pango/GObject native libs aren't installed there. Browser-side
    printing is portable, reliable, and needs no server deps."""
    show = Show.query.get_or_404(show_id)
    sort_by = (request.args.get("sort") or "check_in").strip().lower()
    if sort_by not in ("check_in", "name", "company", "position"):
        sort_by = "check_in"
    assignments = _travel_assignments_sorted(show_id, sort_by)
    grand_total  = sum((a.hotel_cost or 0) for a in assignments)
    grand_nights = sum((a.stay_nights or 0) for a in assignments)
    return render_template(
        "shows/show_crew_travel.html",
        show=show,
        assignments=assignments,
        grand_total=grand_total,
        grand_nights=grand_nights,
        company_counts=_company_counts(assignments),
        sort_by=sort_by,
        print_mode=True,
    )


# ── Note 4: add someone to the roster without leaving the day editor ─────────

@show_crew_bp.route("/<int:show_id>/crew/quick-add", methods=["POST"])
def quick_add(show_id):
    """Put a person on this show's roster and hand back their new option.

    The crew-call dropdown is roster-only, so there has to be a way to add a
    missing person from inside the day editor. Navigating to the roster page
    and back would lose the user's place mid-edit on an autosaving form —
    which is the same shape as the blank-time data-loss bug — so this returns
    JSON and the page splices the option in.

    Accepts either an existing ``crew_member_id`` or a new ``first_name`` /
    ``last_name`` (+ optional company and position).
    """
    show = Show.query.get_or_404(show_id)
    f = request.form

    cm = None
    if f.get("crew_member_id"):
        cm = CrewMember.query.get(int(f["crew_member_id"]))
        if cm is None:
            return jsonify(ok=False, error="That crew member no longer exists."), 404
    else:
        first = (f.get("first_name") or "").strip()
        last = (f.get("last_name") or "").strip()
        # No name at all is allowed ONLY when company or position says what the
        # slot is for — that is an unfilled slot ("SPARKS Lead Rigger"), not a
        # typo. A blank record with nothing on it would render as bare "TBD"
        # and tell a reader nothing, so that is still rejected.
        if not first and not last and not (f.get("company_id")
                                           or f.get("position_id")):
            return jsonify(
                ok=False,
                error="Give a name, or a company/position for an unfilled slot."
            ), 400
        cm = CrewMember(
            first_name=first or "TBD",
            last_name=last or "TBD",
            company_id=int(f["company_id"]) if f.get("company_id") else None,
            position_id=int(f["position_id"]) if f.get("position_id") else None,
            active=True,
        )
        db.session.add(cm)
        db.session.flush()

    existing = ShowCrewAssignment.query.filter_by(
        show_id=show.id, crew_member_id=cm.id).first()
    if existing is None:
        # sort_order stays NULL so the new person slots into the Crew Database
        # position rather than landing at the bottom — Jason's call, 2026-08-11.
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.commit()

    label = cm.display_label
    if cm.position:
        label = f"{label} — {cm.position.title}"
    return jsonify(ok=True, id=cm.id, label=label,
                   position=cm.position.title if cm.position else "",
                   already_on_roster=existing is not None)


@show_crew_bp.route("/<int:show_id>/crew/reset-order", methods=["POST"])
def reset_roster_order(show_id):
    """Drop every manual roster position and fall back to the Crew Database.

    Recovery hatch. Roster order is a derived-ish thing — the Crew Database is
    the seed — so a scrambled roster is always recoverable by clearing the
    manual overrides rather than restoring a backup. Added after a header drag
    wrote the roster on 2026-08-11 and reordered every crew call in the show.
    """
    show = Show.query.get_or_404(show_id)
    n = 0
    for a in ShowCrewAssignment.query.filter_by(show_id=show.id).all():
        if a.sort_order is not None:
            a.sort_order = None
            n += 1
    db.session.commit()
    flash(f"Roster order reset to Crew Database order ({n} manual "
          f"position{'s' if n != 1 else ''} cleared).", "success")
    return redirect(url_for("show_crew.show_crew", show_id=show.id))

"""
One source of truth for the OSS master timeline.

The Master tab, the XLSX export and the client PDF must never disagree about
what is on the schedule. Previously the timeline was assembled inline inside
the oss_hub route; anything else wanting the same data had to rebuild it, and
rebuilt copies drift (exactly how the F&B tab and the master came to disagree).
Everything that renders the master now calls build_master_items() here.

An item is a plain dict so templates, openpyxl and ReportLab can all consume it
without knowing about the ORM:

    day_id, day, sort_time (int minutes), time (display str),
    icon, dept, activity, count, duration_hrs, notes, source
"""
import re
from datetime import date as _date_cls

from breaks import break_export_text, is_crew_start
from local_labor import line_label
from time_utils import sort_minutes, UNKNOWN as UNKNOWN_GUARD

# Undated rows sort after every real day rather than jumping to the top.
DATE_MAX = _date_cls.max

# Non-department sources that also appear on the master timeline.
SOURCE_OSS = "oss"
SOURCE_MEAL = "meal"
SOURCE_ACTIVITY = "activity"
SOURCE_CREW = "crew"
SOURCE_HARDCODED = "hardcoded"

# Head-count wording. "pax" is a travel/hospitality term and reads wrong in AV
# production, so it is gone. Kept in ONE place because the XLSX, the PDF and the
# Master tab all print it and must agree — change the word here, not in three
# files. F&B counts people being fed rather than people called, hence the split.
COUNT_NOUNS = {"Crew": "crew", "F&B": "people"}


def count_label(dept, count):
    """'11 crew' / '18 people' for departments that carry a head count."""
    noun = COUNT_NOUNS.get(dept)
    if not noun or not count:
        return ""
    return f"{count} {noun}"


def master_label(item):
    """What the timeline shows on the row itself.

    A crew call reads as a headcount; the names follow underneath, one per row
    (note 5). Lives here rather than in one exporter because the XLSX and the
    PDF used to disagree about this exact row — the XLSX printed a headcount
    while the PDF printed a comma-joined list of every name.
    """
    if item.get("source") == SOURCE_CREW and item.get("count"):
        n = item["count"]
        return "1 crew called" if n == 1 else f"{n} crew called"
    return item.get("activity") or "—"


# Department accent colours, shared by the XLSX and the PDF so the two read as
# one system. Every entry pairs a colour with a short TEXT label: these get
# printed in black and white constantly, and hue alone doesn't survive that.
# Emoji are deliberately absent — ReportLab's built-in fonts can't render them.
DEPARTMENT_STYLE = {
    "Schedule":     {"hex": "1F2937", "short": "SCHED"},
    "Crew":         {"hex": "0F766E", "short": "CREW"},
    "Dock":         {"hex": "B45309", "short": "DOCK"},
    "Haze":         {"hex": "6D28D9", "short": "HAZE"},
    "Doors":        {"hex": "1D4ED8", "short": "DOOR"},
    "Security":     {"hex": "991B1B", "short": "SEC"},
    "F&B":          {"hex": "15803D", "short": "F&B"},
    "House Lights": {"hex": "A16207", "short": "LX"},
    "HVAC / AC":    {"hex": "0E7490", "short": "HVAC"},
    "Wristbands":   {"hex": "BE185D", "short": "BAND"},
    "COMS":         {"hex": "4338CA", "short": "COMS"},
    "Cleaning":     {"hex": "525252", "short": "CLEAN"},
    "Hard-Coded":   {"hex": "92400E", "short": "FIXED"},
}
DEFAULT_STYLE = {"hex": "334155", "short": ""}


def department_style(dept):
    """Colour + short label for a department, with a safe fallback."""
    return DEPARTMENT_STYLE.get(dept_label(dept), DEFAULT_STYLE)


def dept_label(value):
    """Display label for a department, given either its stored type key or an
    already-resolved label.

    Three departments store a type that differs from what users see —
    Hazer/Haze, House LX/House Lights, HVAC/HVAC / AC. OSS entries surface the
    LABEL while hard-coded events store the TYPE, so without normalising here
    the same department shows up twice on the master and would produce two
    separate sheets in the export.
    """
    from models import SUB_SCHEDULE_META
    meta = SUB_SCHEDULE_META.get(value)
    return meta.get("label", value) if meta else value


def _item(day, time_value, dept, activity, *, icon="•", count=None, kind="act",
          duration_hrs=None, notes="", source=SOURCE_OSS, day_id=None,
          end_time=None, break_label=None, break_call_id=None,
          break_call_time=None):
    """One master-timeline row. sort_time is minutes-since-midnight so every
    source lands on ONE comparable scale — string compares put '1:00 PM'
    after '18:00' and sink afternoon rows to the bottom of the day."""
    return {
        "day_id":       day_id if day_id is not None else (day.id if day else None),
        "day":          day,
        "sort_time":    sort_minutes(time_value),
        "time":         time_value or "",
        # When the row ENDS, where that is known. `time` stays the start so
        # sort_time still parses — a range in that field would sink the row to
        # the bottom of its day.
        "end_time":     end_time or None,
        # Set on break rows so `_collapse_crew_breaks` can group sittings from
        # the record rather than regexing them back out of a display string.
        "break_label":     break_label,
        "break_call_id":   break_call_id,
        "break_call_time": break_call_time,
        "icon":         icon,
        # Interface Spec §07/§09. The row kind, decided HERE — at the one
        # place that actually knows what each row is — rather than re-derived
        # by each exporter from a display string. brand.KIND_CODE turns it
        # into the two letters that print.
        "kind":         kind,
        "dept":         dept,
        "activity":     activity or "",
        "count":        count,
        "duration_hrs": duration_hrs,
        "notes":        notes or "",
        "source":       source,
    }


def _sort_key(item):
    day = item["day"]
    return (day.date if day and day.date else DATE_MAX, item["sort_time"])


def _qty(value):
    """A local-labour line's headcount, read the way line_label() reads it.

    Same coercion, deliberately — the number in "14 × Rigger" and the number
    added into the call's headcount must be the same number, and they came
    from two different readings of the same field once already.
    """
    try:
        n = int(value or 1)
    except (TypeError, ValueError):
        n = 1
    return n if n >= 1 else 1


CREW_BREAK_RE = re.compile(
    r'^(?P<base>.+?)\s*[—–-]\s*(?P<call>\d{1,2}:\d{2}\s*(?:[AP]\.?M\.?)?)\s+CREW\s*$',
    re.I)


def _merge_text(*candidates):
    """The most informative of several descriptions — the longest non-empty.

    A linked pair usually says the same thing at different lengths, e.g.
    "CL Truss/LX Truck 1&2 - 53' Semi" against "CL Truss/LX Truck 1&2 at Dock
    00 - Two (2) 53' Semi". The longer text is the one worth keeping.
    """
    texts = [str(c).strip() for c in candidates if c and str(c).strip()]
    return max(texts, key=len) if texts else ""


def _merge_notes(*candidates):
    """Union of several note fields, order-preserving, no repeats."""
    out = []
    for c in candidates:
        text = (c or "").strip()
        if text and text not in out:
            out.append(text)
    return " · ".join(out)


def _collapse_crew_breaks(items):
    """One row per break period instead of one per crew start.

    The break builder emits a separate activity per crew start — "COFFEE BREAK
    — 07:00 CREW" at 09:30 and "COFFEE BREAK — 08:00 CREW" at 10:30. On an
    11-day show that quadrupled every break period. These collapse to a single
    row at the earliest time, carrying every call time in the notes so the
    staggering is still legible.

    Deliberately narrow: only activities matching the generated
    "<name> — <time> CREW" pattern are touched. Anything hand-written is left
    exactly as it is.
    """
    keep, groups = [], {}
    for item in items:
        if item.get("break_label"):
            # A real CrewBreak. Group from the record, and split when two
            # sittings come off the same crew call — one crew taking two
            # breaks of the same name is two periods, exactly as the day page
            # reads it. `seq` is how many of this label that call already has.
            bucket = [k for k in groups
                      if k[0] == item["day_id"] and k[1] == item["break_label"]]
            seq = sum(1 for k in bucket
                      for m, _c, _b in groups[k]
                      if m.get("break_call_id") == item.get("break_call_id")
                      and item.get("break_call_id") is not None)
            key = (item["day_id"], item["break_label"], seq)
            groups.setdefault(key, []).append(
                (item, item.get("break_call_time") or "", item["activity"]))
            continue
        match = (CREW_BREAK_RE.match(item["activity"] or "")
                 if item["source"] == SOURCE_ACTIVITY else None)
        if not match:
            keep.append(item)
            continue
        # Legacy path: a show not switched over has no records, so the only
        # evidence of a sitting is the builder's "<name> — <time> CREW" stamp.
        key = (item["day_id"], match.group("base").strip().upper(), 0)
        groups.setdefault(key, []).append(
            (item, match.group("call").strip(), match.group("base").strip()))

    for (_day_id, base, _seq), members in groups.items():
        members.sort(key=lambda pair: pair[0]["sort_time"])
        first = dict(members[0][0])
        first["activity"] = members[0][2] or base.title()
        detail = ", ".join(f"{call} crew {_fmt_12h(m['time'])}"
                           for m, call, _b in members if call)
        first["notes"] = _merge_notes(first["notes"], detail) \
            if (len(members) > 1 and detail) else first["notes"]
        first["collapsed_calls"] = [call for _m, call, _b in members]
        # The period feeds every sitting, not just the earliest one. Taking the
        # first member's count wholesale printed "11 crew" against a lunch that
        # stops 21.
        counts = [m["count"] for m, _call, _b in members
                  if m.get("count") is not None]
        first["count"] = sum(counts) if counts else first.get("count")
        keep.append(first)
    return keep


def time_range_text(item, fmt=None):
    """A row's time for a document: ``12:00 – 13:00`` when it has an end.

    ONE definition, so the XLSX, the PDF and the Master tab cannot disagree
    about a break's window the way they once disagreed about a crew row.
    ``fmt`` formats a single time for that surface — 12-hour on screen, brand
    formatting in the PDF — because only the caller knows which it wants.
    """
    f = fmt if fmt is not None else (lambda v: v or "")
    start = f(item.get("time")) or ""
    end = item.get("end_time")
    if not end:
        return start
    return f"{start} – {f(end) or ''}".strip()


def _fmt_12h(value):
    """'13:00' -> '1:00 PM'. Presentation only; storage stays 24-hour."""
    mins = sort_minutes(value)
    if mins >= UNKNOWN_GUARD:
        return value or ""
    h, m = divmod(mins, 60)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def build_master_items(show, entries, meal_services):
    """Assemble the full per-show master timeline.

    Returns (master_items, hardcoded_by_dept). `entries` are the show's
    SubScheduleEntry rows and `meal_services` its MealService rows — passed in
    so the caller controls querying and we don't hit the DB twice per page.

    An OSS entry or meal linked to an activity IS that activity with
    departmental detail attached, so the two are merged into a single row
    rather than both being listed. Before this, 18% of rows on a real 11-day
    show were the same event printed twice — 33 of them character-identical.
    """
    from models import SUB_SCHEDULE_TYPES, CrewBreak
    from hardcoded_service import overlay_for_day

    # Queried here rather than passed in: unlike entries and meal services,
    # no caller already holds these, and it is one query for the whole export.
    # Empty for any show not switched over, which then prints exactly as before.
    crew_breaks = {cb.activity_id: cb
                   for cb in CrewBreak.query.filter_by(show_id=show.id).all()}

    items = []
    # activity_id -> the department rows that claim that activity
    claimed = {}
    for e in entries:
        if e.activity_id:
            claimed.setdefault(e.activity_id, []).append(("entry", e))
    for svc in meal_services:
        if svc.activity_id:
            claimed.setdefault(svc.activity_id, []).append(("meal", svc))


    # ── Department OSS entries ──────────────────────────────────────────
    for e in entries:
        meta = e.meta
        act = e.linked_activity if e.activity_id else None
        items.append(_item(
            e.schedule_day, e.effective_time,
            meta.get("label", e.type),
            _merge_text(e.activity, act.description if act else None),
            icon=meta.get("icon", "•"), count=e.count,
            duration_hrs=e.duration_hrs,
            notes=_merge_notes(e.notes, act.notes if act else None),
            source=SOURCE_OSS, day_id=e.schedule_day_id,
        ))

    # ── F&B v2: one row per location, or one row if a service has none ──
    for svc in meal_services:
        act = svc.linked_activity if svc.activity_id else None
        for loc in (svc.locations_ordered or [None]):
            label = svc.name + (f" · {loc.location_name}"
                                if loc and loc.location_name else "")
            items.append(_item(
                svc.schedule_day,
                (loc.start_time if loc else svc.earliest_time),
                "F&B", _merge_text(label, act.description if act else None),
                icon="🍽",
                # A standing beverage table is not a stop; a meal service is.
                # The `or is_recurring` belt-and-braces is gone: since
                # 2026-08-13 `is_standing` reads breaks.is_beverage_service,
                # which already tests is_recurring along with the kind and the
                # name. Keeping the fallback would have hidden the fact that
                # the property was wrong.
                kind=("bev" if getattr(svc, "is_standing", None) else "break"),
                # effective_headcount, not headcount: an export must carry the
                # number F&B is actually working to, which is the crew call
                # unless somebody has deliberately typed over it.
                count=(loc.effective_headcount if loc else svc.total_headcount or None),
                notes=_merge_notes((loc.notes if loc else None), svc.notes,
                                   act.notes if act else None),
                source=SOURCE_MEAL, day_id=svc.schedule_day_id,
            ))


    # ── #39: day activities + crew call times. An activity already carried
    # by a linked department row is skipped — it was merged in above.
    for d in show.days:
        crew_by_time = {}
        # Local labour is kept in a SEPARATE list from the moment it is read.
        # It used to be appended to `names`, so "14 × Rigger" and "Ann One"
        # were the same shape everywhere downstream — one indented row under
        # "N crew called" on the master, in the PDF and in the XLSX. Fourteen
        # humans and one human, indistinguishable on the page.
        local_by_time = {}
        for a in d.activities:
            if a.id not in claimed:
                cb = crew_breaks.get(a.id)
                if cb is not None:
                    # A break prints as what it is, with the same text and the
                    # same window the day page shows.
                    items.append(_item(
                        d, a.time, "Schedule",
                        break_export_text(cb.label, cb.duration_minutes),
                        icon="☕", kind="break", count=cb.derived_headcount,
                        end_time=cb.end_time or None,
                        break_label=(cb.label or "BREAK").strip().upper(),
                        break_call_id=cb.crew_call_id,
                        break_call_time=(cb.crew_call.time if cb.crew_call else None),
                        notes=a.notes, source=SOURCE_ACTIVITY))
                else:
                    items.append(_item(d, a.time, "Schedule", a.description,
                                       icon="🗓", notes=a.notes,
                                       kind=("crew" if is_crew_start(a.description)
                                             else "act"),
                                       source=SOURCE_ACTIVITY))
            # Crew on a Crew Start all share that event's call time.
            if is_crew_start(a.description):
                names = crew_by_time.setdefault(a.time or "", [])
                local = local_by_time.setdefault(a.time or "", [])
                for row in a.ordered_crew_rows:
                    if row.is_group_header:
                        continue
                    if row.crew_member_id:
                        cm = row.crew_member
                        who = cm.display_label if cm else (row.name_override or "TBD")
                        if who not in names:
                            names.append(who)
                        continue
                    # LOCAL LABOUR (2026-08-12). A row with no crew member is
                    # a COUNT of a position — "14 × Rigger". It used to be
                    # skipped entirely, so eighteen lighting hands appeared
                    # nowhere on the client master and the headcount beside
                    # the call counted only the named leads.
                    #
                    # Not deduplicated, unlike names: two lines of the same
                    # position at the same call time are two different crews
                    # doing two different tasks, and merging them would lose
                    # the count.
                    if row.position or row.position_id:
                        title = row.position or (row.position_ref.title
                                                 if row.position_ref else None)
                        local.append({
                            "label":    line_label(title, row.qty, row.task),
                            "qty":      _qty(row.qty),
                            "position": (title or "Crew"),
                            "task":     (row.task or "").strip(),
                        })

        # #47 — one grouped Crew row per distinct call time, not one per person.
        for t, names in crew_by_time.items():
            local = local_by_time.get(t, [])
            # A call can be ENTIRELY local labour — four riggers and no named
            # lead. Testing `names` alone used to be enough only because the
            # local lines were in it.
            if not names and not local:
                continue
            # HEADCOUNT, not line count. A local labour line is one row but N
            # people on site, and this number is what the client master prints
            # and what a caterer reads.
            head = 0
            for a in d.activities:
                if not is_crew_start(a.description) or (a.time or "") != t:
                    continue
                head += a.crew_headcount
            labels = [l["label"] for l in local]
            # `activity` stays the full one-line summary — people then
            # positions — because it is what a surface that has only this
            # field shows, and dropping the local lines from it would hide
            # them there. The SHAPE of the two is what separates now.
            item = _item(d, t, "Crew", ", ".join(names + labels),
                         icon="👤", kind="crew",
                         count=head or (len(names)
                                        + sum(l["qty"] for l in local)),
                         source=SOURCE_CREW)
            # Exports show the count and put the names on the Crew sheet —
            # 40 names in one cell is unreadable and wrecks PDF pagination.
            item["crew_names"] = list(names)
            # Counts of a POSITION, never mixed in with the people. Rendered
            # with the LL code and the local-labour fill, so one line reading
            # "14 × Rigger" cannot be mistaken for one person.
            item["local_lines"] = list(local)
            items.append(item)


    # ── #37 Phase 2b: dept-tagged hard-coded events, computed per day from
    # SOD/EOD offsets. Nothing stored — the same virtual event surfaces on the
    # master and on its department's tab.
    hardcoded_by_dept = {t: [] for t in SUB_SCHEDULE_TYPES}
    for d in show.days:
        overlay, _missing = overlay_for_day(d)
        for ev in overlay:
            dept = ev.get("department")
            # Normalise: hard-coded events store the TYPE, OSS entries the
            # LABEL. Unnormalised, one department renders as two.
            items.append(_item(d, ev.get("time"),
                               dept_label(dept) if dept else "Hard-Coded",
                               ev.get("name"),
                               icon="📌", kind="recur",
                               source=SOURCE_HARDCODED))
            if dept:
                hardcoded_by_dept.setdefault(dept, []).append(dict(ev, day=d))

    items = _collapse_crew_breaks(items)
    items.sort(key=_sort_key)
    return items, hardcoded_by_dept


def build_dept_rows(entries, hardcoded):
    """One department tab's rows: its own OSS entries and the recurring
    events tagged to it, merged into a single day-grouped stream.

    Returns [(day, [row, ...]), ...] in schedule order, undated last. Each
    row is a dict carrying "kind" ("recur" or "act"), the clock fields, and
    exactly one of "entry" (a SubScheduleEntry, editable) or "event" (a
    computed recurring occurrence, read-only).

    These used to be two stacked lists — a block of recurring events above
    the department's own table. That reads fine when a department has one or
    two worth mentioning as a footnote. Doors has twenty-one and they ARE
    its schedule, so its own six entries sat below a wall of unrelated lines
    and the recurring events themselves had no day grouping at all.

    Ordering within a day is the clock, then recurring before entered. A
    recurring event is a fixed fact of the venue's day — doors open at
    18:00 whatever anyone schedules against it — so when the two land on the
    same minute the fixed one reads first and the department's response to
    it reads second.
    """
    rows = []
    for e in entries or []:
        rows.append({
            "kind":      "act",
            "day":       getattr(e, "schedule_day", None),
            "day_id":    getattr(e, "schedule_day_id", None),
            "time":      e.effective_time or "",
            "end_time":  None,
            "sort_time": sort_minutes(e.effective_time),
            # Recurring first on a tie; see the docstring.
            "tie":       1,
            "order":     getattr(e, "sort_order", 0) or 0,
            "entry":     e,
            "event":     None,
        })
    for ev in hardcoded or []:
        day = ev.get("day")
        # sort_min is already minutes-since-midnight off the day's SOD/EOD.
        # Falling back to sort_minutes() keeps a malformed overlay from
        # throwing the whole tab rather than one row.
        sort_min = ev.get("sort_min")
        rows.append({
            "kind":      "recur",
            "day":       day,
            "day_id":    getattr(day, "id", None),
            "time":      ev.get("time") or "",
            "end_time":  ev.get("end_time"),
            "sort_time": sort_min if sort_min is not None
                         else sort_minutes(ev.get("time")),
            "tie":       0,
            "order":     0,
            "entry":     None,
            "event":     ev,
        })

    def _key(r):
        day = r["day"]
        return (day.date if day and day.date else DATE_MAX,
                r["sort_time"], r["tie"], r["order"])
    rows.sort(key=_key)

    # Grouped the way group_by_day() groups the master timeline, so a day is
    # one contiguous run and never splits into two headed blocks.
    ordered, seen = [], {}
    for r in rows:
        key = r["day_id"]
        if key not in seen:
            seen[key] = []
            ordered.append((r["day"], seen[key]))
        seen[key].append(r)
    return ordered


def group_by_day(master_items):
    """[(day, [items]), ...] in schedule order, undated last.

    Grouped on the day OBJECT, not the id, so a day is never split into two
    blocks — the exports rely on each day being one contiguous run.
    """
    ordered, seen = [], {}
    for item in master_items:
        key = item["day_id"]
        if key not in seen:
            seen[key] = []
            ordered.append((item["day"], seen[key]))
        seen[key].append(item)
    return ordered


def group_by_department(master_items):
    """[(dept, [items]), ...] ordered by the department's OSS sort position,
    with the non-department sources (Schedule, Crew) first."""
    from models import SUB_SCHEDULE_META

    def rank(dept):
        for meta in SUB_SCHEDULE_META.values():
            if meta.get("label") == dept:
                return meta.get("sort", 99)
        return {"Schedule": -2, "Crew": -1}.get(dept, 98)

    buckets = {}
    for item in master_items:
        buckets.setdefault(item["dept"], []).append(item)
    return [(d, buckets[d]) for d in sorted(buckets, key=lambda d: (rank(d), d))]

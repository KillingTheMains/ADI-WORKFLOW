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

from time_utils import sort_minutes, UNKNOWN as UNKNOWN_GUARD

# Undated rows sort after every real day rather than jumping to the top.
DATE_MAX = _date_cls.max

# Non-department sources that also appear on the master timeline.
SOURCE_OSS = "oss"
SOURCE_MEAL = "meal"
SOURCE_ACTIVITY = "activity"
SOURCE_CREW = "crew"
SOURCE_HARDCODED = "hardcoded"


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


def _item(day, time_value, dept, activity, *, icon="•", count=None,
          duration_hrs=None, notes="", source=SOURCE_OSS, day_id=None):
    """One master-timeline row. sort_time is minutes-since-midnight so every
    source lands on ONE comparable scale — string compares put '1:00 PM'
    after '18:00' and sink afternoon rows to the bottom of the day."""
    return {
        "day_id":       day_id if day_id is not None else (day.id if day else None),
        "day":          day,
        "sort_time":    sort_minutes(time_value),
        "time":         time_value or "",
        "icon":         icon,
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
        match = (CREW_BREAK_RE.match(item["activity"] or "")
                 if item["source"] == SOURCE_ACTIVITY else None)
        if not match:
            keep.append(item)
            continue
        key = (item["day_id"], match.group("base").strip().upper())
        groups.setdefault(key, []).append((item, match.group("call").strip()))

    for (_day_id, base), members in groups.items():
        members.sort(key=lambda pair: pair[0]["sort_time"])
        first = dict(members[0][0])
        first["activity"] = members[0][0]["activity"].split("—")[0].split("–")[0].strip() \
            or base.title()
        detail = ", ".join(f"{call} crew {_fmt_12h(m['time'])}" for m, call in members)
        first["notes"] = _merge_notes(first["notes"], detail) if len(members) > 1 \
            else first["notes"]
        first["collapsed_calls"] = [call for _m, call in members]
        keep.append(first)
    return keep


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
    from models import SUB_SCHEDULE_TYPES
    from hardcoded_service import overlay_for_day

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
                count=(loc.headcount if loc else None),
                notes=_merge_notes((loc.notes if loc else None), svc.notes,
                                   act.notes if act else None),
                source=SOURCE_MEAL, day_id=svc.schedule_day_id,
            ))


    # ── #39: day activities + crew call times. An activity already carried
    # by a linked department row is skipped — it was merged in above.
    for d in show.days:
        crew_by_time = {}
        for a in d.activities:
            if a.id not in claimed:
                items.append(_item(d, a.time, "Schedule", a.description,
                                   icon="🗓", notes=a.notes,
                                   source=SOURCE_ACTIVITY))
            # Crew on a Crew Start all share that event's call time.
            if "CREW START" in (a.description or "").upper():
                names = crew_by_time.setdefault(a.time or "", [])
                for row in a.crew_rows:
                    if row.is_group_header or not row.crew_member_id:
                        continue
                    cm = row.crew_member
                    who = cm.full_name if cm else (row.name_override or "TBD")
                    if who not in names:
                        names.append(who)

        # #47 — one grouped Crew row per distinct call time, not one per person.
        for t, names in crew_by_time.items():
            if not names:
                continue
            item = _item(d, t, "Crew", ", ".join(names),
                         icon="👤", count=len(names), source=SOURCE_CREW)
            # Exports show the count and put the names on the Crew sheet —
            # 40 names in one cell is unreadable and wrecks PDF pagination.
            item["crew_names"] = list(names)
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
                               icon="📌", source=SOURCE_HARDCODED))
            if dept:
                hardcoded_by_dept.setdefault(dept, []).append(dict(ev, day=d))

    items = _collapse_crew_breaks(items)
    items.sort(key=_sort_key)
    return items, hardcoded_by_dept
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

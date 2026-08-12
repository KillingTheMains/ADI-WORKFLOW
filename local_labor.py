"""
Local labour — positions hired in MULTIPLES, tracked by title not by name.

"5 Riggers", "18 Lighting Hands". These come from a labour provider, a house
crew or a local union; they are not the same people every day, they are not
from a production vendor, and they are not lead crew. The whole point is that
the position is the unit, and there are N of it.

Pure data and arithmetic — no ORM, no Flask — same as breaks.py, so the rules
can be tested without a database and cannot drift between the catalogue, the
crew call and the exports.

Everything here is taken from Jason's real SAP Sapphire labour workbooks
rather than invented. See `ADI_Local_Labor_Findings.md` for the source and for
the decisions behind the shape.

TWO THINGS THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------------
**Rates.** Not yet. And when they come they are not a price list: the
workbooks resolve minimum call, OT/DT thresholds, weekend and 6th/7th-day
treatment and overnight premiums from the PROVIDER, and the eight providers
disagree — Freeman and Deco go to overtime at 8 hours, not 10. A rate card in
this business is a rules set. `billing.py` currently applies one global rule
to everybody and is therefore already wrong for most providers; that is known
and deferred, not overlooked.

**Splitting a line into individual bodies.** The workbooks record one row per
person per day, because each row carries its own in/out times and three of the
twelve hands might stay late. The app carries `qty` instead, which is correct
for planning and for headcounts and cannot hold per-person actuals. Jason's
call: keep `qty`, and explode a line into individual rows when actuals are
being entered. Nothing here forecloses that.
"""

# The prefixes Jason's workbooks use to mean "nameless multiples". Kept as
# documentation of where the seed list came from, and useful for recognising a
# pasted title from one of those sheets.
WORKBOOK_PREFIXES = ("Local - ", "House - ", "Deco - Teamster - ", "Freeman - ")


# The seed catalogue: (title, department, type).
#
# `type` reuses the existing Position vocabulary — 'lead' for the ones who run
# the crew, 'hand' for the ones you hire N of. That distinction matters
# already: the 2026 workbook's unfilled rate blocks were headed `Leads` and
# `Hands`, so when rates arrive they most likely attach to this, not to each
# title.
#
# Departments use the app's existing `Position.department` values. Larry's
# pull-down disagrees (it has AV, Production Electrical, Show Operations) and
# so do the SAP letter codes — that is Larry question A5, still unanswered.
# `department` is a string, so remapping later is a data migration, not a
# schema change.
SEED_POSITIONS = [
    # Who runs the crew. One or two of these, not eighteen.
    ("Labor Steward",        "General",  "lead"),
    ("Labor Coordinator",    "General",  "lead"),
    ("Crew Chief",           "General",  "lead"),
    ("Steward / Timekeeper", "General",  "lead"),

    # General hands — the bulk of a load-in.
    ("Stagehand",            "General",  "hand"),
    ("Prep Hand",            "General",  "hand"),
    ("Forklift Operator",    "General",  "hand"),
    ("Truck Loader",         "General",  "hand"),
    ("Truck Unloader",       "General",  "hand"),
    ("Driver",               "General",  "hand"),

    # Rigging. Up and Down are the house-crew pair in the workbooks; High
    # Rigger is Jason's term for the same job description.
    ("Rigger",               "Rigging",  "hand"),
    ("High Rigger",          "Rigging",  "hand"),
    ("Up Rigger",            "Rigging",  "hand"),
    ("Down Rigger",          "Rigging",  "hand"),
    ("Ground Rigger",        "Rigging",  "hand"),

    # Departmental hands.
    ("Lighting Hand",        "Lighting", "hand"),
    ("Dimmer Hand",          "Lighting", "hand"),
    ("LED Hand",             "LED",      "hand"),
    ("Video Hand",           "Video",    "hand"),
    ("Audio Hand",           "Audio",    "hand"),
    ("Scenic Hand",          "Scenic",   "hand"),
    ("Drape Hand",           "Scenic",   "hand"),
]

# What a crew is DOING on a call. Free text on the row, offered as a datalist
# — a fixed list would be wrong within a week, and these are only the ones
# that actually recur in the workbooks.
SEED_TASKS = [
    "Unload / Push",
    "Hang / Circuit Lights",
    "Distros / Cable",
    "Pin/Bolt Truss",
    "Cable / UnPin Truss",
    "Rigging Cable / GakFlex",
    "Floor Mark",
    "Catwalk Strike",
    "Strike Lights",
    "Org Empty / Push",
    "Load Out",
    "Shop Prep",
]


# Department order for the catalogue. Anything not listed sorts last,
# alphabetically, so adding a department never hides it.
DEPARTMENT_ORDER = [
    "General", "Rigging", "Lighting", "LED", "Video", "Audio", "Scenic",
    "Power", "Production", "Specialty",
]


def department_key(name):
    """Sort key putting known departments in house order, unknowns last."""
    name = (name or "").strip()
    try:
        return (0, DEPARTMENT_ORDER.index(name), "")
    except ValueError:
        return (1, 0, name.lower())


# Who reads first within a department. The crew chief runs the crew, the
# shadow is one skilled individual, the hands are the many. That is the order
# a call sheet puts them in, so it is the order everywhere.
TYPE_ORDER = {"lead": 0, "specialty": 1, "hand": 2}


def type_key(value):
    return TYPE_ORDER.get((value or "").strip().lower(), 3)


def group_by_department(positions):
    """``[(department, [position, ...]), ...]`` in house order.

    Leads, then shadows, then hands, then alphabetical — a crew chief reads
    above the fourteen hands they are running.
    """
    buckets = {}
    for p in positions:
        buckets.setdefault((getattr(p, "department", None) or "Unassigned"),
                           []).append(p)
    for rows in buckets.values():
        rows.sort(key=lambda p: (type_key(getattr(p, "type", None)),
                                 (getattr(p, "title", "") or "").lower()))
    return sorted(buckets.items(), key=lambda kv: department_key(kv[0]))


def group_rows_by_department(rows):
    """The same grouping and order, for CREW ROWS on a call.

    ONE ordering, so the Local Labor Database and the local labour section of
    a crew call cannot disagree about where Rigging sits or whether the head
    reads above the hands. Jason, 2026-08-12 — the crew call follows the
    catalogue.

    A row with no catalogue position still appears, under "Unassigned", which
    sorts last. It is usually a real crew of real people that nobody has named
    a position for yet, and hiding it would hide them.
    """
    buckets = {}
    for r in rows or []:
        pos = getattr(r, "position_ref", None)
        dept = (getattr(pos, "department", None) if pos else None) or "Unassigned"
        buckets.setdefault(dept, []).append(r)

    def _row_key(r):
        pos = getattr(r, "position_ref", None)
        title = (getattr(r, "position", None)
                 or (getattr(pos, "title", "") if pos else "") or "")
        return (type_key(getattr(pos, "type", None) if pos else None),
                title.lower(), getattr(r, "id", 0) or 0)

    for rs in buckets.values():
        rs.sort(key=_row_key)
    return sorted(buckets.items(), key=lambda kv: department_key(kv[0]))


def line_label(position_title, qty, task=None):
    """How one local-labour line reads: ``18 × Lighting Hand — Catwalk Strike``.

    ONE definition, so the crew call, the call sheet and the master export
    cannot describe the same line three ways. The multiplication sign is the
    point — this is a line about a NUMBER of people, and a line that reads
    "Lighting Hand" alone has lost the only fact that matters about it.
    """
    title = (position_title or "Crew").strip() or "Crew"
    try:
        n = int(qty or 1)
    except (TypeError, ValueError):
        n = 1
    if n < 1:
        n = 1
    label = f"{n} × {title}" if n > 1 else title
    task = (task or "").strip()
    return f"{label} — {task}" if task else label


def headcount(rows):
    """Total bodies across local-labour rows. ``qty``, not row count.

    Deliberately the same rule `ScheduleActivity.crew_headcount` already
    applies, restated here so a caller that only has the rows can ask without
    reaching for the ORM.
    """
    total = 0
    for r in rows or []:
        if getattr(r, "is_group_header", False):
            continue
        try:
            total += int(getattr(r, "qty", 1) or 1)
        except (TypeError, ValueError):
            total += 1
    return total

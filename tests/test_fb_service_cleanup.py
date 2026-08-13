"""One beverage table per day, one service per meal — the decision, tested.

Measured on production 2026-08-13: 48 meal services, 36 of them beverage
services across 10 days, six on 2026-09-10. Reading their names told the
story — 25 were named "Crew Break - Refresh as Needed" or "Refresh Beverage",
kind='other', no locations. They are the OLD F&B model's way of STORING each
beverage top-up, one row per refresh. The modern model computes those from
the day's first crew call, the day's EOD and the service's own offset and
interval. Every one of them rendered as its own service card on the F&B tab,
which is what "clutter and lots of old events" looked like.

They only accumulated because `fb_standing_add`'s "one per day" guard was a
SQL filter on `is_recurring` and every legacy row carries False, so it never
fired. Fixed in bf1d80e; this clears up what it let through.

`cleanup_fb_services.plan_for_day` is the decision, and it is ONE RULE rather
than a list of row ids — ids are production-specific and a script that
hard-codes them cannot be tested. These tests are that rule. It deletes rows
off a production database, so the logic does not get to live inside a
`main()` where the tested version and the running version can differ.
"""
import pytest

from cleanup_fb_services import plan_for_day


class _Loc:
    def __init__(self, name):
        self.location_name = name


class _Svc:
    """Duck-typed MealService. The planner never touches the ORM."""
    def __init__(self, id, name, kind="other", is_recurring=False,
                 location=None, notes=None):
        self.id = id
        self.name = name
        self.kind = kind
        self.is_recurring = is_recurring
        self.locations = [_Loc(location)] if location else []
        self.notes = notes


def _beverage(svc):
    """Stand-in for breaks.is_beverage_service — same three tests."""
    if svc.is_recurring:
        return True
    if (svc.kind or "").lower() == "beverages":
        return True
    name = (svc.name or "").upper()
    return any(w in name for w in ("BEVERAGE", "REFRESH", "COFFEE", "WATER"))


def _plan(services, breaks=None, **kw):
    return plan_for_day(services, breaks or {}, is_beverage=_beverage, **kw)


# ── The survivor rule, one clause at a time ──────────────────────────────

def test_the_modern_row_wins():
    """Jason, 2026-08-13: keep All Day Beverages, copy the location over."""
    legacy = _Svc(20, "Crew Beverage Set", "beverages", location="Back Wall")
    modern = _Svc(124, "All Day Beverages", "beverages", is_recurring=True)
    promote, doomed, _b = _plan([legacy, modern])
    assert [s.id for s, _r, _k in doomed] == [20]
    (kept, changes), = promote
    assert kept.id == 124
    assert changes["location"] == "Back Wall", "the location must carry over"


def test_a_row_with_a_location_beats_one_without():
    bare = _Svc(65, "Crew Break - Refresh as Needed")
    sited = _Svc(64, "Crew Break - Refresh as Needed", location="Back Wall")
    promote, doomed, _b = _plan([bare, sited])
    assert [s.id for s, _c in promote] == [64]
    assert [s.id for s, _r, _k in doomed] == [65]


def test_promoting_the_only_refresh_row_makes_it_a_beverage_table():
    """2026-09-17 has no "Crew Beverage Set" — only refresh rows, one of which
    carries the location. That day still needs a table, so the rule elects
    it and normalises its kind."""
    a = _Svc(64, "Crew Break - Refresh as Needed", location="Back Wall")
    b = _Svc(65, "Crew Break - Refresh as Needed")
    c = _Svc(66, "Crew Break - Refresh as Needed")
    promote, doomed, _b = _plan([a, b, c])
    (kept, changes), = promote
    assert kept.id == 64
    assert changes["kind"] == "beverages"
    assert changes["is_recurring"] is True
    assert sorted(s.id for s, _r, _k in doomed) == [65, 66]


def test_a_non_refresh_name_beats_a_refresh_name():
    refresh = _Svc(9, "Refresh Beverage", "beverages")
    table = _Svc(30, "Crew Beverage Set", "beverages")
    promote, _d, _b = _plan([refresh, table])
    assert [s.id for s, _c in promote] == [30]


def test_the_last_tiebreak_is_the_lowest_id():
    """Stable, so a second run elects the same row and changes nothing."""
    a = _Svc(50, "Crew Beverage Set", "beverages")
    b = _Svc(30, "Crew Beverage Set", "beverages")
    promote, _d, _b = _plan([a, b])
    assert [s.id for s, _c in promote] == [30]


def test_a_lone_beverage_table_is_normalised_not_deleted():
    only = _Svc(30, "Crew Beverage Set", "beverages")
    promote, doomed, _b = _plan([only])
    assert doomed == []
    (kept, changes), = promote
    assert kept.id == 30 and changes == {"is_recurring": True}


def test_a_day_with_no_beverage_service_is_left_alone():
    promote, doomed, blocked = _plan([_Svc(126, "Meal Break", "meal")])
    assert (promote, doomed, blocked) == ([], [], [])


# ── Meals ────────────────────────────────────────────────────────────────

def test_duplicate_meals_collapse_to_one():
    """With neither feeding a break the tiebreak is the lowest id, so 37
    survives. On production 2026-09-13 it is the other way round, because
    there 38 is the one attached to a break — see the test below."""
    a = _Svc(37, "LUNCH BREAK — 08:00 CREW", "lunch")
    b = _Svc(38, "LUNCH BREAK — 08:00 CREW", "lunch")
    _p, doomed, _b = _plan([a, b])
    assert [s.id for s, _r, _k in doomed] == [38]
    assert [k.id for _s, _r, k in doomed] == [37]


def test_the_meal_that_feeds_a_break_is_the_one_kept():
    """Whichever is doing real work survives, whatever its id."""
    a = _Svc(37, "LUNCH BREAK — 08:00 CREW", "lunch")
    b = _Svc(38, "LUNCH BREAK — 08:00 CREW", "lunch")
    _p, doomed, _b = _plan([a, b], breaks={38: ["a break"]})
    assert [s.id for s, _r, _k in doomed] == [37]
    assert [k.id for _s, _r, k in doomed] == [38]


def test_two_meals_feeding_DIFFERENT_breaks_are_not_duplicates():
    """Two crew groups an hour apart genuinely need two services — that is
    the food-out rule, not a mistake. Nothing is deleted and it says so."""
    a = _Svc(37, "LUNCH BREAK — 08:00 CREW", "lunch")
    b = _Svc(38, "LUNCH BREAK — 08:00 CREW", "lunch")
    _p, doomed, blocked = _plan([a, b], breaks={37: ["x"], 38: ["y"]})
    assert doomed == []
    assert sorted(s.id for s, _w in blocked) == [37, 38]


def test_meals_that_differ_by_name_or_kind_are_not_duplicates():
    """CREW BREAKFAST on two days is two breakfasts. Within a day, a lunch
    and a dinner are two meals."""
    lunch = _Svc(52, "LUNCH BREAK — 08:00 CREW", "lunch")
    dinner = _Svc(63, "DINNER BREAK — 08:00 CREW", "dinner")
    _p, doomed, _b = _plan([lunch, dinner])
    assert doomed == []


def test_a_meal_is_never_swept_up_with_the_beverages():
    bev = _Svc(30, "Crew Beverage Set", "beverages")
    refresh = _Svc(31, "Crew Break - Refresh as Needed")
    lunch = _Svc(37, "LUNCH BREAK — 08:00 CREW", "lunch")
    _p, doomed, _b = _plan([bev, refresh, lunch])
    assert [s.id for s, _r, _k in doomed] == [31]


# ── Safety properties ────────────────────────────────────────────────────

def test_the_plan_is_idempotent():
    """Running it twice must find nothing the second time, or a re-run after
    a partial failure would keep eating rows."""
    services = [
        _Svc(20, "Crew Beverage Set", "beverages", location="Back Wall"),
        _Svc(124, "All Day Beverages", "beverages", is_recurring=True),
        _Svc(31, "Crew Break - Refresh as Needed"),
    ]
    promote, doomed, _b = _plan(services)
    survivors = [s for s in services if s.id not in {d.id for d, _r, _k in doomed}]
    for svc, changes in promote:          # apply
        for field, value in changes.items():
            if field == "location":
                svc.locations.append(_Loc(value))
            else:
                setattr(svc, field, value)

    promote2, doomed2, blocked2 = _plan(survivors)
    assert (promote2, doomed2, blocked2) == ([], [], [])


def test_every_doomed_row_names_a_survivor():
    """Nothing is deleted without something taking its place — that is what
    makes the report readable and the decision reversible in the head."""
    services = [
        _Svc(20, "Crew Beverage Set", "beverages", location="Back Wall"),
        _Svc(124, "All Day Beverages", "beverages", is_recurring=True),
        _Svc(37, "LUNCH BREAK — 08:00 CREW", "lunch"),
        _Svc(38, "LUNCH BREAK — 08:00 CREW", "lunch"),
    ]
    _p, doomed, _b = _plan(services)
    assert doomed
    for svc, reason, keep in doomed:
        assert keep is not None and keep.id != svc.id
        assert reason


def test_the_planner_writes_nothing():
    """It is a plan. The caller applies it, and only under --commit."""
    a = _Svc(20, "Crew Beverage Set", "beverages", location="Back Wall")
    b = _Svc(124, "All Day Beverages", "beverages", is_recurring=True)
    before = (a.kind, a.is_recurring, len(a.locations),
              b.kind, b.is_recurring, len(b.locations))
    _plan([a, b])
    assert (a.kind, a.is_recurring, len(a.locations),
            b.kind, b.is_recurring, len(b.locations)) == before


def test_renaming_is_opt_in():
    only = _Svc(64, "Crew Break - Refresh as Needed", location="Back Wall")
    (_k, changes), = _plan([only])[0]
    assert "name" not in changes
    (_k2, changes2), = _plan([_Svc(64, "Crew Break - Refresh as Needed",
                                   location="Back Wall")],
                             beverage_name="All Day Beverages")[0]
    assert changes2["name"] == "All Day Beverages"


# ── The production shape, end to end ─────────────────────────────────────

def test_the_real_2026_09_10_day():
    """Six beverage services on one day: the table, and five stored refreshes."""
    services = [
        _Svc(29, "Crew Break - Refresh as Needed"),
        _Svc(30, "Crew Beverage Set", "beverages", location="Summit Ballroom Back Wall"),
        _Svc(31, "Crew Break - Refresh as Needed"),
        _Svc(32, "Crew Break - Refresh as Needed"),
        _Svc(33, "Crew Break - Refresh as Needed"),
        _Svc(34, "Crew Break - Refresh as Needed"),
    ]
    promote, doomed, blocked = _plan(services)
    assert [s.id for s, _c in promote] == [30]
    assert sorted(s.id for s, _r, _k in doomed) == [29, 31, 32, 33, 34]
    assert blocked == []

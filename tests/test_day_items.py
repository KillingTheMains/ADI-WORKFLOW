"""Note 11 — day-level "what is happening today" items.

Larry asked for two things that pull against each other: add them freely, and
more than one on the same day — a day can be both Travel and Load In.

Jason's calls, 2026-09-04: it is a LABEL on the day, not a timed row (the day
page already has timed activities, and a second way to say "Load In 08:00" is
how one fact gets entered twice); and it shares ONE vocabulary with production
phase types, so Larry maintains a single list.

Sharing the vocabulary is what makes the seed the interesting part. Larry's
own `07 Lists` Scope/Activity list contains "Load-In", and the phase types
already contain "Load In" — which is load-bearing, resolved by other modules
as a literal string. Seeding his spelling next to it would be the
`Load In` / `Load-In` / `load in` split this project keeps warning about,
landing right beside a name that must not have a twin.
"""
import datetime as dt

from models import (DayItem, PhaseType, SCOPE_ACTIVITY_SEED, ScheduleDay,
                    Show, normalise_type_name)


def _show_day(db):
    seq = Show.query.count() + 1
    show = Show(name=f"Day Item Show {seq}", code=f"DI{seq}")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 5, 4))
    db.session.add(day); db.session.flush()
    db.session.commit()
    return show, day


def _type(name):
    return PhaseType.query.filter_by(name=name).one()


def _add(client, show, day, pt):
    return client.post(f"/shows/{show.id}/schedule/{day.id}/items/add",
                       data={"phase_type_id": str(pt.id)},
                       follow_redirects=True)


# ── The seed ─────────────────────────────────────────────────────────────────

def test_larrys_whole_vocabulary_is_available(app, db):
    """His list is the seed because it is HIS — already chronological, and
    ending in "Other", which is the escape hatch that makes "add freely" and
    "a controlled list" compatible rather than opposed."""
    names = {normalise_type_name(r.name) for r in PhaseType.query.all()}
    for wanted in SCOPE_ACTIVITY_SEED:
        assert normalise_type_name(wanted) in names, wanted
    assert "other" in names


def test_the_hyphenated_spelling_does_not_become_a_second_load_in(app, db):
    """THE ONE THAT MATTERS. "Load-In" from Larry's list and "Load In" in the
    app are the same thing, and "Load In" is load-bearing — other modules look
    it up as a literal string. A twin beside it is the worst version of the
    duplicate-vocabulary bug this project keeps hitting."""
    rows = [r for r in PhaseType.query.all()
            if normalise_type_name(r.name) == "load in"]
    assert len(rows) == 1, [r.name for r in rows]
    assert rows[0].name == "Load In"
    assert rows[0].is_builtin, "the surviving row must be the load-bearing one"


def test_show_and_strike_are_not_duplicated_either(app, db):
    for name in ("show", "strike"):
        rows = [r for r in PhaseType.query.all()
                if normalise_type_name(r.name) == name]
        assert len(rows) == 1, [r.name for r in rows]


def test_the_list_reads_chronologically(app, db):
    """Alphabetical would read wrong — these are stages of a load-in, and the
    reason Larry's list is worth seeding is that it is already in order."""
    ordered = [r.name for r in PhaseType.query
               .order_by(PhaseType.sort_order, PhaseType.name).all()]
    for earlier, later in (("Travel", "Load In"), ("Load In", "Show"),
                           ("Show", "Strike"), ("Strike", "Load-Out")):
        assert ordered.index(earlier) < ordered.index(later), ordered


def test_the_seed_is_idempotent(app, db):
    """It reports counts rather than running blind, and a second run must add
    nothing — a count you did not predict is a failure signal."""
    from migrations import _seed_scope_activity_types
    before = PhaseType.query.count()
    _seed_scope_activity_types(db.session)
    db.session.commit()
    assert PhaseType.query.count() == before


# ── The day items themselves ─────────────────────────────────────────────────

def test_a_day_can_be_several_things_at_once(client, db):
    """Larry's actual requirement: "more than one can be assigned to the same
    day" — a day can be both Travel and Load In."""
    show, day = _show_day(db)
    _add(client, show, day, _type("Travel"))
    _add(client, show, day, _type("Load In"))

    assert DayItem.query.filter_by(day_id=day.id).count() == 2
    assert set(day.item_labels) == {"Travel", "Load In"}


def test_items_read_in_the_vocabularys_own_order(client, db):
    """Added in any order, they read chronologically — which is the reason the
    seed carries Larry's ordering rather than sorting his names."""
    show, day = _show_day(db)
    _add(client, show, day, _type("Strike"))
    _add(client, show, day, _type("Travel"))
    assert day.item_labels == ["Travel", "Strike"]


def test_the_same_item_twice_does_nothing_rather_than_500ing(client, db):
    """`uq_day_item` would raise. A 500 for double-clicking Add is a worse
    answer than nothing happening."""
    show, day = _show_day(db)
    pt = _type("Travel")
    _add(client, show, day, pt)
    r = _add(client, show, day, pt)
    assert r.status_code == 200
    assert DayItem.query.filter_by(day_id=day.id).count() == 1
    assert "already on this day" in r.get_data(as_text=True)


def test_an_item_can_be_taken_off_a_day(client, db):
    show, day = _show_day(db)
    _add(client, show, day, _type("Travel"))
    item = DayItem.query.filter_by(day_id=day.id).one()

    r = client.post(
        f"/shows/{show.id}/schedule/{day.id}/items/{item.id}/delete",
        follow_redirects=True)
    assert r.status_code == 200
    assert DayItem.query.filter_by(day_id=day.id).count() == 0


def test_removing_a_day_item_leaves_the_vocabulary_alone(client, db):
    """This is the day's tag, not Larry's list. Deleting the tag must not
    delete the thing it points at."""
    show, day = _show_day(db)
    pt = _type("Travel")
    _add(client, show, day, pt)
    item = DayItem.query.filter_by(day_id=day.id).one()
    client.post(f"/shows/{show.id}/schedule/{day.id}/items/{item.id}/delete",
                follow_redirects=True)
    assert PhaseType.query.filter_by(name="Travel").count() == 1


def test_deleting_a_day_takes_its_items_with_it(client, db):
    show, day = _show_day(db)
    _add(client, show, day, _type("Travel"))
    client.post(f"/shows/{show.id}/schedule/{day.id}/delete",
                follow_redirects=True)
    assert DayItem.query.count() == 0


# ── Where they show up ───────────────────────────────────────────────────────

def test_the_day_page_shows_them_and_offers_the_managed_list(client, db):
    show, day = _show_day(db)
    _add(client, show, day, _type("Travel"))
    body = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    assert "What&#39;s Happening Today" in body or "What's Happening Today" in body
    assert "Travel" in body
    # The vocabulary is offered, not free-typed — free text is how one name
    # becomes three across three shows.
    assert "Focus/Programming" in body
    assert 'name="phase_type_id"' in body


def test_a_deactivated_type_stops_being_offered_but_stays_where_it_is(client, db):
    """Deactivate-not-delete, the same rule the client and phase-type screens
    already follow. A day that already says Travel must not rewrite itself
    because Larry tidied the list."""
    show, day = _show_day(db)
    pt = _type("Travel")
    _add(client, show, day, pt)

    pt.is_active = False
    db.session.commit()

    body = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    assert f'<option value="{pt.id}">Travel</option>' not in body
    assert day.item_labels == ["Travel"]


def test_the_call_sheet_carries_them(client, db):
    """The sheet the crew actually holds is where "today is Travel AND Load
    In" earns its keep."""
    show, day = _show_day(db)
    _add(client, show, day, _type("Travel"))
    _add(client, show, day, _type("Load In"))

    body = client.get(
        f"/shows/{show.id}/schedule/{day.id}/call-sheet").get_data(as_text=True)
    assert "Travel · Load In" in body


def test_one_definition_of_how_they_read(client, db):
    """The day page and the call sheet both go through `item_labels`, so the
    separator and the ordering cannot diverge between them."""
    show, day = _show_day(db)
    _add(client, show, day, _type("Load In"))
    _add(client, show, day, _type("Travel"))
    assert day.item_labels == ["Travel", "Load In"]

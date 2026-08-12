"""
Create Crew Call — the call, its crew and its breaks in one transaction.

Replaces Bulk Assign Crew, which could only fill a CREW START somebody had
already typed. The ORDER is the point: crew before breaks, because
`breaks.needs_second_meal` reads their hours.
"""
import datetime as dt


def _show_day(db, new_breaks=True):
    from models import Show, ScheduleDay
    show = Show(name="Call Show", code="CC26")
    show.uses_new_breaks = new_breaks
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 3),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.commit()
    return show, day


def _crew(db, show, n=2):
    from models import CrewMember, ShowCrewAssignment
    made = []
    for i in range(n):
        cm = CrewMember(first_name="Person", last_name=str(i), active=True)
        db.session.add(cm)
        db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
        made.append(cm)
    db.session.commit()
    return made


def _url(show, day):
    return f"/shows/{show.id}/schedule/{day.id}/crew-call/create"


def test_creates_the_call_with_its_crew_and_its_breaks(app, client, db):
    from models import CrewBreak, ScheduleActivity
    show, day = _show_day(db)
    people = _crew(db, show, 2)

    r = client.post(_url(show, day), data={
        "time": "08:00",
        "crew_member_ids": [str(p.id) for p in people],
        "add_breaks": "1",
    })
    assert r.status_code in (200, 302)

    call = ScheduleActivity.query.filter_by(
        day_id=day.id, description="CREW START").one()
    assert call.time == "08:00"
    assert len(call.crew_rows) == 2

    breaks = CrewBreak.query.filter_by(crew_call_id=call.id).all()
    # Exactly break_options_for's standard set — nothing invented here.
    assert sorted(b.offset_minutes for b in breaks) == [150, 300, 510]


def test_the_breaks_come_out_with_a_kind_and_a_real_duration(app, client, db):
    """The whole reason the day-level builder was removed: a label is not a
    duration, and a break with no kind asks a catering question it shouldn't.
    """
    from breaks import KIND_COFFEE, KIND_MEAL
    from models import CrewBreak, ScheduleActivity
    show, day = _show_day(db)
    client.post(_url(show, day), data={"time": "08:00", "add_breaks": "1"})

    call = ScheduleActivity.query.filter_by(day_id=day.id).first()
    by_offset = {b.offset_minutes: b
                 for b in CrewBreak.query.filter_by(crew_call_id=call.id).all()}
    assert by_offset[150].kind == KIND_COFFEE
    assert by_offset[150].duration_minutes == 15
    assert by_offset[300].kind == KIND_MEAL
    assert by_offset[300].duration_minutes == 60
    assert by_offset[510].kind == KIND_COFFEE


def test_breaks_land_at_the_right_clock_times(app, client, db):
    from models import CrewBreak
    show, day = _show_day(db)
    client.post(_url(show, day), data={"time": "08:00", "add_breaks": "1"})
    times = sorted(b.activity.time for b in CrewBreak.query.all())
    assert times == ["10:30", "13:00", "16:30"]


def test_a_long_call_gets_the_second_meal(app, client, db):
    """Crew are added BEFORE the breaks so their hours are readable. Reverse
    the order in the route and this drops silently back to three breaks.
    """
    from models import CrewBreak
    show, day = _show_day(db)
    people = _crew(db, show, 1)
    client.post(_url(show, day), data={
        "time": "06:00", "hours": "15",
        "crew_member_ids": [str(people[0].id)],
        "add_breaks": "1",
    })
    assert sorted(b.offset_minutes for b in CrewBreak.query.all()) == \
        [150, 300, 510, 660]


def test_a_short_call_does_not(app, client, db):
    from models import CrewBreak
    show, day = _show_day(db)
    people = _crew(db, show, 1)
    client.post(_url(show, day), data={
        "time": "08:00", "hours": "10",
        "crew_member_ids": [str(people[0].id)],
        "add_breaks": "1",
    })
    assert 660 not in [b.offset_minutes for b in CrewBreak.query.all()]


def test_a_named_crew_still_reads_as_a_crew_start(app, client, db):
    """`is_crew_start` is the one test five other places use to find these. A
    call it cannot see has no breaks, no headcount and no line on the master.
    """
    from breaks import is_crew_start
    from models import ScheduleActivity
    show, day = _show_day(db)
    client.post(_url(show, day), data={"time": "07:00", "description": "rigging"})
    act = ScheduleActivity.query.filter_by(day_id=day.id).one()
    assert act.description == "CREW START — RIGGING"
    assert is_crew_start(act.description)


def test_a_description_already_saying_crew_start_is_left_alone(app, client, db):
    from models import ScheduleActivity
    show, day = _show_day(db)
    client.post(_url(show, day),
                data={"time": "07:00", "description": "CREW START — AUDIO"})
    act = ScheduleActivity.query.filter_by(day_id=day.id).one()
    assert act.description == "CREW START — AUDIO"


def test_no_time_creates_nothing(app, client, db):
    from models import ScheduleActivity
    show, day = _show_day(db)
    client.post(_url(show, day), data={"time": "", "add_breaks": "1"})
    assert ScheduleActivity.query.filter_by(day_id=day.id).count() == 0


def test_breaks_are_not_added_on_a_legacy_show(app, client, db):
    """A show still on the old model must not gain CrewBreak records behind
    its back — that is what `uses_new_breaks` is for.
    """
    from models import CrewBreak, ScheduleActivity
    show, day = _show_day(db, new_breaks=False)
    client.post(_url(show, day), data={"time": "08:00", "add_breaks": "1"})
    assert ScheduleActivity.query.filter_by(day_id=day.id).count() == 1
    assert CrewBreak.query.count() == 0


def test_crew_are_not_duplicated_when_already_on_a_call(app, client, db):
    """The assign path is shared with the old bulk pop-up and is additive."""
    from models import ScheduleActivity
    from routes.schedule import _assign_crew_to_activity
    show, day = _show_day(db)
    people = _crew(db, show, 1)
    client.post(_url(show, day), data={
        "time": "08:00", "crew_member_ids": [str(people[0].id)]})
    call = ScheduleActivity.query.filter_by(
        day_id=day.id, description="CREW START").one()

    added, skipped = _assign_crew_to_activity(call, [people[0].id])
    db.session.commit()
    assert (added, skipped) == (0, 1)
    assert len(call.crew_rows) == 1


def test_the_day_page_offers_the_wizard_not_the_old_pop_up(app, client, db):
    show, day = _show_day(db)
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    assert "Create Crew Call" in html
    # The old pop-up and its trigger are gone. Anchored on the element id, not
    # the words — this file's own header comment names the thing it replaced.
    assert "bulkAssignCrewModal" not in html


# ── Roster order in the picker (Jason, 2026-08-12) ───────────────────────────

def _rostered(db, show, people):
    """Give the show a deliberate roster order: `people` is the order wanted."""
    from models import ShowCrewAssignment
    for i, cm in enumerate(people):
        a = ShowCrewAssignment.query.filter_by(
            show_id=show.id, crew_member_id=cm.id).one()
        a.sort_order = (i + 1) * 10
    db.session.commit()


def _picker_order(html):
    """The crew checkbox ids, in the order the picker draws them."""
    import re
    body = html.split('id="createCrewCallModal"')[1]
    return [int(x) for x in
            re.findall(r'class="ccc-crew" name="crew_member_ids" value="(\d+)"',
                       body)]


def test_the_picker_lists_crew_in_roster_order(app, client, db):
    """Same order the crew call itself renders in. Two different orders for the
    same names on one page reads as a bug — it is what crew_ordering exists to
    stop.
    """
    from models import Company
    show, day = _show_day(db)
    co = Company(name="Alpha AV")
    db.session.add(co)
    db.session.flush()
    people = _crew(db, show, 4)
    for cm in people:
        cm.company_id = co.id
    db.session.commit()

    wanted = [people[2], people[0], people[3], people[1]]
    _rostered(db, show, wanted)

    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    assert _picker_order(html) == [cm.id for cm in wanted]


def test_company_groups_follow_the_roster_not_the_alphabet(app, client, db):
    """The groups are ordered by where their first person sits in the roster,
    so the whole list reads top to bottom in one order.
    """
    from models import Company
    show, day = _show_day(db)
    zulu = Company(name="Zulu Rigging")
    alpha = Company(name="Alpha AV")
    db.session.add_all([zulu, alpha])
    db.session.flush()
    people = _crew(db, show, 2)
    people[0].company_id = zulu.id      # first in the roster
    people[1].company_id = alpha.id
    db.session.commit()
    _rostered(db, show, people)

    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    body = html.split('id="createCrewCallModal"')[1]
    assert body.index("Zulu Rigging") < body.index("Alpha AV")
    assert _picker_order(html) == [people[0].id, people[1].id]


def test_the_picker_is_one_column(app, client, db):
    """A wrapped grid reads left-to-right-then-down, which hides the order."""
    show, day = _show_day(db)
    _crew(db, show, 3)
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    body = html.split('id="createCrewCallModal"')[1]
    body = body[:body.index("3. What do they stop for?")]
    assert "flex-wrap:wrap" not in body

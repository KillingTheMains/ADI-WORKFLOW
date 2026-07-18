"""Tests for bulk-assign crew to a Crew Start event (#38).

Strictly additive: never removes/overwrites existing crew rows, skips crew
already on the target event, and only assigns crew actually on the show.
"""
import datetime as dt


def _setup(db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewMember,
                        ShowCrewAssignment, Company)
    show = Show(name="Bulk Show", code="BK26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 20))
    db.session.add(day); db.session.flush()
    cs = ScheduleActivity(day_id=day.id, time="8:00 AM",
                          description="CREW START", sort_order=10)
    db.session.add(cs); db.session.flush()
    co = Company(name="Acme"); db.session.add(co); db.session.flush()
    crew = []
    for i in range(3):
        cm = CrewMember(first_name="C%d" % i, last_name="X", company_id=co.id)
        db.session.add(cm); db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
        crew.append(cm)
    outsider = CrewMember(first_name="Out", last_name="Sider", company_id=co.id)
    db.session.add(outsider); db.session.flush()
    db.session.commit()
    return show, day, cs, crew, outsider


def _url(app, show_id, day_id):
    from flask import url_for
    with app.test_request_context():
        return url_for("schedule.bulk_assign_crew", show_id=show_id, day_id=day_id)


def test_assigns_selected_crew_to_crew_start(app, client, db):
    from models import CrewRow
    show, day, cs, crew, outsider = _setup(db)
    client.post(_url(app, show.id, day.id), data={
        "activity_id": str(cs.id),
        "crew_member_ids": [str(crew[0].id), str(crew[1].id)],
    })
    assigned = {r.crew_member_id for r in CrewRow.query.filter_by(activity_id=cs.id).all()}
    assert crew[0].id in assigned and crew[1].id in assigned
    assert crew[2].id not in assigned          # not selected


def test_additive_preserves_existing_and_skips_dupes(app, client, db):
    from models import CrewRow
    show, day, cs, crew, outsider = _setup(db)
    # crew[0] already on the event, plus a manual section-header row
    db.session.add(CrewRow(activity_id=cs.id, crew_member_id=crew[0].id, sort_order=5))
    db.session.add(CrewRow(activity_id=cs.id, is_group_header=True,
                           group_label="LEAD", sort_order=1))
    db.session.commit()
    before = CrewRow.query.filter_by(activity_id=cs.id).count()   # 2

    client.post(_url(app, show.id, day.id), data={
        "activity_id": str(cs.id),
        "crew_member_ids": [str(crew[0].id), str(crew[1].id)],    # crew[0] is a dupe
    })
    rows = CrewRow.query.filter_by(activity_id=cs.id).all()
    assert any(r.is_group_header for r in rows)                   # header untouched
    assert sum(1 for r in rows if r.crew_member_id == crew[0].id) == 1  # no dupe
    assert any(r.crew_member_id == crew[1].id for r in rows)      # crew[1] added
    assert len(rows) == before + 1                               # exactly one new row


def test_ignores_crew_not_assigned_to_show(app, client, db):
    from models import CrewRow
    show, day, cs, crew, outsider = _setup(db)
    client.post(_url(app, show.id, day.id), data={
        "activity_id": str(cs.id),
        "crew_member_ids": [str(outsider.id)],
    })
    rows = CrewRow.query.filter_by(activity_id=cs.id).all()
    assert len(rows) == 0                                         # outsider ignored

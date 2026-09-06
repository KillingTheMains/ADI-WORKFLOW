"""Note 3 — every company with people on a crew call gets a header.

Jason, 2026-09-03: "all companies that have employees on the crew call should
be represented by a header in every crew call, and the header should auto
populate based on who is added to the crew call."

Before this, headers were created by hand. `insert_index_for` already knew how
to put a person in their company's section — but only if that section existed,
and nothing ever made one. So the first person from any company fell through
to "end of list", which is how a call ends up full of people and no headers.

Both doors are covered and that is deliberate: the day-page add, and the shared
bulk helper behind the Create Crew Call wizard and the older bulk-assign popup.
A second copy of "where does this person go" is how the two started to drift
before.
"""
from datetime import date as _date

from extensions import db as _db
from models import (Company, CrewMember, CrewRow, ScheduleActivity,
                    ScheduleDay, Show)


def _fixture(db, companies=("Encore",)):
    show = Show(name="Header Show", code="HS1")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=_date(2026, 10, 1), phase="Load In")
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00", description="CREW CALL")
    db.session.add(act); db.session.flush()
    cos = []
    for name in companies:
        c = Company(name=name)
        db.session.add(c); db.session.flush()
        cos.append(c)
    db.session.commit()
    return show, day, act, cos


def _member(db, company, first, last="Hand"):
    cm = CrewMember(first_name=first, last_name=last, company_id=company.id)
    db.session.add(cm); db.session.commit()
    return cm


def _headers(act):
    return [r for r in act.crew_rows if r.is_group_header]


def test_adding_the_first_person_creates_their_company_header(client, db):
    show, day, act, (co,) = _fixture(db)
    cm = _member(db, co, "Ann")
    client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                data={"crew_member_id": str(cm.id)}, follow_redirects=True)
    labels = [h.group_label for h in _headers(act)]
    assert labels == ["Encore"]


def test_the_header_is_bound_to_the_company_not_just_named_after_it(client, db):
    """Binding by company_id is what makes placement authoritative — the label
    fallback exists only for headers that predate binding."""
    show, day, act, (co,) = _fixture(db)
    cm = _member(db, co, "Ann")
    client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                data={"crew_member_id": str(cm.id)}, follow_redirects=True)
    assert _headers(act)[0].company_id == co.id


def test_a_second_person_from_the_same_company_does_not_make_a_second_header(client, db):
    show, day, act, (co,) = _fixture(db)
    for name in ("Ann", "Bob"):
        cm = _member(db, co, name)
        client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                    data={"crew_member_id": str(cm.id)}, follow_redirects=True)
    assert len(_headers(act)) == 1


def test_two_companies_get_two_headers(client, db):
    show, day, act, (a, b) = _fixture(db, ("Encore", "Sparks"))
    for co, name in ((a, "Ann"), (b, "Bob")):
        cm = _member(db, co, name)
        client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                    data={"crew_member_id": str(cm.id)}, follow_redirects=True)
    assert sorted(h.group_label for h in _headers(act)) == ["Encore", "Sparks"]


def test_the_person_lands_under_their_own_header(client, db):
    """A header nobody is under is worse than no header."""
    show, day, act, (a, b) = _fixture(db, ("Encore", "Sparks"))
    for co, name in ((a, "Ann"), (b, "Bob")):
        cm = _member(db, co, name)
        client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                    data={"crew_member_id": str(cm.id)}, follow_redirects=True)

    from crew_sections import walk
    rows = sorted(act.crew_rows, key=lambda r: r.sort_order or 0)
    for row, l1, _l2 in walk(rows):
        assert l1 is not None, "a person ended up outside every section"
        assert l1.company_id == row.crew_member.company_id


def test_an_existing_header_is_reused_not_duplicated(client, db):
    """Larry's real headers predate company binding and only carry a label."""
    show, day, act, (co,) = _fixture(db)
    _db.session.add(CrewRow(activity_id=act.id, is_group_header=True,
                            header_level=1, group_label="ENCORE",
                            qty=0, sort_order=10))
    _db.session.commit()
    cm = _member(db, co, "Ann")
    client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                data={"crew_member_id": str(cm.id)}, follow_redirects=True)
    assert len(_headers(act)) == 1


def test_a_local_labor_line_makes_no_header(client, db):
    """Local labor lines name nobody, and inventing a section for a count
    would be noise — they render in their own block anyway."""
    show, day, act, (co,) = _fixture(db)
    client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                data={"position": "Lighting Hand", "qty": "6",
                      "crew_type": "Local Crew"}, follow_redirects=True)
    assert _headers(act) == []


def test_a_named_person_with_no_company_goes_under_unassigned(client, db):
    """Jason, 2026-09-06, closing the question note 3 left open: yes, an
    "Unassigned" header. Every row sits under a header, and this one is
    visibly a gap to fill rather than a person floating outside every
    section. Two such people share the one header."""
    show, day, act, (co,) = _fixture(db)
    for name in ("Ann", "Bob"):
        cm = CrewMember(first_name=name, last_name="Nobody")
        db.session.add(cm); db.session.commit()
        client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                    data={"crew_member_id": str(cm.id)}, follow_redirects=True)
    headers = _headers(act)
    assert [h.group_label for h in headers] == ["Unassigned"]
    assert headers[0].company_id is None
    people = [r for r in act.ordered_crew_rows if not r.is_group_header]
    assert len(people) == 2
    # and they sit UNDER it, not above it
    order = [r.group_label if r.is_group_header else r.crew_member.first_name
             for r in act.ordered_crew_rows]
    assert order == ["Unassigned", "Ann", "Bob"]


def test_a_company_person_never_lands_under_unassigned(client, db):
    show, day, act, (co,) = _fixture(db)
    nobody = CrewMember(first_name="Ann", last_name="Nobody")
    db.session.add(nobody); db.session.commit()
    client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                data={"crew_member_id": str(nobody.id)}, follow_redirects=True)
    cm = _member(db, co, "Bob")
    client.post(f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
                data={"crew_member_id": str(cm.id)}, follow_redirects=True)
    order = [r.group_label if r.is_group_header else r.crew_member.first_name
             for r in act.ordered_crew_rows]
    assert order == ["Unassigned", "Ann", "Encore", "Bob"]


def test_the_bulk_path_creates_headers_too(client, db):
    """The wizard and the bulk popup share one helper — it used to APPEND, so a
    select-all landed everyone in one block under whatever header was last."""
    from routes.schedule import _assign_crew_to_activity
    show, day, act, (a, b) = _fixture(db, ("Encore", "Sparks"))
    ids = [_member(db, a, "Ann").id, _member(db, b, "Bob").id]
    added, skipped = _assign_crew_to_activity(act, ids, None)
    _db.session.commit()
    assert (added, skipped) == (2, 0)
    assert sorted(h.group_label for h in _headers(act)) == ["Encore", "Sparks"]

"""Note 17 — the Call Sheet became a packet, and two defects fell out of it.

Larry: the Call Sheet button opens a picker with Select All and the chosen
days come out as one batch document. Building that meant lifting the per-day
computation out of the route, and lifting it out exposed two things that had
been wrong the whole time:

  * the double-booking back-mark was a no-op — the line dicts never carried
    `crew_member_id`, so only the SECOND booking of a person was ever flagged
    and a conflict showed one end of itself;
  * the sheet read `act.crew_rows` rather than `ordered_crew_rows`, so it
    listed crew in insertion order while the day page listed them in roster
    order. Two surfaces, two answers to "who reads first".

A single-day call sheet is a batch of one, so both go through the same code
and cannot drift apart again.
"""
import datetime as dt

from models import (CrewMember, CrewRow, ScheduleActivity, ScheduleDay, Show,
                    ShowCrewAssignment)
from routes.schedule import _call_sheet_sheet


def _show(db, n_days=3):
    seq = Show.query.count() + 1
    show = Show(name=f"Packet Show {seq}", code=f"PS{seq}")
    db.session.add(show); db.session.flush()
    days = []
    for i in range(n_days):
        d = ScheduleDay(show_id=show.id, date=dt.date(2026, 11, 2 + i),
                        phase="Load In")
        db.session.add(d); db.session.flush()
        days.append(d)
    db.session.commit()
    return show, days


def _act(db, day, time="08:00", description="CREW START", sort_order=10):
    a = ScheduleActivity(day_id=day.id, time=time, description=description,
                         sort_order=sort_order)
    db.session.add(a); db.session.flush()
    return a


def _person(db, first, last="Hand"):
    cm = CrewMember(first_name=first, last_name=last)
    db.session.add(cm); db.session.flush()
    return cm


def _batch(client, show, day_ids):
    return client.post(f"/shows/{show.id}/call-sheet",
                       data={"day_ids[]": [str(i) for i in day_ids]},
                       follow_redirects=True)


def test_both_ends_of_a_double_booking_are_flagged(client, db):
    """The defect. One person on two calls the same day is two conflicting
    lines, not one — flagging only the later booking hides half of it."""
    show, days = _show(db)
    a1 = _act(db, days[0], time="08:00", description="RIGGING CREW START")
    a2 = _act(db, days[0], time="13:00", description="LIGHTING CREW START",
              sort_order=20)
    cm = _person(db, "Ann")
    db.session.add_all([
        CrewRow(activity_id=a1.id, crew_member_id=cm.id, sort_order=10),
        CrewRow(activity_id=a2.id, crew_member_id=cm.id, sort_order=10),
    ])
    db.session.commit()

    sheet = _call_sheet_sheet(days[0])
    assert len(sheet["crew_lines"]) == 2
    assert [l["conflict"] for l in sheet["crew_lines"]] == [True, True]
    assert sheet["conflicts"] is True


def test_local_labor_on_two_calls_the_same_day_is_not_a_conflict(client, db):
    """Jason, 2026-09-05: double-booked means the same NAMED person on two
    calls in one day. A local-labor line is a count of a position, not a
    person — "4 × Lighting Hand" at 08:00 and again at 13:00 is two separate
    crews, never a conflict. Even a name attached to such a line does not
    make it one, and the day's headcount counts the line by its qty."""
    from models import Position
    show, days = _show(db)
    a1 = _act(db, days[0], time="08:00", description="RIGGING CREW START")
    a2 = _act(db, days[0], time="13:00", description="LOAD OUT CREW",
              sort_order=20)
    pos = Position(title="LL Test Hand", department="Lighting", is_local_labor=True)
    db.session.add(pos); db.session.flush()
    cm = _person(db, "Named")
    db.session.add_all([
        CrewRow(activity_id=a1.id, position_id=pos.id, qty=4, sort_order=10),
        CrewRow(activity_id=a2.id, position_id=pos.id, qty=4, sort_order=10),
        # a named person attached to a local-labor line is still a line
        CrewRow(activity_id=a1.id, position_id=pos.id, crew_member_id=cm.id,
                qty=1, sort_order=20),
        CrewRow(activity_id=a2.id, position_id=pos.id, crew_member_id=cm.id,
                qty=1, sort_order=20),
    ])
    db.session.commit()

    sheet = _call_sheet_sheet(days[0])
    assert sheet["conflicts"] is False
    assert all(l["conflict"] is False for l in sheet["crew_lines"])
    assert all(l["is_local_labor"] for l in sheet["crew_lines"])


def test_total_crew_is_a_headcount_not_a_line_count(client, db):
    """One named person on three calls is one body; four open slots are four.
    "96 people" for a 32-person day was the document the venue catered from."""
    show, days = _show(db)
    acts = [_act(db, days[0], time=t, description=f"CALL {i}", sort_order=10*i)
            for i, t in enumerate(("08:00", "12:00", "16:00"), 1)]
    cm = _person(db, "Thrice")
    for a in acts:
        db.session.add(CrewRow(activity_id=a.id, crew_member_id=cm.id, sort_order=10))
    db.session.add(CrewRow(activity_id=acts[0].id, qty=4, sort_order=20))  # open slots
    db.session.commit()

    sheet = _call_sheet_sheet(days[0])
    assert sheet["total_crew"] == 1 + 4
    assert sheet["total_lines"] == 3 + 4


def test_a_person_called_on_two_different_days_is_not_a_conflict(client, db):
    """Conflicts are scoped to one day. A packet must not invent one across
    pages — everybody on a run of days works more than one of them."""
    show, days = _show(db)
    cm = _person(db, "Ann")
    for d in (days[0], days[1]):
        a = _act(db, d)
        db.session.add(CrewRow(activity_id=a.id, crew_member_id=cm.id,
                               sort_order=10))
    db.session.commit()

    for d in (days[0], days[1]):
        sheet = _call_sheet_sheet(d)
        assert sheet["conflicts"] is False
        assert [l["conflict"] for l in sheet["crew_lines"]] == [False]


def test_crew_read_in_roster_order_not_insertion_order(client, db):
    """`ordered_crew_rows`, not `crew_rows`. The day page and the call sheet
    have to agree about who reads first."""
    show, days = _show(db)
    act = _act(db, days[0])
    first = _person(db, "Zoe", "Zulu")
    second = _person(db, "Amy", "Alpha")
    # Entered Zoe then Amy...
    db.session.add_all([
        CrewRow(activity_id=act.id, crew_member_id=first.id, sort_order=10),
        CrewRow(activity_id=act.id, crew_member_id=second.id, sort_order=20),
    ])
    # ...but the show roster says Amy reads first.
    db.session.add_all([
        ShowCrewAssignment(show_id=show.id, crew_member_id=second.id,
                           sort_order=10),
        ShowCrewAssignment(show_id=show.id, crew_member_id=first.id,
                           sort_order=20),
    ])
    db.session.commit()

    names = [l["name"] for l in _call_sheet_sheet(days[0])["crew_lines"]]
    assert names[0].startswith("Amy")


def test_a_packet_holds_every_chosen_day_in_one_document(client, db):
    show, days = _show(db)
    for i, d in enumerate(days[:2]):
        a = _act(db, d)
        db.session.add(CrewRow(activity_id=a.id, crew_member_id=_person(
            db, f"P{i}").id, sort_order=10))
    db.session.commit()

    r = _batch(client, show, [days[0].id, days[1].id])
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "November 2, 2026" in body
    assert "November 3, 2026" in body
    # Two sheets means a packet, and a packet unpins the per-day footer.
    assert 'class="packet"' in body


def test_days_come_out_in_date_order_however_they_were_ticked(client, db):
    """A packet that runs backwards is a packet that gets handed back."""
    show, days = _show(db)
    for i, d in enumerate(days):
        a = _act(db, d)
        db.session.add(CrewRow(activity_id=a.id, crew_member_id=_person(
            db, f"Q{i}").id, sort_order=10))
    db.session.commit()

    body = _batch(client, show,
                  [days[2].id, days[0].id, days[1].id]).get_data(as_text=True)
    positions = [body.index(d.date.strftime("%B %-d, %Y")) for d in days]
    assert positions == sorted(positions)


def test_a_day_with_nobody_called_is_left_out(client, db):
    """Larry hides empty days before issuing a schedule; a packet should not
    hand a crew a page nobody is on."""
    show, days = _show(db)
    a = _act(db, days[0])
    db.session.add(CrewRow(activity_id=a.id,
                           crew_member_id=_person(db, "Ann").id, sort_order=10))
    db.session.commit()

    body = _batch(client, show,
                  [days[0].id, days[1].id]).get_data(as_text=True)
    assert days[0].date.strftime("%B %-d, %Y") in body
    assert days[1].date.strftime("%B %-d, %Y") not in body
    # One sheet is not a packet.
    assert 'class="packet"' not in body


def test_an_entirely_empty_selection_says_so_rather_than_printing_nothing(client, db):
    show, days = _show(db)
    r = _batch(client, show, [days[0].id, days[1].id])
    body = r.get_data(as_text=True)
    assert "Nobody is called" in body
    assert "DAILY CALL SHEET" not in body


def test_a_day_from_another_show_is_ignored(client, db):
    show, days = _show(db)
    _other, other_days = _show(db)
    a = _act(db, other_days[0])
    db.session.add(CrewRow(activity_id=a.id,
                           crew_member_id=_person(db, "Ann").id, sort_order=10))
    db.session.commit()

    body = _batch(client, show, [other_days[0].id]).get_data(as_text=True)
    assert "Nobody is called" in body


def test_the_day_page_offers_the_picker_with_this_day_ticked(client, db):
    """The old button was a one-click link. It is a picker now, and the day
    you are standing on arrives pre-ticked so the old behaviour survives."""
    show, days = _show(db)
    r = client.get(f"/shows/{show.id}/schedule/{days[0].id}")
    body = r.get_data(as_text=True)
    assert 'id="callSheetDaysModal"' in body
    assert f'id="sheet-day-check-{days[0].id}"' in body
    assert f'id="sheet-day-check-{days[1].id}"' in body
    # ...and the copy picker still cannot target the day you are on.
    assert f'id="copy-day-check-{days[0].id}"' not in body
    assert f'id="copy-day-check-{days[1].id}"' in body

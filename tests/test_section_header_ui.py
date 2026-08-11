"""Section header rendering and editing (note 1, 2026-08-11)."""
import datetime as dt


def _day_with_sections(db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        Company, CrewMember, ShowCrewAssignment, Position)
    co = Company(name="Encore", code="ENCORE")
    db.session.add(co); db.session.flush()
    pos = Position(title="Head Rigger", department="Rigging")
    db.session.add(pos); db.session.flush()

    show = Show(name="Hdr Show", code="HDR26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 4))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:00", description="CREW START")
    db.session.add(act); db.session.flush()

    hdr = CrewRow(activity_id=act.id, is_group_header=True,
                  group_label="ENCORE", header_level=1,
                  company_id=co.id, sort_order=10)
    sub = CrewRow(activity_id=act.id, is_group_header=True,
                  group_label="ENCORE RIGGING", header_level=2, sort_order=20)
    db.session.add_all([hdr, sub]); db.session.flush()
    db.session.commit()
    return show, day, act, hdr, sub, co, pos


def test_day_page_renders_tiered_collapsible_headers(app, client, db):
    show, day, act, hdr, sub, co, pos = _day_with_sections(db)
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert 'data-level="1"' in html
    assert 'data-level="2"' in html
    assert "sect-toggle" in html            # collapse arrow
    assert "crew-drag-row" in html          # drag handle row
    assert "ENCORE RIGGING" in html


def test_header_can_be_renamed_and_rebound(app, client, db):
    from models import CrewRow, Company
    show, day, act, hdr, sub, co, pos = _day_with_sections(db)
    other = Company(name="VRA", code="VRA")
    db.session.add(other); db.session.commit()

    client.post("/shows/%d/schedule/%d/crew/%d/edit" % (show.id, day.id, hdr.id),
                data={"group_label": "ENCORE AV", "header_level": "1",
                      "header_company_id": other.id})
    again = CrewRow.query.get(hdr.id)
    assert again.group_label == "ENCORE AV"
    assert again.company_id == other.id


def test_header_can_be_nested(app, client, db):
    from models import CrewRow
    show, day, act, hdr, sub, co, pos = _day_with_sections(db)
    client.post("/shows/%d/schedule/%d/crew/%d/edit" % (show.id, day.id, hdr.id),
                data={"header_level": "2"})
    assert CrewRow.query.get(hdr.id).header_level == 2


def test_removing_a_header_leaves_its_crew_on_the_call(app, client, db):
    from models import CrewRow, CrewMember
    show, day, act, hdr, sub, co, pos = _day_with_sections(db)
    cm = CrewMember(first_name="Rig", last_name="Ger", company_id=co.id)
    db.session.add(cm); db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id,
                           sort_order=30))
    db.session.commit()

    client.post("/shows/%d/schedule/%d/crew/%d/delete"
                % (show.id, day.id, sub.id))
    remaining = CrewRow.query.filter_by(activity_id=act.id).all()
    assert any(r.crew_member_id == cm.id for r in remaining)
    assert not any(r.id == sub.id for r in remaining)


def test_new_crew_lands_in_the_matching_company_section(app, client, db):
    """Note 3: not under whatever header happened to be last."""
    from models import CrewRow, CrewMember, ShowCrewAssignment
    show, day, act, hdr, sub, co, pos = _day_with_sections(db)
    # A trailing manual section that used to swallow every new addition.
    db.session.add(CrewRow(activity_id=act.id, is_group_header=True,
                           group_label="LEAD CREW", header_level=1,
                           sort_order=100))
    cm = CrewMember(first_name="Ria", last_name="Rig", company_id=co.id,
                    position_id=pos.id)
    db.session.add(cm); db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.commit()

    client.post("/shows/%d/schedule/%d/activities/%d/crew/add"
                % (show.id, day.id, act.id),
                data={"crew_member_id": cm.id, "qty": "1"})

    rows = sorted(CrewRow.query.filter_by(activity_id=act.id).all(),
                  key=lambda r: r.sort_order or 0)
    labels = [r.group_label if r.is_group_header else r.display_name
              for r in rows]
    # Slotted under ENCORE RIGGING, well before LEAD CREW.
    assert labels.index("Ria Rig") < labels.index("LEAD CREW")
    assert labels.index("Ria Rig") > labels.index("ENCORE RIGGING")

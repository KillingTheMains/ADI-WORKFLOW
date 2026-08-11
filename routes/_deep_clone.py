"""Deep-clone helpers for duplicate_show (2026-08-11).

Structure-only cloning answers "next year's version of this show". Deep
cloning answers "a working copy of a live show" — which is what you need to
rehearse a change against real crew, real headcounts and real meal services.
Structure alone cannot exercise any of that.

Field names here were checked against the models rather than assumed: five of
them differ from the obvious guess (SubScheduleEntry.activity not
.description, MealServiceLocation.location_name not .location, and the
dietary/radio/comms models again).
"""
from extensions import db
from models import (CrewCommAssignment, MealService, MealServiceLocation,
                    RadioChannel, ShowCommChannel, ShowCrewAssignment,
                    ShowDietaryNote, ShowOpenSlot, SubScheduleEntry)


def clone_show_crew_and_fnb(src, new_show, day_map, act_map, shift):
    """Copy roster, open slots, OSS entries, F&B and COMS onto ``new_show``.

    ``day_map`` / ``act_map`` translate source ids to the clone's ids. A row
    whose parent did not come across is SKIPPED rather than attached to
    whatever id happens to be there — a mis-mapped row is worse than a missing
    one, because it looks correct.
    """
    for a in src.crew_assignments:
        db.session.add(ShowCrewAssignment(
            show_id=new_show.id, crew_member_id=a.crew_member_id,
            role_override=a.role_override, booking_task=a.booking_task,
            travel_in_date=shift(a.travel_in_date),
            start_date=shift(a.start_date), end_date=shift(a.end_date),
            travel_out_date=shift(a.travel_out_date),
            sort_order=a.sort_order,
            hotel_name=a.hotel_name,
            hotel_check_in=shift(a.hotel_check_in),
            hotel_check_out=shift(a.hotel_check_out),
            hotel_confirmation=a.hotel_confirmation,
            hotel_cost=a.hotel_cost,
            arrival_flight=a.arrival_flight, arrival_time=a.arrival_time,
            departure_flight=a.departure_flight,
            departure_time=a.departure_time,
            itinerary_link=a.itinerary_link,
        ))

    for s in ShowOpenSlot.query.filter_by(show_id=src.id).all():
        db.session.add(ShowOpenSlot(
            show_id=new_show.id, position_id=s.position_id,
            placeholder_label=s.placeholder_label, booking_task=s.booking_task,
            travel_in_date=shift(s.travel_in_date),
            start_date=shift(s.start_date), end_date=shift(s.end_date),
            travel_out_date=shift(s.travel_out_date),
            notes=s.notes, sort_order=s.sort_order,
        ))

    for e in SubScheduleEntry.query.filter_by(show_id=src.id).all():
        new_day_id = day_map.get(e.schedule_day_id)
        if new_day_id is None:
            continue
        db.session.add(SubScheduleEntry(
            show_id=new_show.id, schedule_day_id=new_day_id,
            activity_id=act_map.get(e.activity_id) if e.activity_id else None,
            type=e.type, time=e.time, activity=e.activity,
            duration_hrs=e.duration_hrs, count=e.count,
            notes=e.notes, sort_order=e.sort_order,
        ))

    for ms in MealService.query.filter_by(show_id=src.id).all():
        new_day_id = day_map.get(ms.schedule_day_id)
        if new_day_id is None:
            continue
        new_ms = MealService(
            show_id=new_show.id, schedule_day_id=new_day_id,
            activity_id=act_map.get(ms.activity_id) if ms.activity_id else None,
            name=ms.name, kind=ms.kind, is_recurring=ms.is_recurring,
            notes=ms.notes, sort_order=ms.sort_order,
            setup_minutes=ms.setup_minutes,
            holdover_minutes=ms.holdover_minutes,
        )
        db.session.add(new_ms)
        db.session.flush()
        for loc in ms.locations:
            db.session.add(MealServiceLocation(
                meal_service_id=new_ms.id, location_name=loc.location_name,
                start_time=loc.start_time, end_time=loc.end_time,
                headcount=loc.headcount, notes=loc.notes,
                sort_order=loc.sort_order,
            ))

    for n in ShowDietaryNote.query.filter_by(show_id=src.id).all():
        db.session.add(ShowDietaryNote(
            show_id=new_show.id, preference=n.preference,
            percentage=n.percentage, count=n.count,
            notes=n.notes, sort_order=n.sort_order,
        ))

    for ch in ShowCommChannel.query.filter_by(show_id=src.id).all():
        db.session.add(ShowCommChannel(
            show_id=new_show.id, name=ch.name, sort_order=ch.sort_order,
        ))

    for rc in RadioChannel.query.filter_by(show_id=src.id).all():
        db.session.add(RadioChannel(
            show_id=new_show.id, slot=rc.slot, name=rc.name,
        ))

    for ca in CrewCommAssignment.query.filter_by(show_id=src.id).all():
        db.session.add(CrewCommAssignment(
            show_id=new_show.id, crew_member_id=ca.crew_member_id,
            radio=ca.radio, headset=ca.headset,
            pack_type=ca.pack_type, pack_brand=ca.pack_brand,
            pack_brand_other=ca.pack_brand_other,
            channel_ids=ca.channel_ids, notes=ca.notes,
        ))

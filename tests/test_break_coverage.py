"""The coverage panel — step 6 (2026-08-12).

What the panel has to get right, and why each one is a real risk:

* it counts what is UNANSWERED, not what somebody answered "no" to. Listing
  answers as problems is what made the keyword warning unusable;
* nothing is counted twice, or the totals lie and the panel stops being read;
* it can reach ZERO. A standalone client lunch is a real thing, and a check
  that can never clear is the next warning nobody looks at;
* the bulk action goes through the SAME tools as the single-row ones, so
  "Provided" cannot come to mean two different things.
"""
import datetime as dt

import break_coverage


def _show(db, code, days=1):
    from models import Show, ScheduleDay
    show = Show(name="Cov", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    out = []
    for i in range(days):
        d = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8 + i),
                        sod="07:00", eod="18:00")
        db.session.add(d); out.append(d)
    db.session.flush()
    return show, out


def _call(db, day, time="07:00", qty=11):
    from models import CrewRow, ScheduleActivity
    call = ScheduleActivity(day_id=day.id, time=time, description="CREW START")
    db.session.add(call); db.session.flush()
    db.session.add(CrewRow(activity_id=call.id, qty=qty, hours=10.0))
    db.session.flush()
    return call


def _break(db, show, day, call, time="12:00", label="LUNCH", duration=60,
           catered="unconfirmed", service=None):
    from models import CrewBreak, ScheduleActivity
    act = ScheduleActivity(day_id=day.id, time=time, description=label)
    db.session.add(act); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label=label, duration_minutes=duration, catered=catered,
                   meal_service_id=service.id if service else None)
    db.session.add(cb); db.session.flush()
    return cb


def _service(db, show, day, name="Crew Lunch", kind="lunch", time="12:00",
             recurring=False):
    from models import MealService, MealServiceLocation
    svc = MealService(show_id=show.id, schedule_day_id=day.id, name=name,
                      kind=kind, is_recurring=recurring)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       start_time=time, sort_order=0))
    db.session.flush()
    return svc


# ── what counts, and what deliberately does not ─────────────────────────────

def test_a_tbd_break_is_the_first_question(app, db):
    show, (day,) = _show(db, "CV01")
    call = _call(db, day)
    _break(db, show, day, call, catered="unconfirmed")
    db.session.commit()
    c = break_coverage.survey(show)["counts"]
    assert c["undecided"] == 1
    assert c["total"] == 1


def test_not_provided_at_coffee_length_is_an_answer_not_a_gap(app, db):
    """A crew walking away for fifteen minutes is not a coverage problem. The
    keyword warning listed exactly this sort of row, which is why nobody could
    use it."""
    show, (day,) = _show(db, "CV02")
    call = _call(db, day)
    _break(db, show, day, call, time="09:30", label="COFFEE",
           duration=15, catered="no")
    db.session.commit()
    assert break_coverage.survey(show)["clear"] is True


def test_a_meal_length_break_with_nothing_feeding_it_is_listed(app, db):
    show, (day,) = _show(db, "CV03")
    call = _call(db, day)
    _break(db, show, day, call, duration=60, catered="no")
    db.session.commit()
    c = break_coverage.survey(show)["counts"]
    assert c["unfed"] == 1 and c["undecided"] == 0


def test_says_provided_with_no_service_is_a_contradiction_at_any_length(app, db):
    """Marking a break Provided is what CREATES its service, so a break in
    this state had one deleted off the F&B tab afterwards. It reads as catered
    and nothing is catering it — the shape of failure that reaches site."""
    show, (day,) = _show(db, "CV04")
    call = _call(db, day)
    cb = _break(db, show, day, call, duration=15, label="COFFEE",
                catered="yes")
    db.session.commit()
    assert break_coverage.is_contradiction(cb) is True
    assert break_coverage.survey(show)["counts"]["unfed"] == 1


def test_a_break_is_never_counted_twice(app, db):
    """TBD and no-service are both true of the same row. It belongs in the
    first list only, or the total overstates the work and stops being read."""
    show, (day,) = _show(db, "CV05")
    call = _call(db, day)
    _break(db, show, day, call, duration=60, catered="unconfirmed")
    db.session.commit()
    c = break_coverage.survey(show)["counts"]
    assert (c["undecided"], c["unfed"]) == (1, 0)
    assert c["total"] == 1


def test_a_service_with_no_break_is_the_orphan_not_provided_leaves(app, db):
    show, (day,) = _show(db, "CV06")
    _service(db, show, day)
    db.session.commit()
    assert break_coverage.survey(show)["counts"]["orphans"] == 1


def test_a_standing_beverage_service_is_never_an_orphan(app, db):
    """It feeds nobody AT a break by definition. Uses is_beverage_service —
    the ONE predicate — so the legacy rows with is_recurring False and only a
    name to go on are excluded too."""
    show, (day,) = _show(db, "CV07")
    _service(db, show, day, name="All Day Beverages", kind="beverages")
    _service(db, show, day, name="Crew Break - Refresh as Needed", kind="other")
    db.session.commit()
    assert break_coverage.survey(show)["counts"]["orphans"] == 0


def test_a_confirmed_standalone_service_drops_out(app, db):
    """A client lunch feeds no crew break and never will. Without this the
    panel can never reach zero, which is how a check stops being read."""
    show, (day,) = _show(db, "CV08")
    svc = _service(db, show, day, name="Client Lunch")
    db.session.commit()
    assert break_coverage.survey(show)["counts"]["orphans"] == 1
    svc.standalone_confirmed = True
    db.session.commit()
    assert break_coverage.survey(show)["clear"] is True


def test_findings_group_under_their_day(app, db):
    show, days = _show(db, "CV09", days=3)
    call = _call(db, days[1])
    _break(db, show, days[1], call)
    db.session.commit()
    result = break_coverage.survey(show)
    assert result["counts"]["days"] == 1
    assert result["days"][0]["day"].id == days[1].id


def test_linking_clears_a_stale_standalone_mark(app, db):
    """Otherwise a service marked standalone and later linked would keep
    hiding from the orphan count while genuinely feeding a break — a wrong
    number in the one place the panel exists to make right."""
    import break_linking
    show, (day,) = _show(db, "CV10")
    call = _call(db, day)
    cb = _break(db, show, day, call)
    svc = _service(db, show, day)
    svc.standalone_confirmed = True
    db.session.commit()
    ok, msg = break_linking.link(cb, svc)
    db.session.commit()
    assert ok, msg
    assert svc.standalone_confirmed is False


# ── the bulk action ─────────────────────────────────────────────────────────

def test_bulk_provided_creates_one_service_per_break(app, db, client):
    show, (day,) = _show(db, "CV11")
    call = _call(db, day)
    a = _break(db, show, day, call, time="12:00")
    b = _break(db, show, day, call, time="13:00")
    db.session.commit()
    r = client.post(f"/shows/{show.id}/breaks/coverage/resolve",
                    data={"catered": "yes",
                          "break_ids": [str(a.id), str(b.id)]},
                    follow_redirects=True)
    assert r.status_code == 200
    assert a.catered == "yes" and b.catered == "yes"
    assert a.meal_service_id and b.meal_service_id
    assert a.meal_service_id != b.meal_service_id


def test_the_created_service_follows_the_crew(app, db, client):
    """No headcount is typed in, so it reads the crew call and keeps reading
    it. A figure frozen when the break was created is wrong by the time it
    matters."""
    show, (day,) = _show(db, "CV12")
    call = _call(db, day, qty=17)
    cb = _break(db, show, day, call)
    db.session.commit()
    client.post(f"/shows/{show.id}/breaks/coverage/resolve",
                data={"catered": "yes", "break_ids": [str(cb.id)]})
    assert cb.meal_service.total_headcount == 17
    assert cb.meal_service.headcount_is_derived is True


def test_bulk_not_provided_unlinks_and_never_deletes(app, db, client):
    """Deleting F&B's work off a bulk tick is not recoverable. The service
    stays and lands in the orphan list, where somebody can decide about it."""
    from models import MealService
    show, (day,) = _show(db, "CV13")
    call = _call(db, day)
    svc = _service(db, show, day)
    cb = _break(db, show, day, call, catered="yes", service=svc)
    db.session.commit()
    client.post(f"/shows/{show.id}/breaks/coverage/resolve",
                data={"catered": "no", "break_ids": [str(cb.id)]})
    assert cb.catered == "no"
    assert cb.meal_service_id is None
    assert MealService.query.get(svc.id) is not None
    assert break_coverage.survey(show)["counts"]["orphans"] == 1


def test_the_bulk_action_cannot_reach_another_show(app, db, client):
    """The app has no authentication. Scoping the query to the show is the
    only guard there is, and a bulk write is the worst place to leave it off."""
    show, (day,) = _show(db, "CV14")
    other, (other_day,) = _show(db, "CV15")
    call = _call(db, other_day)
    theirs = _break(db, other, other_day, call)
    db.session.commit()
    client.post(f"/shows/{show.id}/breaks/coverage/resolve",
                data={"catered": "yes", "break_ids": [str(theirs.id)]})
    assert theirs.catered == "unconfirmed"
    assert theirs.meal_service_id is None


def test_answering_standalone_on_the_fb_tab_is_recorded(app, db, client):
    """It was always an offered answer with nowhere to be stored, which left
    it indistinguishable from a question nobody had asked."""
    show, (day,) = _show(db, "CV16")
    svc = _service(db, show, day, name="Client Lunch")
    db.session.commit()
    client.post(f"/shows/{show.id}/oss/fb/service/{svc.id}/feeds",
                data={"break_id": ""})
    assert svc.standalone_confirmed is True
    assert break_coverage.survey(show)["clear"] is True


def test_the_panel_renders(app, db, client):
    show, (day,) = _show(db, "CV17")
    call = _call(db, day)
    _break(db, show, day, call)
    _service(db, show, day, name="Client Lunch")
    db.session.commit()
    r = client.get(f"/shows/{show.id}/breaks/coverage")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Not decided" in body and "Feeding nobody" in body

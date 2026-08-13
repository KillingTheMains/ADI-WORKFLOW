#!/usr/bin/env python3
"""READ-ONLY audit: how far is the OSS from being a summary of the day pages?

Jason, 2026-08-13: "The OSS and all the tabs are purely intended to be a
summary of things that exist on the daily schedules ... they are not their own
schedules themselves."

Today they ARE their own schedule, and not by accident. `ScheduleActivity` has
six columns and none of them is a department, so an activity cannot say "I am
a Dock event". That is why `SubScheduleEntry` carries its own day, time, count
and notes, why `schedule_day_id` is NOT NULL while `activity_id` is nullable,
and why the day page has a form labelled "an operational item that isn't tied
to an activity".

Making the OSS a view means giving activities a department. This script
measures what that would cost:

  · how many OSS entries are unlinked, by department — the ones that would
    become activities;
  · how many of those already have an activity at the same day and time they
    could merge into, rather than creating a duplicate;
  · what legacy is still in the F&B model.

It CHANGES NOTHING and rolls back.

RUN IT ON THE PYTHONANYWHERE CONSOLE:

    cd ~/adi-workflow && DATABASE_URL='sqlite:////home/killingthemains/adi_workflow.db' python3 audit_oss_legacy.py

Options:
    --csv PATH    row-by-row list of unlinked entries (default ~/oss_audit.csv)
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=os.path.expanduser("~/oss_audit.csv"))
    args = ap.parse_args()

    os.environ.setdefault("SECRET_KEY", "audit-read-only")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from app import create_app
    from extensions import db
    from breaks import is_beverage_service
    from models import (CrewBreak, MealService, ScheduleActivity, ScheduleDay,
                        Show, SubScheduleEntry, SUB_SCHEDULE_META)
    from time_utils import sort_minutes

    app = create_app()
    with app.app_context():
        url = str(db.engine.url)
        print("=" * 78)
        print("OSS / F&B LEGACY AUDIT — read-only, nothing is written")
        print("database: %s" % url)
        if "memory" in url:
            print("\n!! In-memory database. Set DATABASE_URL and run again.")
            return 1
        print("=" * 78)

        shows = Show.query.all()
        print("\nshows: %d" % len(shows))

        # ── OSS entries ─────────────────────────────────────────────────
        entries = SubScheduleEntry.query.all()
        linked = [e for e in entries if e.activity_id]
        unlinked = [e for e in entries if not e.activity_id]
        print("\n" + "-" * 78)
        print("OSS ENTRIES")
        print("-" * 78)
        print("  total ................ %d" % len(entries))
        print("  linked to an activity  %d" % len(linked))
        print("  UNLINKED ............. %d   <- these have no home on a day page"
              % len(unlinked))

        by_dept = Counter(e.type for e in entries)
        un_by_dept = Counter(e.type for e in unlinked)
        print("\n  %-16s %8s %8s %10s" % ("department", "total", "linked", "unlinked"))
        for dept, n in sorted(by_dept.items(),
                              key=lambda kv: SUB_SCHEDULE_META.get(kv[0], {}).get("sort", 99)):
            print("  %-16s %8d %8d %10d"
                  % (SUB_SCHEDULE_META.get(dept, {}).get("label", dept),
                     n, n - un_by_dept.get(dept, 0), un_by_dept.get(dept, 0)))

        # ── Could an unlinked entry merge into an existing activity? ────
        #
        # THE SIZING QUESTION. If a Dock entry at 07:00 on day 4 sits at the
        # same minute as an activity on that day, the unification can merge
        # them and tag the activity 'Dock'. If nothing is there, the entry
        # becomes a NEW activity. The first is free; the second grows the day
        # page, which is the thing to know before agreeing to this.
        acts_by_day = defaultdict(list)
        for a in ScheduleActivity.query.all():
            acts_by_day[a.day_id].append(a)

        would_merge, would_add, no_time = [], [], []
        for e in unlinked:
            mins = sort_minutes(e.effective_time)
            if e.effective_time is None or mins is None or mins > 24 * 60:
                no_time.append(e)
                continue
            hit = next((a for a in acts_by_day.get(e.schedule_day_id, [])
                        if sort_minutes(a.time) == mins), None)
            (would_merge if hit else would_add).append((e, hit))

        print("\n  Of the %d unlinked:" % len(unlinked))
        print("    %4d share a minute with an existing activity — MERGE, free"
              % len(would_merge))
        print("    %4d have no activity at that time — become NEW activities"
              % len(would_add))
        print("    %4d have no readable time at all — need a human"
              % len(no_time))

        days_with_acts = len({a.day_id for a in ScheduleActivity.query.all()})
        if days_with_acts:
            print("    that is %.1f new rows per scheduled day on average"
                  % (len(would_add) / float(days_with_acts)))

        # ── F&B ─────────────────────────────────────────────────────────
        print("\n" + "-" * 78)
        print("F&B")
        print("-" * 78)
        stray = SubScheduleEntry.query.filter_by(type="F&B").count()
        print("  legacy type='F&B' entries (pre-v2) ....... %d" % stray)

        services = MealService.query.all()
        bev = [s for s in services if is_beverage_service(s)]
        bev_legacy = [s for s in bev if not s.is_recurring]
        print("  meal services ............................ %d" % len(services))
        print("    beverage services ...................... %d" % len(bev))
        print("    ...of which carry is_recurring=False .... %d   <- legacy shape"
              % len(bev_legacy))

        per_day = Counter(s.schedule_day_id for s in bev)
        doubled = {d: n for d, n in per_day.items() if n > 1}
        print("  days with MORE THAN ONE beverage service .. %d   <- the guard "
              "that never fired" % len(doubled))
        for day_id, n in sorted(doubled.items()):
            day = ScheduleDay.query.get(day_id)
            print("      %s: %d" % (day.date if day else "day %s" % day_id, n))

        unlinked_svc = [s for s in services if not s.activity_id]
        orphan_svc = [s for s in services
                      if not is_beverage_service(s)
                      and getattr(s, "crew_break", None) is None
                      and not s.standalone_confirmed]
        print("  services not linked to an activity ....... %d" % len(unlinked_svc))
        print("  services feeding nobody, unconfirmed ..... %d" % len(orphan_svc))

        # ── Breaks ──────────────────────────────────────────────────────
        print("\n" + "-" * 78)
        print("BREAKS")
        print("-" * 78)
        breaks = CrewBreak.query.all()
        act_ids = {a.id for a in ScheduleActivity.query.all()}
        no_call = [b for b in breaks if not b.crew_call_id]
        orphaned = [b for b in breaks if b.activity_id not in act_ids]
        print("  total .................................... %d" % len(breaks))
        print("  no crew-call anchor (headcount unknown) .. %d" % len(no_call))
        print("  ORPHANED — activity no longer exists ..... %d" % len(orphaned))
        if orphaned:
            print("      still holding a meal service: %d"
                  % sum(1 for b in orphaned if b.meal_service_id))
        print("  by kind:    %s" % dict(Counter(b.kind for b in breaks)))
        print("  by catered: %s" % dict(Counter(b.catered for b in breaks)))

        # ── One meal, many calls ────────────────────────────────────────
        #
        # Jason's 2026-08-13 decision: a service should be able to feed
        # several crew calls, with the food-out rule measured across the span
        # it covers. Today the rule is 1:1. This is how many services would
        # want a second break if that changes — not computable from here, but
        # the count of breaks with no service and a meal length is the pool.
        fed = sum(1 for b in breaks if b.meal_service_id)
        meal_unfed = [b for b in breaks
                      if b.kind != "coffee" and not b.meal_service_id]
        print("\n  breaks fed by a service .................. %d" % fed)
        print("  meal-kind breaks with NO service ......... %d" % len(meal_unfed))

        # ── Activities ──────────────────────────────────────────────────
        print("\n" + "-" * 78)
        print("ACTIVITIES  (what would need a department)")
        print("-" * 78)
        acts = ScheduleActivity.query.all()
        claimed = {e.activity_id for e in linked} | {
            s.activity_id for s in services if s.activity_id}
        print("  total .................................... %d" % len(acts))
        print("  already claimed by an OSS entry or meal .. %d" % len(claimed))
        print("  would keep no department ................. %d"
              % (len(acts) - len(claimed)))

        # ── The list ────────────────────────────────────────────────────
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["show", "day", "department", "time", "label", "count",
                        "hours", "notes", "verdict", "merges_into"])
            for e, hit in list(would_merge) + [(e, None) for e, _h in would_add]:
                day = e.schedule_day
                w.writerow([
                    day.show.code if day and day.show else "",
                    day.date if day else "",
                    SUB_SCHEDULE_META.get(e.type, {}).get("label", e.type),
                    e.effective_time or "", e.activity or "",
                    e.count if e.count is not None else "",
                    e.duration_hrs if e.duration_hrs is not None else "",
                    e.notes or "",
                    "merge" if hit else "new activity",
                    hit.description if hit else "",
                ])
            for e in no_time:
                day = e.schedule_day
                w.writerow([
                    day.show.code if day and day.show else "",
                    day.date if day else "",
                    SUB_SCHEDULE_META.get(e.type, {}).get("label", e.type),
                    "", e.activity or "",
                    e.count if e.count is not None else "",
                    e.duration_hrs if e.duration_hrs is not None else "",
                    e.notes or "", "no time — needs a human", "",
                ])
        print("\nwrote %s" % args.csv)
        print("\nNothing was changed.")

        db.session.rollback()
    return 0


if __name__ == "__main__":
    sys.exit(main())

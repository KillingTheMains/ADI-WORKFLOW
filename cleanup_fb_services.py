#!/usr/bin/env python3
"""One beverage table per day, one service per meal. DRY RUN by default.

Measured on production 2026-08-13: 48 meal services, of which 36 were
beverage services spread across 10 days — up to SIX on one day. Reading their
names told the story:

  · 25 rows named "Crew Break - Refresh as Needed" or "Refresh Beverage",
    kind='other', no locations. These are the OLD F&B model's way of storing
    each beverage top-up — one row per refresh. The modern model COMPUTES
    those from the day's first crew call, the day's EOD, and the service's
    own offset and interval (`beverage_service.plan_for_service`). They are
    stored copies of a calculation, and each one renders as its own service
    card on the F&B tab. That is the clutter.

  · 9 rows named "Crew Beverage Set", one per day, each carrying a real
    location. These are the actual beverage tables.

  · 2 rows named "All Day Beverages" carrying is_recurring=1 — the modern
    shape, created through the current button, on two days that ALREADY had a
    "Crew Beverage Set". Genuine duplicates, created because
    `fb_standing_add`'s "one per day" guard was a SQL filter on is_recurring
    and every legacy row carries False, so it never fired. Fixed in bf1d80e;
    these are the ones it let through first.

  · 3 pairs of identically-named "LUNCH BREAK — 08:00 CREW" meal services on
    consecutive days. Same crew, same name, no locations.

THE RULE, and it is one rule rather than a list of row ids — ids are
production-specific and a script that hard-codes them cannot be tested:

  For each day, among the services `breaks.is_beverage_service` recognises,
  keep exactly ONE and delete the rest. The survivor is chosen by, in order:
     1. is_recurring=1        — the modern shape wins (Jason, 2026-08-13)
     2. has a location        — a real table was set somewhere
     3. name says no "refresh"
     4. lowest id             — stable, so a re-run picks the same one
  The survivor inherits a location from a deleted row if it has none, is
  flagged is_recurring=1 and kind='beverages'.

  Separately, non-beverage services sharing a day AND a name AND a kind
  collapse to one. The survivor is whichever feeds a crew break, else the
  lowest id.

That rule produces the outcome Jason chose on all three questions, including
promoting the one refresh row on 2026-09-17 that carries a location — that
day has no "Crew Beverage Set", so rule 2 elects it.

NOTHING IS DELETED WITHOUT BEING PRINTED FIRST. The dry run names every row,
every location and note that would go with it, and every crew break that
points at one.

    cd ~/adi-workflow && DATABASE_URL='sqlite:////home/killingthemains/adi_workflow.db' python3 cleanup_fb_services.py
    ...read it, then:
    cd ~/adi-workflow && DATABASE_URL='sqlite:////home/killingthemains/adi_workflow.db' python3 cleanup_fb_services.py --commit

Take a backup first: `python3 backup_sqlite.py`
"""
import argparse
import os
import sys
from collections import defaultdict

REFRESH_WORDS = ("refresh",)


def _has_location(svc):
    return any((l.location_name or "").strip() for l in (svc.locations or []))


def _first_location_name(svc):
    for l in (svc.locations or []):
        if (l.location_name or "").strip():
            return l.location_name.strip()
    return None


def _survivor_key(svc):
    """Lower sorts first, so this is the ranking in the docstring."""
    return (
        0 if svc.is_recurring else 1,
        0 if _has_location(svc) else 1,
        1 if any(w in (svc.name or "").lower() for w in REFRESH_WORDS) else 0,
        svc.id or 0,
    )


def plan_for_day(day_services, breaks_by_service, beverage_name=None,
                 is_beverage=None):
    """What to do with ONE day's services. Pure — reads, never writes.

    Returns ``(promote, doomed, blocked)``:
      promote — [(service, {field: new value})] the survivors, normalised
      doomed  — [(service, reason, survivor)]
      blocked — [(service, why)] left alone for a human

    Lives out here so the decision can be tested without a database or an
    app context. Deleting rows off production on the strength of logic buried
    in a `main()` is not something to do twice.
    """
    if is_beverage is None:                      # injectable for tests
        from breaks import is_beverage_service as is_beverage
    promote, doomed, blocked = [], [], []

    # ── One beverage table per day ──────────────────────────────────────
    bev = sorted([s for s in day_services if is_beverage(s)], key=_survivor_key)
    if bev:
        keep, rest = bev[0], bev[1:]
        changes = {}
        if not keep.is_recurring:
            changes["is_recurring"] = True
        if (keep.kind or "") != "beverages":
            changes["kind"] = "beverages"
        if beverage_name and keep.name != beverage_name:
            changes["name"] = beverage_name
        if not _has_location(keep):
            inherited = next((_first_location_name(s) for s in rest
                              if _first_location_name(s)), None)
            if inherited:
                changes["location"] = inherited
        if changes:
            promote.append((keep, changes))
        for s in rest:
            doomed.append((s, "second beverage service on this day", keep))

    # ── Meals: collapse exact duplicates ────────────────────────────────
    meals = [s for s in day_services if not is_beverage(s)]
    groups = {}
    for s in meals:
        groups.setdefault(((s.name or "").strip().lower(),
                           (s.kind or "").strip()), []).append(s)
    for group in groups.values():
        if len(group) < 2:
            continue
        fed = [s for s in group if breaks_by_service.get(s.id)]
        if len(fed) > 1:
            # Two of them genuinely feed different breaks. That is not a
            # duplicate, it is two crew groups — leave it alone and say so.
            for s in group:
                blocked.append((s, "several of these feed different breaks"))
            continue
        keep = fed[0] if fed else sorted(group, key=lambda s: s.id or 0)[0]
        for s in group:
            if s is not keep:
                doomed.append((s, "duplicate meal service on this day", keep))

    return promote, doomed, blocked


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="actually apply. Without this it only reports.")
    ap.add_argument("--beverage-name", default=None,
                    help="rename every surviving beverage table to this")
    args = ap.parse_args()

    os.environ.setdefault("SECRET_KEY", "cleanup")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from app import create_app
    from extensions import db
    from breaks import is_beverage_service
    from models import CrewBreak, MealService, ScheduleDay

    app = create_app()
    with app.app_context():
        url = str(db.engine.url)
        print("=" * 78)
        print("F&B SERVICE CLEANUP — %s"
              % ("COMMITTING" if args.commit else "DRY RUN, nothing is written"))
        print("database: %s" % url)
        print("=" * 78)
        if "memory" in url:
            print("\n!! In-memory database. Set DATABASE_URL and run again.")
            return 1

        services = MealService.query.all()
        breaks_by_service = defaultdict(list)
        for cb in CrewBreak.query.filter(CrewBreak.meal_service_id.isnot(None)).all():
            breaks_by_service[cb.meal_service_id].append(cb)

        by_day = defaultdict(list)
        for s in services:
            by_day[s.schedule_day_id].append(s)

        doomed = []            # (svc, reason, survivor)
        promote = []           # (svc, changes dict)
        blocked = []           # (svc, why)

        # ONE planner, per day, defined above and tested directly in
        # tests/test_fb_service_cleanup.py. main() used to hold a second copy
        # of this logic, which is how a script that deletes production rows
        # ends up with the tested version and the running version differing.
        for _day_id, day_services in sorted(by_day.items()):
            p, d, b = plan_for_day(day_services, breaks_by_service,
                                   beverage_name=args.beverage_name,
                                   is_beverage=is_beverage_service)
            promote += p
            doomed += d
            blocked += b

        # ── Report ──────────────────────────────────────────────────────
        day_dates = {d.id: d.date for d in ScheduleDay.query.all()}

        print("\n%d service(s) would be KEPT and normalised:" % len(promote))
        for svc, changes in sorted(promote, key=lambda p: str(day_dates.get(p[0].schedule_day_id))):
            bits = ", ".join("%s -> %s" % (k, v) for k, v in sorted(changes.items()))
            print("  %s  id %-4s %-34s  %s"
                  % (day_dates.get(svc.schedule_day_id), svc.id, svc.name[:34], bits))

        # A location on a doomed row is only LOST if nothing inherits it. The
        # survivor rule copies the first one it finds, so say which.
        inherited_locations = {
            (svc.id, changes["location"])
            for svc, changes in promote if "location" in changes
        }
        inherited_names = {name for _sid, name in inherited_locations}

        print("\n%d service(s) would be DELETED:" % len(doomed))
        carried = lost_locations = lost_notes = relinked = orphaned_breaks = 0
        for svc, reason, keep in sorted(
                doomed, key=lambda t: (str(day_dates.get(t[0].schedule_day_id)), t[0].id or 0)):
            extra = []
            loc = _first_location_name(svc)
            if loc:
                if loc in inherited_names:
                    extra.append("location %r carried to id %s" % (loc, keep.id))
                    carried += 1
                else:
                    extra.append("LOCATION %r LOST" % loc)
                    lost_locations += 1
            if (svc.notes or "").strip():
                extra.append("NOTES %r" % svc.notes.strip()[:40])
                lost_notes += 1
            for cb in breaks_by_service.get(svc.id, []):
                if is_beverage_service(svc):
                    extra.append("break %s would be UNLINKED" % cb.id)
                    orphaned_breaks += 1
                elif breaks_by_service.get(keep.id):
                    extra.append("break %s BLOCKED — survivor already fed" % cb.id)
                else:
                    extra.append("break %s moves to id %s" % (cb.id, keep.id))
                    relinked += 1
            print("  %s  id %-4s %-34s  <- %s%s"
                  % (day_dates.get(svc.schedule_day_id), svc.id, svc.name[:34],
                     reason, ("  [" + "; ".join(extra) + "]") if extra else ""))

        if blocked:
            print("\n%d service(s) LEFT ALONE for a human:" % len(blocked))
            for svc, why in blocked:
                print("  %s  id %-4s %-34s  <- %s"
                      % (day_dates.get(svc.schedule_day_id), svc.id,
                         svc.name[:34], why))

        # A survivor still named "refresh" is now the day's beverage table
        # under a name that describes a top-up. Worth saying out loud.
        odd_names = [(svc, day_dates.get(svc.schedule_day_id))
                     for svc, _c in promote
                     if any(w in (svc.name or "").lower() for w in REFRESH_WORDS)]
        if odd_names:
            print("\n⚠ %d surviving beverage table(s) still named as a refresh:"
                  % len(odd_names))
            for svc, date in odd_names:
                print("  %s  id %-4s %r" % (date, svc.id, svc.name))
            print("  Pass --beverage-name 'All Day Beverages' to rename every"
                  " surviving table.")

        print("\n" + "-" * 78)
        print("  services now .............. %d" % len(services))
        print("  would be deleted .......... %d" % len(doomed))
        print("  would remain .............. %d" % (len(services) - len(doomed)))
        print("  locations carried over .... %d" % carried)
        print("  locations LOST ............ %d" % lost_locations)
        print("  notes LOST ................ %d" % lost_notes)
        print("  breaks re-pointed ......... %d" % relinked)
        print("  breaks unlinked ........... %d" % orphaned_breaks)
        print("-" * 78)

        if not args.commit:
            print("\nDRY RUN — nothing was written. Re-run with --commit to apply.")
            db.session.rollback()
            return 0

        # ── Apply ───────────────────────────────────────────────────────
        from models import MealServiceLocation
        for svc, changes in promote:
            for field, value in changes.items():
                if field == "location":
                    db.session.add(MealServiceLocation(
                        meal_service_id=svc.id, location_name=value))
                else:
                    setattr(svc, field, value)
        for svc, _reason, keep in doomed:
            for cb in breaks_by_service.get(svc.id, []):
                if is_beverage_service(svc):
                    cb.meal_service_id = None
                elif not breaks_by_service.get(keep.id):
                    cb.meal_service_id = keep.id
                else:
                    cb.meal_service_id = None
            db.session.delete(svc)
        db.session.commit()
        print("\nCOMMITTED. %d deleted, %d normalised."
              % (len(doomed), len(promote)))
        remaining = MealService.query.count()
        print("services remaining: %d" % remaining)
    return 0


if __name__ == "__main__":
    sys.exit(main())

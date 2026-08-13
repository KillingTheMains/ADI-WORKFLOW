#!/usr/bin/env python3
"""READ-ONLY audit: which crew records are really local-labour positions?

Larry's roster has position names sitting in it as people. Two different
things got in there by two different doors, and only one of them is
machine-detectable:

  * UNNAMED SLOTS — no real name, but a company and a position, so
    `display_label` renders them as "Sparks A1" or "Sparks Lighting Hand".
    `CrewMember.is_unnamed_slot` finds these exactly. They came from the
    day-editor quick add (routes/show_crew.py), which is *designed* to make
    them.

  * POSITION NAMES TYPED INTO THE NAME FIELDS — first="Lighting",
    last="Hand". No predicate in the app finds these; they look exactly like
    a person called Lighting Hand. They came from the XLSX importer
    (routes/crew_import.py), which only recognises a literal "TBD" with a
    blank surname and waves everything else through as a person. Finding
    them means matching names against the position catalogue and then having
    a human read the list.

This script CHANGES NOTHING. It classifies, counts, predicts the headcount
effect of converting, and writes a CSV for you and Larry to go through. The
migration comes after somebody has read the list, not before.

RUN IT ON THE PYTHONANYWHERE CONSOLE:

    cd ~/adi-workflow && DATABASE_URL='sqlite:////home/killingthemains/adi_workflow.db' python3 audit_crew_local_labor.py

The DATABASE_URL matters. Without it this reads a different, empty database
and cheerfully tells you there is nothing to do.

Options:
    --csv PATH     where to write the row-by-row list (default ~/crew_audit.csv)
    --all          list every record, including the ones judged to be people
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

# ── The vocabulary used to spot a position wearing a person's name ─────────
#
# Deliberately NOT a regex over job-sounding words. "Hand" and "Driver" are
# real surnames, and a false positive here proposes deleting a real person
# from the roster. Two narrow tests instead, and a third that only ever
# SUGGESTS.

# Titles that came off Jason's SAP workbooks with the provider welded on.
WORKBOOK_PREFIXES = ("local - ", "house - ", "deco - teamster - ", "freeman - ")

# Words that make a name worth a human look, never an automatic verdict.
SUSPICIOUS_WORDS = {
    "hand", "hands", "rigger", "stagehand", "steward", "loader", "unloader",
    "operator", "forklift", "electrician", "spot", "spotop", "grip",
    "carpenter", "audio", "video", "lighting", "led", "scenic", "drape",
    "labor", "labour", "crew", "utility", "runner", "pusher",
}

BUCKETS = [
    ("A", "Unnamed slot — renders as company + position"),
    ("B", "Name IS a catalogue position title"),
    ("C", "Name carries a workbook provider prefix"),
    ("D", "Partial placeholder name"),
    ("E", "Worth a look — position-ish word in the name"),
    ("F", "Looks like a real person"),
]


def _norm(value):
    return " ".join((value or "").split()).strip().lower()


def classify(cm, position_titles, local_titles):
    """Which bucket a crew record falls into. First match wins, and the
    order is deliberate: the confident tests run before the speculative one
    so that a record with a real verdict never lands in 'worth a look'."""
    first, last = _norm(cm.first_name), _norm(cm.last_name)
    whole = " ".join(p for p in (first, last) if p)

    if cm.is_unnamed_slot:
        return "A"
    if whole and whole in position_titles:
        return "B"
    if any(whole.startswith(p) for p in WORKBOOK_PREFIXES):
        return "C"
    if cm.looks_like_placeholder:
        return "D"
    if {first, last} & SUSPICIOUS_WORDS:
        return "E"
    return "F"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=os.path.expanduser("~/crew_audit.csv"))
    ap.add_argument("--all", action="store_true",
                    help="include records judged to be real people")
    args = ap.parse_args()

    os.environ.setdefault("SECRET_KEY", "audit-read-only")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from app import create_app
    from extensions import db
    from models import (CrewCommAssignment, CrewMember, CrewRow, Position,
                        ScheduleActivity, ScheduleDay, Show,
                        ShowCrewAssignment, count_people)

    app = create_app()
    with app.app_context():
        url = str(db.engine.url)
        print("=" * 78)
        print("CREW / LOCAL LABOUR AUDIT — read-only, nothing is written")
        print("database: %s" % url)
        if "memory" in url:
            print("\n!! This is an in-memory database. Set DATABASE_URL and run again.")
            return 1
        print("=" * 78)

        positions = Position.query.all()
        position_titles = {_norm(p.title) for p in positions if p.title}
        local_titles = {_norm(p.title) for p in positions if p.title and p.is_local_labor}
        print("\npositions catalogue: %d total, %d flagged as local labour"
              % (len(positions), len(local_titles)))

        members = CrewMember.query.all()
        print("crew records: %d (%d active)"
              % (len(members), sum(1 for m in members if m.active)))

        # ── Index the references, one query each rather than per record ──
        rows_by_member = defaultdict(list)
        for row in CrewRow.query.filter(CrewRow.crew_member_id.isnot(None)).all():
            rows_by_member[row.crew_member_id].append(row)

        shows_by_member = defaultdict(list)
        show_names = {s.id: (s.code or s.name or "show %d" % s.id)
                      for s in Show.query.all()}
        for a in ShowCrewAssignment.query.all():
            shows_by_member[a.crew_member_id].append(show_names.get(a.show_id, "?"))

        comms_by_member = defaultdict(int)
        for c in CrewCommAssignment.query.all():
            comms_by_member[c.crew_member_id] += 1

        buckets = defaultdict(list)
        for cm in members:
            buckets[classify(cm, position_titles, local_titles)].append(cm)

        # ── Summary ──────────────────────────────────────────────────────
        print("\n" + "-" * 78)
        print("%-4s %-46s %6s %8s %8s" % ("", "", "records", "rows", "people"))
        print("-" * 78)
        for key, label in BUCKETS:
            group = buckets.get(key, [])
            n_rows = sum(len(rows_by_member.get(m.id, [])) for m in group)
            n_people = sum(sum(int(r.qty or 1) for r in rows_by_member.get(m.id, []))
                           for m in group)
            print("%-4s %-46s %6d %8d %8d" % (key, label, len(group), n_rows, n_people))
        print("-" * 78)

        candidates = [m for k in ("A", "B", "C") for m in buckets.get(k, [])]
        print("\nCONVERSION CANDIDATES (buckets A + B + C): %d records"
              % len(candidates))
        print("Bucket D and E are NOT candidates — they need a human verdict.")

        # ── Predicted headcount effect, per the standing rule ────────────
        #
        # Converting means clearing `crew_member_id` on the affected rows.
        # Where several rows share one placeholder at qty 1, today they count
        # as ONE person between them; afterwards each counts as one. That may
        # well be the correct number — it is the same defect family as the
        # two headcount bugs — but it is a CHANGE, and a change to a number
        # that feeds catering should be predicted rather than discovered.
        candidate_ids = {m.id for m in candidates}
        affected_rows = [r for m in candidates for r in rows_by_member.get(m.id, [])]
        affected_activity_ids = {r.activity_id for r in affected_rows}

        print("\nHEADCOUNT PREDICTION")
        print("  crew rows that would be repointed: %d" % len(affected_rows))
        print("  crew calls touched:                %d" % len(affected_activity_ids))

        deltas = []
        for act_id in sorted(affected_activity_ids):
            act = ScheduleActivity.query.get(act_id)
            if act is None:
                continue
            rows = list(act.crew_rows)
            before = count_people(rows)

            # Simulate in memory ONLY. Nothing is flushed; the session is
            # rolled back below and this script never commits.
            class _Sim(object):
                __slots__ = ("is_group_header", "qty", "crew_member_id",
                             "is_unfilled")

            sim = []
            for r in rows:
                s = _Sim()
                s.is_group_header = r.is_group_header
                s.qty = r.qty
                if r.crew_member_id in candidate_ids:
                    s.crew_member_id = None      # becomes a position count
                    s.is_unfilled = True
                else:
                    s.crew_member_id = r.crew_member_id
                    s.is_unfilled = r.is_unfilled
                sim.append(s)
            after = count_people(sim)
            if before != after:
                day = act.day
                deltas.append((day.date if day else None, act.time,
                               act.description, before, after))

        if deltas:
            print("\n  calls whose headcount would CHANGE: %d" % len(deltas))
            print("  %-12s %-9s %-30s %7s %7s" % ("day", "time", "activity", "now", "after"))
            for date, time, desc, before, after in deltas[:40]:
                print("  %-12s %-9s %-30s %7d %7d"
                      % (date or "—", time or "—", (desc or "")[:30], before, after))
            if len(deltas) > 40:
                print("  ... and %d more (all of them are in the CSV)" % (len(deltas) - 40))
        else:
            print("\n  no headcount anywhere would change.")

        # ── The row-by-row list ─────────────────────────────────────────
        listed = [k for k, _ in BUCKETS] if args.all else ["A", "B", "C", "D", "E"]
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["bucket", "crew_id", "first_name", "last_name",
                        "renders_as", "company", "position", "active",
                        "shows", "crew_rows", "people_on_those_rows",
                        "rows_already_pointing_at_a_position", "comms_gear"])
            for key, _label in BUCKETS:
                if key not in listed:
                    continue
                for cm in sorted(buckets.get(key, []),
                                 key=lambda m: (m.last_name or "", m.first_name or "")):
                    rows = rows_by_member.get(cm.id, [])
                    w.writerow([
                        key, cm.id, cm.first_name, cm.last_name,
                        cm.display_label,
                        cm.company.name if cm.company else "",
                        cm.position.title if cm.position else "",
                        "yes" if cm.active else "no",
                        " ".join(sorted(set(shows_by_member.get(cm.id, [])))),
                        len(rows),
                        sum(int(r.qty or 1) for r in rows),
                        sum(1 for r in rows if r.position_id),
                        comms_by_member.get(cm.id, 0),
                    ])
        print("\nwrote %s" % args.csv)

        print("\nWHAT TO DO WITH THIS")
        print("  Bucket A is mechanical — those records were built as slots.")
        print("  Bucket B and C are near-certain but worth a skim.")
        print("  Bucket D and E are the judgement calls. Read them with Larry;")
        print("  a false positive here proposes retiring a real person.")
        print("  Nothing has been changed. The migration is a separate step.")

        db.session.rollback()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Which crew records are the same person twice?

REPORT ONLY. Nothing in this module writes, deletes or merges anything. It
answers one question and hands the answer to a human.

WHY (found 2026-09-09 on the production snapshot)

Seven names existed more than once — Jose Mora three times, and Larry Kargol,
Kevin Leckey, Chris Dallos, Kerrilyn Garma, Dakota Wagenbrenner and
Alessandro Romualdi twice each. It reads as untidiness. It is not:

  * **Overtime goes missing.** The 6th/7th-consecutive-day rule and the
    short-turnaround rule both resolve per `crew_member_id`. A person split
    across two records is two four-day weeks to the payroll rules, never one
    eight-day one, so they can never trip the 6th-day rule and their hours
    never combine for OT.
  * **Rates disagree.** Two records can hold two different `rate_standard`
    values, and which one prices a day depends on which record the row
    happened to be booked against.
  * **It looks fine.** On GHC26's Hours Report, Dakota Wagenbrenner appears
    as two adjacent rows, 11.0 h and 21.0 h. Nothing marks them as the same
    person; you have to already know.

Note 15 deliberately deferred a merge tool, and Jason confirmed on 2026-09-09
that this stays a report for now: a merge has to repoint every crew row,
assignment and break, and decide which rate history survives. That is a real
piece of work and it should not be done by a side-effect of a report.

So: name the collisions, show enough beside each record to tell which is the
keeper, and let Larry resolve them by hand.

WHAT COUNTS AS A COLLISION

The same normalised name — case-folded, whitespace collapsed — on two active
records. Stand-ins are excluded: after the punctuation rule landed there are
dozens of records legitimately called "TBD", and they are not each other.
Deliberately conservative: an exact name match only, no fuzzy matching. A
false positive here costs Larry a second look at a real pair of twins; a
fuzzy matcher that merges two different Chris Dallases costs a payroll.
"""
from collections import defaultdict


def normalise_name(first, last):
    """The key two records collide on. Case-folded, whitespace collapsed."""
    whole = f"{(first or '').strip()} {(last or '').strip()}".strip()
    return " ".join(whole.split()).casefold()


EMPTY_USAGE = {"shows": 0, "rows": 0, "hours": 0.0}


def usage_by_member(member_ids):
    """``{member_id: {"shows": n, "rows": n, "hours": f}}`` in ONE query.

    The evidence for which record of a pair is the keeper. `shows` usually
    settles it — a record used on one show beside a record used on four is
    rarely a real pair of people.

    Deliberately one grouped query rather than walking a relationship per
    member: this runs on every Crew Database page load, and `CrewMember` has
    no `crew_rows` backref to walk anyway.
    """
    ids = [i for i in (member_ids or []) if i is not None]
    if not ids:
        return {}

    from sqlalchemy import func
    from extensions import db
    from models import CrewRow, ScheduleActivity, ScheduleDay

    rows = (db.session.query(
                CrewRow.crew_member_id,
                ScheduleDay.show_id,
                func.count(CrewRow.id),
                func.sum(func.coalesce(CrewRow.hours, 0)
                         * func.coalesce(CrewRow.qty, 1)))
            .join(ScheduleActivity, ScheduleActivity.id == CrewRow.activity_id)
            .join(ScheduleDay, ScheduleDay.id == ScheduleActivity.day_id)
            .filter(CrewRow.crew_member_id.in_(ids))
            .group_by(CrewRow.crew_member_id, ScheduleDay.show_id)
            .all())

    out = {}
    for member_id, show_id, row_count, hour_sum in rows:
        bucket = out.setdefault(member_id, {"shows": set(), "rows": 0, "hours": 0.0})
        if show_id is not None:
            bucket["shows"].add(show_id)
        bucket["rows"] += int(row_count or 0)
        bucket["hours"] += float(hour_sum or 0)
    return {mid: {"shows": len(b["shows"]),
                  "rows": b["rows"],
                  "hours": round(b["hours"], 1)}
            for mid, b in out.items()}


def find_duplicates(members, usage=None):
    """Groups of records that share a name, most-used group first.

    Returns a list of dicts::

        {"name": "Jose Mora",
         "count": 3,
         "records": [{"member": <CrewMember>, "company": "ADI",
                      "position": "A1", "shows": 2, "rows": 14,
                      "hours": 154.0}, ...]}

    Records inside a group are ordered by how much they are used, most first,
    so the likely keeper is at the top. Nothing is marked AS the keeper — that
    is Larry's call, and the module has no business guessing.
    """
    by_key = defaultdict(list)
    for member in members or []:
        # A stand-in is not a person, so two stand-ins are not each other.
        if getattr(member, "is_unnamed_slot", False):
            continue
        key = normalise_name(member.first_name, member.last_name)
        if not key:
            continue
        by_key[key].append(member)

    colliding = {k: v for k, v in by_key.items() if len(v) > 1}
    if usage is None:
        usage = usage_by_member([m.id for found in colliding.values()
                                 for m in found])

    groups = []
    for _key, found in colliding.items():
        records = []
        for member in found:
            company = getattr(member, "company", None)
            position = getattr(member, "position", None)
            records.append({
                "member": member,
                "company": (getattr(company, "name", "") or "").strip(),
                "position": (getattr(position, "title", "") or "").strip(),
                **usage.get(member.id, EMPTY_USAGE),
            })
        records.sort(key=lambda r: (-r["shows"], -r["rows"], -r["hours"],
                                    r["member"].id))
        groups.append({
            "name": found[0].full_name.strip(),
            "count": len(found),
            "records": records,
        })

    # Most records first, then the busiest, then alphabetical so the order is
    # stable between page loads.
    groups.sort(key=lambda g: (-g["count"],
                               -sum(r["rows"] for r in g["records"]),
                               g["name"].casefold()))
    return groups

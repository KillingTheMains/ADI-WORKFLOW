"""Canonical crew ordering (#29 Phase 1).

The Crew Database order — each person's `sort_order` within their company — is
the single source of truth that sorts crew everywhere downstream (per-show
roster, travel grid, day schedules, contact sheet, exports).

Two tiers, decided 2026-08-11:

  * The Crew Database SEEDS a show's roster order.
  * Once someone reorders that show's roster, the ROSTER wins for that show,
    and crew calls follow it live.

"Live" is not a sync step. Crew calls DERIVE their order from the roster at
render time (``order_crew_rows``) instead of storing a private copy in
``CrewRow.sort_order``. A stored copy is what drifts, and drift is exactly the
bug this replaces.
"""
from models import CrewMember

# A large sentinel so crew without a sort_order fall to the end, then sort by name.
_UNSET = 10 ** 9


def crew_order_by():
    """SQLAlchemy order_by columns for canonical crew order:
    company, then the Crew Database sort_order, then last name as a tiebreak."""
    return (
        CrewMember.company_id,
        CrewMember.sort_order.asc().nullslast(),
        CrewMember.last_name,
    )


def crew_sort_key(cm):
    """In-memory canonical key for a CrewMember (lists, grouped rows, exports)."""
    return (
        cm.company_id or 0,
        cm.sort_order if cm.sort_order is not None else _UNSET,
        (cm.last_name or "").lower(),
        (cm.first_name or "").lower(),
    )


def roster_index(show_id):
    """``{crew_member_id: ordinal}`` for one show's roster order.

    Assignments the user has dragged (``sort_order`` set) come first in that
    order; everyone else falls back to the Crew Database order. Cached per
    request because a day page renders this for every activity on the day.
    """
    from models import ShowCrewAssignment

    cache = _request_cache()
    if cache is not None and show_id in cache:
        return cache[show_id]

    assignments = (ShowCrewAssignment.query
                   .filter_by(show_id=show_id).all())
    ordered = sorted(
        assignments,
        key=lambda a: ((a.sort_order if a.sort_order is not None else _UNSET,)
                       + (crew_sort_key(a.crew_member) if a.crew_member
                          else (_UNSET,))),
    )
    index = {a.crew_member_id: i for i, a in enumerate(ordered)}
    if cache is not None:
        cache[show_id] = index
    return index


def _request_cache():
    """Per-request memo for roster_index, or None outside an app context."""
    try:
        from flask import g, has_app_context
        if not has_app_context():
            return None
        if not hasattr(g, "_adi_roster_index"):
            g._adi_roster_index = {}
        return g._adi_roster_index
    except (RuntimeError, ImportError):
        return None


def _invalidate_roster_index(session, flush_context, instances=None):
    """Drop the memo as soon as any roster assignment changes.

    Without this the cache outlives the change that invalidates it: reorder the
    roster and re-render in the same context and you get the OLD order back.
    That is the exact drift this module exists to remove, so the cache has to
    lose to correctness. Fires on every flush touching a ShowCrewAssignment.
    """
    from models import ShowCrewAssignment
    touched = (list(session.new) + list(session.dirty) + list(session.deleted))
    if any(isinstance(o, ShowCrewAssignment) for o in touched):
        cache = _request_cache()
        if cache is not None:
            cache.clear()


def _register_invalidation():
    from sqlalchemy import event
    from extensions import db
    event.listen(db.session, "after_flush", _invalidate_roster_index)


_register_invalidation()


def order_crew_rows(rows, index):
    """Sort crew rows by roster position, WITHIN each section.

    Section headers are landmarks, not sortable content: they stay exactly
    where they are, and only the rows beneath each one get reordered. A row
    with nobody linked (a free-text override) has no roster position, so it
    holds its existing place at the end of its section rather than jumping.
    """
    out, section = [], []

    def flush():
        section.sort(key=lambda r: (index.get(r.crew_member_id, _UNSET),
                                    r.sort_order or 0, r.id or 0))
        out.extend(section)
        del section[:]

    for row in rows:
        if row.is_group_header:
            flush()
            out.append(row)
        else:
            section.append(row)
    flush()
    return out


def apply_partial_order(show_id, member_ids):
    """Rewrite the roster so ``member_ids`` sit in the given relative order.

    Jason's call, 2026-08-11: dragging a name inside a crew call reorders the
    SHOW ROSTER, so every crew call follows. One order, nothing to desync.

    A crew call only ever holds a subset of the roster, so this must not
    flatten the rest. It keeps the slots those members already occupy in the
    roster and refills them in the dragged order — everyone not involved keeps
    their position exactly.
    """
    from models import ShowCrewAssignment

    assignments = (ShowCrewAssignment.query.filter_by(show_id=show_id).all())
    if not assignments:
        return
    ordered = sorted(
        assignments,
        key=lambda a: ((a.sort_order if a.sort_order is not None else _UNSET,)
                       + (crew_sort_key(a.crew_member) if a.crew_member
                          else (_UNSET,))),
    )
    by_member = {a.crew_member_id: a for a in ordered}
    moving = [m for m in member_ids if m in by_member]
    if len(moving) < 2:
        return

    slots = [i for i, a in enumerate(ordered) if a.crew_member_id in set(moving)]
    for slot, member_id in zip(slots, moving):
        ordered[slot] = by_member[member_id]

    for i, a in enumerate(ordered):
        a.sort_order = (i + 1) * 10

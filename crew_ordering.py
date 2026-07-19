"""Canonical crew ordering (#29 Phase 1).

The Crew Database order — each person's `sort_order` within their company — is
the single source of truth that sorts crew everywhere downstream (per-show
roster, travel grid, day schedules, contact sheet, exports). Manual drag stays
an override on the surfaces that support it; this only changes the DEFAULT sort
from alphabetical to the Crew Database order.
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

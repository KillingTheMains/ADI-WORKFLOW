"""The crew database must not carry the full position list once per row.

Found by the 09-05 whole-project audit: `/crew/` rendered at 2.5 MB for ~200
people. Every row was its own <form>, and inside each row the position and
company <select>s re-rendered the complete option lists — 400-odd selects,
each with 130-odd options. The weight scaled with rows × positions, and on
PythonAnywhere over venue wifi it was the page Larry waited for.

The fix: a row's select carries only its current value; the full lists are
rendered ONCE in two <template> elements and cloned into a select on first
focus. The form posts exactly what it did before, and the new-position /
new-company modals update the templates as well as any hydrated selects.

This test seeds 40 crew and 30 positions and checks two things: the
templates exist, and no row select carries the whole list. The second is
the guard — if someone puts the loop back inside the row, the option count
per row jumps from 1 to 30+ and this fails.
"""
import re

from extensions import db as _db
from models import CrewMember, Position


def _seed(n_crew=40, n_positions=30):
    positions = []
    for i in range(n_positions):
        p = Position(title=f"Weight Test Position {i:02d}", department="Lighting")
        _db.session.add(p)
        positions.append(p)
    _db.session.flush()
    for i in range(n_crew):
        _db.session.add(CrewMember(first_name=f"Crew{i:02d}", last_name="Weight",
                                   position_id=positions[i % n_positions].id))
    _db.session.commit()


def test_row_selects_are_lazy(client, db):
    _seed()
    html = client.get("/crew/").get_data(as_text=True)

    assert 'id="position-options"' in html and 'id="company-options"' in html

    # Every row's position select: count its <option>s.
    row_selects = re.findall(
        r'<select name="position_id"[^>]*lazy-options[^>]*>(.*?)</select>', html, re.S
    )
    assert len(row_selects) >= 40, "expected one lazy select per crew row"
    per_row = [len(re.findall(r"<option\b", body)) for body in row_selects]
    assert max(per_row) <= 2, f"a row select carries the whole list again: {max(per_row)} options"

    # The full list is present exactly once, in the template.
    tpl = re.search(r'<template id="position-options">(.*?)</template>', html, re.S).group(1)
    assert tpl.count("Weight Test Position") == 30


def test_each_row_still_shows_its_own_value(client, db):
    _seed(n_crew=3, n_positions=3)
    html = client.get("/crew/").get_data(as_text=True)
    row_selects = re.findall(
        r'<select name="position_id"[^>]*lazy-options[^>]*>(.*?)</select>', html, re.S
    )
    shown = [re.search(r"<option[^>]*selected[^>]*>(.*?)</option>", b, re.S).group(1).strip()
             for b in row_selects[:3]]
    assert shown == ["Weight Test Position 00", "Weight Test Position 01", "Weight Test Position 02"]

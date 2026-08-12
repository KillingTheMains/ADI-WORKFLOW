"""
Local labour — positions hired in multiples, tracked by title not by name.

"5 Riggers", "18 Lighting Hands". The unit is the POSITION and there are N of
it. Everything downstream — headcounts, meals, the client master — has to
count the N rather than the line.

Source for the vocabulary and the design: ADI_Local_Labor_Findings.md.
"""
import datetime as dt

from local_labor import (SEED_POSITIONS, SEED_TASKS, department_key,
                         group_by_department, headcount, line_label)


class _P:
    def __init__(self, title, department=None, type=None):
        self.title, self.department, self.type = title, department, type


class _R:
    def __init__(self, qty=1, is_group_header=False):
        self.qty, self.is_group_header = qty, is_group_header


# ── The label ────────────────────────────────────────────────────────────────

def test_a_line_reads_as_a_count():
    assert line_label("Lighting Hand", 18) == "18 × Lighting Hand"


def test_one_of_something_is_not_multiplied():
    """"1 × Labor Steward" reads like a mistake. There is one of him."""
    assert line_label("Labor Steward", 1) == "Labor Steward"


def test_the_task_qualifies_the_position():
    assert line_label("Rigger", 5, "Pin/Bolt Truss") == "5 × Rigger — Pin/Bolt Truss"
    assert line_label("Rigger", 5, "   ") == "5 × Rigger"


def test_a_missing_or_daft_quantity_never_breaks_the_label():
    for bad in (None, 0, -3, "", "abc"):
        assert line_label("Stagehand", bad) == "Stagehand"


# ── Grouping ─────────────────────────────────────────────────────────────────

def test_departments_come_out_in_house_order_not_alphabetical():
    groups = group_by_department([_P("Rigger", "Rigging"),
                                  _P("Stagehand", "General"),
                                  _P("LED Hand", "LED")])
    assert [d for d, _ in groups] == ["General", "Rigging", "LED"]


def test_an_unknown_department_sorts_last_rather_than_vanishing():
    groups = group_by_department([_P("Zebra Wrangler", "Menagerie"),
                                  _P("Rigger", "Rigging")])
    assert [d for d, _ in groups] == ["Rigging", "Menagerie"]
    assert department_key("Menagerie") > department_key("Rigging")


def test_leads_read_above_the_hands_they_run():
    groups = group_by_department([_P("Stagehand", "General", "hand"),
                                  _P("Crew Chief", "General", "lead"),
                                  _P("Prep Hand", "General", "hand")])
    titles = [p.title for p in groups[0][1]]
    assert titles == ["Crew Chief", "Prep Hand", "Stagehand"]


def test_a_position_with_no_department_is_still_shown():
    groups = group_by_department([_P("Mystery Hand", None)])
    assert groups[0][0] == "Unassigned"


# ── Headcount ────────────────────────────────────────────────────────────────

def test_headcount_counts_bodies_not_lines():
    assert headcount([_R(18), _R(5), _R(1)]) == 24


def test_a_section_header_is_not_a_person():
    assert headcount([_R(18), _R(0, is_group_header=True)]) == 18


# ── The seed list ────────────────────────────────────────────────────────────

def test_the_seed_list_has_no_duplicate_titles():
    """Two positions called Rigger would split every count that matters."""
    titles = [t.lower() for t, _, _ in SEED_POSITIONS]
    assert len(titles) == len(set(titles))


def test_every_seeded_position_is_a_lead_or_a_hand():
    assert {typ for _, _, typ in SEED_POSITIONS} == {"lead", "hand"}


def test_jasons_own_examples_are_in_the_list():
    """The three he named when asking for this."""
    titles = {t for t, _, _ in SEED_POSITIONS}
    assert {"Labor Steward", "High Rigger", "Lighting Hand"} <= titles


def test_no_task_is_welded_into_a_position_title():
    """The whole design: task on the row, not in the name. A title carrying a
    parenthetical is the 117-slot mistake coming back.
    """
    for title, _, _ in SEED_POSITIONS:
        assert "(" not in title, title
    for task in SEED_TASKS:
        assert task.strip() == task

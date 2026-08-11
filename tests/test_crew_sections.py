"""Tiered sections and automatic slotting (notes 1 + 3, 2026-08-11).

Modelled on the 133 real headers in production: ENCORE at level 1 with
ENCORE RIGGING beneath it, alongside unbound manual sections like LEAD CREW.
"""
from crew_sections import insert_index_for, walk


class Co:
    def __init__(self, id, name, code=None):
        self.id, self.name, self.code = id, name, code


class Pos:
    def __init__(self, department):
        self.department = department


class Person:
    def __init__(self, company=None, department=None):
        self.company = company
        self.company_id = company.id if company else None
        self.position = Pos(department) if department else None


class Row:
    def __init__(self, label=None, level=1, company_id=None, tag=None):
        self.is_group_header = label is not None
        self.group_label = label
        self.header_level = level
        self.company_id = company_id
        self.tag = tag
        self.sort_order = 0


ENCORE = Co(1, "Encore", "ENCORE")
VRA = Co(2, "VRA", "VRA")


def _sheet():
    """ENCORE (with a RIGGING sub-header), then VRA, then a manual section."""
    return [
        Row("ENCORE"),                       # 0
        Row(tag="encore-general"),           # 1
        Row("ENCORE RIGGING", level=2),      # 2
        Row(tag="encore-rigger"),            # 3
        Row("VRA"),                          # 4
        Row(tag="vra-1"),                    # 5
        Row("LEAD CREW"),                    # 6
        Row(tag="lead-1"),                   # 7
    ]


def test_person_lands_in_their_company_section():
    rows = _sheet()
    idx = insert_index_for(rows, Person(company=VRA))
    assert idx == 6          # end of the VRA section, before LEAD CREW


def test_department_sub_header_wins_over_the_company_section():
    rows = _sheet()
    idx = insert_index_for(rows, Person(company=ENCORE, department="Rigging"))
    assert idx == 4          # end of ENCORE RIGGING, before VRA


def test_company_match_without_a_matching_sub_header():
    """Lands in the company's own rows, above its sub-sections."""
    rows = _sheet()
    idx = insert_index_for(rows, Person(company=ENCORE, department="Audio"))
    assert idx == 2          # after encore-general, before ENCORE RIGGING


def test_unknown_company_falls_back_to_the_end():
    rows = _sheet()
    other = Co(9, "Someone Else", "SE")
    assert insert_index_for(rows, Person(company=other)) == len(rows)


def test_no_company_falls_back_to_the_end():
    rows = _sheet()
    assert insert_index_for(rows, Person()) == len(rows)


def test_no_sections_at_all_appends():
    rows = [Row(tag="a"), Row(tag="b")]
    assert insert_index_for(rows, Person(company=VRA)) == 2


def test_company_id_binding_beats_the_label():
    """A bound header wins even when its label says something else entirely."""
    rows = [Row("THE RIGGERS", company_id=VRA.id), Row(tag="x"),
            Row("VRA"), Row(tag="y")]
    assert insert_index_for(rows, Person(company=VRA)) == 2


def test_walk_reports_the_section_each_person_is_in():
    rows = _sheet()
    got = [(r.tag, l1.group_label if l1 else None,
            l2.group_label if l2 else None) for r, l1, l2 in walk(rows)]
    assert got == [
        ("encore-general", "ENCORE", None),
        ("encore-rigger", "ENCORE", "ENCORE RIGGING"),
        ("vra-1", "VRA", None),
        ("lead-1", "LEAD CREW", None),
    ]


def test_level_one_header_resets_the_sub_header():
    """VRA must not inherit ENCORE RIGGING as its sub-section."""
    rows = _sheet()
    pairs = {r.tag: l2 for r, _, l2 in walk(rows)}
    assert pairs["vra-1"] is None

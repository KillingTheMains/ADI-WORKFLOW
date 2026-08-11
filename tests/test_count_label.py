"""Head-count wording (note 5b, 2026-08-11).

"pax" is a travel/hospitality term and reads wrong in AV production. The
wording lives in one place because the XLSX, the PDF and the Master tab all
print it and must agree.
"""
from oss_export import count_label


def test_crew_rows_read_as_crew():
    assert count_label("Crew", 11) == "11 crew"


def test_fnb_counts_people_being_fed():
    assert count_label("F&B", 18) == "18 people"


def test_pax_is_gone():
    for dept in ("Crew", "F&B"):
        assert "pax" not in count_label(dept, 4)


def test_departments_without_a_headcount_get_nothing():
    """Dock/Haze/etc. carry a quantity, not a headcount — caller falls back
    to the '×N' form."""
    assert count_label("Dock", 3) == ""
    assert count_label("Schedule", 2) == ""


def test_missing_or_zero_count_is_blank():
    assert count_label("Crew", None) == ""
    assert count_label("Crew", 0) == ""

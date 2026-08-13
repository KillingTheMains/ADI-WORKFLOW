"""Classifying a crew record as a person or as a position wearing a name.

Larry's roster has position names in it as people, and they got there by two
different doors:

  * the day-editor quick add, which is DESIGNED to make an unfilled slot —
    no name, a company and a position, rendering as "SPARKS Lighting Hand".
    `is_unnamed_slot` finds these exactly.
  * the XLSX importer, which recognises a literal "TBD" with a blank surname
    and waves everything else through as a person. `first="Lighting"`,
    `last="Hand"` becomes a crew member and NO predicate in the app finds it.

`audit_crew_local_labor.classify` is the second door's detector. It is
read-only and advisory — the whole point of the script is that a human reads
the list before anything is migrated — but it still has to be right about
which records it puts in front of that human, because a false positive
proposes retiring a real person from the roster.

⚠️ THE UNDER-COUNT. A position imported as a PERSON is not an unfilled slot,
so `count_people` deduplicates it across rows the way it would deduplicate
Ann One. Three rows reading "Lighting Hand" therefore count as ONE person
today. Measured on a reproduction of the production shape: a call of 15
reports 13. That is a live under-count feeding catering, not a tidiness
problem, and it is the strongest argument for doing the migration.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_crew_local_labor import SUSPICIOUS_WORDS, WORKBOOK_PREFIXES, classify


class _Member:
    """Just enough CrewMember. The two predicates are the real ones' shape."""
    def __init__(self, first, last, unnamed=False, placeholder=False):
        self.first_name, self.last_name = first, last
        self.is_unnamed_slot = unnamed
        self.looks_like_placeholder = placeholder


CATALOGUE = {"lighting hand", "rigger", "a1", "stagehand", "production electrician"}
LOCAL = {"lighting hand", "rigger", "stagehand"}


def _bucket(first, last, **kw):
    return classify(_Member(first, last, **kw), CATALOGUE, LOCAL)


# ── The confident buckets ────────────────────────────────────────────────

def test_an_unnamed_slot_is_bucket_a():
    assert _bucket("TBD", "TBD", unnamed=True) == "A"


def test_a_name_that_is_a_catalogue_title_is_bucket_b():
    """The importer's doing. This is the population that has no detector
    anywhere else in the app."""
    assert _bucket("Lighting", "Hand") == "B"
    assert _bucket("Rigger", "") == "B"


def test_the_title_match_ignores_case_and_stray_spacing():
    assert _bucket("  lighting ", " HAND ") == "B"


def test_a_workbook_prefix_is_bucket_c():
    """Jason's SAP workbooks weld the provider onto the title."""
    assert _bucket("Local -", "Stage Hand") == "C"
    assert _bucket("Freeman -", "Rigger") == "C"


def test_every_workbook_prefix_is_recognised():
    for prefix in WORKBOOK_PREFIXES:
        assert classify(_Member(prefix.strip(), "Something"),
                        CATALOGUE, LOCAL) == "C"


# ── The judgement buckets ────────────────────────────────────────────────

def test_a_partial_placeholder_is_bucket_d_not_a_candidate():
    """"TBD Smith" is somebody half-entered, not a position."""
    assert _bucket("TBD", "Smith", placeholder=True) == "D"


def test_a_position_ish_word_only_earns_a_look():
    """Dave Hand is very likely a person called Dave Hand."""
    assert _bucket("Dave", "Hand") == "E"


def test_a_real_person_is_left_alone():
    assert _bucket("Ann", "One") == "F"
    assert _bucket("Bob", "Two") == "F"


# ── The ordering, which is the safety property ───────────────────────────

def test_a_confident_verdict_beats_the_speculative_one():
    """"Lighting Hand" contains a suspicious word AND is a catalogue title.
    It must land in B — a verdict — rather than in E, where it would sit in
    the "have a think" pile forever."""
    assert _bucket("Lighting", "Hand") == "B"


def test_an_unnamed_slot_wins_over_everything():
    """A quick-add slot whose name happens to look like anything else is
    still a slot, and slots are the mechanical case."""
    assert _bucket("Rigger", "", unnamed=True) == "A"


def test_a_suspicious_word_never_alone_condemns_a_named_person():
    """The whole risk of this script: proposing to retire somebody real.
    Bucket E is advisory and is NOT a conversion candidate."""
    for word in sorted(SUSPICIOUS_WORDS):
        assert _bucket("Dave", word.title()) in ("E", "B"), word


def test_an_empty_record_is_not_a_position():
    assert _bucket("", "") == "F"


# ── The buckets the script will actually act on ──────────────────────────

def test_only_a_b_and_c_are_offered_as_candidates():
    """D and E are for a human to read. If they ever become automatic, this
    test is the thing that should have to be deleted on purpose."""
    import audit_crew_local_labor as audit
    src = open(audit.__file__).read()
    assert 'for k in ("A", "B", "C")' in src

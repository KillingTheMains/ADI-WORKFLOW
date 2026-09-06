"""Note 18, closed 2026-09-06: no day template writes a break as a plain
activity any more, and the migration that cleaned production's six rows
reports what it did.

Replaces `test_template_break_warning.py`, which asserted the DEFECT so the
warning stayed honest. That file is gone with the warning; this one asserts
the fix, at both the seed and the migration.
"""
import json
import os

from sqlalchemy import text

from extensions import db
from migrations import _strip_legacy_break_rows_from_day_templates
from models import DayTemplate

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _seeded_templates():
    with open(os.path.join(_REPO, "seed_data.sql")) as fh:
        sql = fh.read()
    out = []
    for line in sql.splitlines():
        if line.startswith("INSERT INTO day_templates VALUES"):
            start = line.index("'[[")
            end = line.rindex("]'") + 1
            out.append(json.loads(line[start + 1:end]))
    return out


def _break_shaped(desc):
    up = desc.upper()
    return "BREAK" in up or "EOD WRAP" in up


def test_the_seed_carries_no_break_rows():
    templates = _seeded_templates()
    assert len(templates) == 6
    offenders = [d for tpl in templates for _t, d in tpl if _break_shaped(d)]
    assert offenders == []


def test_the_seed_keeps_the_legitimate_rows():
    descs = {d for tpl in _seeded_templates() for _t, d in tpl}
    for keep in ("CREW START", "DOORS OPEN", "GENERAL SESSION BEGINS",
                 "END OF SHOW", "STRIKE COMPLETE"):
        assert keep in descs, keep


def test_rehearsal_templates_carry_a_phase_hint_in_the_seed():
    with open(os.path.join(_REPO, "seed_data.sql")) as fh:
        sql = fh.read()
    assert "'tech_rehearsal','Tech Rehearsal','Technical Rehearsal'" in sql
    assert "'presenter_rehearsal','Presenter Rehearsal','Presenter Rehearsal'" in sql


def test_the_migration_strips_breaks_and_reports_counts(app, capsys):
    """Fed the exact six rows production held on the morning of 2026-09-06.
    Predicted there: 7 removed, 0 renamed, 2 hints. This is that prediction."""
    prod = {
        "load_in": ("Load In", [["7:00 AM", "CREW START"],
                                ["12:30 PM", "LUNCH BREAK — 30 min"],
                                ["3:00 PM", "AFTERNOON BREAK — 15 min"]]),
        "show_day": ("Show", [["7:00 AM", "CREW START"], ["8:00 AM", "DOORS OPEN"],
                              ["9:00 AM", "GENERAL SESSION BEGINS"],
                              ["12:00 PM", "LUNCH BREAK — 60 min"],
                              ["1:00 PM", "AFTERNOON SESSION"], ["5:00 PM", "END OF SHOW"]]),
        "tech_rehearsal": (None, [["7:00 AM", "CREW START"], ["9:00 AM", "TECH REHEARSAL BEGINS"],
                                  ["12:30 PM", "LUNCH BREAK — 30 min"],
                                  ["1:00 PM", "TECH REHEARSAL RESUMES"], ["5:00 PM", "END OF TECH"]]),
        "presenter_rehearsal": (None, [["8:00 AM", "CREW START"],
                                       ["9:00 AM", "PRESENTER REHEARSAL BEGINS"],
                                       ["12:00 PM", "LUNCH BREAK — 30 min"],
                                       ["1:00 PM", "PRESENTER REHEARSAL RESUMES"],
                                       ["5:00 PM", "END OF REHEARSAL"]]),
        "strike": ("Strike", [["8:00 AM", "CREW START — STRIKE BEGINS"],
                              ["12:00 PM", "LUNCH BREAK — 30 min"],
                              ["6:00 PM", "STRIKE COMPLETE"]]),
        "prep": ("Prep", [["9:00 AM", "CREW START — PREP"],
                          ["12:30 PM", "LUNCH BREAK — 30 min"]]),
    }
    with app.app_context():
        DayTemplate.query.delete()
        for i, (key, (hint, acts)) in enumerate(prod.items()):
            db.session.add(DayTemplate(key=key, label=key, phase_hint=hint,
                                       activities_json=json.dumps(acts), sort_order=i))
        db.session.commit()
        capsys.readouterr()
        _strip_legacy_break_rows_from_day_templates(db.session)
        db.session.commit()
        out = capsys.readouterr().out
        assert "6 rows, 7 break row(s) removed, 0 renamed, 2 phase hint(s) set" in out
        for tpl in DayTemplate.query.all():
            assert not [d for _t, d in tpl.activities if _break_shaped(d)], tpl.key
        assert DayTemplate.query.filter_by(key="tech_rehearsal").one().phase_hint == "Technical Rehearsal"
        assert DayTemplate.query.filter_by(key="presenter_rehearsal").one().phase_hint == "Presenter Rehearsal"
        assert DayTemplate.query.filter_by(key="prep").one().activities == [["09:00", "CREW START — PREP"]]


def test_the_migration_renames_a_row_that_only_mentions_eod_wrap(app, capsys):
    with app.app_context():
        DayTemplate.query.delete()
        db.session.add(DayTemplate(key="strike", label="Strike", phase_hint="Strike",
                                   activities_json=json.dumps(
                                       [["6:00 PM", "STRIKE COMPLETE / EOD WRAP"]])))
        db.session.commit()
        capsys.readouterr()
        _strip_legacy_break_rows_from_day_templates(db.session)
        db.session.commit()
        assert "1 rows, 0 break row(s) removed, 1 renamed, 0 phase hint(s) set" in capsys.readouterr().out
        assert DayTemplate.query.one().activities == [["18:00", "STRIKE COMPLETE"]]


def test_the_migration_is_registered():
    from migrations import DATA_MIGRATIONS
    keys = [k for k, _ in DATA_MIGRATIONS]
    assert "2026-09-06-strip-legacy-break-rows-from-day-templates" in keys


def test_neither_door_warns_any_more():
    for parts in (("templates", "schedule", "overview.html"),
                  ("templates", "schedule", "day.html")):
        with open(os.path.join(_REPO, *parts)) as fh:
            assert "tpl-warn" not in fh.read(), parts[-1]

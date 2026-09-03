"""Note 18 — the day templates still write breaks the old way, and both doors
to them must say so.

Found 2026-09-03 while answering "what does 'with templates' actually do".
All six rows in `day_templates` carry activities like "LUNCH BREAK — 30 min",
"COFFEE BREAK - 15 min" and "EOD WRAP" as PLAIN ScheduleActivity rows. That is
the shape the 2026-08-12 repair migrations spent a day undoing — the codebase
says so itself, in a comment sitting directly beneath `apply_template`.

The generators were removed then. The templates that do the same thing were
not. The real fix is a data migration over `day_templates`, which is not a
show-week job with MCDC26 loading in on 2026-09-08.

So this is a GUARD, not a fix, and these tests exist to keep the guard honest
until the fix lands. When the templates are cleaned up, delete this file and
the warning with it.
"""
import json
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(_REPO, *parts)) as fh:
        return fh.read()


def _seeded_templates():
    """The six templates as seed_data.sql actually writes them."""
    sql = _read("seed_data.sql")
    out = []
    for line in sql.splitlines():
        if line.startswith("INSERT INTO day_templates VALUES"):
            start = line.index("'[[")
            end = line.rindex("]'") + 1
            out.append(json.loads(line[start + 1:end]))
    return out


# ── The defect itself, asserted so nobody has to take my word for it ─────────

def test_the_seeded_templates_really_do_write_break_rows():
    """If this ever fails, the templates were fixed — delete this whole file
    and the warning it defends."""
    templates = _seeded_templates()
    assert len(templates) == 6, "expected six seeded templates"

    offenders = [
        desc for tpl in templates for _t, desc in tpl
        if "BREAK" in desc.upper() or "EOD WRAP" in desc.upper()
    ]
    assert offenders, (
        "no break-shaped rows left in the templates — the fix has landed, so "
        "remove the warning and this file"
    )


def test_every_template_is_affected_not_just_one():
    """Six of six. The warning says 'these templates', and that has to be true."""
    for tpl in _seeded_templates():
        descs = " ".join(d.upper() for _t, d in tpl)
        assert "BREAK" in descs or "EOD WRAP" in descs


# ── The guard ────────────────────────────────────────────────────────────────

def test_the_auto_generate_checkbox_warns():
    overview = _read("templates", "schedule", "overview.html")
    assert overview.count("tpl-warn") >= 2, (
        "both the toolbar checkbox and the empty-state checkbox need the warning"
    )


def test_the_apply_template_modal_warns():
    """The modal is the OTHER door, and the only door to Tech Rehearsal and
    Presenter Rehearsal — neither carries a phase hint, so Auto-Generate can
    never reach them."""
    assert "tpl-warn-box" in _read("templates", "schedule", "day.html")


def test_templates_are_no_longer_on_by_default_for_a_new_show():
    """The empty-state box was `checked`, so the default path for a brand-new
    show seeded every day with the legacy shape — the worst place for it,
    because a new show is where nobody is looking."""
    overview = _read("templates", "schedule", "overview.html")
    i = overview.index('id="with-templates-empty-chk"')
    field = overview[overview.rindex("<input", 0, i):overview.index(">", i)]
    assert "checked" not in field


def test_the_label_no_longer_advertises_lunch():
    """It read 'Crew Start, Lunch, EOD' — offering the broken thing by name."""
    overview = _read("templates", "schedule", "overview.html")
    i = overview.index('id="with-templates-empty-chk"')
    label = overview[i:overview.index("</label>", i)]
    assert "Lunch" not in label


def test_the_warning_marker_is_an_icon_not_a_pictograph():
    """Interface Spec §05. The first cut of this warning used a literal ⚠ and
    test_no_pictographs_under_templates caught it — correctly. The rule is not
    decoration: a pictograph renders differently per platform and prints
    unpredictably on the mono laser this paperwork goes to."""
    for tpl in ("overview.html", "day.html"):
        html = _read("templates", "schedule", tpl)
        i = html.index('class="tpl-warn"')
        span = html[i:html.index("</span>", i)]
        assert "ico.icon('alert-triangle'" in span
        assert "⚠" not in span


def test_the_warning_uses_the_brand_tokens():
    """Not Bootstrap's .alert-warning — that would add another off-brand amber
    to the ~500 already queued for the token pass."""
    css = _read("static", "css", "style.css")
    i = css.index(".tpl-warn-box {")
    block = css[i:css.index("}", i)]
    assert "var(--adi-warn-bg)" in block
    assert "var(--adi-warn)" in block
    assert "alert-warning" not in _read("templates", "schedule", "day.html")

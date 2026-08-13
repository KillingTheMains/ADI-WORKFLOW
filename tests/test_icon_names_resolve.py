"""Interface Spec §05 — every icon NAME the app stores must be a glyph the
macro can actually draw.

This is the "two surfaces agree" shape, not a "the definition is correct"
shape. SUB_SCHEDULE_META now stores Lucide names rather than emoji; a typo
there ("headphone", "light-bulb") would not raise, it would render an empty
16x16 box on the day page, the OSS master and every department tab at once,
and nothing would fail. So: ask the macro to draw each stored name and
assert something came back.
"""
import re

import pytest
from flask import render_template_string

from models import SUB_SCHEDULE_META


def _draw(app, name):
    """Render one glyph and return only what is INSIDE the <svg>."""
    with app.app_context():
        out = render_template_string(
            "{%% import '_icons.html' as ico %%}{{ ico.icon('%s') }}" % name)
    return re.sub(r'(?s)^.*?>', '', out, count=1).replace('</svg>', '').strip()


def test_every_department_icon_is_a_glyph_the_macro_can_draw(app):
    empty = []
    for dept, meta in SUB_SCHEDULE_META.items():
        if not _draw(app, meta["icon"]):
            empty.append("%s -> %r" % (dept, meta["icon"]))
    assert not empty, (
        "SUB_SCHEDULE_META names a glyph _icons.html does not have, so these "
        "departments render an empty box on all three screens: " + ", ".join(empty))


def test_department_icons_are_names_not_characters(app):
    """A stray emoji put back into the table would sail past the test above,
    because an unknown name draws nothing and so would an emoji."""
    bad = [(d, m["icon"]) for d, m in SUB_SCHEDULE_META.items()
           if not re.fullmatch(r'[a-z0-9-]+', m["icon"] or "")]
    assert not bad, "these are not Lucide names: %r" % (bad,)


def test_the_exporters_icon_names_also_resolve(app):
    """oss_export._item stamps an icon onto every master-timeline row, and the
    OSS master renders it. Same failure mode, different table."""
    import oss_export
    names = set(re.findall(r'icon="([^"]*)"', open(oss_export.__file__).read()))
    names.discard("")
    missing = [n for n in sorted(names) if not _draw(app, n)]
    assert not missing, "oss_export names glyphs the macro lacks: %r" % (missing,)


def test_an_unknown_name_draws_nothing_rather_than_garbage(app):
    assert _draw(app, "no-such-glyph-anywhere") == ""

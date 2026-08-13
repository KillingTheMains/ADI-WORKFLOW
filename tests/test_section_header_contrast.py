"""Section headers must keep their Midnight band. All of them, always.

Jason, 2026-08-13: "some of the section headers are white text on grey
background which is illegible. Other section headers in the crew calls are
dark blue background, so they should probably all follow that."

TWO causes, both found by reading the computed style in a browser rather than
by reading the CSS:

1. A SPECIFICITY LOSS. The zebra-removal rule
   `.crew-table tbody tr:nth-child(even) td` scores (0,2,3) and the header
   rule `.crew-table .group-header td` scores (0,2,1), so every section header
   that happened to land on an EVEN row inside tbody lost its Midnight fill
   and kept `color:#fff` — white text on white. Which headers broke depended
   on how many rows sat above them, which is why one section looked right and
   the next looked blank. The hover rule (0,2,2) did the same to any header
   under the cursor. Level-2 headers were accidentally immune: the
   `[data-level="2"]` attribute selector bought them one point.

2. A WASHED SUB-SECTION. Level-2 headers were `--adi-kind-local` (#24405F)
   with an inline `opacity:.85`, which lands near rgb(69,93,119) over white —
   a grey-blue, and at an inline `font-size:7.6pt` (10.1px) under the 11px
   small-text floor.

These are CSS-and-markup facts, so they are asserted against the files. A
rendering assertion would need a browser; what these catch is the exact edit
that would bring either cause back.
"""
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css():
    """style.css with /* comments */ stripped — the comments in it describe
    the broken selectors on purpose, and an assertion that reads them is
    testing the prose rather than the rules."""
    with open(os.path.join(_REPO, "static", "css", "style.css")) as fh:
        return re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)


def _day_template():
    """day.html with {# Jinja comments #} stripped, for the same reason."""
    with open(os.path.join(_REPO, "templates", "schedule", "day.html")) as fh:
        return re.sub(r"\{#.*?#\}", "", fh.read(), flags=re.S)


def test_the_zebra_rule_cannot_touch_a_section_header():
    """The rule that broke them. Without the :not() it outranks the header."""
    css = _css()
    assert ".crew-table tbody tr:nth-child(even):not(.group-header) td" in css
    assert not re.search(
        r"\.crew-table tbody tr:nth-child\(even\) td", css), \
        "unguarded zebra rule outranks .group-header and blanks the band"


def test_the_hover_rule_cannot_touch_a_section_header():
    css = _css()
    assert ".crew-table tbody tr:not(.group-header):hover td" in css
    assert not re.search(r"\.crew-table tbody tr:hover td", css), \
        "unguarded hover rule blanks the band under the cursor"


def test_every_header_level_is_the_same_dark_blue():
    """Jason: they should all follow the dark blue."""
    css = _css()
    base = re.search(r"\.crew-table \.group-header td \{(.*?)\}", css, re.S)
    sub = re.search(r"\.crew-table \.group-header\[data-level=\"2\"\] td \{(.*?)\}",
                    css, re.S)
    assert base and sub
    assert "background: var(--adi-dark);" in base.group(1)
    assert "background: var(--adi-dark);" in sub.group(1)


def test_a_sub_section_is_told_apart_by_shape_not_by_hue():
    """If both levels are the same navy, something else has to carry the
    hierarchy — and it has to survive a mono laser."""
    css = _css()
    sub = re.search(r"\.crew-table \.group-header\[data-level=\"2\"\] td \{(.*?)\}",
                    css, re.S).group(1)
    assert "padding-left" in sub
    assert '.crew-table .group-header[data-level="2"] .sect-label::before' in css


def test_no_inline_opacity_or_sub_floor_size_on_a_header_cell():
    """Inline styles beat the stylesheet, so this is where a washed band comes
    back from."""
    day = _day_template()
    assert "opacity:.85" not in day
    assert "font-size:7.6pt" not in day


def test_no_crew_table_text_sits_under_the_small_text_floor():
    """§02 sets the floor at 11px. .68rem is 10.88px."""
    day = _day_template()
    header_block = day[day.index('<tr class="group-header">'):]
    header_block = header_block[:header_block.index("</tr>")]
    assert "font-size:.68rem" not in header_block
    assert "font-size:11px" in header_block

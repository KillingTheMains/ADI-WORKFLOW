"""`|tojson` must never sit inside a DOUBLE-quoted HTML attribute.

Flask's `tojson` escapes `<`, `>`, `&` and `'` — so its output is safe inside
a `<script>` block and inside a single-quoted attribute. It does NOT escape the
double quote, because JSON is built out of them. Put it in a double-quoted
attribute and the value ends the attribute at its own first quote:

    onclick="openCopyModal(159, "CREW START", "08:00")"

The browser reads the handler as `openCopyModal(159,`, reports "Uncaught
SyntaxError: Unexpected end of input", and the control is dead. Silently: the
button renders, it has a tooltip, it highlights on hover, and clicking it does
nothing at all.

This is not hypothetical. It shipped in `7e9f9eb` (note 16, "copy a crew call
to other days") and reached production, where the Copy to Other Days button did
nothing from the day it landed. The route behind it had ELEVEN passing tests
the entire time — they exercised the route, and nothing had ever clicked the
button. It was found by opening the page in a browser on 2026-09-04.

Two more reasons this deserves a test rather than a code review habit:

  * the failure is invisible server-side — the HTML renders, the response is
    200, and no test that posts to the route can see it;
  * it is a one-character difference from correct, in a spot where the
    surrounding attributes are all legitimately double-quoted.

A rendered-HTML check would be stronger still, but it would only cover the
pages a test happens to render. This covers every template.
"""
import pathlib
import re

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"

# Any attribute (not just event handlers) opened with a double quote whose
# value reaches a `| tojson` before the closing quote.
TOJSON_IN_DQ_ATTR = re.compile(r'[a-zA-Z-]+\s*=\s*"[^"]*\|\s*tojson\b')


def _offenders():
    hits = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if TOJSON_IN_DQ_ATTR.search(line):
                hits.append(f"{path.relative_to(TEMPLATES.parent)}:{lineno}: {line.strip()}")
    return hits


def test_tojson_is_never_inside_a_double_quoted_attribute():
    hits = _offenders()
    assert not hits, (
        "`tojson` does not escape the double quote, so inside a double-quoted "
        "attribute its own quotes end the attribute early and the handler dies "
        "with 'Unexpected end of input'. Use single quotes on the attribute.\n  "
        + "\n  ".join(hits)
    )


def test_the_pattern_catches_the_line_that_shipped_the_bug():
    """A guard that cannot fail guards nothing. First line is verbatim from
    `7e9f9eb`; the rest are the spellings that must stay legal."""
    bad = ('onclick="openCopyModal({{ act.id }}, {{ act.description|tojson }}, '
           '{{ (act.time|to_24hr)|tojson }})"')
    assert TOJSON_IN_DQ_ATTR.search(bad)
    assert TOJSON_IN_DQ_ATTR.search('data-rows="{{ rows | tojson }}"')
    # Single-quoted attribute: the correct form.
    assert not TOJSON_IN_DQ_ATTR.search("onclick='openCopyModal({{ act.id }}, {{ d|tojson }})'")
    # Inside a <script> block, not an attribute at all.
    assert not TOJSON_IN_DQ_ATTR.search("  const rows = {{ rows|tojson }};")

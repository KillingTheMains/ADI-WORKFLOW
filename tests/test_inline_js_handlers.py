"""Values interpolated into inline JS handlers must go through `|js_str`.

An inline handler is a value crossing TWO parsers: the HTML attribute parser
reads it first, then the JavaScript parser reads what the HTML parser produced.
Jinja's autoescaping is built for the first one alone, and its output is
actively wrong for the second:

    onsubmit="return confirm('Remove {{ member.full_name }} ...')"

An apostrophe becomes `&#39;`, the HTML parser turns that straight back into
`'`, and the JavaScript parser then sees:

    return confirm('Remove Allison O'Brien from the roster?')

which does not compile. `|e` changes nothing — it produces the same `&#39;`.

WHY THIS IS WORSE THAN A DEAD BUTTON

A handler that does not compile is never registered, so `onsubmit` never gets
to return false — and the form submits **with no confirmation at all**. Every
one of the twenty sites this was found at guards a destructive action: delete
a client, delete a show, remove crew from a roster, undo a batch of changes.
The guard does not fail loudly. It silently stops existing, for exactly the
people whose names contain an apostrophe — O'Brien, O'Connor, D'Angelo — which
in a crew database is not an edge case.

Found 2026-09-04 by renaming one local crew member to O'Brien and parsing every
rendered handler with node. Before: one broken. After: 248 handlers across ten
pages, none broken.

THE RELATED BUG, same root cause, different quote

`tojson` in a double-quoted attribute has its own test
(test_no_tojson_in_double_quoted_attrs.py). That one killed the Copy to Other
Days button outright. Both are the same mistake: reasoning about one parser
when the value has to survive two.

WHY A TEST AND NOT A CODE-REVIEW HABIT

The failure is invisible from the server. The HTML renders, the response is
200, the template test passes, and the route test passes — because the route
is fine. Nothing short of parsing the rendered attribute can see it, and the
data that triggers it (a name with an apostrophe) is rarely what a fixture
uses.
"""
import pathlib
import re

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"

# An on*="..." attribute. We only care about ones containing a JS string
# literal (a single quote) AND a Jinja interpolation.
HANDLER = re.compile(r'\bon[a-z]+\s*=\s*"([^"]*)"', re.I)
INTERP = re.compile(r"\{\{(.*?)\}\}", re.S)


def _offenders():
    hits = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for h in HANDLER.finditer(line):
                body = h.group(1)
                if "'" not in body:
                    continue                       # no JS string literal here
                for e in INTERP.finditer(body):
                    if "js_str" not in e.group(1):
                        hits.append(
                            f"{path.relative_to(TEMPLATES.parent)}:{lineno}: "
                            f"{{{{{e.group(1)}}}}}"
                        )
    return hits


def test_interpolations_in_inline_handlers_use_js_str():
    hits = _offenders()
    assert not hits, (
        "A value inside a JS string inside an HTML attribute crosses two "
        "parsers. Jinja escaping is wrong for the second one: an apostrophe "
        "becomes &#39;, the HTML parser turns it back into ', and the handler "
        "stops compiling — so a confirm() guard silently stops asking and the "
        "form submits anyway. Add |js_str.\n  " + "\n  ".join(hits)
    )


def test_js_str_neutralises_both_quotes_and_stays_readable(app):
    """The filter has to satisfy two parsers at once: emit nothing the HTML
    attribute parser will act on, and nothing that ends a JS string — while
    still evaluating back to the original text, because this is a message a
    person reads in a dialog."""
    with app.app_context():
        from flask import render_template_string
        out = render_template_string(
            """<form onsubmit="return confirm('Remove {{ n|js_str }}?')"></form>""",
            n="""O'Brien "Bo" <b>&""",
        )
    # Nothing the HTML attribute parser or the JS parser can act on.
    for ch in ("'", '"', "<", ">", "&"):
        assert ch not in out.split("confirm(", 1)[1].split(")", 1)[0].replace(
            "'Remove ", "").replace("?'", "")
    # And the escapes are the readable kind, not mangled entities.
    assert "\\u0027" in out and "&#39;" not in out


def test_the_pattern_catches_the_line_that_shipped_the_bug():
    """A guard that cannot fail guards nothing."""
    def flags(line):
        for h in HANDLER.finditer(line):
            body = h.group(1)
            if "'" in body:
                for e in INTERP.finditer(body):
                    if "js_str" not in e.group(1):
                        return True
        return False

    assert flags("""onsubmit="return confirm('Remove {{ member.full_name }}?')" """)
    assert flags("""onsubmit="return confirm('Delete “{{ c.name|e }}”?')" """)
    assert not flags("""onsubmit="return confirm('Remove {{ member.full_name|js_str }}?')" """)
    # No JS string literal in it at all — nothing to break.
    assert not flags("""data-count="{{ rows|length }}" """)

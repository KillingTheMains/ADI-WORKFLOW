"""A colour token must never end up inside a DOM lookup.

WHAT HAPPENED (found 2026-09-09, live since 52b88b7 on 09-05).

The design pass that moved the app onto palette tokens ran a find-and-replace
over the templates, turning literal hex colours into `var(--adi-…)`. Four of
the strings it rewrote were not colours at all — they were CSS ID SELECTORS
sitting inside JavaScript, on the day page's Create Crew Call modal:

    modal.querySelector('#ccc-count')
                          ↑ this '#' was read as the start of a hex colour

became

    modal.querySelector('var(--adi-border-strong)-count')

`querySelector` throws a SyntaxError on an invalid selector, so the FIRST of
those four lines killed the whole IIFE and none of its listeners were ever
attached. On production that meant: ticking a company header in the modal
selected none of its crew (measured: 0 of BAV's 13), the "N crew selected"
readout never moved off zero, and the break preview never filled in. Four
days, MCDC26's entire load-in.

WHY THE PALETTE TEST DID NOT CATCH IT

`test_palette` looks for literal hex OUTSIDE `:root` — the failure mode where
a colour escapes the palette. This is the opposite shape: a perfectly
well-formed token in a place no colour belongs. Nothing was looking there.

THE RULE

A quoted argument to a DOM lookup may not contain `var(--`. There is no
legitimate reason to select an element by a CSS custom property, so this can
only ever mean a selector was mangled. Cheap, total, and it fires at the
exact moment the mistake is made rather than four days later.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")
STATIC_JS = os.path.join(ROOT, "static", "js")

# Every DOM call that takes a selector or an element id.
LOOKUPS = (
    "querySelector",
    "querySelectorAll",
    "getElementById",
    "getElementsByClassName",
    "getElementsByName",
    "closest",
    "matches",
)

# e.g.  querySelector('var(--adi-border-strong)-count')
#       getElementById("var(--adi-blue)-total")
MANGLED = re.compile(
    r"\b(" + "|".join(LOOKUPS) + r")\s*\(\s*(['\"])([^'\"]*var\(--[^'\"]*)\2"
)


def _source_files():
    for base in (TEMPLATES, STATIC_JS):
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for fn in filenames:
                if fn.endswith((".html", ".js")):
                    yield os.path.join(dirpath, fn)


def test_no_colour_token_inside_a_dom_lookup():
    """A palette token in a selector string is always a mangled '#id'."""
    offences = []
    for path in _source_files():
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                m = MANGLED.search(line)
                if m:
                    rel = os.path.relpath(path, ROOT)
                    offences.append(f"{rel}:{lineno}  {m.group(1)}('{m.group(3)}')")

    assert not offences, (
        "A colour token is being used as a DOM selector. This is what a "
        "find-and-replace over '#rrggbb' does to a '#id' selector written in "
        "JavaScript, and querySelector throws on it — killing every listener "
        "in the same script block.\n\n  " + "\n  ".join(offences)
    )


@pytest.mark.parametrize(
    "ident",
    ["ccc-count", "ccc-time", "ccc-hours", "ccc-break-preview"],
)
def test_create_crew_call_modal_still_wires_its_ids(ident):
    """The four that broke: each id is BOTH declared and looked up.

    Pins the actual repair, not just the absence of the bad shape — renaming
    one end and not the other would otherwise pass the guard above silently.
    """
    day = os.path.join(TEMPLATES, "schedule", "day.html")
    with open(day, encoding="utf-8") as fh:
        src = fh.read()

    assert f'id="{ident}"' in src, f'no element declares id="{ident}"'
    assert f"'#{ident}'" in src, f"nothing looks up '#{ident}'"

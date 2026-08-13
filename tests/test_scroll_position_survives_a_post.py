"""Deleting something must not throw you back to the top of the page.

Jason, 2026-08-13: "every time i delete something from any of the pages, the
page refreshes and puts me back at the top of the page."

Every mutation in this app is a form POST that redirects to the page it came
from, and the browser renders that response at the top. There are 30
destructive controls and the day page runs past 4,000 pixels, so deleting the
ninth crew row means scrolling back down to reach the tenth. Adds and edits
did it too.

The fix is ~40 lines in base.html: stash the scroll position on submit,
restore it on the next load of the same path.

VERIFIED IN A REAL BROWSER against a running dev server, not just asserted
here — deleting a crew row from y=1000 came back to y=1000, deleting an
activity from y=1200 came back to y=1200, and a fresh navigation to the same
URL still landed at the top. These tests exist to stop the three easy edits
that would silently break it again; a rendering assertion needs a browser.
"""
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script():
    """The scroll block of base.html, JS comments stripped — the comments in
    it describe the traps on purpose, so an assertion that reads them is
    testing the prose rather than the code."""
    with open(os.path.join(_REPO, "templates", "base.html")) as fh:
        html = fh.read()
    start = html.index("Keep your place across a form POST")
    js = html[start:]
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    js = re.sub(r"//.*", "", js)
    return js


def test_the_helper_is_in_base_so_every_page_gets_it():
    """30 delete controls across 18 templates. Per-template would miss some,
    and would miss every add and edit."""
    with open(os.path.join(_REPO, "templates", "base.html")) as fh:
        html = fh.read()
    assert "Keep your place across a form POST" in html
    # Outside {% block extra_js %}, or pages that override it would lose this.
    assert html.index("Keep your place across a form POST") < html.index("{% block extra_js %}")


def test_the_restore_is_instant_not_animated():
    """THE TRAP. style.css sets `html { scroll-behavior: smooth }`, so
    scrollTo(0, y) and behavior:'auto' both animate — and starting the
    animation twice interrupts it. Measured in the browser: asking for 1000
    landed at 169."""
    js = _script()
    assert "behavior: 'instant'" in js
    assert not re.search(r"window\.scrollTo\(\s*0\s*,", js), \
        "the two-argument form animates under scroll-behavior:smooth"


def test_a_stale_position_expires():
    """Without this, arriving at a page fresh from the dashboard drops you
    halfway down it because of something you did ten minutes ago."""
    js = _script()
    assert "FRESH_MS" in js
    m = re.search(r"FRESH_MS\s*=\s*(\d+)", js)
    assert m and 1000 <= int(m.group(1)) <= 30000


def test_it_only_restores_onto_the_same_page():
    js = _script()
    assert "saved.path !== location.pathname" in js


def test_an_autosave_form_leaves_no_stash():
    """An autosave form calls preventDefault() and never navigates. If it
    stashed anyway, the position would be restored onto some later, unrelated
    navigation."""
    js = _script()
    assert "e.defaultPrevented" in js


def test_the_stash_is_cleared_when_it_is_used():
    """A stash that survives its own restore would fire again on the next
    load of the page."""
    js = _script()
    assert "removeItem" in js


def test_the_back_button_is_left_alone():
    """history.scrollRestoration = 'manual' looks like the right move and is
    not: the browser's own restoration only runs on a history traversal,
    where it is correct. A POST that redirects is a fresh navigation with
    nothing to fight, so turning it off would break back/forward to fix
    something it was never doing."""
    js = _script()
    assert "scrollRestoration = 'manual'" not in js
    assert 'scrollRestoration = "manual"' not in js


def test_storage_failures_never_break_a_save():
    """Private mode and quota errors throw on sessionStorage. Losing your
    scroll position is a nuisance; losing the delete is not."""
    js = _script()
    body = js[js.index("function stash"):]
    body = body[:body.index("function takeStash")]
    assert "try {" in body and "catch" in body

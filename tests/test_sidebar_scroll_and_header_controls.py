"""Notes 1 and 6, from Jason 2026-09-03.

Two reports, both only visible on a screen:

  6.  "when the mouse scrolls over the sidebar, it needs to scroll all the way
      down the sidebar and not the main screen" — specifically when zoomed in.
  1a. the section header's edit and remove controls "are too dark of color.
      Please make them white."
  1b. "when you delete one, it just disappears and you don't have to refresh."

Like test_scroll_position_survives_a_post, these are SOURCE assertions. A
rendered scroll container and a computed colour need a browser; what these
tests defend is the small set of edits that would silently undo the fix.

The 1a diagnosis is worth keeping written down, because the markup looks
correct without it: `.crew-table .group-header td` already sets `color:#fff`,
but neither control inherits it — an <a> takes the link colour and a <button>
takes the UA's `buttontext`. Both are near-black on the #0B2545 band.
"""
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css():
    with open(os.path.join(_REPO, "static", "css", "style.css")) as fh:
        return fh.read()


def _day():
    with open(os.path.join(_REPO, "templates", "schedule", "day.html")) as fh:
        return fh.read()


def _rule(css, selector):
    """The declaration block for a selector, COMMENTS STRIPPED, or '' if the
    selector is gone.

    Stripping is not tidiness. A house rule here reads "comments are served,
    and contain the very strings a 'did it go?' assertion searches for" — and
    this file proved it on the first run: the #sidebar comment explains what
    `min-height: 100vh` used to do, so an assertion that the declaration is
    gone matched the prose describing its removal."""
    i = css.find(selector)
    if i == -1:
        return ""
    block = css[i:css.index("}", i)]
    return re.sub(r"/\*.*?\*/", "", block, flags=re.S)


# ── Note 6 ───────────────────────────────────────────────────────────────────

def test_the_sidebar_height_is_bounded_by_the_viewport():
    """A position:fixed element taller than the viewport has nowhere to scroll,
    so the wheel falls through to the page behind. min-height alone is what
    caused that."""
    block = _rule(_css(), "#sidebar {")
    assert "height: 100vh" in block
    assert "min-height: 100vh" not in block, (
        "min-height lets the sidebar grow past the viewport again"
    )


def test_the_nav_is_its_own_scroll_container():
    block = _rule(_css(), "#sidebar nav {")
    assert "overflow-y: auto" in block
    # Without min-height:0 a flex child will not shrink below its content, so
    # the overflow never engages and the fix silently does nothing.
    assert "min-height: 0" in block


def test_the_wheel_does_not_chain_to_the_page_behind():
    """The actual complaint: scrolling over the sidebar moved the main screen."""
    assert "overscroll-behavior: contain" in _rule(_css(), "#sidebar nav {")


# ── Note 1a ──────────────────────────────────────────────────────────────────

def test_the_header_controls_are_explicitly_white():
    css = _css()
    assert ".crew-table .group-header .sect-actions a," in css
    block = _rule(css, ".crew-table .group-header .sect-actions a,")
    assert "color: #fff" in block


def test_both_controls_are_covered_not_just_the_link():
    """The <button> is the one that was blackest — it takes `buttontext` from
    the UA sheet, which inherits nothing."""
    block = _rule(_css(), ".crew-table .group-header .sect-actions a,")
    assert ".sect-actions button" in block


def test_the_controls_carry_no_inline_opacity():
    """An inline style beats the stylesheet. day.html already carries a comment
    about that exact trap on this exact row, so the opacity must stay in CSS or
    the hover state cannot work."""
    day = _day()
    span = day[day.index('<span class="sect-actions"'):]
    span = span[:span.index("</span>")]
    assert "opacity" not in span, "opacity belongs in style.css, not inline here"


def test_the_span_still_carries_the_hook_class():
    assert '<span class="sect-actions"' in _day()


# ── Note 1b ──────────────────────────────────────────────────────────────────

def test_the_delete_form_is_hooked():
    assert 'class="js-section-delete"' in _day()


def test_it_is_still_a_real_post_form():
    """The upgrade must degrade: with JS off this still has to delete."""
    day = _day()
    i = day.index('class="js-section-delete"')
    form = day[day.rindex("<form", 0, i):day.index(">", i) + 1]
    assert 'method="POST"' in form
    assert "delete_crew_row" in form


def test_the_handler_removes_the_header_and_its_edit_panel():
    """The edit panel is a separate sibling <tr>. Leaving it behind orphans a
    form pointing at a row id that no longer exists."""
    day = _day()
    js = day[day.index("Note 1b: removing a section header"):]
    js = js[:js.index("Note 1: collapsible sections")]
    assert "hdr-edit-" in js
    assert "hdr.remove()" in js


def test_a_cancelled_confirm_does_not_ask_twice():
    """The inline confirm() runs first and preventDefaults on cancel."""
    day = _day()
    js = day[day.index("Note 1b: removing a section header"):]
    js = js[:js.index("Note 1: collapsible sections")]
    assert "defaultPrevented" in js


def test_a_failed_delete_falls_back_to_a_real_submit():
    """A delete that silently does nothing is worse than one that reloads."""
    day = _day()
    js = day[day.index("Note 1b: removing a section header"):]
    js = js[:js.index("Note 1: collapsible sections")]
    assert "catch" in js
    assert "form.submit()" in js

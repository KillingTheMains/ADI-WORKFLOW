"""Interface Spec §05 — no pictographs under templates/.

This test should have existed from the start. Without it, §05 regresses the
next time anyone adds a button: it already happened once, in the very session
that reported §05 complete. A count is not a guarantee; a test is.

WHAT COUNTS AS A VIOLATION

Everything pictographic, with three deliberate exceptions:

  1. ⠿ U+283F, the drag handle. §05 names it: "the one pictograph that stays:
     it is a texture, it prints, and its hitbox is tuned."

  2. ☰ U+2630, but ONLY as a drag handle. requests/index.html uses it the way
     every other table uses ⠿, and §01 puts drag handles on the do-not-touch
     list. It is allowlisted BY CLASS, not by character, so a decorative ☰
     anywhere else still fails.

  3. Glyph arrows, U+2190..U+21FF. These are text, not emoji -- §06 itself
     prints "07:00 → 23:30", and Jason, 2026-08-13: "we should be using the
     glyph arrows not the emoji arrows." The EMOJI arrows (⬇ U+2B07, ➕ U+2795)
     are not exempt and were converted. ↶/↷ are also not exempt, because §05's
     own table maps them to undo-2/redo-2.

Comments are NOT stripped before scanning, on purpose. HTML, CSS and Jinja
comments reach the browser, and a session that "removed the emoji" while
leaving them in comments would still be shipping them.
"""
import os
import re
import unicodedata

import pytest

TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "templates")

DRAG_HANDLE = "⠿"          # U+283F -- §05 keeps it
MENU_HANDLE = "☰"          # U+2630 -- kept only inside a drag-handle element
ARROWS = (0x2190, 0x21FF)
SPEC_NAMED_ARROWS = {"↶", "↷"}

PICTOGRAPH_RANGES = (
    (0x1F300, 0x1FAFF),   # emoji & pictographs
    (0x1F000, 0x1F0FF),   # mahjong / cards
    (0x2600, 0x27BF),     # misc symbols + dingbats
    (0x2B00, 0x2BFF),     # misc symbols and arrows (⬇ lives here)
    (0x2190, 0x21FF),     # arrows
    (0x2900, 0x297F),     # supplemental arrows
    (0xFE0F, 0xFE0F),     # variation selector-16
    (0x20E3, 0x20E3),     # combining keycap
    (0xFF0B, 0xFF0B),     # fullwidth plus
)

# A ☰ is forgiven only when it is the content of an element carrying
# class="drag-handle". Anything else is a decorative glyph and fails.
DRAG_HANDLE_ELEMENT = re.compile(r'class="[^"]*drag-handle[^"]*"[^>]*>\s*☰\s*<')


def _is_violation(ch):
    if ch == DRAG_HANDLE:
        return False
    if ch in SPEC_NAMED_ARROWS:
        return True
    o = ord(ch)
    if ARROWS[0] <= o <= ARROWS[1]:
        return False
    if o < 0x00A1:
        return False
    return any(lo <= o <= hi for lo, hi in PICTOGRAPH_RANGES)


def _template_files():
    for dirpath, _dirnames, filenames in os.walk(TEMPLATES):
        for fn in sorted(filenames):
            if fn.endswith((".html", ".jinja", ".j2")):
                yield os.path.join(dirpath, fn)


def _violations(path):
    text = open(path, encoding="utf-8").read()
    forgiven = {m.start() + m.group(0).index("☰")
                for m in DRAG_HANDLE_ELEMENT.finditer(text)}
    out = []
    for i, ch in enumerate(text):
        if ch == MENU_HANDLE and i in forgiven:
            continue
        if _is_violation(ch):
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = "?"
            out.append((text.count("\n", 0, i) + 1, ch, name))
    return out


def test_no_pictographs_under_templates():
    found = {}
    for path in _template_files():
        v = _violations(path)
        if v:
            found[os.path.relpath(path, TEMPLATES)] = v

    if found:
        lines = ["", "Interface Spec §05: pictographs found under templates/.",
                 "Use {{ ico.icon('name') }} -- see templates/_icons.html.", ""]
        total = 0
        for rel in sorted(found):
            for line, ch, name in found[rel]:
                total += 1
                lines.append("  %s:%d  %s  U+%04X  %s" % (rel, line, ch, ord(ch), name))
        lines.append("")
        lines.append("  %d violation(s) in %d file(s)." % (total, len(found)))
        pytest.fail("\n".join(lines))


def test_the_drag_handle_is_still_there():
    """The allowlist has to be load-bearing, or it proves nothing. If ⠿ ever
    disappears from the tree, somebody "finished the job" and this test's
    exception quietly stopped meaning anything."""
    handles = sum(open(p, encoding="utf-8").read().count(DRAG_HANDLE)
                  for p in _template_files())
    assert handles > 0, (
        "⠿ has vanished from templates/. §05 says it stays -- it is a texture, "
        "it prints, and its hitbox is tuned in style.css with !important.")


def test_the_menu_handle_exception_is_narrow():
    """A ☰ that is NOT a drag handle must still fail, or exception 2 is a hole
    big enough to walk an emoji through."""
    sample = '<span class="drag-handle">☰</span><span class="decorative">☰</span>'
    forgiven = {m.start() + m.group(0).index("☰")
                for m in DRAG_HANDLE_ELEMENT.finditer(sample)}
    caught = [i for i, ch in enumerate(sample)
              if ch == MENU_HANDLE and i not in forgiven]
    assert len(forgiven) == 1, "the drag-handle ☰ should be forgiven"
    assert len(caught) == 1, "the decorative ☰ should still be caught"


def test_glyph_arrows_are_allowed_but_emoji_arrows_are_not():
    """§06 prints "07:00 → 23:30", so → is typography. ⬇ and ➕ are not."""
    assert not _is_violation("→")
    assert not _is_violation("←")
    assert _is_violation("⬇")
    assert _is_violation("➕")
    assert _is_violation("↶"), "§05 maps ↶ to undo-2"
    assert _is_violation("🚚")

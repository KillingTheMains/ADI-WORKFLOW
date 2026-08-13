"""Interface Spec §10 — the contrast audit, checked pair by pair.

§10 is a table of every pair the spec specifies, with a ratio and a verdict.
Until now nobody had checked it against the tree; the table was believed. It
was in fact right about every pair it names -- but the app had a hardcoded
#C9A45C on white in the printed show book, at 2.35:1, which is one of the two
pairs the table lists as BANNED.

So there are two jobs here, and they are different:
  1. The TOKENS must still produce the ratios §10 claims. A future "just
     darken that grey a bit" is caught by the first test.
  2. The two banned pairs must not reappear anywhere, including in a
     template's own <style> block, which is where this one was hiding.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(ROOT, "static", "css", "style.css")
TEMPLATES = os.path.join(ROOT, "templates")


def _lin(c):
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexv):
    h = hexv.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg, bg):
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def tokens():
    """The :root custom properties, read from the stylesheet itself, so this
    tests the TREE rather than a copy of the palette kept in the test."""
    css = re.sub(r"/\*.*?\*/", "", open(CSS, encoding="utf-8").read(), flags=re.S)
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", css)}


# (foreground, background, where, threshold). Thresholds are §10's: 4.5 for
# text, 3.0 for large text and non-text (1.4.11).
PAIRS = [
    ("--adi-ok",         "--adi-ok-bg",     "status pill — ok",      4.5),
    ("--adi-warn",       "--adi-warn-bg",   "status pill — warn",    4.5),
    ("--adi-danger",     "--adi-danger-bg", "status pill — danger",  4.5),
    ("--adi-info",       "--adi-info-bg",   "status pill — info",    4.5),
    ("--adi-mineral-dk", "--adi-tint-break", "secondary on break tint", 4.5),
    ("--adi-kind-crew",  "--adi-tint-break", "kind rail vs its fill", 3.0),
    # The bev rail is var(--adi-blue) -- see _row_kinds.html, which sets
    # 'border-left:6px double var(--adi-blue)'. NOT --adi-kind-bev: that token
    # is declared at style.css:73 and referenced by nothing. It holds #35C4D8,
    # signal cyan, which against its own tint is 1.90:1 and would fail this
    # test if it were ever wired up -- which is the reason to assert the pair
    # that actually renders rather than the one that merely exists.
    ("--adi-blue",       "--adi-tint-bev",   "bev rail vs its fill",  3.0),
]

# Pairs §10 names with literal hexes rather than tokens.
LITERAL_PAIRS = [
    ("#16202E", "#F7F4EE", "body text on the app ground", 4.5, 14.94),
    ("#16202E", "#FFFFFF", "data cell on a card",         4.5, 16.40),
    ("#0B2545", "#FFFFFF", "heading / page title",        3.0, 15.39),
    ("#414A54", "#FFFFFF", "secondary text, 13px",        4.5, 9.00),
    ("#59636E", "#FFFFFF", "mineral label",               4.5, 6.11),
    ("#59636E", "#F7F4EE", "mineral label on ground",     4.5, 5.57),
    ("#0C6B79", "#FFFFFF", "link / time, rest",           4.5, 6.19),
    ("#095A66", "#FFFFFF", "link, hover",                 4.5, 7.88),
    ("#FFFFFF", "#0C6B79", "primary button label",        4.5, 6.19),
    ("#CED3DA", "#0B2545", "sidebar nav link, rest",      4.5, 10.22),
    ("#A2ACB8", "#0B2545", "sidebar section label",       4.5, 6.69),
    ("#35C4D8", "#0B2545", "show-code kicker",            4.5, 7.36),
    ("#C9A45C", "#0B2545", "milestone gold on Midnight",  4.5, 6.56),
    ("#7A5C1E", "#FFFFFF", "ink gold text",               4.5, 6.22),
    ("#7A5C1E", "#F7F1E4", "ink gold on recurring tint",  4.5, 5.52),
    ("#FFFFFF", "#24405F", "section header row, level 2", 4.5, 10.64),
    ("#7E8794", "#FFFFFF", "form-control boundary",       3.0, 3.63),
    ("#7E8794", "#F7F4EE", "same control on the ground",  3.0, 3.31),
]

# §10's last two rows: the pairs the app must never produce.
BANNED = {
    "#35C4D8": "signal cyan as text on light — 2.09:1",
    "#C9A45C": "milestone gold as text on light — 2.35:1",
}

# Selectors verified to sit on Midnight (#0B2545), where these two are FINE
# and are in fact what §10 prescribes. Narrow on purpose.
BANNED_OK_ON_DARK = (
    ".no-print", ".day-header", ".masthead", ".sidebar", "#sidebar",
    ".oss-eyebrow", ".show-code", ".cover",
)


def test_the_token_pairs_still_meet_their_threshold():
    t = tokens()
    missing = [n for pair in PAIRS for n in pair[:2] if n not in t]
    assert not missing, "token(s) missing from style.css: %r" % (sorted(set(missing)),)
    bad = []
    for fg, bg, where, need in PAIRS:
        r = ratio(t[fg], t[bg])
        if r < need:
            bad.append("%s: %s %s on %s %s = %.2f:1, needs %.1f"
                       % (where, fg, t[fg], bg, t[bg], r, need))
    assert not bad, "Interface Spec §10 pairs now failing:\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("fg,bg,where,need,claimed", LITERAL_PAIRS)
def test_every_pair_in_the_audit_table_is_what_it_claims(fg, bg, where, need, claimed):
    """§10 states a ratio for each pair. Recompute it rather than believe it."""
    r = ratio(fg, bg)
    assert r >= need, "%s: %.2f:1, needs %.1f" % (where, r, need)
    assert abs(r - claimed) < 0.02, (
        "%s: spec says %.2f:1, actual is %.2f:1" % (where, claimed, r))


def test_the_two_banned_pairs_are_not_used_as_text_on_light():
    """This is the one that would have caught the show book. A template's own
    <style> block is still a stylesheet."""
    offenders = []
    files = [CSS] + [os.path.join(dp, fn)
                     for dp, _dn, fns in os.walk(TEMPLATES)
                     for fn in sorted(fns) if fn.endswith(".html")]
    for path in files:
        text = re.sub(r"/\*.*?\*/", "", open(path, encoding="utf-8").read(), flags=re.S)
        # each rule block, so we can look at the selector that owns the colour
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            selector, body = m.group(1), m.group(2)
            for hexv, why in BANNED.items():
                if re.search(r"(?<![-\w])color\s*:\s*" + hexv, body, re.I):
                    if any(ok in selector for ok in BANNED_OK_ON_DARK):
                        continue      # verified to sit on Midnight
                    offenders.append("%s  {%s}  %s"
                                     % (os.path.relpath(path, ROOT),
                                        " ".join(selector.split())[-60:], why))
    assert not offenders, (
        "Interface Spec §10 bans these as text on a light ground:\n  "
        + "\n  ".join(offenders))


def test_the_banned_check_would_actually_catch_something():
    """An allowlist that forgives everything proves nothing."""
    selector = ".activity-time"
    assert not any(ok in selector for ok in BANNED_OK_ON_DARK)
    assert re.search(r"(?<![-\w])color\s*:\s*#C9A45C",
                     "font-weight: bold; color: #C9A45C;", re.I)

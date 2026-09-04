"""`--adi-gold` is a TEXT colour. It must never be a background.

style.css says so in its own comments, and says why the distinction exists:

    --adi-gold    = INK gold  #7A5C1E (6.22:1 on white) — text
    --adi-gold-lt = TRUE gold #C9A45C — rails and fills, on Midnight

Used as a fill under the app's near-black navy text, INK gold gives roughly
1.9:1 — dark on dark, unreadable. That is not a hypothetical: it is note 1,
which Larry reported himself ("the edit button and the x are too dark"), and
on 2026-09-04 it was reintroduced TWICE in two days — the day-item badges
(note 11) and the OPEN SLOT badge (note 19). Both were written by someone who
read "gold" and reached for the variable called `--adi-gold`, and both were
caught only by looking at the rendered screen.

A count is not a guarantee; a test is. The same reasoning as
test_no_emoji_in_templates.py, which exists because §05 regressed in the
session that reported it complete.

This checks the CSS declaration, not the palette: swapping the hex behind
either variable leaves the rule correct, because the rule is about which role
each variable plays.
"""
import pathlib
import re

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"

# background / background-color, any whitespace, var(--adi-gold) — but NOT
# var(--adi-gold-lt) or --adi-gold-brand, which are the fill golds.
INK_GOLD_AS_FILL = re.compile(
    r"background(?:-color)?\s*:\s*[^;\"']*var\(\s*--adi-gold\s*[,)]",
    re.IGNORECASE,
)


def _offenders():
    hits = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if INK_GOLD_AS_FILL.search(line):
                hits.append(f"{path.relative_to(TEMPLATES.parent)}:{lineno}: {line.strip()}")
    return hits


def test_ink_gold_is_never_used_as_a_background():
    hits = _offenders()
    assert not hits, (
        "--adi-gold is INK gold (#7A5C1E), a TEXT colour. As a fill under the "
        "app's dark navy text it is about 1.9:1 and unreadable — this is the "
        "note-1 defect. Use --adi-gold-lt (#C9A45C) for fills.\n  "
        + "\n  ".join(hits)
    )


def test_the_pattern_actually_catches_the_thing_it_is_for():
    """A guard that cannot fail guards nothing. These are the exact two lines
    that shipped the bug, and the two spellings that must stay legal."""
    assert INK_GOLD_AS_FILL.search("background:var(--adi-gold, #E8B84B);")
    assert INK_GOLD_AS_FILL.search("background:var(--adi-gold,#E8B84B);border-radius:3px;")
    assert INK_GOLD_AS_FILL.search("background-color: var(--adi-gold);")
    assert not INK_GOLD_AS_FILL.search("background:var(--adi-gold-lt,#C9A45C);")
    assert not INK_GOLD_AS_FILL.search("color:var(--adi-gold);")

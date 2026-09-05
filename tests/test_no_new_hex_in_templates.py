"""Colour in templates comes from the tokens, not from hex literals.

The 09-05 whole-project audit counted 617 hard-coded hex literals against
283 token references across 34 templates — 117 distinct hexes that were not
tokens at all. Most were one habit repeated: a stock utility-framework
palette (#16A34A green, #F59E0B amber, #EF4444 red, #1E40AF blue) pasted
next to a badge instead of the semantic tokens style.css already defined
(--adi-ok / --adi-warn / --adi-danger / --adi-info, each with a -bg). The
cost was not taste: white on #16A34A was the Save button at 3.3:1, and every
colour added straight to a template skipped the other four surfaces.

327 of them were replaced with tokens on 09-05. The rest — mostly on the
paper surfaces, plus a handful of one-off tints — are a job for another day,
so this is a RATCHET, not a ban: the count may go down, never up. Lower the
ceiling when you remove some. If this fails after your change, you added a
hex where a token belonged.

What counts: any #rgb / #rrggbb outside Jinja and HTML comments that is not
declared in style.css or paper.css, and is not pure white or black.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
TOKEN_SHEETS = [ROOT / "static" / "css" / "style.css", ROOT / "static" / "css" / "paper.css"]

CEILING = 152   # 2026-09-05. Ratchet DOWN as templates are tokenised.

HEX = re.compile(r"#[0-9a-fA-F]{3,6}\b")


def _norm(h):
    h = h.upper()
    if len(h) == 4:
        h = "#" + "".join(c * 2 for c in h[1:])
    return h


def _token_hexes():
    out = set()
    for sheet in TOKEN_SHEETS:
        if sheet.exists():
            out |= {_norm(h) for h in HEX.findall(sheet.read_text(encoding="utf-8"))}
    return out


def _strays():
    tokens = _token_hexes()
    hits = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        for lineno, line in enumerate(text.splitlines(), 1):
            for h in HEX.findall(line):
                H = _norm(h)
                if len(H) != 7:
                    continue
                if H in tokens or H in ("#FFFFFF", "#000000"):
                    continue
                hits.append(f"{path.relative_to(TEMPLATES)}:{lineno} {h}")
    return hits


def test_no_new_hex_literals_in_templates():
    strays = _strays()
    assert len(strays) <= CEILING, (
        f"{len(strays)} hex literals in templates, ceiling is {CEILING}. "
        "Use a token (var(--adi-…)) instead of a hex. Newest-looking ones:\n  "
        + "\n  ".join(strays[-15:])
    )


def test_the_ceiling_is_honest():
    """If the count has dropped well below the ceiling, lower the ceiling so
    the ratchet keeps biting. 10% slack so an incidental removal does not
    fail the build."""
    n = len(_strays())
    assert n >= CEILING * 0.9, (
        f"only {n} stray hexes left — lower CEILING in this file to {n}"
    )


def test_the_line_that_shipped_is_caught():
    """The Save button that was 3.3:1."""
    assert _norm("#16A34A") not in _token_hexes()

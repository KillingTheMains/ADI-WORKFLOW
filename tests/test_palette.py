"""#21 — the settable palette, and the safety net under it.

The palette's derivation rules were FITTED to the values already in
style.css and paper.css, not chosen. That is what makes this job safe, and
it is only true for as long as something checks it:

    test_the_defaults_reproduce_the_stylesheets

reads both stylesheets off disk and asserts that brand.palette() with no
agency reproduces every colour token in them. If a future change to the
rules quietly restyles the app, that test says so and names the token.

Four tokens change on purpose (Jason, 2026-09-08) — the screen's ok/warn
statuses collapse onto the two paper pill roles, so there is one status
colour app-wide. Those are excepted BY NAME (brand.STATUS_COLLAPSED), never
by a tolerance wide enough to hide a real regression.
"""
import json
import os
import re

import pytest

import brand

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLE = os.path.join(ROOT, "static", "css", "style.css")
PAPER = os.path.join(ROOT, "static", "css", "paper.css")

# Two tokens sit on dark navy and fit to within 6 and 4 units out of 255 —
# invisible there, and no rule fitted them closer (mixing toward Signal cyan
# reached 5 and coupled the hover to a second role, which is worse).
TOLERATED = {"--adi-dark-2": 6, "--adi-kind-local": 4}
DEFAULT_TOLERANCE = 2

# Declared in the stylesheets but not colours, so not the palette's business.
NOT_A_COLOUR = ("--sp-", "--r-", "--el-", "--adi-topbar-h", "--paper-font",
                "--paper-display", "--paper-pt", "--bs-focus-ring-width")


def _declared(path):
    """Every custom property in a stylesheet, first declaration wins."""
    css = re.sub(r"/\*.*?\*/", "", open(path, encoding="utf-8").read(), flags=re.S)
    found = {}
    for m in re.finditer(
            r"(--[a-z0-9-]+)\s*:\s*"
            r"(#[0-9A-Fa-f]{3,6}|rgba\([^)]*\)|[0-9]+\s*,\s*[0-9]+\s*,\s*[0-9]+)\s*;", css):
        found.setdefault(m.group(1), m.group(2).strip())
    return found


def _norm(value):
    """A colour as (kind, numbers) so #FFF, rgba(1,2,3,.5) and "1,2,3"
    compare as colour rather than as text. The tree writes alpha both as
    '.35' and as '0.14'; that is formatting, not a difference."""
    value = value.strip()
    if value.startswith("rgba"):
        parts = [float(x) for x in value[value.index("(") + 1:value.index(")")].split(",")]
        return "rgba", tuple(round(x, 4) for x in parts)
    if value.startswith("#"):
        h = value.lstrip("#")
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return "rgb", tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "rgb", tuple(int(x.strip()) for x in value.split(","))


def _miss(a, b):
    ka, va = _norm(a)
    kb, vb = _norm(b)
    assert ka == kb, f"{a} and {b} are different kinds of value"
    return max(abs(x - y) for x, y in zip(va, vb))


def stylesheet_tokens():
    out = _declared(STYLE)
    for key, value in _declared(PAPER).items():
        out.setdefault(key, value)
    return out


# ── the safety net ─────────────────────────────────────────────────────────

def test_the_defaults_reproduce_the_stylesheets():
    """brand.palette() with no agency IS the app as it stands today."""
    today = stylesheet_tokens()
    palette = brand.palette()
    drifted = []
    for name, generated in palette.items():
        if name not in today or name in brand.STATUS_COLLAPSED:
            continue
        allowed = TOLERATED.get(name, DEFAULT_TOLERANCE)
        miss = _miss(today[name], generated)
        if miss > allowed:
            drifted.append(f"{name}: stylesheet {today[name]} -> palette "
                           f"{generated} (off by {miss}, allowed {allowed})")
    assert not drifted, "the default palette no longer matches the tree:\n" + \
        "\n".join(drifted)


def test_every_colour_token_in_the_tree_is_in_the_palette():
    """The reconciliation has to be COMPLETE. A token left behind is a colour
    that silently stops following the palette — which is exactly how the
    Bootstrap bridge was found: eight literal copies, one of them the app's
    own background."""
    palette = brand.palette()
    orphans = [name for name in stylesheet_tokens()
               if name not in palette and not name.startswith(NOT_A_COLOUR)]
    assert not orphans, f"colour tokens the palette does not drive: {orphans}"


def test_the_status_collapse_is_exactly_four_colours_under_eight_names():
    """The one deliberate visual change. If this list grows, someone has
    restyled something and called it a reconciliation."""
    palette = brand.palette()
    assert set(brand.STATUS_COLLAPSED) == {
        "--adi-ok", "--adi-ok-bg", "--adi-warn", "--adi-warn-bg",
        "--ok", "--ok-bg", "--warn", "--warn-bg"}
    assert palette["--adi-ok"] == palette["--ok"] == brand.OK_INK
    assert palette["--adi-ok-bg"] == palette["--ok-bg"] == brand.OK_BG
    assert palette["--adi-warn"] == palette["--warn"] == brand.WAIT_INK
    assert palette["--adi-warn-bg"] == palette["--warn-bg"] == brand.WAIT_BG
    # and each really did move — otherwise the exception is dead weight
    today = stylesheet_tokens()
    for name, was in brand.STATUS_COLLAPSED.items():
        assert _norm(today[name]) == _norm(was), f"{name} is no longer {was}"
        assert _norm(palette[name]) != _norm(was), f"{name} did not actually move"


def test_kind_fill_reproduces_the_shipped_ladder():
    derived = brand.kind_fill()
    for kind, shipped in brand.KIND_FILL.items():
        assert _miss(shipped, derived[kind]) <= 2, f"{kind}: {shipped} vs {derived[kind]}"


# ── the roles ──────────────────────────────────────────────────────────────

class _Agency:
    def __init__(self, palette_json=None):
        self.palette_json = palette_json


def test_an_override_reaches_every_token_that_derives_from_it():
    agency = _Agency(json.dumps({"midnight": "#402000"}))
    palette = brand.palette(agency)
    assert palette["--adi-midnight"] == "#402000"
    assert palette["--navy"] == "#402000"            # the paper namespace
    assert palette["--adi-kind-crew"] == "#402000"   # the rails
    assert palette["--bs-emphasis-color-rgb"] == "64,32,0"   # Bootstrap
    assert palette["--adi-tint-break"] != brand.palette()["--adi-tint-break"]


@pytest.mark.parametrize("stored", [
    None, "", "not json", "[]", '{"midnight": "red"}', '{"midnight": "#ABC"}',
    '{"midnight": "#12345"}', '{"nonsense": "#123456"}', '{"midnight": null}',
])
def test_a_bad_stored_palette_falls_back_instead_of_failing(stored):
    """A malformed row must not take the app down — every surface reads this."""
    assert brand.roles(_Agency(stored))["midnight"] == brand.MIDNIGHT


def test_roles_and_rows_agree():
    """Every role has a control, and every control has a role."""
    in_rows = [key for _, fields, _ in brand.ROLE_ROWS for key, _ in fields]
    assert sorted(in_rows) == sorted(brand.ROLE_DEFAULTS)
    assert len(brand.ROLE_ROWS) == 11 and len(in_rows) == 13
    for _, _, drives in brand.ROLE_ROWS:
        assert drives.strip().endswith("."), "say what the colour drives"


# ── contrast ───────────────────────────────────────────────────────────────

def test_contrast_ratio_against_known_values():
    assert round(brand.contrast_ratio("#000000", "#FFFFFF"), 2) == 21.0
    assert round(brand.contrast_ratio("#FFFFFF", "#FFFFFF"), 2) == 1.0
    # the two the paper spec states outright
    assert round(brand.contrast_ratio(brand.CYAN_INK, "#FFFFFF"), 1) == 6.2
    assert round(brand.contrast_ratio(brand.GOLD_INK, "#FFFFFF"), 1) == 6.2


def test_the_shipped_palette_passes_its_own_audit():
    """If the defaults failed, the save-time check would refuse ADI's own
    colours and the whole feature would be unusable."""
    assert brand.audit() == []


def test_the_audit_catches_an_unreadable_text_role():
    """The reason the check exists: a light 'text' colour must not be able to
    reach paperwork."""
    bad = brand.audit(_Agency(json.dumps({"mineral": "#CCCCCC"})))
    what = [row[0] for row in bad]
    assert "column headers on white" in what
    assert all(row[3] < row[4] for row in bad)


def test_the_audit_catches_the_two_banned_brand_colours_as_type():
    """True gold and true cyan are 2.4:1 and 2.1:1 on white. The Interface
    Spec bans them as type; putting one in an ink role must be refused."""
    for role, hexv in (("gold_ink", brand.MILESTONE_GOLD),
                       ("cyan_ink", brand.SIGNAL_CYAN)):
        assert brand.audit(_Agency(json.dumps({role: hexv}))), \
            f"{role}={hexv} should have been refused"


def test_a_pill_that_loses_its_own_fill_is_caught():
    bad = brand.audit(_Agency(json.dumps({"ok_bg": brand.OK_INK})))
    assert "the Live pill" in [row[0] for row in bad]


# ── delivery ───────────────────────────────────────────────────────────────

def test_theme_css_carries_both_namespaces_in_one_root():
    css = brand.theme_css()
    assert css.count(":root") == 1
    for name in ("--adi-midnight", "--navy", "--paper-ink", "--bs-body-bg"):
        assert f"{name}:" in css, name
    assert css.rstrip().endswith("}")


def test_theme_css_declares_every_token_once():
    css = brand.theme_css()
    declared = re.findall(r"(--[a-z0-9-]+)\s*:", css)
    assert len(declared) == len(set(declared)) == len(brand.palette())


def test_no_palette_colour_is_still_typed_as_a_literal():
    """#21 replaced 43 hard-coded hexes in the two stylesheets — 39 of them in
    the print block, which is where the paper spec's colours had been typed
    out by hand. If one comes back, that rule silently stops following the
    palette, which is exactly the failure this job existed to remove.

    :root declarations are the exception: those ARE the definitions, and they
    are what the page falls back to when theme.css never arrives.
    """
    roles = {v.upper() for v in brand.ROLE_DEFAULTS.values()}
    offenders = []
    for path in (STYLE, PAPER):
        src = open(path, encoding="utf-8").read()
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)      # comments explain, they don't render
        src = re.sub(r":root\s*\{[^}]*\}", "", src)          # the definitions themselves
        for hexv in roles:
            if hexv in src.upper():
                offenders.append(f"{os.path.basename(path)}: {hexv}")
    assert not offenders, ("palette colours typed as literals again: "
                           + ", ".join(sorted(offenders)))


def test_every_surface_links_the_theme_after_its_own_stylesheet():
    """Five templates, five links. The order matters: theme.css redefines the
    same custom properties, so it has to come after the stylesheet that
    declares them — and because those declarations stay put, a theme.css that
    never arrives degrades to the ADI defaults instead of an unstyled page.
    """
    import pathlib
    root = pathlib.Path(STYLE).parent.parent.parent / "templates"
    surfaces = {
        "base.html": "css/style.css",
        "oss/show_book.html": "css/paper.css",
        "schedule/call_sheet.html": "css/paper.css",
        "shows/crew_contact_sheet.html": "css/paper.css",
        "shows/show_crew_travel_pdf.html": "css/paper.css",
    }
    for name, sheet in surfaces.items():
        text = (root / name).read_text(encoding="utf-8")
        assert "agency.theme_css" in text, f"{name} does not load the palette"
        assert text.index(sheet) < text.index("agency.theme_css"), \
            f"{name} loads the theme before the stylesheet it overrides"

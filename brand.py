"""
ADI brand constants — the single place colour and page geometry are defined.

Sourced from Larry's Drive folder "05 - Brand & Marketing" (reviewed
2026-08-09), specifically the "Measured Confidence" direction. The palette is
stated identically in three independent places, one of which is a
machine-readable token file (ADI_Brand_Tokens_Working.json), so it is the
authoritative version:

  * ADI_Brand_Tokens_Working.json  -> proposed_direction_palette
  * ADI_Designer_Handoff_Guide.pdf -> section 03, TOKEN/HEX/ROLE table
  * ADI_Experience_Group_Brand_Strategy_V1.pdf -> p.15 PRIMARY PALETTE

STATUS: the brand package is explicitly PRE-APPROVAL. The token file's own
status field reads "creative-development working tokens; final design approval
required", and the strategy document says "DO NOT PRODUCE YET" for templates
and guidelines. Everything here is provisional and will need revisiting once
the designer lands.
"""

import json
import re


# ── Palette ─────────────────────────────────────────────────────────────────
# Role descriptions are verbatim from the token file.

MIDNIGHT = "#0B2545"        # Primary authority and typography
WARM_WHITE = "#F7F4EE"      # Primary field and editorial warmth
SIGNAL_CYAN = "#35C4D8"     # Decisions, links, active datum
MINERAL = "#59636E"         # Structure and secondary information
MILESTONE_GOLD = "#C9A45C"  # Rare milestone emphasis


PRIMARY = MIDNIGHT          # what AgencySetting.primary_hex defaults to

# Guardrail, verbatim: "Keep gold rare; cyan is the active signal, not a
# decorative gradient."

# Superseded values, kept ONLY so migrations and tests can recognise them.
# Do not use for new work.
LEGACY_HEXES = {
    "#071B34",   # sampled from a legacy logo PNG before the brand was found
    "#0A162E",   # legacy "ADI Navy", still baked into merchandise artwork
    "#0072CE",   # legacy "ADI Blue"
    "#0B2239",   # rate-card navy; appears nowhere in the brand folder
    "#2E74B5",   # Word's stock accent, mistaken for a brand colour
}


# ── Page geometry ───────────────────────────────────────────────────────────
# Recovered from the OOXML of Larry's five .docx templates, which are
# byte-consistent with each other. Values in inches.

PAGE_WIDTH_IN = 8.5         # US Letter portrait
PAGE_HEIGHT_IN = 11.0
MARGIN_TOP_IN = 0.78
MARGIN_BOTTOM_IN = 0.75
MARGIN_LEFT_IN = 1.00
MARGIN_RIGHT_IN = 1.00
CONTENT_WIDTH_IN = 6.5      # every table in every ADI document is this wide
HEADER_FOOTER_DIST_IN = 0.42
LOGO_BAND_W_IN = 6.5        # logo sits full content width in the page header
LOGO_BAND_H_IN = 0.66


# ── Type scale ──────────────────────────────────────────────────────────────
# Point sizes from the same .docx set. NOTE: no typeface has been chosen and
# no font files exist anywhere in the brand package — the direction is
# "contemporary grotesk" for display and "humanist serif" for editorial, both
# "to be selected and licensed". The only sanctioned fallback in the brand
# material is Arial / Helvetica Neue, so that is what generated documents use
# until a licensed family exists.

FONT_FALLBACK = "Helvetica"     # ReportLab base-14, no licence risk
FONT_FALLBACK_XLSX = "Arial"

PT_TITLE = 21
PT_HEADING_1 = 16
PT_HEADING_2 = 13
PT_HEADING_3 = 12
PT_BODY = 8.5
PT_SMALL = 8
PT_EYEBROW = 9                  # bold, MINERAL, above the title
PT_FOOTER = 9                   # right-aligned, pipe-delimited, page number


# ── Document conventions (Larry, 2026-08-09) ────────────────────────────────
# Answers to the three questions the Drive folders could not settle. These
# govern GENERATED DOCUMENTS (PDF, XLSX). The on-screen app still displays
# 12-hour via the |to_12hr filter — that is deliberate and separate.

TIME_24_HOUR = True             # "13:00", not "1:00 PM"

# strftime patterns. "%-d"/"%-m" (no zero padding) are GNU/BSD extensions —
# fine on macOS and on PythonAnywhere, would need "%d"/"%m" on Windows.
DATE_FORMAT_LONG = "%a %-d %b"      # "Mon 19 Jan" — day headers, cover page
DATE_FORMAT_SHORT = "%-m/%-d"       # "1/19" — tight columns
DATE_FORMAT_FULL = "%a %-d %b %Y"   # "Mon 19 Jan 2026"

PAGE_ORIENTATION = "portrait"   # Letter portrait, per ADI house standard


def fmt_date(value, style="long"):
    """Format a date for a generated document. Empty string when absent."""
    if value is None:
        return ""
    return value.strftime({
        "long": DATE_FORMAT_LONG,
        "short": DATE_FORMAT_SHORT,
        "full": DATE_FORMAT_FULL,
    }.get(style, DATE_FORMAT_LONG))


def fmt_time(value):
    """Format a time for a generated document — 24-hour HH:MM."""
    from time_utils import parse_minutes
    minutes = parse_minutes(value)
    if minutes is None:
        return value or ""
    return "%02d:%02d" % divmod(minutes, 60)


# ── House rules worth encoding, not just documenting ────────────────────────
# "Every substantive block is a table with a shaded header row. There are no
# bullet lists in any ADI document." Generated output should follow suit.
USE_TABLES_NOT_BULLETS = True

# ── Row kind, on paper ─────────────────────────────────────────────────────
# Interface Spec Rev 1 §07/§09. The screen tells seven kinds apart with a
# two-letter chip, a rail pattern and a silhouette. Paper cannot carry a rail
# pattern or a silhouette, so the CODE does the whole job there — and because
# it is two capital letters it survives a fax, a photocopy and a mono laser,
# which is how these documents are actually consumed.
#
# Here rather than in each exporter, next to the palette, because oss_pdf and
# oss_xlsx printing DIFFERENT codes for the same row would be worse than
# printing none: a reader would have no reason to distrust either.
KIND_CODE = {
    "crew": "CC", "act": "AC", "break": "BR", "bev": "BV",
    "local": "LL", "recur": "RC", "sod": "SD", "eod": "ED",
}

# ── Department, on paper ───────────────────────────────────────────────────
# A department event is an ordinary event in every structural way — it has a
# time, it happens on a day, it is a line on the schedule. What it is NOT is
# anonymous. Jason, 2026-08-13: "DOCK events are REAL events. Those are trucks
# coming and going and delivering and picking up gear from the venue. So they
# need to be on the daily schedules as their own events at the times they are
# listed with probably DOCK in the little indicator box to the left instead
# of 'AC'."
#
# So the ROW keeps the activity's rail and fill — same silhouette, because it
# is the same kind of thing — and only the CODE changes. AC is the code for a
# row whose department nobody recorded; a row that HAS one should say so.
#
# Two letters, not four, for the same reason every other code is two: the box
# is a fixed 26px on screen and a fixed column in the PDF and the sheet, and
# "SECURITY" does not fit any of the three. The full department name rides
# alongside as a badge on screen and in its own column on paper, so nothing
# is lost — the chip is an alphabet, not a label.
#
# HVAC is HV and not the obvious AC because AC is already the activity code.
# Two rows meaning different things must never print the same two letters;
# that is the entire premise of this table.
DEPT_CODE = {
    "Dock": "DK", "Hazer": "HZ", "Doors": "DR", "Security": "SC",
    "F&B": "FB", "House LX": "HL", "HVAC": "HV", "Wristbands": "WB",
    "COMS": "CM", "Cleaning": "CL",
}


def row_code(kind, dept=None):
    """The two letters this row prints, on every surface.

    ONE rule, called by the day page, the OSS hub, the department tabs, the
    PDF and the sheet. Jason, 2026-08-13: "the OSS and its tabs are just a
    reflection of the day schedule, so anything you change should encompass
    all 3 areas of the site." A row that says DK on the day and AC on the
    summary of that same day is the summary contradicting its source.

    A plain activity carrying a department IS a department event — that is
    the only shape an OSS entry takes in these streams — so it prints the
    department's code. Everything else keeps its kind: a crew call is CC
    whether or not somebody tagged it F&B, because what a reader needs from
    that row is that it is a crew call.
    """
    if kind == "act" and dept in DEPT_CODE:
        return DEPT_CODE[dept]
    return KIND_CODE.get(kind, KIND_CODE["act"])

# Three tiers, not seven. On paper the fill carries GROUPING — "these rows
# belong together" — and the code column carries KIND. Trying to make a fill
# mean kind is what fails in greyscale: these three sit at 236, 235 and 231,
# which is a texture, not an alphabet.
#
# 'bev' deliberately shares 'break's fill. On screen they are told apart by a
# double rail against a dashed one; on paper that job belongs entirely to BV
# against BR, and giving them two near-identical greys would only suggest a
# distinction the reader cannot actually resolve.
# Warmed 2026-09-07 with the paper spec: the cool blue-greys sat on the
# warm-white bands like a form on a letter. Same three tiers, same
# greyscale separation (≈236 / 232 / 228), now on the paper's own cast.
KIND_FILL = {
    "break": "#EDEAE3",
    "bev":   "#EDEAE3",
    "local": "#E8E4DC",
    "recur": "#F3EBDB",
}

KIND_LEGEND = "CC crew call · AC activity · BR break · BV beverage · LL local labor · RC recurring · SD/ED day anchors"

# Naming: public signature is "ADI"; "ADI Experience Group" is reserved for
# legal, formal and first-reference contexts. The legal entity is
# Allure Designs, Inc. — which appears on contracts and insurance but nowhere
# in the brand folder. Which of the three belongs on generated client
# paperwork is an open question for Larry.
SIGNATURE_SHORT = "ADI"
SIGNATURE_FORMAL = "ADI Experience Group"
LEGAL_ENTITY = "Allure Designs, Inc."


def as_openpyxl(hex_value):
    """openpyxl wants a bare RRGGBB with no leading hash."""
    return (hex_value or "").lstrip("#").upper()


# ── Paper, 2026-09-07 ──────────────────────────────────────────────────────
# The look of "Notes from the week" (the 2026-09-06 list for Larry), which
# Jason asked to become the look of every printed document the app makes.
# Recorded in full in claude/ADI_Print_Design_Spec_2026-09-07.md. These are
# the tokens; the exporters and paper.css read them so no two surfaces can
# drift.
#
# Two rules the palette above did not need on screen but paper does:
#   * Gold and cyan are TEXT here only in their ink forms (GOLD_INK,
#     CYAN_INK). The brand's true gold (#C9A45C) is 2.35:1 on white and is
#     never set as type; it stays a rail colour.
#   * Fills are warm (WARM_WHITE), rules are warm (LINE). Cool greys read as
#     "form" against Barlow; warm ones read as paper.

INK        = "#1B2A3F"      # body text
LINE       = "#DDD8CE"      # hairlines between rows, under column headers
STRIPE     = WARM_WHITE     # section/group band fill
CYAN_INK   = "#0C6B79"      # eyebrow, links — cyan as TEXT on white (6.0:1)
GOLD_INK   = "#7A5C1E"      # item numbers, row codes — gold as TEXT (6.2:1)
OK_BG, OK_INK     = "#E6F2EC", "#1F6B45"   # "Live" pill
WAIT_BG, WAIT_INK = "#FBF3DF", "#7A5C1E"   # "Waiting" pill

# Typeface. Barlow (text) and Barlow Condensed (display), SIL OFL, bundled
# in static/fonts so PDFs embed them and a print engine without web fonts
# still gets them. Before this the PDF was Helvetica and the screen Barlow.
FONT_TEXT    = "Barlow"
FONT_DISPLAY = "BarlowCondensed"

# Page: Letter, tight margins — 12mm top, 13mm sides, 11mm bottom. The
# 1in margins above are Larry's .docx templates and still govern anything
# built to drop into one of those; a schedule that has to hold six columns
# gets the width.
PAPER_MARGIN_TOP_MM    = 12
PAPER_MARGIN_SIDE_MM   = 13
PAPER_MARGIN_BOTTOM_MM = 11
PAPER_CONTENT_WIDTH_IN = round(PAGE_WIDTH_IN - 2 * PAPER_MARGIN_SIDE_MM / 25.4, 3)  # 7.476

# Type scale, points. Body is the base; everything else is a ratio of it so
# the whole sheet scales together (9.4 was the size that held the Larry
# list at two pages with room).
PAPER_PT_BODY     = 9.4
PAPER_PT_SMALL    = 7.5    # column headers, footer      (0.80×)
PAPER_PT_EYEBROW  = 8.9    # "ADI WORKFLOW" line        (0.95×)
PAPER_PT_GROUP    = 9.9    # section band               (1.05×)
PAPER_PT_NUMBER   = 12.7   # item number / row code     (1.35×)
PAPER_PT_TITLE    = 27.0   # document title             (2.9×)
PAPER_LEADING     = 1.3    # line-height on body text
PAPER_RULE_PT     = 2.0    # the midnight rule under the document header
PAPER_HAIRLINE_PT = 0.6

# Column headers: uppercase, tracked, MINERAL, no fill, hairline below.
# Section bands: uppercase condensed bold, MIDNIGHT on STRIPE.
# Rows: hairline LINE below; never a zebra.
# Numbers and codes: condensed bold GOLD_INK, right-aligned in their column.


# ── Settable palette (#21, 2026-09-08) ─────────────────────────────────────
#
# Eleven roles, thirteen values, and every other colour token in the app
# derived from them by a fixed rule.
#
# The rules were not chosen. They were FITTED to the values already sitting in
# style.css and paper.css, which is why palette() with no agency reproduces
# both stylesheets as they stand — fifteen of eighteen derivations land within
# two units out of 255, three of them exactly. That property is the safety
# net: tests/test_palette.py asserts it token by token, so "make the palette
# settable" cannot quietly restyle the app.
#
# FOUR tokens change on purpose (Jason, 2026-09-08): the screen's ok/warn
# statuses collapse onto the two paper pill roles, so there is one status
# colour app-wide instead of two sets that nearly matched. They are named in
# STATUS_COLLAPSED and excepted by name in the test.
#
# Danger is deliberately NOT settable, on screen or on paper. The print spec
# is explicit that paperwork gets no red ("a problem is a sentence in the
# cell, not a colour"), and on screen a danger colour is a safety signal
# rather than branding — the same reason the two *-on-dark tokens stay fixed.
#
# Why eleven roles and not the print spec's nine: SIGNAL_CYAN and
# MILESTONE_GOLD are not paper colours by design (never set as type there),
# but on screen they are the beverage rail, the recurring rail, the focus
# ring and the active signal on Midnight — and three tints derive from
# nothing else.

ROLE_DEFAULTS = {
    "midnight": MIDNIGHT,   "ink":      INK,       "mineral":  MINERAL,
    "line":     LINE,       "stripe":   STRIPE,    "cyan_ink": CYAN_INK,
    "gold_ink": GOLD_INK,   "cyan":     SIGNAL_CYAN,
    "gold":     MILESTONE_GOLD,
    "ok_ink":   OK_INK,     "ok_bg":    OK_BG,
    "wait_ink": WAIT_INK,   "wait_bg":  WAIT_BG,
}

# What the Agency Branding page shows: eleven labelled rows, thirteen inputs.
# The prose is the point — a colour picker with no statement of what it drives
# is a guess, and this page exists so nobody has to guess.
ROLE_ROWS = [
    ("Midnight", (("midnight", None),),
     "Document titles, section-band text, the rule under a document header, "
     "the crew-call plate and the crew and break rails."),
    ("Ink", (("ink", None),),
     "Body text, on screen and on paper."),
    ("Mineral", (("mineral", None),),
     "Column headers, labels, meta lines, footers, secondary cells such as "
     "notes and detail, and the activity rail."),
    ("Line", (("line", None),),
     "Every hairline — between rows, under column headers, under the running "
     "head — and the borders on form controls."),
    ("Stripe", (("stripe", None),),
     "The fill behind a section band, and the app's own ground."),
    ("Cyan ink", (("cyan_ink", None),),
     "Eyebrows, links, primary buttons and the information state. This is "
     "cyan as TEXT; it has to stay readable on white."),
    ("Gold ink", (("gold_ink", None),),
     "Item numbers, the two-letter row codes and call times. Gold as TEXT; "
     "it has to stay readable on white."),
    ("Signal cyan", (("cyan", None),),
     "Screen only: the beverage rail, the focus ring, and the active signal "
     "on Midnight. Never set as type on paper."),
    ("Milestone gold", (("gold", None),),
     "Screen only: the recurring rail and its fill. Kept rare by design."),
    ("Live pill", (("ok_ink", "Text"), ("ok_bg", "Fill")),
     "Live or done, on screen and on paper."),
    ("Waiting pill", (("wait_ink", "Text"), ("wait_bg", "Fill")),
     "Waiting on something, on screen and on paper."),
]

# The four the collapse moves. Named here so the safety-net test excepts them
# by name rather than by a tolerance wide enough to hide a real regression.
STATUS_COLLAPSED = {
    "--adi-ok": "#1A6B3C", "--adi-ok-bg": "#DCFCE7",
    "--adi-warn": "#8A5A00", "--adi-warn-bg": "#FDF3D8",
    "--ok": "#1A6B3C", "--ok-bg": "#DCFCE7",
    "--warn": "#8A5A00", "--warn-bg": "#FDF3D8",
}

WHITE = "#FFFFFF"


def _R(key):            return ("role", key)
def _M(key, to, pct):   return ("mix", key, to, pct)
def _A(key, alpha):     return ("alpha", key, alpha)
def _F(value):          return ("fix", value)
def _RGB(spec):         return ("csv", spec)     # "11,37,69" — Bootstrap's shape


# (css names, rule). Names that share a rule share a line — which is also the
# reconciliation of the two namespaces made visible: --adi-border and paper's
# --border were always the same colour typed twice.
#
# Every percentage below reproduces the value in the comment. "±n" is the
# largest single-channel miss out of 255.
TOKEN_SPECS = [
    # ── the five brand names, verbatim ──────────────────────────────────
    (("--adi-midnight", "--adi-dark", "--adi-kind-crew",
      "--adi-kind-break", "--navy"),            _R("midnight")),
    (("--adi-warm-white", "--adi-surface",
      "--surface", "--paper-stripe",
      "--bs-body-bg"),                          _R("stripe")),
    (("--adi-cyan", "--adi-blue-lt", "--blue-lt"),  _R("cyan")),
    (("--adi-mineral", "--adi-muted", "--adi-kind-act",
      "--adi-kind-anchor", "--muted",
      "--bs-secondary-color"),                  _R("mineral")),
    (("--adi-gold-brand", "--adi-gold-lt",
      "--adi-kind-recur", "--gold-lt"),         _R("gold")),

    # ── the ink pair and the hairline ───────────────────────────────────
    (("--adi-blue", "--adi-info", "--blue"),    _R("cyan_ink")),
    (("--adi-gold", "--gold"),                  _R("gold_ink")),
    (("--paper-ink", "--adi-ink"),              _R("ink")),
    (("--paper-line", "--adi-line"),            _R("line")),

    # ── derived: measured against the tree, not invented ────────────────
    (("--adi-dark-2",),        _M("midnight", "white", .06)),   # #143055 ±6
    (("--adi-kind-local",),    _M("midnight", "white", .12)),   # #24405F ±4
    (("--adi-rail-neutral",),  _M("midnight", "white", .76)),   # #C3CAD3 ±1
    (("--adi-tint-local",),    _M("midnight", "white", .93)),   # #EDF0F4 ±2
    (("--adi-tint-anchor",),   _M("midnight", "white", .93)),   # #EDEFF1 ±1
    (("--adi-tint-break",),    _M("midnight", "white", .94)),   # #EEF1F6 ±2
    (("--adi-text", "--text",
      "--bs-body-color"),      _M("ink", "black", .24)),        # #16202E ±2
    (("--adi-border-strong",
      "--border-strong"),      _M("ink", "white", .44)),        # #7E8794 ±1
    (("--adi-mineral-dk",
      "--muted-dk"),           _M("mineral", "black", .25)),    # #414A54 ±2
    (("--adi-border", "--border",
      "--bs-border-color"),    _M("line", "white", .11)),      # #E2DDD3 ±1
    (("--adi-row-rule",),      _M("line", "stripe", .60)),      # #EDE9E1 exact
    (("--adi-band",),          _M("line", "stripe", .88)),      # #F4F1EA exact
    (("--adi-hover",),         _M("cyan_ink", "white", .92)),   # #EAF4F6 ±2
    (("--adi-tint-bev",
      "--adi-info-bg"),        _M("cyan", "white", .87)),       # #E6F7FA ±1
    (("--adi-tint-recur",),    _M("gold", "white", .83)),       # #F7F1E4 ±1
    (("--adi-blue-dim",),      _A("cyan", .14)),

    # ── status: the two pills are settable, red is not ──────────────────
    (("--adi-ok", "--ok"),          _R("ok_ink")),      # was #1A6B3C
    (("--adi-ok-bg", "--ok-bg"),    _R("ok_bg")),       # was #DCFCE7
    (("--adi-warn", "--warn"),      _R("wait_ink")),    # was #8A5A00
    (("--adi-warn-bg", "--warn-bg"), _R("wait_bg")),    # was #FDF3D8
    (("--adi-danger", "--danger"),       _F("#B3261E")),
    (("--adi-danger-bg", "--danger-bg"), _F("#FDECEA")),
    (("--adi-warn-on-dark",),            _F("#FBBF24")),
    (("--adi-danger-on-dark",),          _F("#F87171")),

    # ── the Bootstrap 5.3 bridge ────────────────────────────────────────
    # Bootstrap reads these at runtime, so alerts, badges, .btn-outline-*,
    # .form-check, .table and focus rings all rebrand from here rather than
    # component by component. They were eight more literal copies of colours
    # already in this table — and --bs-body-bg IS the app's ground, so a
    # palette that did not reach them would recolour everything except the
    # page behind it.
    (("--bs-link-color-rgb",),       _RGB(_R("cyan_ink"))),
    (("--bs-link-hover-color-rgb",), _RGB(_M("cyan_ink", "black", .306))), # 8,74,84 exact
    (("--bs-emphasis-color-rgb",),   _RGB(_R("midnight"))),
    (("--bs-focus-ring-color",),     _A("cyan_ink", .35)),

    # ── not a brand decision: paper is white ────────────────────────────
    (("--adi-card",),                    _F(WHITE)),
]


def _rgb(value):
    h = (value or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(triple):
    return "#%02X%02X%02X" % tuple(
        max(0, min(255, int(round(c)))) for c in triple)


def mix(a, b, pct):
    """`pct` of the way from colour a to colour b, in sRGB."""
    x, y = _rgb(a), _rgb(b)
    return _hex(tuple(x[i] + (y[i] - x[i]) * pct for i in range(3)))


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def is_hex(value):
    """A settable colour is exactly #RRGGBB. Nothing else is accepted —
    a three-digit shorthand or a named colour would store fine and then
    disagree with the contrast check that read it."""
    return bool(_HEX_RE.match((value or "").strip()))


def roles(agency=None):
    """The thirteen role values: the agency's overrides on top of the ADI
    defaults. A missing, unparseable or invalid entry falls back rather than
    failing — a bad row in the database must not take the app down."""
    out = dict(ROLE_DEFAULTS)
    raw = getattr(agency, "palette_json", None) if agency is not None else None
    if not raw:
        return out
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return out
    if not isinstance(stored, dict):
        return out
    for key, value in stored.items():
        if key in out and is_hex(value):
            out[key] = value.upper()
    return out


def palette(agency=None):
    """Every colour token in the app, as {css-var-name: value}.

    One call site for all four namespaces — style.css, paper.css, the print
    block's literals and the exporters — which is the whole point: before
    this, the same colour was typed in up to four places and nothing stopped
    them drifting.
    """
    role = roles(agency)
    toward = dict(role)
    toward["white"], toward["black"] = WHITE, "#000000"

    def resolve(spec):
        kind = spec[0]
        if kind == "role":
            return role[spec[1]]
        if kind == "mix":
            return mix(role[spec[1]], toward[spec[2]], spec[3])
        if kind == "alpha":
            r, g, b = _rgb(role[spec[1]])
            return f"rgba({r},{g},{b},{spec[2]})"
        if kind == "csv":
            return "%d,%d,%d" % _rgb(resolve(spec[1]))
        return spec[1]

    out = {}
    for names, spec in TOKEN_SPECS:
        value = resolve(spec)
        for name in names:
            out[name] = value
    return out


def theme_css(agency=None):
    """The palette as one :root block, carrying BOTH namespaces so a single
    file serves base.html and the four standalone paper templates."""
    pal = palette(agency)
    pad = max(len(n) for n in pal) + 1
    body = "\n".join(f"  {n}:{' ' * (pad - len(n))}{v};" for n, v in pal.items())
    return ("/* Generated from the agency palette. Edit it on the Agency\n"
            "   Branding page, not here — brand.palette() is the source. */\n"
            ":root {\n" + body + "\n}\n")


def kind_fill(agency=None):
    """The row-kind fills on paper, derived from the palette.

    Three tiers, not seven — see KIND_FILL above for why. The greyscale
    ladder (≈236 / 232 / 228) is what has to survive a mono laser, and it
    does: these are mixes of Line and Gold, so a re-coloured palette moves
    the cast without collapsing the separation.
    """
    role = roles(agency)
    quiet = mix(role["line"], WHITE, .43)                    # #EDEAE3 ±1
    return {"break": quiet, "bev": quiet,
            "local": mix(role["line"], role["stripe"], .43),  # #E8E4DC exact
            "recur": mix(role["gold"], WHITE, .78)}           # #F3EBDB exact


# ── Contrast, one implementation ───────────────────────────────────────────
# Lifted out of tests/test_contrast_audit.py, which now imports it. The
# save-time check and the audit test have to be the same arithmetic or the
# page will accept a palette the suite then fails on.

def _lin(channel):
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(value):
    r, g, b = _rgb(value)
    return .2126 * _lin(r) + .7152 * _lin(g) + .0722 * _lin(b)


def contrast_ratio(fg, bg):
    """WCAG 2.1 relative-luminance ratio, 1.0 to 21.0."""
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + .05) / (lo + .05)


# Checked on the DERIVED tokens, not the thirteen roles — what a reader's eye
# meets is the derived value. Thresholds are Interface Spec §10's: 4.5 for
# text, 3.0 for non-text (WCAG 1.4.11).
#
# Hairlines are deliberately absent. --adi-border is 1.3:1 on white and always
# has been; style.css calls it a "decorative hairline ONLY" and points form
# controls at --adi-border-strong, which IS audited. Auditing the hairline
# would fail the shipped palette, which would make the check worthless.
AUDIT_PAIRS = [
    ("--paper-ink",      WHITE,              "body text on paper",              4.5),
    ("--adi-text",       "--adi-surface",    "body text on the app ground",     4.5),
    ("--adi-muted",      WHITE,              "column headers on white",         4.5),
    ("--adi-muted",      "--adi-surface",    "column headers on a band",        4.5),
    ("--adi-blue",       WHITE,              "eyebrows and links",              4.5),
    ("--adi-gold",       WHITE,              "item numbers and row codes",      4.5),
    ("--adi-midnight",   "--adi-surface",    "section-band text",               4.5),
    ("--adi-ok",         "--adi-ok-bg",      "the Live pill",                   4.5),
    ("--adi-warn",       "--adi-warn-bg",    "the Waiting pill",                4.5),
    ("--adi-mineral-dk", "--adi-tint-break", "secondary text on a break row",   4.5),
    ("--adi-mineral-dk", "--adi-tint-recur", "secondary text on a recurring row", 4.5),
    ("--adi-border-strong", WHITE,           "borders on form controls",        3.0),
    ("--adi-kind-crew",  "--adi-tint-break", "a row's rail against its fill",   3.0),
    ("--adi-blue",       "--adi-tint-bev",   "the beverage rail against its fill", 3.0),
    ("--adi-blue-lt",    "--adi-midnight",   "the active signal on the crew plate", 3.0),
]


def audit(agency=None):
    """Every pair that has to hold, checked on the derived palette.

    Returns the failures as (what, foreground, background, ratio, needed).
    Empty means the palette is safe to save. This is what stops a light
    "text" colour quietly making a printed call sheet unreadable.
    """
    pal = palette(agency)
    bad = []
    for fg, bg, what, need in AUDIT_PAIRS:
        f, b = pal.get(fg, fg), pal.get(bg, bg)
        got = contrast_ratio(f, b)
        if round(got, 2) < need:
            bad.append((what, f, b, round(got, 2), need))
    return bad

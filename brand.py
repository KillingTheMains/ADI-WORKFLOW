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

# Three tiers, not seven. On paper the fill carries GROUPING — "these rows
# belong together" — and the code column carries KIND. Trying to make a fill
# mean kind is what fails in greyscale: these three sit at 236, 235 and 231,
# which is a texture, not an alphabet.
#
# 'bev' deliberately shares 'break's fill. On screen they are told apart by a
# double rail against a dashed one; on paper that job belongs entirely to BV
# against BR, and giving them two near-identical greys would only suggest a
# distinction the reader cannot actually resolve.
KIND_FILL = {
    "break": "#E9ECF1",
    "bev":   "#E9ECF1",
    "local": "#E7EBF0",
    "recur": "#EFE7D6",
}

KIND_LEGEND = "CC crew call · AC activity · BR break · BV beverage · LL local labour · RC recurring · SD/ED day anchors"

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

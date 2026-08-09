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


# ── House rules worth encoding, not just documenting ────────────────────────
# "Every substantive block is a table with a shaded header row. There are no
# bullet lists in any ADI document." Generated output should follow suit.
USE_TABLES_NOT_BULLETS = True

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

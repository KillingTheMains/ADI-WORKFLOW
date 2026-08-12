"""
The one-off conversion of show 3 (MCDC26) to local labour.

Separate from `local_labor.py` on purpose: that module is the house rules and
outlives everything, this one is a list of what was on ONE show on ONE day and
should be read as an archive note once it has run.

Every title, count and department below was measured off production
2026-08-12 and approved by Jason before anything ran. The full table with
row counts is in `ADI_Show3_Local_Labor_Mapping.md`.

Scope: **the whole Sparks union block plus the Encore crews** — every crew row
on show 3 that has no real person in it. 160 rows, 340 people.

Decisions baked in, all Jason's:
  * asterisk variants stay SEPARATE positions — `EIC* (SHDW)` is not
    `EIC (SHDW)`. The mark means something operational;
  * the show's own wording wins over the seed's guesses — `Rigger High`, not
    `High Rigger`; `Forklift Driver`, not `Forklift Operator`;
  * every steward collapses to one `Labor Steward`;
  * the union A1/A2 shadows convert with the rest of their block.
"""

# title -> (department, type). Departments use the app's existing vocabulary.
# `lead` runs a crew, `hand` is hired in multiples, `specialty` is one skilled
# person shadowing a visiting counterpart.
SHOW3_POSITIONS = {
    # ── Hands, hired in multiples ───────────────────────────────────────────
    "Scenic Hand":                  ("Scenic",   "hand"),
    "Lighting Hand":                ("Lighting", "hand"),
    "LED Hand":                     ("LED",      "hand"),
    "Audio Hand":                   ("Audio",    "hand"),
    "Video Hand":                   ("Video",    "hand"),
    "Camera Op (Local)":            ("Video",    "hand"),
    "Rigger High":                  ("Rigging",  "hand"),
    "Rigger Low":                   ("Rigging",  "hand"),
    "Rigger Ground":                ("Rigging",  "hand"),
    "Utility (Truss)":              ("Rigging",  "hand"),
    "Carpenters -- Loader/Pusher":  ("General",  "hand"),
    "Car Loader":                   ("General",  "hand"),
    "Forklift Driver":              ("General",  "hand"),
    "Power":                        ("Power",    "hand"),

    # ── Heads — they run the hands beneath them ─────────────────────────────
    "Scenic Head":                  ("Scenic",   "lead"),
    "Lighting Head":                ("Lighting", "lead"),
    "Lighting Head*":               ("Lighting", "lead"),
    "LED Head":                     ("LED",      "lead"),
    "Audio Head":                   ("Audio",    "lead"),
    "Video Head":                   ("Video",    "lead"),

    # ── The union shadow block ──────────────────────────────────────────────
    "A1 (SHDW)":                    ("Audio",    "specialty"),
    "A1* (SHDW)":                   ("Audio",    "specialty"),
    "A2":                           ("Audio",    "specialty"),
    "EIC (SHDW)":                   ("Video",    "specialty"),
    "EIC* (SHDW)":                  ("Video",    "specialty"),
    "Audio System Engineer (SHDW)":  ("Audio",   "specialty"),
    "Audio System Engineer* (SHDW)": ("Audio",   "specialty"),
    "Wireless Intercom Tech (SHDW)":  ("Audio",  "specialty"),
    "Wireless Intercom Tech* (SHDW)": ("Audio",  "specialty"),
    "LX Programmer (SHDW)":         ("Lighting", "specialty"),
    "LX Programmer* (SHDW)":        ("Lighting", "specialty"),
    "E2 Engineer (SHDW)":           ("Video",    "specialty"),
    "E2 Engineer* (SHDW)":          ("Video",    "specialty"),
    "GFX Operator (SHDW)":          ("Video",    "specialty"),
    "GFX Operator* (SHDW)":         ("Video",    "specialty"),
    "Millumin Playback (SHDW)":     ("Video",    "specialty"),
    "Millumin Playback* (SHDW)":    ("Video",    "specialty"),
    "Video Director (SHDW)":        ("Video",    "specialty"),
    "Video TD (SHDW)":              ("Video",    "specialty"),
    "Video TD* (SHDW)":             ("Video",    "specialty"),
    "Prompter (SHDW)":              ("Video",    "specialty"),
    "Prompter* (SHDW)":             ("Video",    "specialty"),
    "LED Head* (SHDW)":             ("LED",      "specialty"),
    "Video Record op/ Livestream Oversight":  ("Video", "specialty"),
    "Video Record op/ Livestream* Oversight": ("Video", "specialty"),

    # ── One steward title, per Jason ────────────────────────────────────────
    "Labor Steward":                ("General",  "lead"),
}

# Row `position` string -> catalogue title, where they differ.
SHOW3_TITLE_MAP = {
    "Steward":       "Labor Steward",
    "Steward - 2nd": "Labor Steward",
}

# Seeded guesses the show's own wording replaces. Removed from the catalogue
# only if nothing is using them.
SHOW3_RETIRE_IF_UNUSED = ("High Rigger", "Ground Rigger", "Forklift Operator",
                          "Steward / Timekeeper", "Up Rigger", "Down Rigger")


# Predicted rows per position string, measured off production 2026-08-12.
# The migration prints actual beside predicted and flags every disagreement —
# a count you cannot check is a count you should not trust.
SHOW3_PREDICTED_ROWS = {
    "Steward": 11, "Scenic Hand": 9, "A2": 8, "Scenic Head": 7,
    "Lighting Hand": 6, "Camera Op (Local)": 6, "Rigger High": 6,
    "EIC (SHDW)": 6, "LED Hand": 5, "Rigger Low": 5,
    "Audio System Engineer (SHDW)": 5, "Wireless Intercom Tech (SHDW)": 5,
    "LX Programmer (SHDW)": 5, "E2 Engineer (SHDW)": 5, "Audio Hand": 4,
    "Video Hand": 4, "Lighting Head": 4, "GFX Operator (SHDW)": 4,
    "Millumin Playback (SHDW)": 4, "Video Director (SHDW)": 4,
    "Video TD (SHDW)": 4, "Video Record op/ Livestream Oversight": 4,
    "Rigger Ground": 3, "Forklift Driver": 3, "Prompter (SHDW)": 3,
    "Utility (Truss)": 2, "Power": 2, "Carpenters -- Loader/Pusher": 2,
    "LED Head": 2, "Wireless Intercom Tech* (SHDW)": 2, "E2 Engineer* (SHDW)": 2,
    "EIC* (SHDW)": 2, "Car Loader": 1, "Lighting Head*": 1,
    "Steward - 2nd": 1, "Audio Head": 1, "Video Head": 1,
    "Audio System Engineer* (SHDW)": 1, "LX Programmer* (SHDW)": 1,
    "GFX Operator* (SHDW)": 1, "Millumin Playback* (SHDW)": 1,
    "Prompter* (SHDW)": 1, "LED Head* (SHDW)": 1, "Video TD* (SHDW)": 1,
    "A1* (SHDW)": 1, "Lighting Head* (SHDW)": 1,
    "Video Record op/ Livestream* Oversight": 1,
}
SHOW3_PREDICTED_TOTAL_ROWS = 160    # includes the one blank-position row
SHOW3_PREDICTED_TOTAL_PEOPLE = 340


def catalogue_title_for(row):
    """Which catalogue position a show-3 crew row belongs to.

    ⚠️ THE EIGHT MISLABELLED ROWS. Eight rows carry `position = 'Steward'`
    while pointing at a placeholder record labelled `Sparks A1`. They are NOT
    stewards. Every one of them sits directly above an `A2 / Sparks A2` row,
    inside the union shadow block, on a day that separately carries both a
    named `A1` lead being shadowed and — where there is one — a genuine
    `Steward / Sparks Steward` row in ENCORE LOCAL CREW.

    Jason asked that the `position` STRING be left alone, so it still reads
    "Steward" on the page. But cataloguing them as `Labor Steward` would put
    eight audio shadows into the steward count and, later, onto the steward
    rate. So the CATALOGUE link follows the evidence while the display string
    keeps his instruction. The migration names all eight so the strings can be
    corrected by hand.

    Identified by shape, not by row id — ids are production-specific and a
    migration that hard-codes them cannot be tested.
    """
    pos = (row.position or "").strip()
    if pos == "Steward":
        cm = row.crew_member
        label = (cm.display_label if cm else "") or ""
        if "A1" in label:
            return "A1 (SHDW)", True      # (title, was_mislabelled)
    return SHOW3_TITLE_MAP.get(pos, pos), False

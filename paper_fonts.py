"""
Barlow for ReportLab.

The screen has been Barlow since the 2026-08 redesign; the PDF stayed on
Helvetica because brand.py (rightly) refused to guess a typeface the brand
package had not chosen. Barlow is the choice now — Jason, 2026-09-07, from
the "Notes from the week" PDF — and it is SIL OFL, so the files live in
static/fonts and every PDF embeds them.

`register()` is idempotent and returns the font NAMES to use. If a file is
missing (a fresh checkout without the fonts, a packaging slip) it falls back
to Helvetica name-for-name so a document is still produced; a schedule that
fails to render over a font is worse than one in the wrong face.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(_HERE, "static", "fonts")

# ReportLab name → file. The names are what Paragraph markup and
# TableStyle FONT commands refer to.
_FILES = {
    "Barlow":                  "Barlow-Regular.ttf",
    "Barlow-Medium":           "Barlow-Medium.ttf",
    "Barlow-SemiBold":         "Barlow-SemiBold.ttf",
    "Barlow-Bold":             "Barlow-Bold.ttf",
    "BarlowCondensed-SemiBold": "BarlowCondensed-SemiBold.ttf",
    "BarlowCondensed-Bold":    "BarlowCondensed-Bold.ttf",
}

_FALLBACK = {
    "Barlow":                  "Helvetica",
    "Barlow-Medium":           "Helvetica",
    "Barlow-SemiBold":         "Helvetica-Bold",
    "Barlow-Bold":             "Helvetica-Bold",
    "BarlowCondensed-SemiBold": "Helvetica-Bold",
    "BarlowCondensed-Bold":    "Helvetica-Bold",
}

_registered = None


def register():
    """Register the family once; return {logical name: font name}."""
    global _registered
    if _registered is not None:
        return dict(_registered)

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    names = {}
    for name, filename in _FILES.items():
        path = os.path.join(FONT_DIR, filename)
        try:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
            names[name] = name
        except Exception:
            names[name] = _FALLBACK[name]

    # <b> inside a Paragraph resolves through the family map. Barlow has no
    # italic in the bundle; italic maps to the upright so nothing errors.
    if names["Barlow"] == "Barlow":
        pdfmetrics.registerFontFamily(
            "Barlow", normal="Barlow", bold="Barlow-Bold",
            italic="Barlow", boldItalic="Barlow-Bold")

    _registered = {
        "text":         names["Barlow"],
        "text_medium":  names["Barlow-Medium"],
        "text_semibold": names["Barlow-SemiBold"],
        "text_bold":    names["Barlow-Bold"],
        "display":      names["BarlowCondensed-SemiBold"],
        "display_bold": names["BarlowCondensed-Bold"],
        "embedded":     names["Barlow"] == "Barlow",
    }
    return dict(_registered)

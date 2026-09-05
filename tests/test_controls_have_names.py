"""Every control a person can operate must have an accessible name.

Two shapes of the same failure, both found by the 09-05 audit of the rendered
app — 20 pages fetched from the local server and checked, not the templates
read:

  * Icon-only buttons with no name. The crew-row remove button on the day
    page rendered 96 times on the busiest day as `<button>` containing only
    `{{ ico.icon('x') }}`. A screen reader announced "button" 96 times with
    no way to tell which row it removed. Nine modal `btn-close` buttons had
    the same problem — Bootstrap's own markup carries aria-label="Close",
    the copies here had dropped it.

  * Form controls with no label binding. 224 of 236 `<label>` elements had
    no `for=`; the pattern everywhere was `<label class="form-label">Date</label>`
    beside an `<input>` with no id — visually adjacent, programmatically
    unrelated. On the rendered crew database that was 1,006 of 1,008 inputs
    and all 407 selects. Assistive tech read "edit text" with no field name.

Neither is visible to a sighted mouse user, which is why both survived. This
test looks at the templates so the next one cannot.

WHAT COUNTS AS A NAME

For a control: an `aria-label`, `aria-labelledby`, `title`, or `placeholder`
attribute; an `id` that some `<label for=>` in the same file points at; or
being inside a `<label>` element (implicit association). Hidden, checkbox,
radio, submit, button and file inputs are exempt here — checkboxes and
radios are named separately by the second test's sibling in the day-page
markup, and submit/button/file inputs carry their value or are handled as
buttons below.

For a button: visible text, `aria-label`, or `title`.
"""
import pathlib
import re

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"

CONTROL = re.compile(r"<(?:input|select|textarea)\b[^>]*>", re.S)
BUTTON = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.S)
LABEL_FOR = re.compile(r'<label\b[^>]*\sfor="([^"]+)"')
ICON = re.compile(r"\{\{\s*ico\.icon\([^}]*\)\s*\}\}")
EXEMPT_TYPES = ('type="hidden"', 'type="checkbox"', 'type="radio"',
                'type="submit"', 'type="button"', 'type="file"')
NAME_ATTRS = ("aria-label", "aria-labelledby", "title=", "placeholder=")


def _strip_comments(text):
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # Script bodies mention tags in comments ("re-fill an activity <select>")
    # and build controls at runtime; neither is template markup.
    return re.sub(r"<script\b.*?</script>", "", text, flags=re.S)


def _unnamed_controls(text):
    bound = set(LABEL_FOR.findall(text))
    hits = []
    for m in CONTROL.finditer(text):
        tag = m.group(0)
        if any(t in tag for t in EXEMPT_TYPES):
            continue
        if any(a in tag for a in NAME_ATTRS):
            continue
        idm = re.search(r'\sid="([^"]+)"', tag)
        if idm and idm.group(1) in bound:
            continue
        before = text[: m.start()]
        if before.rfind("<label") > before.rfind("</label>"):
            continue  # inside a <label>: implicit association
        hits.append(tag)
    return hits


def _unnamed_buttons(text):
    hits = []
    for m in BUTTON.finditer(text):
        attrs, body = m.group(1), m.group(2)
        if "aria-label" in attrs or "title=" in attrs:
            continue
        visible = re.sub(r"<[^>]+>|\s", "", ICON.sub("", body))
        if visible:
            continue
        hits.append(m.group(0))
    return hits


def _offenders():
    out = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = _strip_comments(path.read_text(encoding="utf-8"))
        for tag in _unnamed_controls(text):
            out.append(f"{path.relative_to(TEMPLATES)}: control {tag[:90]!r}")
        for tag in _unnamed_buttons(text):
            out.append(f"{path.relative_to(TEMPLATES)}: button {tag[:90]!r}")
    return out


def test_every_control_and_icon_button_has_a_name():
    offenders = _offenders()
    assert not offenders, (
        "Controls without an accessible name. Add aria-label (or for/id, or "
        "title on an icon-only button):\n  " + "\n  ".join(offenders)
    )


def test_the_line_that_shipped_is_caught():
    """The exact crew-row remove button from day.html before 09-05, and the
    exact label/input pair. If this stops failing, the guard stopped guarding."""
    shipped_button = (
        '<button type="submit" class="btn btn-sm btn-link text-danger p-0"\n'
        '        style="font-size:.7rem;">{{ ico.icon(\'x\') }}</button>'
    )
    assert _unnamed_buttons(shipped_button), "the unnamed remove button must be caught"

    shipped_pair = (
        '<label class="form-label">Date</label>\n'
        '<input type="date" name="date" class="form-control form-control-sm">'
    )
    assert _unnamed_controls(shipped_pair), "the unbound label/input pair must be caught"

    fixed_pair = (
        '<label class="form-label">Date</label>\n'
        '<input type="date" name="date" class="form-control form-control-sm" aria-label="Date">'
    )
    assert not _unnamed_controls(fixed_pair)
    assert not _unnamed_buttons(
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>'
    )

"""
Agency branding — ADI Productions' own logo, used on generated paperwork and
on the Master OSS exports.

Follows the #48 show-artwork pattern (uploads under ~/adi_workflow_uploads,
extension allowlist, size cap, mimetype re-derived from the extension on
serve). One addition: uploads are auto-trimmed. The logo we were handed was a
white wordmark baked onto a solid navy rectangle with ~47% dead margin on the
right and ~38% at the bottom — dropped into a document unmodified it reads as
a navy block with the mark shoved in a corner. Normalising on upload means
that can't recur when someone swaps the asset later.
"""
import json
import os

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort, make_response)
from werkzeug.utils import secure_filename

import brand
from extensions import db
from models import AgencySetting

agency_bp = Blueprint("agency", __name__)

LOGO_ROOT = os.path.expanduser("~/adi_workflow_uploads/agency")
LOGO_MAX_BYTES = 5 * 1024 * 1024
LOGO_EXT_TO_MIME = {".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".gif": "image/gif",
                    ".webp": "image/webp", ".svg": "image/svg+xml"}


def logo_path(setting=None):
    """Absolute path to the stored logo, or None when unset/missing."""
    setting = setting or AgencySetting.get()
    if not setting.logo_filename:
        return None
    p = os.path.join(LOGO_ROOT, setting.logo_filename)
    return p if os.path.exists(p) else None


def _autotrim(path):
    """Crop uniform border padding so the mark fills its canvas.

    Best-effort: any failure leaves the uploaded file exactly as it was. SVGs
    and anything Pillow can't open are skipped rather than mangled.
    """
    if os.path.splitext(path)[1].lower() == ".svg":
        return
    try:
        from PIL import Image, ImageChops
    except Exception:
        return
    try:
        im = Image.open(path)
        fmt = im.format
        rgb = im.convert("RGB")
        # Border colour sampled from the top-left pixel: works for both a
        # transparent margin and a solid-colour plate like the reversed mark.
        plate = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
        box = ImageChops.difference(rgb, plate).convert("L") \
                        .point(lambda v: 255 if v > 40 else 0).getbbox()
        if not box:
            return
        pad = int(max(box[2] - box[0], box[3] - box[1]) * 0.06)
        box = (max(box[0] - pad, 0), max(box[1] - pad, 0),
               min(box[2] + pad, im.size[0]), min(box[3] + pad, im.size[1]))
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            return          # implausible crop — leave the original alone
        im.crop(box).save(path, format=fmt)
    except Exception:
        return


class _Proposed:
    """A stand-in agency carrying a palette that has NOT been saved.

    brand.audit() reads `palette_json` off whatever it is given, so checking a
    submitted palette is a matter of handing it one of these. The check
    therefore runs on exactly the same code path as a stored palette — there
    is no second implementation to disagree with the first.
    """

    def __init__(self, chosen):
        self.palette_json = json.dumps(chosen) if chosen else None


def _page(setting, **extra):
    """The Branding page's context, in one place — the save routes re-render
    it on a refusal rather than redirecting, so the colours somebody just
    picked are still on screen next to the reason they were rejected."""
    context = dict(setting=setting,
                   has_logo=logo_path(setting) is not None,
                   role_rows=brand.ROLE_ROWS,
                   defaults=brand.ROLE_DEFAULTS,
                   roles=brand.roles(setting),
                   is_custom=bool(setting.palette_json),
                   attempted=None, failures=None)
    context.update(extra)
    return render_template("agency/index.html", **context)


@agency_bp.route("/agency")
def agency_settings():
    return _page(AgencySetting.get())


@agency_bp.route("/agency/palette/save", methods=["POST"])
def palette_save():
    """Save the palette, or refuse it and say which pair failed.

    Only roles that DIFFER from the ADI default are stored, so the blob stays
    small and a role we add later picks up its new default automatically
    instead of being pinned to whatever it was the day someone last pressed
    Save.
    """
    setting = AgencySetting.get()
    chosen, malformed = {}, []
    for key, default in brand.ROLE_DEFAULTS.items():
        raw = (request.form.get(key) or "").strip()
        if not raw:
            continue
        if not brand.is_hex(raw):
            malformed.append(key)
            continue
        if raw.upper() != default.upper():
            chosen[key] = raw.upper()

    attempted = dict(brand.ROLE_DEFAULTS, **chosen)
    if malformed:
        flash("Every colour has to be a six-digit hex value like #0B2545. "
              "Not saved.", "danger")
        return _page(setting, attempted=attempted)

    failures = brand.audit(_Proposed(chosen))
    if failures:
        flash("That palette would make something unreadable, so nothing was "
              "saved. Fix the colours below and save again.", "danger")
        return _page(setting, attempted=attempted, failures=failures)

    setting.palette_json = json.dumps(chosen, sort_keys=True) if chosen else None
    # primary_hex IS the Midnight role now. Kept in step here so the workbook
    # cover and the logo preview, which have read it since long before the
    # palette existed, cannot end up on a different navy from everything else.
    setting.primary_hex = attempted["midnight"]
    db.session.commit()
    flash("Palette saved — the app, the printed pages and the exports all "
          "follow it." if chosen else
          "Palette is back to the ADI defaults.", "success")
    return redirect(url_for("agency.agency_settings"))


@agency_bp.route("/agency/palette/reset", methods=["POST"])
def palette_reset():
    setting = AgencySetting.get()
    setting.palette_json = None
    setting.primary_hex = brand.PRIMARY
    db.session.commit()
    flash("Palette reset to the ADI defaults.", "success")
    return redirect(url_for("agency.agency_settings"))


@agency_bp.route("/agency/logo/upload", methods=["POST"])
def logo_upload():
    setting = AgencySetting.get()
    f = request.files.get("logo")
    if not f or not f.filename:
        flash("Choose an image file to upload.", "warning")
        return redirect(url_for("agency.agency_settings"))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in LOGO_EXT_TO_MIME:
        flash("Logo must be a PNG, JPG, GIF, WEBP or SVG.", "danger")
        return redirect(url_for("agency.agency_settings"))
    f.seek(0, os.SEEK_END)
    if f.tell() > LOGO_MAX_BYTES:
        flash("Logo must be under 5 MB.", "danger")
        return redirect(url_for("agency.agency_settings"))
    f.seek(0)

    os.makedirs(LOGO_ROOT, exist_ok=True)
    if setting.logo_filename:                       # don't leave orphans
        old = os.path.join(LOGO_ROOT, setting.logo_filename)
        if os.path.exists(old):
            try: os.remove(old)
            except OSError: pass

    name = (secure_filename(f.filename) or "logo")[:300]
    if os.path.splitext(name)[1].lower() not in LOGO_EXT_TO_MIME:
        name += ext
    dest = os.path.join(LOGO_ROOT, name)
    f.save(dest)
    _autotrim(dest)
    setting.logo_filename = name
    db.session.commit()
    flash("Agency logo updated — it now appears on paperwork and exports.",
          "success")
    return redirect(url_for("agency.agency_settings"))


@agency_bp.route("/agency/logo/delete", methods=["POST"])
def logo_delete():
    setting = AgencySetting.get()
    p = logo_path(setting)
    if p:
        try: os.remove(p)
        except OSError: pass
    setting.logo_filename = None
    db.session.commit()
    flash("Agency logo removed.", "success")
    return redirect(url_for("agency.agency_settings"))


@agency_bp.route("/agency/logo")
def logo():
    setting = AgencySetting.get()
    p = logo_path(setting)
    if not p:
        abort(404)
    # Re-derive the mimetype from the extension — never trust a stored one.
    ext = os.path.splitext(setting.logo_filename)[1].lower()
    return send_file(p, mimetype=LOGO_EXT_TO_MIME.get(
        ext, "application/octet-stream"))


@agency_bp.route("/agency/save", methods=["POST"])
def agency_save():
    setting = AgencySetting.get()
    name = (request.form.get("name") or "").strip()
    primary = (request.form.get("primary_hex") or "").strip()
    if name:
        setting.name = name[:200]
    if primary.startswith("#") and len(primary) == 7:
        setting.primary_hex = primary.upper()
    db.session.commit()
    flash("Agency details saved.", "success")
    return redirect(url_for("agency.agency_settings"))


@agency_bp.route("/agency/theme.css")
def theme_css():
    """The agency palette as one stylesheet, for every surface.

    Loaded after style.css on app pages and after paper.css on the four
    standalone paper templates, so it carries BOTH token namespaces and one
    file serves the lot. The stylesheets keep their own :root declarations,
    which means a failure here degrades to the ADI defaults rather than to an
    unstyled page.

    Cached hard and busted by ?v=<updated_at>, which the context processor
    puts on every link — the palette changes about once a year, and this is
    on every page load.
    """
    setting = AgencySetting.get()
    resp = make_response(brand.theme_css(setting))
    resp.headers["Content-Type"] = "text/css; charset=utf-8"
    resp.headers["Cache-Control"] = "private, max-age=31536000"
    return resp

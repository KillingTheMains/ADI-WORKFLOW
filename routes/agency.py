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
import os

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort)
from werkzeug.utils import secure_filename

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


@agency_bp.route("/agency")
def agency_settings():
    setting = AgencySetting.get()
    return render_template("agency/index.html", setting=setting,
                           has_logo=logo_path(setting) is not None)


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

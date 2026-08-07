"""
Agency branding: ADI Productions' own logo, used on paperwork and exports.

Follows the #48 show-artwork pattern. The one addition is auto-trim on upload:
the original supplied asset was a white wordmark baked onto a navy plate with
~47% dead margin, which would have rendered as a navy block with the mark in a
corner. Normalising on upload stops that recurring on the next asset swap.
"""
import io
import os


def _png_with_padding(mark_box=(40, 40, 60, 60), size=(200, 200),
                      plate=(7, 27, 52), mark=(255, 255, 255)):
    """A small mark on a large solid plate — i.e. lots of dead margin."""
    from PIL import Image
    im = Image.new("RGB", size, plate)
    for x in range(mark_box[0], mark_box[2]):
        for y in range(mark_box[1], mark_box[3]):
            im.putpixel((x, y), mark)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    return buf


def test_setting_is_a_singleton(app, db):
    from models import AgencySetting
    first = AgencySetting.get()
    again = AgencySetting.get()
    assert first.id == again.id
    assert AgencySetting.query.count() == 1
    assert first.primary_hex == "#071B34"      # brand navy from the logo


def test_upload_stores_serves_and_trims(app, client, db, tmp_path, monkeypatch):
    from models import AgencySetting
    import routes.agency as agency
    from PIL import Image
    monkeypatch.setattr(agency, "LOGO_ROOT", str(tmp_path))

    r = client.post("/agency/logo/upload",
                    data={"logo": (_png_with_padding(), "ADI_Reversed.png")},
                    content_type="multipart/form-data")
    assert r.status_code in (200, 302)

    setting = AgencySetting.get()
    assert setting.logo_filename == "ADI_Reversed.png"
    stored = os.path.join(str(tmp_path), setting.logo_filename)
    assert os.path.exists(stored)

    # 200x200 canvas holding a 20x20 mark must come back close to the mark.
    w, h = Image.open(stored).size
    assert w < 60 and h < 60, f"upload was not trimmed (still {w}x{h})"

    served = client.get("/agency/logo")
    assert served.status_code == 200
    assert served.mimetype == "image/png"


def test_rejects_non_image_and_leaves_setting_alone(app, client, db, tmp_path,
                                                    monkeypatch):
    from models import AgencySetting
    import routes.agency as agency
    monkeypatch.setattr(agency, "LOGO_ROOT", str(tmp_path))

    client.post("/agency/logo/upload",
                data={"logo": (io.BytesIO(b"#!/bin/sh\nrm -rf /"), "evil.sh")},
                content_type="multipart/form-data")
    assert AgencySetting.get().logo_filename is None
    assert os.listdir(str(tmp_path)) == []


def test_svg_upload_is_not_mangled(app, client, db, tmp_path, monkeypatch):
    """Pillow can't open SVG — the trim step must skip it, not corrupt it."""
    from models import AgencySetting
    import routes.agency as agency
    monkeypatch.setattr(agency, "LOGO_ROOT", str(tmp_path))

    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    client.post("/agency/logo/upload",
                data={"logo": (io.BytesIO(svg), "adi.svg")},
                content_type="multipart/form-data")
    stored = os.path.join(str(tmp_path), AgencySetting.get().logo_filename)
    with open(stored, "rb") as fh:
        assert fh.read() == svg


def test_settings_page_and_delete(app, client, db, tmp_path, monkeypatch):
    from models import AgencySetting
    import routes.agency as agency
    monkeypatch.setattr(agency, "LOGO_ROOT", str(tmp_path))

    assert client.get("/agency").status_code == 200

    client.post("/agency/logo/upload",
                data={"logo": (_png_with_padding(), "logo.png")},
                content_type="multipart/form-data")
    assert AgencySetting.get().logo_filename == "logo.png"

    client.post("/agency/logo/delete")
    assert AgencySetting.get().logo_filename is None
    assert client.get("/agency/logo").status_code == 404


def test_save_details_validates_hex(app, client, db):
    from models import AgencySetting
    client.post("/agency/save", data={"name": "ADI Productions",
                                      "primary_hex": "not-a-colour"})
    setting = AgencySetting.get()
    assert setting.name == "ADI Productions"
    assert setting.primary_hex == "#071B34"     # rejected, default retained
    client.post("/agency/save", data={"name": "ADI", "primary_hex": "#123ABC"})
    assert AgencySetting.get().primary_hex == "#123ABC"

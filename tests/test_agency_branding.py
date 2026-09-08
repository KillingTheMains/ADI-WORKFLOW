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
    assert first.primary_hex == "#0B2545"      # Midnight, the ADI primary


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
    assert setting.primary_hex == "#0B2545"     # rejected, default retained
    client.post("/agency/save", data={"name": "ADI", "primary_hex": "#123ABC"})
    assert AgencySetting.get().primary_hex == "#123ABC"


# ── #21, the settable palette ───────────────────────────────────────────────

def test_theme_css_is_served_and_carries_both_namespaces(app, client, db):
    """One stylesheet for every surface: the app's --adi-* names, the paper
    pages' short names and the Bootstrap bridge."""
    r = client.get("/agency/theme.css")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/css")
    body = r.get_data(as_text=True)
    for token in ("--adi-midnight:", "--navy:", "--paper-ink:", "--bs-body-bg:"):
        assert token in body, token


def test_theme_css_follows_a_saved_palette(app, client, db):
    from models import AgencySetting
    assert "#402000" not in client.get("/agency/theme.css").get_data(as_text=True)
    client.post("/agency/palette/save", data={"midnight": "#402000"})
    body = client.get("/agency/theme.css").get_data(as_text=True)
    assert "#402000" in body
    # and it reached every token that derives from Midnight, in both namespaces
    assert body.count("#402000") >= 5
    assert AgencySetting.get().primary_hex == "#402000"   # kept in step


def test_only_changed_roles_are_stored(app, client, db):
    """A role left at the ADI default is not written, so a default we improve
    later reaches an installation that never touched that colour."""
    from models import AgencySetting
    import brand
    client.post("/agency/palette/save",
                data={k: v for k, v in brand.ROLE_DEFAULTS.items()} | {"gold": "#B08D3F"})
    assert AgencySetting.get().palette_json == '{"gold": "#B08D3F"}'


def test_an_unreadable_palette_is_refused_and_nothing_is_stored(app, client, db):
    from models import AgencySetting
    before = AgencySetting.get().palette_json
    r = client.post("/agency/palette/save", data={"mineral": "#CCCCCC"})
    assert r.status_code == 200                      # re-rendered, not redirected
    page = r.get_data(as_text=True)
    assert "column headers on white" in page         # the pair is NAMED
    assert "Nothing was saved" in page
    assert AgencySetting.get().palette_json == before


def test_the_refused_colours_are_still_on_the_page(app, client, db):
    """A refusal that also loses what you picked would make the check hostile."""
    r = client.post("/agency/palette/save", data={"mineral": "#CCCCCC"})
    assert "#CCCCCC" in r.get_data(as_text=True)


def test_a_malformed_colour_is_refused(app, client, db):
    from models import AgencySetting
    r = client.post("/agency/palette/save", data={"midnight": "octarine"})
    assert "six-digit hex" in r.get_data(as_text=True)
    assert AgencySetting.get().palette_json is None


def test_reset_clears_the_palette_and_the_primary(app, client, db):
    from models import AgencySetting
    import brand
    client.post("/agency/palette/save", data={"midnight": "#402000"})
    assert AgencySetting.get().palette_json
    client.post("/agency/palette/reset")
    setting = AgencySetting.get()
    assert setting.palette_json is None
    assert setting.primary_hex == brand.PRIMARY


def test_the_branding_page_names_every_role_and_says_what_it_drives(app, client, db):
    import brand
    page = client.get("/agency").get_data(as_text=True)
    for name, fields, drives in brand.ROLE_ROWS:
        assert name in page, name
        assert drives[:40] in page, name
        for key, _sub in fields:
            assert f'name="{key}"' in page, key


def test_the_exports_follow_the_palette(app, client, db):
    """The whole point: a colour changed on this page reaches the PDF and the
    workbook, not just the screen. Before #21 the PDF froze its colours at
    import and would have ignored this until the process restarted."""
    import brand, oss_pdf, oss_xlsx
    from models import AgencySetting
    client.post("/agency/palette/save", data={"midnight": "#402000"})
    agency = AgencySetting.get()
    oss_pdf._use_palette(agency)
    oss_xlsx._use_palette(agency)
    try:
        assert oss_pdf.MIDNIGHT.hexval().endswith("402000")
        assert oss_xlsx.KIND_FILLS["recur"].fgColor.rgb.endswith(
            brand.kind_fill(agency)["recur"].lstrip("#"))
    finally:
        oss_pdf._use_palette(None)
        oss_xlsx._use_palette(None)

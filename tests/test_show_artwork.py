"""#48 — show artwork uploads, serves, and headers all generated paperwork."""
import io
import datetime as dt


def test_show_artwork_upload_serve_and_paperwork(app, client, db, tmp_path, monkeypatch):
    import routes.shows as shows_routes
    from models import Show, ScheduleDay
    monkeypatch.setattr(shows_routes, "ART_ROOT", str(tmp_path))

    show = Show(name="Art Show", code="ART26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 8, 2))
    db.session.add(day); db.session.commit()

    # upload an image
    r = client.post("/shows/%d/artwork/upload" % show.id,
                    data={"artwork": (io.BytesIO(b"fake-png-bytes"), "keyart.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(show)
    assert show.artwork_filename and show.artwork_filename.endswith(".png")

    # serve route returns it with an image mimetype
    rs = client.get("/shows/%d/artwork" % show.id)
    assert rs.status_code == 200 and rs.mimetype.startswith("image/")

    # it appears as a header on the paperwork (call sheet references the serve URL)
    cs = client.get("/shows/%d/schedule/%d/call-sheet" % (show.id, day.id)).get_data(as_text=True)
    assert "/shows/%d/artwork" % show.id in cs

    # a non-image is rejected (artwork unchanged)
    client.post("/shows/%d/artwork/upload" % show.id,
                data={"artwork": (io.BytesIO(b"nope"), "evil.txt")},
                content_type="multipart/form-data", follow_redirects=True)
    db.session.refresh(show)
    assert show.artwork_filename.endswith(".png")

    # delete clears it and the serve route 404s
    client.post("/shows/%d/artwork/delete" % show.id, follow_redirects=True)
    db.session.refresh(show)
    assert show.artwork_filename is None
    assert client.get("/shows/%d/artwork" % show.id).status_code == 404

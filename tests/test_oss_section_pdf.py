"""Notes 9 / 9b — PDF the sections you tick, not the whole OSS.

Larry: "PDF an individual section — Dock, or Security — without having to PDF
the whole thing", then, in the same conversation, check the ones you want and
one batch button.

The content generation already existed: `oss_pdf` has rendered a per-department
section of the master since it was written. What was missing was a scoped entry
point — so the whole feature is a filter applied to `master_items` and nothing
else, because the cover, the department key, the at-a-glance table, the day
sections and the department sections are all derived from that one list.

The thing these tests are really guarding is that a section PDF cannot be
mistaken for the master. It carries the same paperwork header and the same
cover, so the title and the Sections line are what tell a reader which
document is in their hand.
"""
import datetime as dt
import io

import pytest

from models import ScheduleActivity, ScheduleDay, Show, SubScheduleEntry


def _show(db, depts=("Dock", "Security", "Hazer")):
    seq = Show.query.count() + 1
    show = Show(name=f"Section Show {seq}", code=f"SX{seq}",
                room_name="Main Hall")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 4, 6))
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="07:00",
                                    description="LOAD IN", sort_order=1))
    for i, d in enumerate(depts):
        db.session.add(SubScheduleEntry(
            show_id=show.id, schedule_day_id=day.id, type=d,
            time="%02d:00" % (8 + i), sort_order=i,
            activity=f"MARKER {d.upper()} ITEM"))
    db.session.commit()
    return show


def _pages(resp):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(resp.data))
    return [p.extract_text() or "" for p in reader.pages]


def _text(resp):
    return "\n".join(_pages(resp))


def _export(client, show, depts):
    return client.post(f"/shows/{show.id}/oss/sections.pdf",
                       data={"depts[]": list(depts)})


def test_the_export_returns_a_pdf_named_for_its_sections(client, db):
    """These land in a Downloads folder beside the master and beside each
    other. Three files all called the same thing is how the wrong one gets
    sent to a department."""
    show = _show(db)
    r = _export(client, show, ["Dock"])
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"
    assert "_Dock_" in r.headers["Content-Disposition"]
    assert "Master_Schedule" not in r.headers["Content-Disposition"]


def test_only_the_chosen_section_is_in_the_document(client, db):
    show = _show(db)
    text = _text(_export(client, show, ["Dock"]))
    assert "MARKER DOCK ITEM" in text
    assert "MARKER SECURITY ITEM" not in text


def test_several_sections_come_out_as_one_document(client, db):
    """9b's open question, answered the same way as note 17's call sheet: one
    batch document, because that is the word Larry used in both places."""
    show = _show(db)
    r = _export(client, show, ["Dock", "Security"])
    text = _text(r)
    assert "MARKER DOCK ITEM" in text
    assert "MARKER SECURITY ITEM" in text
    assert "MARKER HAZE ITEM" not in text
    assert r.mimetype == "application/pdf"


def test_a_section_pdf_says_it_is_a_section_pdf(client, db):
    """The safety one. Same header, same cover, same key as the master —
    somebody holding a Dock-only schedule and believing it is the whole show
    is the failure this guards."""
    show = _show(db)
    text = _text(_export(client, show, ["Dock"]))
    assert "Section Schedule" in text
    assert "Master Schedule" not in text
    assert "sections" in text.lower()     # the cover label prints in capitals
    assert "Dock" in text


def test_the_eyebrow_is_on_every_page_not_just_the_cover(client, db):
    """An assertion over concatenated pages is not an assertion about any
    page (09-05 finding). A cover that says "Section Schedule" above thirty
    pages that do not would pass the test above. Every page, separately."""
    show = _show(db)
    pages = _pages(_export(client, show, ["Dock"]))
    assert len(pages) >= 2, "need a cover and at least one content page"
    for i, page in enumerate(pages):
        assert "Section Schedule" in page, f"page {i + 1} lacks the eyebrow"
        assert "Master Schedule" not in page, f"page {i + 1} says Master"


def test_the_master_pdf_is_unchanged(client, db):
    """The filter is opt-in. With no departments the document must be exactly
    what it was."""
    show = _show(db)
    text = _text(client.get(f"/shows/{show.id}/oss/master.pdf"))
    assert "Master Schedule" in text
    assert "Section Schedule" not in text
    for marker in ("MARKER DOCK ITEM", "MARKER SECURITY ITEM"):
        assert marker in text


def test_a_stored_type_matches_the_label_users_see(client, db):
    """Hazer/Haze, House LX/House Lights, HVAC/HVAC / AC — three departments
    store a type that differs from their label. A section export that matched
    on the raw string would hand somebody a blank PDF for those three and say
    nothing about it."""
    show = _show(db)
    by_type = _text(_export(client, show, ["Hazer"]))
    by_label = _text(_export(client, show, ["Haze"]))
    assert "MARKER HAZER ITEM" in by_type
    assert "MARKER HAZER ITEM" in by_label


def test_picking_nothing_says_so_instead_of_downloading_an_empty_pdf(client, db):
    show = _show(db)
    r = client.post(f"/shows/{show.id}/oss/sections.pdf", data={},
                    follow_redirects=True)
    assert r.mimetype != "application/pdf"
    assert "Pick at least one section" in r.get_data(as_text=True)


def test_the_picker_offers_only_sections_that_have_something_in_them(client, db):
    """Offered from the departments actually present, which is also why this
    note did not need the canonical department list — the question that has
    been open since August and blocks #2, #11 and #12."""
    show = _show(db, depts=("Dock", "Security"))
    body = client.get(f"/shows/{show.id}/oss").get_data(as_text=True)
    assert 'id="ossSectionsModal"' in body
    assert 'id="oss-section-check-Dock"' in body
    assert 'id="oss-section-check-Security"' in body
    assert 'id="oss-section-check-Doors"' not in body


def test_the_picker_counts_what_is_in_each_section(client, db):
    show = _show(db, depts=("Dock", "Dock", "Security"))
    body = client.get(f"/shows/{show.id}/oss").get_data(as_text=True)
    assert "(2 items)" in body
    assert "(1 item)" in body

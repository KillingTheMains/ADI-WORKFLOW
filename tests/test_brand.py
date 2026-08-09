"""
Brand constants and the colour-correction migration.

The palette came from Larry's Drive brand package (reviewed 2026-08-09), not
from sampling artwork — which is how the previous wrong navy got in.
"""
import pytest


def test_primary_is_midnight():
    import brand
    assert brand.PRIMARY == "#0B2545"
    assert brand.MIDNIGHT == "#0B2545"


def test_superseded_colours_are_recorded_not_reused():
    """The wrong values are kept only so the migration can recognise them."""
    import brand
    assert "#071B34" in brand.LEGACY_HEXES      # sampled from a logo PNG
    assert "#0B2239" in brand.LEGACY_HEXES      # rate-card navy
    assert "#2E74B5" in brand.LEGACY_HEXES      # Word's stock accent
    assert brand.PRIMARY not in brand.LEGACY_HEXES


def test_page_geometry_matches_the_adi_word_templates():
    import brand
    assert (brand.PAGE_WIDTH_IN, brand.PAGE_HEIGHT_IN) == (8.5, 11.0)
    # Content width is the load-bearing number: every table in every ADI
    # document is exactly this wide.
    assert brand.CONTENT_WIDTH_IN == 6.5
    assert (brand.PAGE_WIDTH_IN - brand.MARGIN_LEFT_IN
            - brand.MARGIN_RIGHT_IN) == brand.CONTENT_WIDTH_IN


def test_as_openpyxl_strips_the_hash():
    import brand
    assert brand.as_openpyxl("#0B2545") == "0B2545"
    assert brand.as_openpyxl("0b2545") == "0B2545"
    assert brand.as_openpyxl(None) == ""


@pytest.mark.parametrize("stored", ["#071B34", "#0A162E", "#0B2239", "", None])
def test_migration_corrects_known_wrong_colours(app, db, stored):
    import brand
    from migrations import _correct_agency_primary_colour
    from models import AgencySetting

    setting = AgencySetting.get()
    setting.primary_hex = stored
    db.session.commit()

    _correct_agency_primary_colour(db.session)
    assert AgencySetting.get().primary_hex == brand.PRIMARY


def test_migration_leaves_a_deliberate_choice_alone(app, db):
    """If someone has picked a colour on purpose, don't overwrite it."""
    from migrations import _correct_agency_primary_colour
    from models import AgencySetting

    setting = AgencySetting.get()
    setting.primary_hex = "#123ABC"
    db.session.commit()

    _correct_agency_primary_colour(db.session)
    assert AgencySetting.get().primary_hex == "#123ABC"


def test_xlsx_cover_uses_the_brand_navy(app, db):
    """The export's cover panel must not carry the old sampled colour."""
    import datetime as dt
    import brand
    from models import (Show, ScheduleDay, ScheduleActivity, SubScheduleEntry,
                        MealService, AgencySetting)
    from oss_xlsx import build_workbook

    show = Show(name="Brand Show", code="BR26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 12, 9))
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="08:00",
                                    description="LOAD IN", sort_order=10))
    db.session.commit()

    wb = build_workbook(show, [], [], agency=AgencySetting.get())
    fill = wb["Cover"].cell(row=2, column=2).fill
    assert brand.as_openpyxl(brand.PRIMARY) in str(fill.fgColor.rgb)

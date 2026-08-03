from datetime import date

import pandas as pd

from alt_asset_explorer.video_ingestion.export import EXPORT_COLUMNS, reviewed_csv
from alt_asset_explorer.video_ingestion.field_parser import parse_currency, parse_date, parse_ocr_text
from alt_asset_explorer.video_ingestion.observation_reconciler import reconcile_observations
from alt_asset_explorer.video_ingestion.schemas import CandidateReading
from alt_asset_explorer.video_ingestion.validators import validate_reading


def reading(day, price, cap, frame=1):
    return CandidateReading(day, price, cap, "synthetic", frame, frame / 10, .9, 1)


def test_currency_and_abbreviated_market_cap_parsing():
    assert parse_currency("$18.55") == 18.55
    assert parse_currency("$52,500") == 52500
    assert parse_currency("$1.2M") == 1_200_000


def test_dates_are_iso_capable_and_ambiguous_numeric_dates_are_rejected():
    assert parse_date("Aug 3, 2025") == date(2025, 8, 3)
    assert parse_date("08/03/2025") is None
    assert parse_date("08/03/2025", day_first=False) == date(2025, 8, 3)


def test_ocr_text_field_extraction():
    parsed = parse_ocr_text("Aug 3, 2025  $18.55  Market cap $1.2M")
    assert (parsed.observation_date, parsed.price_per_share, parsed.market_cap) == (date(2025, 8, 3), 18.55, 1_200_000)


def test_duplicates_conflicts_and_chronological_sorting():
    later = reading(date(2025, 8, 3), 18.55, 18550, 3)
    earlier = reading(date(2024, 1, 2), 10, 10000, 1)
    duplicate = reading(date(2025, 8, 3), 18.55, 18550, 4)
    conflict = reading(date(2025, 8, 3), 185.5, 185500, 5)
    result = reconcile_observations([later, earlier, duplicate, conflict])
    assert [item.observation_date for item in result] == [date(2024, 1, 2), date(2025, 8, 3)]
    assert result[1].supporting_frame_count == 2 and result[1].conflict


def test_implied_share_count_validation_flags_without_rewriting():
    item = validate_reading(reading(date(2025, 1, 1), 10, 5000), shares_outstanding=1000)
    assert item.price_per_share == 10
    assert any("implied_share_count_mismatch" in note for note in item.validation_notes)


def test_reviewed_csv_schema():
    result = reconcile_observations([reading(date(2025, 1, 1), 10, 10000)])
    frame = pd.read_csv(__import__('io').StringIO(reviewed_csv(result, "rally-test", "clip.mp4")))
    assert list(frame.columns) == EXPORT_COLUMNS
    assert frame.loc[0, "source_type"] == "rally_ios_screen_recording"

import pandas as pd
import pytest

from alt_asset_explorer.portfolio_lab import (
    AlignmentPolicy,
    align_canonical_history,
    build_eligibility_timeline,
    component_series_compatibility_adapter,
    resolve_canonical_history,
)


def _observations():
    return pd.DataFrame(
        [
            {"asset_id": "a", "period_end": "2024-03-31", "observed_at": "2024-03-29", "frequency": "quarterly", "price_per_share": 10},
            {"asset_id": "a", "period_end": "2024-03-31", "observed_at": "2024-04-02", "frequency": "quarterly", "price_per_share": 11},
            {"asset_id": "a", "period_end": "2024-06-30", "observed_at": "2024-06-28", "frequency": "quarterly", "price_per_share": 12},
            {"asset_id": "b", "period_end": "2024-03-31", "observed_at": "2024-03-30", "frequency": "quarterly", "price_per_share": 20},
            {"asset_id": "b", "period_end": "2024-06-30", "observed_at": "2024-07-03", "frequency": "quarterly", "price_per_share": 22},
            {"asset_id": "b", "period_end": "2024-07-05", "observed_at": "2024-07-05", "frequency": "weekly", "price_per_share": 23},
        ]
    )


def test_resolver_preserves_source_and_separates_observation_date_from_period():
    source = _observations()
    untouched = source.copy(deep=True)

    result = resolve_canonical_history(source, ["a", "b"], as_of_cutoff="2024-06-30")

    pd.testing.assert_frame_equal(source, untouched)
    pd.testing.assert_frame_equal(result.source_rows, untouched)
    assert {"source_observed_at", "canonical_period", "available_at"}.issubset(result.canonical_rows)
    q1_a = result.canonical_rows.query("asset_id == 'a' and canonical_period == '2024-03-31'").iloc[0]
    assert q1_a["source_observed_at"] == pd.Timestamp("2024-04-02")
    assert q1_a["canonical_period"] == pd.Timestamp("2024-03-31")
    assert set(result.excluded_rows["exclusion_reason"]) >= {
        "canonical_period_collision", "after_availability_cutoff", "not_canonical_frequency_or_invalid_date"
    }


def test_availability_cutoff_prevents_future_quote_lookahead():
    before = resolve_canonical_history(_observations(), ["a"], as_of_cutoff="2024-03-31")
    after = resolve_canonical_history(_observations(), ["a"], as_of_cutoff="2024-04-02")

    assert before.canonical_rows.iloc[0]["price_per_share"] == 10
    assert after.canonical_rows.iloc[0]["price_per_share"] == 11


def test_alignment_is_no_fill_and_timeline_explains_missing_periods():
    result = resolve_canonical_history(_observations(), ["a", "b"], as_of_cutoff="2024-06-30")
    union = AlignmentPolicy(periods="union")
    timeline = build_eligibility_timeline(result, ["a", "b"], alignment_policy=union)
    panel = align_canonical_history(result, ["a", "b"], alignment_policy=union)

    assert pd.isna(panel.loc[pd.Timestamp("2024-06-30"), "b"])
    missing = timeline.query("asset_id == 'b' and canonical_period == '2024-06-30'").iloc[0]
    assert not missing["eligible"]
    assert missing["eligibility_reason"] == "missing_observation_no_fill"
    assert missing["carry_policy"] == "none"


def test_carry_cannot_be_enabled_implicitly():
    with pytest.raises(ValueError, match="carry is not supported"):
        AlignmentPolicy(carry="carry_last_observation")


def test_legacy_component_adapter_keeps_both_date_meanings_visible():
    result = resolve_canonical_history(_observations(), ["a"], as_of_cutoff="2024-04-02")
    adapted = component_series_compatibility_adapter(result.canonical_rows)

    assert adapted.iloc[0]["date"] == pd.Timestamp("2024-03-31")
    assert adapted.iloc[0]["source_observed_at"] == pd.Timestamp("2024-04-02")
    assert adapted.iloc[0]["index_level"] == 11

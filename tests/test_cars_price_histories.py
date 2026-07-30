import pandas as pd
import pytest

from alt_asset_explorer.paths import DATA_NORMALIZED, DATA_PROCESSED


EXPECTED_COUNTS = {
    "rally-65ag1": 26,
    "rally-82av1": 18,
    "rally-69bm1": 29,
    "rally-92ld1": 29,
    "rally-92cc1": 29,
}
TICKERS = {"65AG1", "82AV1", "69BM1", "92LD1", "92CC1"}


def test_five_cars_histories_match_authoritative_master_and_reconcile_market_caps():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    cars = assets[assets["category"].eq("cars")]
    selected = cars[cars["ticker"].isin(TICKERS)]
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    history = observations[observations["asset_id"].isin(selected["asset_id"])].copy()

    assert len(cars) == 20
    assert set(selected["ticker"]) == TICKERS
    assert selected["ticker"].is_unique and selected["asset_id"].is_unique
    assert selected["status"].eq("trading").all()
    assert history.groupby("asset_id").size().to_dict() == EXPECTED_COUNTS
    assert not history.duplicated(["asset_id", "observed_at"]).any()

    shares = selected.set_index("asset_id")["shares_outstanding"]
    expected_caps = history["price_per_share"] * history["asset_id"].map(shares)
    assert history["market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())
    assert history["implied_market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())


def test_cars_quarterly_selection_preserves_raw_dates_sparse_periods_and_same_quarter_evidence():
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    history = observations[observations["asset_id"].isin(EXPECTED_COUNTS)]

    assert history["frequency"].value_counts().to_dict() == {"quarterly": 127, "weekly": 4}
    cc = history[history["asset_id"].eq("rally-92cc1")].set_index("observed_at")
    assert cc.loc["2024-04-01T00:00:00Z", "period_end"] == "2024-03-31"
    assert cc.loc["2024-07-01T00:00:00Z", "period_end"] == "2024-06-30"
    assert cc.loc["2024-06-21T00:00:00Z", "frequency"] == "weekly"
    assert not history[history["asset_id"].eq("rally-69bm1")]["period_end"].eq("2022-03-31").any()
    assert not history[history["asset_id"].eq("rally-69bm1")]["period_end"].eq("2022-06-30").any()


def test_cars_equal_and_market_cap_weighted_indexes_are_rebuilt():
    indexes = pd.read_csv(DATA_PROCESSED / "rally_quarterly_indices.csv")
    cars = indexes[indexes["category"].eq("cars")]

    assert set(cars["weighting_method"]) == {"equal", "market_cap"}
    assert cars.groupby("weighting_method").size().to_dict() == {"equal": 35, "market_cap": 35}
    assert cars["date"].max() == "2026-06-30"
    assert cars.groupby("weighting_method")["constituent_count"].max().to_dict() == {
        "equal": 10,
        "market_cap": 10,
    }

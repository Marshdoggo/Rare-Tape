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
    assert selected["status"].isin(["trading", "buyout_pending"]).all()
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


def test_69bm1_first_row_uses_offering_price_not_offering_market_cap():
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    history = observations[observations["asset_id"].eq("rally-69bm1")].sort_values("observed_at")
    first = history.iloc[0]

    assert first["observed_at"] == "2017-11-21T00:00:00Z"
    assert first["event_type"] == "offering_price"
    assert first["price_per_share"] == pytest.approx(57.5)
    assert first["market_cap"] == pytest.approx(115_000)
    assert first["implied_market_cap"] == pytest.approx(115_000)


def test_cars_equal_and_market_cap_weighted_indexes_are_rebuilt():
    indexes = pd.read_csv(DATA_PROCESSED / "rally_quarterly_indices.csv")
    cars = indexes[indexes["category"].eq("cars")]

    assert set(cars["weighting_method"]) == {"equal", "market_cap"}
    assert cars.groupby("weighting_method").size().to_dict() == {"equal": 36, "market_cap": 36}
    assert cars["date"].max() == "2026-06-30"
    assert cars.groupby("weighting_method")["constituent_count"].max().to_dict() == {
        "equal": 20,
        "market_cap": 20,
    }

FINAL_EXPECTED_COUNTS = {
    "rally-61je1": 28,
    "rally-61mg1": 26,
    "rally-72mc1": 28,
    "rally-75ra1": 26,
    "rally-77le1": 34,
    "rally-11bm1": 28,
    "rally-94fs1": 26,
    "rally-99ss1": 27,
    "rally-91mv1": 29,
    "rally-94dv1": 29,
}
FINAL_TICKERS = {asset_id.removeprefix("rally-").upper() for asset_id in FINAL_EXPECTED_COUNTS}
FINAL_QUARTERLY_COUNTS = {
    "rally-61je1": 28,
    "rally-61mg1": 25,
    "rally-72mc1": 26,
    "rally-75ra1": 25,
    "rally-77le1": 31,
    "rally-11bm1": 28,
    "rally-94fs1": 26,
    "rally-99ss1": 27,
    "rally-91mv1": 28,
    "rally-94dv1": 29,
}


def test_final_cars_histories_complete_category_without_duplicate_records_or_observations():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    cars = assets[assets["category"].eq("cars")]
    selected = cars[cars["ticker"].isin(FINAL_TICKERS)]
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    history = observations[observations["asset_id"].isin(FINAL_EXPECTED_COUNTS)].copy()

    assert len(cars) == 20
    assert cars["ticker"].nunique() == 20
    assert set(selected["ticker"]) == FINAL_TICKERS
    assert "61JE1" in set(cars["ticker"])
    assert "61GE1" not in set(cars["ticker"])
    assert selected["ticker"].is_unique and selected["asset_id"].is_unique
    assert selected["status"].isin(["trading", "buyout_pending"]).all()
    assert history.groupby("asset_id").size().to_dict() == FINAL_EXPECTED_COUNTS
    assert not history.duplicated(["asset_id", "observed_at"]).any()

    shares = selected.set_index("asset_id")["shares_outstanding"]
    expected_caps = history["price_per_share"] * history["asset_id"].map(shares)
    assert history["market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())
    assert history["implied_market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())


def test_final_cars_quarterly_normalization_keeps_sparse_and_same_quarter_evidence():
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    history = observations[observations["asset_id"].isin(FINAL_EXPECTED_COUNTS)]

    quarterly = history[history["frequency"].eq("quarterly")]
    assert quarterly.groupby("asset_id").size().to_dict() == FINAL_QUARTERLY_COUNTS
    assert history["frequency"].value_counts().to_dict() == {"quarterly": 273, "weekly": 8}
    assert not history[
        history["asset_id"].eq("rally-11bm1")
    ]["period_end"].eq("2022-03-31").any()

    jaguar = history[history["asset_id"].eq("rally-61je1")].set_index("observed_at")
    assert jaguar.loc["2024-06-24T00:00:00Z", "price_per_share"] == pytest.approx(32.67)
    alpine = history[history["asset_id"].eq("rally-75ra1")].set_index("observed_at")
    assert alpine.loc["2025-09-24T00:00:00Z", "price_per_share"] == pytest.approx(25.25)


def test_all_twenty_trading_cars_have_history_and_rebuilt_indexes():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    cars = assets[assets["category"].eq("cars")]

    assert len(cars) == 20
    assert cars["status"].eq("trading").sum() == 15
    assert cars["status"].eq("buyout_pending").sum() == 5
    assert set(cars["asset_id"]) <= set(observations["asset_id"])

    indexes = pd.read_csv(DATA_PROCESSED / "rally_quarterly_indices.csv")
    cars_indexes = indexes[indexes["category"].eq("cars")]
    assert cars_indexes.groupby("weighting_method").size().to_dict() == {
        "equal": 36,
        "market_cap": 36,
    }
    assert cars_indexes.groupby("weighting_method")["constituent_count"].max().to_dict() == {
        "equal": 20,
        "market_cap": 20,
    }
    assert cars_indexes["date"].max() == "2026-06-30"

from pathlib import Path

import pandas as pd
import pytest

from alt_asset_explorer.asset_registry import active_registry, historical_registry, pending_buyouts
from alt_asset_explorer.canonical_market import load_asset_master


ROOT = Path(__file__).parents[1]
ASSETS_PATH = ROOT / "data/normalized/assets.csv"
OBSERVATIONS_PATH = ROOT / "data/normalized/price_observations.csv"

ACTIVE = {
    "SUPER21", "BATMAN3", "STARWARS1", "AVENGERS57", "FAN45", "BATMAN2",
    "SPIDER1", "BATMAN181", "PENGUIN", "SURFER4", "SPIDER129", "SHOWCASE4",
    "HULK180", "59FLASH", "AC23", "SPIDER10", "FLASH123", "XLXMEN1",
    "XMEN94", "DRACULA10", "GHOST1", "CAPTAIN3", "SUPERMAN6",
}
PENDING = {"BATMAN6", "WOLVERINE"}
EXITED = {
    "BATMAN", "BATMAN1", "JUSTISE1", "THOR", "TMNT1", "AF15", "FAN41",
    "XMEN1", "AVENGERS1", "TOS39", "HULK1", "DAREDEV1", "SUPER14",
}
ROUNDED_TOTALS = {"BATMAN": 2_000_000, "THOR": 261_000, "XMEN1": 325_000}


def _comics() -> pd.DataFrame:
    return pd.read_csv(ASSETS_PATH).query("category == 'comics'")


def test_comics_category_registry_is_complete_unique_and_loadable():
    comics = _comics()
    assert len(comics) == comics["ticker"].nunique() == comics["asset_id"].nunique() == 38
    assert set(comics["ticker"]) == ACTIVE | PENDING | EXITED
    assert len(load_asset_master().query("category == 'comics'")) == 38
    assert comics["underlying_collectible"].notna().all()


def test_comics_lifecycle_counts_and_registry_scopes():
    comics = _comics()
    assert set(active_registry(comics)["ticker"]) == ACTIVE
    assert set(pending_buyouts(comics)["ticker"]) == PENDING
    assert set(historical_registry(comics)["ticker"]) == ACTIVE | PENDING | EXITED
    assert set(comics.query("status == 'exited' and lifecycle_event_status == 'completed'")["ticker"]) == EXITED


def test_comics_offerings_exits_and_pending_offers_reconcile():
    comics = _comics().set_index("ticker")
    assert (comics["shares_outstanding"] * comics["offering_price_per_share"]).to_numpy() == pytest.approx(
        comics["offering_market_cap"].to_numpy()
    )
    for ticker in EXITED - ROUNDED_TOTALS.keys():
        row = comics.loc[ticker]
        assert row["shares_outstanding"] * row["exit_price_per_share"] == pytest.approx(row["exit_value_total"])
    for ticker, authoritative_total in ROUNDED_TOTALS.items():
        assert comics.loc[ticker, "exit_value_total"] == authoritative_total
    for ticker in PENDING:
        row = comics.loc[ticker]
        assert row["shares_outstanding"] * row["buyout_offer_price_per_share"] == pytest.approx(row["buyout_offer_total_value"])
        assert pd.isna(row["exit_date"])
        assert pd.isna(row["exit_price_per_share"])
        assert pd.isna(row["exit_value_total"])


def test_comics_collectible_identity_keeps_related_securities_distinct():
    comics = _comics().set_index("ticker")
    assert comics.loc["HULK180", "underlying_collectible"] == "The Incredible Hulk #180"
    assert comics.loc["WOLVERINE", "underlying_collectible"] == "The Incredible Hulk #181"
    assert comics.loc["BATMAN", "underlying_collectible"] == "Batman #1, CGC 8.0"
    assert comics.loc["BATMAN1", "underlying_collectible"] == "Batman #1, CGC 1.5"
    assert comics.loc["BATMAN", "grade"] == "CGC 8.0"
    assert comics.loc["BATMAN1", "grade"] == "CGC 1.5"


def test_comics_price_history_is_limited_to_authored_assets_and_pending_events_are_not_prices():
    comics = _comics()
    observations = pd.read_csv(OBSERVATIONS_PATH)
    comics_observations = observations[observations["asset_id"].isin(comics["asset_id"])]
    expected_counts = {
        "rally-super21": 25,
        "rally-batman3": 25,
        "rally-starwars1": 23,
        "rally-avengers57": 22,
        "rally-fan45": 21,
        "rally-batman2": 21,
        "rally-spider1": 25,
        "rally-batman181": 18,
        "rally-penguin": 18,
        "rally-surfer4": 18,
    }

    assert comics_observations.groupby("asset_id").size().to_dict() == expected_counts
    assert not comics_observations.duplicated(["asset_id", "observed_at"]).any()
    assert comics_observations["frequency"].value_counts().to_dict() == {"quarterly": 210, "weekly": 6}

    shares = comics.set_index("asset_id")["shares_outstanding"]
    expected_caps = comics_observations["price_per_share"] * comics_observations["asset_id"].map(shares)
    assert comics_observations["market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())
    assert comics_observations["implied_market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())

    assert comics.query("status == 'exited'")["exit_date"].isna().all()
    assert not observations["event_type"].isin(["buyout_offer", "pending_buyout"]).any()


def test_second_comics_price_batch_preserves_dates_prices_and_offering_boundary():
    observations = pd.read_csv(OBSERVATIONS_PATH)
    batch = observations[observations["asset_id"].isin({
        "rally-batman2", "rally-spider1", "rally-batman181", "rally-penguin", "rally-surfer4"
    })].copy()

    assert len(batch) == 100
    assert not batch.duplicated(["asset_id", "observed_at"]).any()
    batman2 = batch.query("asset_id == 'rally-batman2'").set_index(batch.query("asset_id == 'rally-batman2'")["observed_at"].str[:10])
    spider1 = batch.query("asset_id == 'rally-spider1'").set_index(batch.query("asset_id == 'rally-spider1'")["observed_at"].str[:10])
    penguin = batch.query("asset_id == 'rally-penguin'").set_index(batch.query("asset_id == 'rally-penguin'")["observed_at"].str[:10])

    assert batman2.loc["2021-05-10", "price_per_share"] == pytest.approx(10.00)
    assert batman2.loc["2021-05-10", "event_type"] == "offering_price"
    assert batman2.loc["2021-10-27", "frequency"] == "weekly"
    assert spider1.loc["2020-06-02", "price_per_share"] == pytest.approx(27.00)
    assert spider1.loc["2020-06-02", "event_type"] == "chart_observation"
    assert spider1.loc["2022-01-24", "frequency"] == "weekly"
    assert spider1.loc["2023-03-31", "price_per_share"] == pytest.approx(86.00)
    assert spider1.loc["2023-12-28", "price_per_share"] == pytest.approx(20.00)
    assert penguin.loc["2022-09-30", "price_per_share"] == pytest.approx(3.75)
    assert penguin.loc["2022-12-29", "price_per_share"] == pytest.approx(3.75)
    assert penguin.loc["2024-06-25", "price_per_share"] == pytest.approx(4.50)

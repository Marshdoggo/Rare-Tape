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
        "rally-spider129": 19,
        "rally-showcase4": 17,
        "rally-hulk180": 18,
        "rally-59flash": 21,
        "rally-ac23": 20,
        "rally-spider10": 22,
        "rally-flash123": 21,
        "rally-xlxmen1": 19,
        "rally-xmen94": 20,
        "rally-dracula10": 16,
        "rally-ghost1": 19,
        "rally-batman6": 20,
        "rally-captain3": 24,
        "rally-superman6": 17,
    }

    assert comics_observations.groupby("asset_id").size().to_dict() == expected_counts
    assert not comics_observations.duplicated(["asset_id", "observed_at"]).any()
    assert comics_observations["frequency"].value_counts().to_dict() == {"quarterly": 480, "weekly": 9}

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


def test_third_comics_price_batch_preserves_canonical_tickers_and_off_quarter_evidence():
    assets = _comics().set_index("ticker")
    observations = pd.read_csv(OBSERVATIONS_PATH)
    expected = {
        "SPIDER129": 19, "SHOWCASE4": 17, "HULK180": 18, "59FLASH": 21,
        "AC23": 20, "SPIDER10": 22, "FLASH123": 21, "XLXMEN1": 19,
    }

    batch_ids = assets.loc[list(expected), "asset_id"]
    batch = observations[observations["asset_id"].isin(batch_ids)]
    actual = batch.groupby("asset_id").size()
    assert {ticker: int(actual[assets.loc[ticker, "asset_id"]]) for ticker in expected} == expected
    assert len(batch) == 157
    assert batch["frequency"].value_counts().to_dict() == {"quarterly": 156, "weekly": 1}
    assert not batch.duplicated(["asset_id", "observed_at"]).any()

    shares = assets["shares_outstanding"]
    ticker_by_id = assets.reset_index().set_index("asset_id")["ticker"]
    expected_caps = batch["price_per_share"] * batch["asset_id"].map(ticker_by_id).map(shares)
    assert batch["market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())
    assert batch["implied_market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())

    flash123 = batch.query("asset_id == 'rally-flash123'").set_index("observed_at")
    spider10 = batch.query("asset_id == 'rally-spider10'").set_index("observed_at")
    assert flash123.loc["2025-01-02T00:00:00Z", "price_per_share"] == pytest.approx(6.40)
    assert flash123.loc["2025-01-02T00:00:00Z", "frequency"] == "quarterly"
    assert flash123.loc["2025-01-02T00:00:00Z", "period_end"] == "2024-12-31"
    assert flash123.loc["2024-12-26T00:00:00Z", "frequency"] == "weekly"
    assert spider10.loc["2026-07-01T00:00:00Z", "price_per_share"] == pytest.approx(3.40)
    assert spider10.loc["2026-07-01T00:00:00Z", "period_end"] == "2026-06-30"
    assert "FLASH59" not in assets.index
    assert assets.loc["59FLASH", "asset_id"] == "rally-59flash"
    assert assets.loc["HULK180", "asset_id"] != assets.loc["WOLVERINE", "asset_id"]
    assert not batch["event_type"].eq("offering_price").any()


def test_final_comics_batch_preserves_sparse_history_and_pending_offer_boundary():
    assets = _comics().set_index("ticker")
    observations = pd.read_csv(OBSERVATIONS_PATH)
    expected = {
        "XMEN94": (20, 20), "DRACULA10": (16, 16), "GHOST1": (19, 19),
        "BATMAN6": (20, 20), "CAPTAIN3": (24, 23), "SUPERMAN6": (17, 16),
    }
    batch_ids = assets.loc[list(expected), "asset_id"]
    batch = observations[observations["asset_id"].isin(batch_ids)]

    for ticker, (raw_count, quarterly_count) in expected.items():
        asset_id = assets.loc[ticker, "asset_id"]
        history = batch[batch["asset_id"].eq(asset_id)]
        assert len(history) == raw_count
        assert history["frequency"].eq("quarterly").sum() == quarterly_count
    assert len(batch) == 116
    assert not batch.duplicated(["asset_id", "observed_at"]).any()

    captain3 = batch.query("asset_id == 'rally-captain3'").set_index("observed_at")
    batman6 = batch.query("asset_id == 'rally-batman6'").set_index("observed_at")
    assert captain3.loc["2026-07-01T00:00:00Z", "period_end"] == "2026-06-30"
    assert captain3.loc["2026-07-01T00:00:00Z", "price_per_share"] == pytest.approx(21.25)
    assert "2021-12-09T00:00:00Z" not in batman6.index
    assert "2025-06-30" not in set(batman6["period_end"])
    assert not batman6["price_per_share"].eq(11.00).any()
    assert assets.loc["BATMAN6", "status"] == "buyout_pending"
    assert assets.loc["BATMAN6", "trading_state"] == "halted"
    assert assets.loc["BATMAN6", "buyout_offer_price_per_share"] == pytest.approx(11.00)
    assert pd.isna(assets.loc["BATMAN6", "exit_price_per_share"])

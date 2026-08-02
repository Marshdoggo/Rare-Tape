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


def test_comics_have_no_fabricated_price_history_or_invented_exit_dates():
    comics = _comics()
    observations = pd.read_csv(OBSERVATIONS_PATH)
    assert observations["asset_id"].isin(comics["asset_id"]).sum() == 0
    assert comics.query("status == 'exited'")["exit_date"].isna().all()
    assert not observations["event_type"].isin(["buyout_offer", "pending_buyout"]).any()

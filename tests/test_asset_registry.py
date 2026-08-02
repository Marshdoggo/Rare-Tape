from pathlib import Path

import pandas as pd

from alt_asset_explorer.asset_registry import (
    active_registry,
    historical_registry,
    pending_buyouts,
    validate_asset_registry,
)
from alt_asset_explorer.current_universe import normalize_asset_status


ROOT = Path(__file__).parents[1]
REGISTRY_PATH = ROOT / "data/normalized/assets.csv"
OBSERVATIONS_PATH = ROOT / "data/normalized/price_observations.csv"
OFFERS = {
    "63CC1": ("2026-06-29", 69.00, 60.44, 120_880, -0.12405797101449279),
    "94FS1": ("2026-06-24", 58.00, 87.00, 174_000, 0.50),
    "94DV1": ("2026-06-29", 30.00, 31.50, 63_000, 0.05),
    "99SS1": ("2026-06-23", 165.00, 165.50, 165_500, 0.00303030303030305),
    "91MV1": ("2026-06-29", 18.00, 20.00, 40_000, 1 / 9),
}


def _data():
    return pd.read_csv(REGISTRY_PATH), pd.read_csv(OBSERVATIONS_PATH)


def test_registry_is_unique_and_lifecycle_contract_validates():
    registry, observations = _data()
    assert not registry["asset_id"].duplicated().any()
    assert not registry["ticker"].duplicated().any()
    assert validate_asset_registry(registry, observations) == []


def test_five_cars_are_halted_pending_buyouts_with_reconciled_offers():
    registry, _ = _data()
    offers = pending_buyouts(registry).set_index("ticker")
    assert set(OFFERS).issubset(offers.index)
    for ticker, (_, reference, offer, total, premium) in OFFERS.items():
        row = offers.loc[ticker]
        assert row["trading_state"] == "halted"
        assert row["lifecycle_event_type"] == "buyout_offer"
        assert row["buyout_offer_price_per_share"] == offer
        assert row["buyout_offer_total_value"] == total
        assert row["buyout_reference_price"] == reference
        assert abs(row["buyout_premium_pct"] - premium) < 1e-12
        assert pd.isna(row["exit_date"])
        assert pd.isna(row["exit_price_per_share"])


def test_offer_metadata_does_not_change_or_extend_canonical_history():
    registry, observations = _data()
    assert len(observations) == 2560
    for ticker, (date, price, offer, _, _) in OFFERS.items():
        asset_id = registry.loc[registry["ticker"].eq(ticker), "asset_id"].item()
        history = observations[observations["asset_id"].eq(asset_id)].sort_values("observed_at")
        assert pd.to_datetime(history.iloc[-1]["observed_at"]).date() == pd.Timestamp(date).date()
        assert history.iloc[-1]["price_per_share"] == price
        assert not history["event_type"].isin(["pending_buyout", "buyout_offer"]).any()
    assert observations.loc[observations["asset_id"].eq("rally-63cc1")].sort_values("observed_at").iloc[-1]["price_per_share"] == 69
    assert not observations.loc[observations["asset_id"].eq("rally-94fs1"), "price_per_share"].eq(87).any()


def test_active_and_historical_filters_keep_pending_history_but_not_tradability():
    registry, _ = _data()
    pending_ids = set(registry.loc[registry["ticker"].isin(OFFERS), "asset_id"])
    assert pending_ids.isdisjoint(set(active_registry(registry)["asset_id"]))
    assert pending_ids.issubset(set(historical_registry(registry)["asset_id"]))
    assert normalize_asset_status("buyout_pending") == "trading_paused"
    assert set(registry.loc[registry["status"].eq("exited"), "category"]) >= {"books", "handbags", "watches", "wine and whiskey", "fossils"}


def test_provisional_vote_snapshot_is_timestamped_and_non_final():
    registry, _ = _data()
    vote = registry.set_index("ticker").loc["99SS1"]
    assert (vote["buyout_vote_yes_pct"], vote["buyout_vote_no_pct"], vote["buyout_vote_advisory_pct"]) == (22, 77, 0.5)
    assert vote["buyout_vote_provisional"]
    assert pd.notna(pd.to_datetime(vote["buyout_vote_as_of"]))
    assert "non-final" in vote["buyout_notes"]

import pandas as pd
import pytest

from alt_asset_explorer.paths import DATA_NORMALIZED
from alt_asset_explorer.schemas import Category


EXPECTED = {
    "GOLD1": ("precious minerals", 4_000, 4.0, 16_000, "2022-04-01"),
    "METEORITE": ("precious minerals", 17_500, 20.0, 350_000, "2021-08-01"),
    "1857COIN": ("coins", 5_000, 5.0, 25_000, "2022-08-01"),
    "JUSTINIAN": ("coins", 2_000, 9.0, 18_000, "2021-12-01"),
    "CROESUS": ("coins", 8_000, 8.0, 64_000, "2022-07-01"),
}


def test_categories_are_registered():
    assert Category.precious_minerals.value == "precious minerals"
    assert Category.coins.value == "coins"


def test_precious_minerals_and_coins_master_records():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    selected = assets[assets["ticker"].isin(EXPECTED)]

    assert selected["ticker"].is_unique
    assert selected["asset_id"].is_unique
    assert selected["status"].value_counts().to_dict() == {"trading": 5}
    assert set(selected["ticker"]) == set(EXPECTED)
    assert selected.groupby("category")["ticker"].count().to_dict() == {
        "coins": 3,
        "precious minerals": 2,
    }

    by_ticker = selected.set_index("ticker")
    for ticker, (category, shares, price, market_cap, offering_date) in EXPECTED.items():
        row = by_ticker.loc[ticker]
        assert row["category"] == category
        assert row["shares_outstanding"] == shares
        assert row["offering_price_per_share"] == pytest.approx(price)
        assert row["offering_market_cap"] == pytest.approx(market_cap)
        assert row["shares_outstanding"] * row["offering_price_per_share"] == pytest.approx(market_cap)
        assert row["offering_date"] == offering_date


def test_coins_price_histories_reconcile_to_existing_master_without_duplicates():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    coins_master = assets[assets["category"].eq("coins")]
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    coins = observations[observations["asset_id"].isin(coins_master["asset_id"])].copy()

    assert len(coins_master) == 3
    assert coins_master["ticker"].is_unique
    assert coins_master["asset_id"].is_unique
    assert not coins.duplicated(["asset_id", "observed_at"]).any()
    assert coins.groupby(["asset_id", "frequency"]).size().to_dict() == {
        ("rally-1857coin", "quarterly"): 16,
        ("rally-1857coin", "weekly"): 4,
        ("rally-croesus", "quarterly"): 16,
        ("rally-justinian", "quarterly"): 18,
    }

    shares = coins_master.set_index("asset_id")["shares_outstanding"]
    expected_caps = coins["price_per_share"] * coins["asset_id"].map(shares)
    assert coins["market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())
    assert coins["implied_market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())

    quarterly = coins[coins["frequency"].eq("quarterly")].set_index(["asset_id", "observed_at"])
    assert quarterly.loc[("rally-1857coin", "2026-06-26T00:00:00Z"), "market_cap"] == pytest.approx(80_000)
    assert quarterly.loc[("rally-justinian", "2026-06-26T00:00:00Z"), "market_cap"] == pytest.approx(30_000)
    assert quarterly.loc[("rally-croesus", "2026-06-30T00:00:00Z"), "market_cap"] == pytest.approx(66_400)
    assert quarterly.loc[("rally-croesus", "2026-04-01T00:00:00Z"), "period_end"] == "2026-03-31"

    intraperiod = coins[
        coins["asset_id"].eq("rally-1857coin") & coins["frequency"].eq("weekly")
    ]
    assert set(intraperiod["observed_at"]) == {
        "2026-04-13T00:00:00Z", "2026-04-17T00:00:00Z",
        "2026-04-21T00:00:00Z", "2026-04-30T00:00:00Z",
    }
    assert set(intraperiod["price_per_share"]) == {25.0}

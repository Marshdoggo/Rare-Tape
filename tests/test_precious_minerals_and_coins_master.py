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


def test_new_master_records_have_no_price_history():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    asset_ids = set(assets.loc[assets["ticker"].isin(EXPECTED), "asset_id"])
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")

    assert observations[observations["asset_id"].isin(asset_ids)].empty

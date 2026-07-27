import pandas as pd
import pytest

from alt_asset_explorer.paths import DATA_NORMALIZED


EXPECTED = {
    "WARHOL1": (17_000, 10.0, 170_000, "2022-05-01"),
    "GRATEFUL1": (12_500, 10.0, 125_000, "2022-10-01"),
    "WARHOL2": (6_500, 10.0, 65_000, "2022-07-01"),
    "SACHS1": (2_150, 10.0, 21_500, "2022-05-01"),
    "ANDYPELE": (6_500, 4.0, 26_000, "2022-08-01"),
    "HIRST1": (5_000, 4.0, 20_000, "2022-03-01"),
}


def test_art_master_has_six_trading_records_with_valid_offerings():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    art = assets[assets["category"].eq("art")]

    assert art["ticker"].is_unique
    assert art["asset_id"].is_unique
    assert art["status"].value_counts().to_dict() == {"trading": 6}
    assert set(art["ticker"]) == set(EXPECTED)

    by_ticker = art.set_index("ticker")
    for ticker, (shares, offer_price, offer_value, offering_date) in EXPECTED.items():
        row = by_ticker.loc[ticker]
        assert row["shares_outstanding"] == shares
        assert row["offering_price_per_share"] == pytest.approx(offer_price)
        assert row["offering_market_cap"] == pytest.approx(offer_value)
        assert row["shares_outstanding"] * row["offering_price_per_share"] == pytest.approx(offer_value)
        assert row["offering_date"] == offering_date


def test_art_price_histories_reconcile_to_master_without_duplicates():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv").set_index("ticker")
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    art_ids = {ticker: assets.loc[ticker, "asset_id"] for ticker in EXPECTED}
    art = observations[observations["asset_id"].isin(art_ids.values())].copy()

    assert len(art) == 95
    assert not art.duplicated(["asset_id", "observed_at"]).any()
    assert art.groupby("asset_id").size().to_dict() == {
        "rally-andypele": 15,
        "rally-grateful1": 15,
        "rally-hirst1": 16,
        "rally-sachs1": 16,
        "rally-warhol1": 17,
        "rally-warhol2": 16,
    }
    assert art[art["frequency"].eq("quarterly")].groupby("asset_id").size().to_dict() == {
        "rally-andypele": 15,
        "rally-grateful1": 15,
        "rally-hirst1": 15,
        "rally-sachs1": 16,
        "rally-warhol1": 16,
        "rally-warhol2": 16,
    }

    shares = assets.set_index("asset_id")["shares_outstanding"]
    expected_caps = art["price_per_share"] * art["asset_id"].map(shares)
    assert art["market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())
    assert art["implied_market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())

    offerings = art[art["event_type"].eq("offering_price")].set_index("asset_id")
    for ticker, (_, offer_price, offer_value, _) in EXPECTED.items():
        row = offerings.loc[art_ids[ticker]]
        assert row["price_per_share"] == pytest.approx(offer_price)
        assert row["market_cap"] == pytest.approx(offer_value)

    hirst = art[art["asset_id"].eq("rally-hirst1")]
    assert not hirst["observed_at"].astype(str).str.startswith("2024-03").any()
    sachs = art.set_index(["asset_id", "observed_at"])
    assert sachs.loc[("rally-sachs1", "2025-09-29T00:00:00Z"), "price_per_share"] == pytest.approx(2.50)

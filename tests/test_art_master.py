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


def test_art_master_has_no_authored_price_observations():
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    assert set(observations["asset_id"]).isdisjoint({f"rally-{ticker.lower()}" for ticker in EXPECTED})

import pandas as pd
import pytest

from alt_asset_explorer.canonical_market import manual_exits_from_assets
from alt_asset_explorer.paths import DATA_NORMALIZED


EXPECTED = {
    "CATCHER": (500, 25.0, 12_500, 27.95, 13_975, 0.118),
    "EINSTEIN": (2_000, 7.25, 14_500, 8.27, 16_540, 8.27 / 7.25 - 1),
    "FEDERAL": (10_000, 15.0, 150_000, 19.5, 195_000, 0.3),
    "HOBBIT": (10_000, 8.0, 80_000, 9.0, 90_000, 0.125),
    "POTTER": (3_000, 24.0, 72_000, 132_500 / 3_000, 132_500, 132_500 / 72_000 - 1),
}


def test_books_master_has_40_trading_and_five_exact_exited_records():
    assets = pd.read_csv(DATA_NORMALIZED / "assets.csv")
    books = assets[assets["category"].eq("books")]

    assert books["ticker"].is_unique
    assert books["asset_id"].is_unique
    assert books["status"].value_counts().to_dict() == {"trading": 40, "exited": 5}
    assert set(books.loc[books["status"].eq("exited"), "ticker"]) == set(EXPECTED)

    exits = manual_exits_from_assets(books).set_index("ticker")
    for ticker, (shares, offer_price, offer_value, exit_price, exit_value, total_return) in EXPECTED.items():
        row = books.set_index("ticker").loc[ticker]
        assert row["shares_outstanding"] * row["offering_price_per_share"] == pytest.approx(offer_value)
        assert row["offering_market_cap"] == pytest.approx(offer_value)
        assert row["exit_value_total"] == pytest.approx(exit_value)
        assert row["exit_price_per_share"] == pytest.approx(exit_price)
        assert exits.loc[ticker, "realized_return"] == pytest.approx(total_return)


def test_exited_books_have_no_authored_price_observations():
    observations = pd.read_csv(DATA_NORMALIZED / "price_observations.csv")
    assert set(observations["asset_id"]).isdisjoint({f"rally-{ticker.lower()}" for ticker in EXPECTED})

import pandas as pd
import pytest

from alt_asset_explorer.canonical_market import build_canonical_market_data
from alt_asset_explorer.component_portfolios import PortfolioComponent, simulate_component_portfolio
from alt_asset_explorer.portfolio_lab import canonical_index, validate_index_constituent_schema


@pytest.fixture(scope="module")
def production_market():
    return build_canonical_market_data(as_of=pd.Timestamp("2026-07-26").date())


def test_production_constituent_schema_is_accepted_without_rebalance_frequency(production_market):
    constituents = production_market.total_return_constituents
    assert list(constituents.columns) == [
        "date", "universe", "category", "universe_scope", "weighting_method",
        "asset_id", "ticker", "constituent_status", "units_held", "price",
        "price_source", "position_value", "portfolio_weight", "entry_date",
        "exit_date", "terminal_proceeds", "realized_pl", "rebalance_trade_value",
    ]
    assert "rebalance_frequency" not in constituents
    validate_index_constituent_schema(constituents)


@pytest.mark.parametrize("method", ["equal_weight", "market_cap_weight"])
@pytest.mark.parametrize("scope", ["include_exited", "active_only"])
def test_books_constituent_expansion_uses_canonical_fields(production_market, method, scope):
    series, weights = canonical_index(
        production_market.total_return_portfolio,
        production_market.total_return_constituents,
        "category_index", "books", method, scope,
    )
    assert not series.empty
    assert weights
    assert sum(weights.values()) == pytest.approx(1.0)
    assert set(series["rebalance_frequency"]) == {"quarterly"}
    eligible = set(production_market.total_return_constituents.loc[
        production_market.total_return_constituents["category"].eq("books")
        & production_market.total_return_constituents["weighting_method"].eq(method)
        & production_market.total_return_constituents["universe_scope"].eq(scope), "asset_id"
    ])
    assert set(weights).issubset(eligible)


def test_top_level_frequency_does_not_change_canonical_books_lookup(production_market):
    series, weights = canonical_index(
        production_market.total_return_portfolio,
        production_market.total_return_constituents,
        "category_index", "books", "equal_weight", "include_exited",
    )
    component = PortfolioComponent("books", "category_index", "Books", 1.0, series, weights)
    results = {
        frequency: simulate_component_portfolio([component], rebalance_frequency=frequency)
        for frequency in ("quarterly", "annual", "none")
    }
    assert all(result.series["date"].tolist() == results["quarterly"].series["date"].tolist() for result in results.values())
    assert results["none"].composition.iloc[0]["rebalance_count"] == 0
    assert results["annual"].composition.iloc[0]["rebalance_count"] < results["quarterly"].composition.iloc[0]["rebalance_count"]
    assert component.underlying_weights == weights


def test_missing_required_constituent_columns_have_controlled_diagnostic():
    fixture = pd.DataFrame(columns=["asset_id", "category", "date"])
    with pytest.raises(ValueError) as error:
        validate_index_constituent_schema(fixture, source="production index constituents")
    message = str(error.value)
    assert "production index constituents" in message
    assert "missing columns" in message
    assert "portfolio_weight" in message
    assert "available columns ['asset_id', 'category', 'date']" in message

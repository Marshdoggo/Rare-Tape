import pandas as pd
import pytest

from alt_asset_explorer.canonical_market import build_canonical_market_data
from alt_asset_explorer.component_portfolios import PortfolioComponent, simulate_component_portfolio
from alt_asset_explorer.paths import DATA_NORMALIZED
from alt_asset_explorer.portfolio_lab import (
    NORMALIZED_ASSET_COLUMNS,
    NORMALIZED_OBSERVATION_COLUMNS,
    build_phase_zero_diagnostic,
    canonical_index,
    validate_index_constituent_schema,
)


BOOK_IDS = (
    "rally-59bond", "rally-59jfk", "rally-62bond", "rally-aghowl", "rally-alice",
    "rally-anmlfarm", "rally-bond1", "rally-bradbury", "rally-brosgrimm",
    "rally-churchill", "rally-congress", "rally-dune", "rally-frost",
    "rally-gatsby", "rally-grapes", "rally-gwtw", "rally-hgwells", "rally-holmes",
    "rally-huckfinn", "rally-irobot", "rally-jekyll", "rally-keller",
    "rally-kerouac", "rally-lotf", "rally-lotr", "rally-marx", "rally-mobydick",
    "rally-newton", "rally-newworld", "rally-rabbit", "rally-roosevelt",
    "rally-shkspr4", "rally-tkam", "rally-treasure", "rally-twocities",
    "rally-ulysses", "rally-walden", "rally-wildthing", "rally-wzrdofoz", "rally-yoko",
)


@pytest.fixture(scope="module")
def production_market():
    return build_canonical_market_data(as_of=pd.Timestamp("2026-07-26").date())


@pytest.fixture(scope="module")
def normalized_sources():
    return (
        pd.read_csv(DATA_NORMALIZED / "assets.csv"),
        pd.read_csv(DATA_NORMALIZED / "price_observations.csv"),
    )


def test_phase_zero_uses_exact_committed_production_schemas_and_books_snapshot(normalized_sources):
    assets, observations = normalized_sources
    assert tuple(assets.columns) == NORMALIZED_ASSET_COLUMNS
    assert tuple(observations.columns) == NORMALIZED_OBSERVATION_COLUMNS
    trading_books = assets.loc[
        assets["category"].eq("books") & assets["status"].eq("trading"), "asset_id"
    ]
    assert tuple(sorted(trading_books)) == BOOK_IDS


def test_phase_zero_books_resolution_and_alignment_contract(normalized_sources):
    assets, observations = normalized_sources
    diagnostic = build_phase_zero_diagnostic(
        assets, observations, (*BOOK_IDS, "rally-not-present", BOOK_IDS[0])
    )
    assert diagnostic.selected_asset_ids == (*BOOK_IDS, "rally-not-present")
    assert diagnostic.resolved_asset_ids == BOOK_IDS
    assert diagnostic.missing_asset_ids == ("rally-not-present",)
    assert diagnostic.observed_date_intersection == ()
    assert diagnostic.canonical_period_intersection == tuple(pd.to_datetime([
        "2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
        "2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31",
        "2025-03-31", "2025-12-31", "2026-03-31", "2026-06-30",
    ]))


def test_phase_zero_books_launch_ranges_and_duplicate_policy_are_stable(normalized_sources):
    assets, observations = normalized_sources
    diagnostic = build_phase_zero_diagnostic(assets, observations, BOOK_IDS)
    launches = diagnostic.launch_ranges.set_index("asset_id")
    assert launches["first_canonical_period"].dt.strftime("%Y-%m-%d").to_dict() == {
        asset_id: period for period, asset_ids in {
            "2019-12-31": ("rally-frost", "rally-twocities"),
            "2020-03-31": ("rally-aghowl", "rally-roosevelt", "rally-ulysses"),
            "2020-06-30": ("rally-bond1", "rally-lotr", "rally-yoko"),
            "2020-09-30": ("rally-alice", "rally-churchill", "rally-gatsby", "rally-shkspr4"),
            "2020-12-31": ("rally-59jfk", "rally-62bond", "rally-anmlfarm", "rally-dune", "rally-grapes", "rally-kerouac", "rally-tkam"),
            "2021-03-31": ("rally-59bond",),
            "2021-06-30": ("rally-brosgrimm", "rally-hgwells", "rally-huckfinn", "rally-newton", "rally-walden", "rally-wzrdofoz"),
            "2021-09-30": ("rally-congress",),
            "2021-12-31": ("rally-holmes", "rally-marx", "rally-wildthing"),
            "2022-03-31": ("rally-bradbury", "rally-gwtw", "rally-irobot", "rally-keller", "rally-lotf", "rally-mobydick", "rally-newworld"),
            "2022-06-30": ("rally-treasure",),
            "2022-09-30": ("rally-jekyll", "rally-rabbit"),
        }.items() for asset_id in asset_ids
    }
    assert set(launches["last_canonical_period"]) == {pd.Timestamp("2026-06-30")}
    assert launches.loc["rally-twocities", "first_observed_at"] == pd.Timestamp("2019-11-01")
    assert launches.loc["rally-anmlfarm", "last_observed_at"] == pd.Timestamp("2026-07-23")
    assert (
        diagnostic.raw_observation_rows,
        diagnostic.unique_observation_rows,
        diagnostic.duplicate_observation_rows_removed,
        diagnostic.raw_canonical_rows,
        diagnostic.unique_canonical_rows,
        diagnostic.duplicate_canonical_rows_removed,
    ) == (850, 850, 0, 841, 837, 4)


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

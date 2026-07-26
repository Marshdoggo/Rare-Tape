import pandas as pd
import pytest

from alt_asset_explorer.component_portfolios import PortfolioBacktestRequest, backtest_component_portfolio, overlap_report
from alt_asset_explorer.components import (
    CanonicalIndexResolver,
    ComponentDefinition,
    ResolutionContext,
    ResolvedComponent,
    resolve_components,
)


def test_canonical_sleeve_resolution_is_point_in_time_and_methodology_owned():
    series = pd.DataFrame({
        "date": ["2024-03-31", "2024-06-30", "2024-09-30"],
        "universe": "category", "category": "Books", "weighting_method": "equal_weight",
        "index_level": [100, 110, 121],
    })
    constituents = pd.DataFrame({
        "date": ["2024-03-31", "2024-03-31", "2024-06-30", "2024-06-30", "2024-09-30"],
        "universe": "category", "category": "Books", "weighting_method": "equal_weight",
        "asset_id": ["a", "b", "a", "b", "a"], "portfolio_weight": [0.5, 0.5, 0.6, 0.4, 1.0],
    })
    definition = ComponentDefinition("books", "category_index", "Books", 1.0, "Books", "equal_weight")

    resolved, = resolve_components(
        [definition], [CanonicalIndexResolver(series, constituents)], ResolutionContext(as_of_cutoff="2024-06-30")
    )

    assert isinstance(resolved, ResolvedComponent)
    assert resolved.series["date"].max() == pd.Timestamp("2024-06-30")
    assert resolved.constituents["date"].max() == pd.Timestamp("2024-06-30")
    assert resolved.methodology["resolver"] == "CanonicalIndexResolver"


def test_resolved_components_feed_accounting_and_reconcile_dynamic_overlap():
    dates = pd.to_datetime(["2024-03-31", "2024-06-30", "2024-09-30"])
    sleeve = ResolvedComponent(
        ComponentDefinition("books", "category_index", "Books", 0.75, "Books", "equal_weight"),
        pd.DataFrame({"date": dates, "index_level": [100, 110, 121]}),
        pd.DataFrame({
            "date": [dates[0], dates[0], dates[1], dates[1], dates[2]],
            "asset_id": ["a", "b", "a", "b", "b"],
            "portfolio_weight": [0.5, 0.5, 0.25, 0.75, 1.0],
        }),
    )
    direct = ResolvedComponent(
        ComponentDefinition("asset:a", "individual_asset", "A", 0.25, "a"),
        pd.DataFrame({"date": dates, "index_level": [10, 12, 15]}),
        pd.DataFrame({"date": dates, "asset_id": "a", "portfolio_weight": 1.0}),
    )

    result = backtest_component_portfolio(PortfolioBacktestRequest([sleeve, direct], rebalance_schedule="none"))

    assert result.reconciliation["reconciled"].all()
    assert result.reconciliation["reconciliation_difference"].abs().max() == pytest.approx(0)
    june = overlap_report([sleeve, direct], as_of="2024-06-30")
    assert june.set_index("asset_id").loc["a", "overlap"]
    september = overlap_report([sleeve, direct], as_of="2024-09-30")
    assert not september.set_index("asset_id").loc["a", "overlap"]


def test_resolution_requires_exactly_one_resolver():
    definition = ComponentDefinition("books", "category_index", "Books", 1.0, "Books", "equal_weight")
    with pytest.raises(ValueError, match="exactly one resolver"):
        resolve_components([definition], [])

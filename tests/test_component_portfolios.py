import pandas as pd
import pytest

from alt_asset_explorer.component_portfolios import (
    PortfolioComponent,
    normalize_component_weights,
    simulate_component_portfolio,
)


def _component(component_id, levels, weight=0.5, dates=None):
    dates = dates or ["2024-01-01", "2024-04-01", "2024-07-01"]
    return PortfolioComponent(
        component_id=component_id,
        component_type="category_index",
        label=f"{component_id.title()} Index",
        target_weight=weight,
        series=pd.DataFrame({"date": dates, "index_level": levels}),
    )


def test_single_component_matches_preexisting_normalized_index_result():
    component = _component("books", [80, 100, 120], weight=1.0)

    result = simulate_component_portfolio([component], starting_value=100, rebalance_frequency="quarterly")

    assert result.warnings == ()
    assert result.series["growth_value"].tolist() == pytest.approx([100, 125, 150])


def test_identical_half_weight_components_reproduce_same_series():
    result = simulate_component_portfolio(
        [_component("books", [100, 110, 121]), _component("watches", [100, 110, 121])],
        rebalance_frequency="none",
    )

    assert result.series["growth_value"].tolist() == pytest.approx([100, 110, 121])


def test_two_known_category_returns_combine_at_sleeve_level():
    result = simulate_component_portfolio(
        [_component("books", [100, 110, 110]), _component("watches", [100, 100, 120])],
        rebalance_frequency="none",
    )

    assert result.series["growth_value"].tolist() == pytest.approx([100, 105, 115])


def test_unequal_weights_are_applied_to_component_returns():
    result = simulate_component_portfolio(
        [_component("books", [100, 120, 120], weight=0.75), _component("watches", [100, 100, 120], weight=0.25)],
        rebalance_frequency="none",
    )

    assert result.series["growth_value"].tolist() == pytest.approx([100, 115, 120])


def test_rebalancing_restores_target_sleeve_weights():
    components = [_component("books", [100, 200, 200]), _component("watches", [100, 100, 200])]

    held = simulate_component_portfolio(components, rebalance_frequency="none")
    rebalanced = simulate_component_portfolio(components, rebalance_frequency="quarterly")

    assert held.series.iloc[-1]["growth_value"] == pytest.approx(200)
    assert rebalanced.series.iloc[-1]["growth_value"] == pytest.approx(225)
    assert rebalanced.composition["rebalance_count"].unique().tolist() == [2]


def test_weight_normalization_sums_to_one_and_invalid_weights_are_rejected():
    assert sum(normalize_component_weights({"books": 60, "watches": 30}).values()) == pytest.approx(1)
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_component_weights({"books": 1, "watches": 0})
    result = simulate_component_portfolio([_component("books", [100, 110, 120], weight=-1)])
    assert result.series.empty
    assert "greater than zero" in result.warnings[0]


def test_common_inception_and_shared_observation_policy_avoid_look_ahead_and_fill():
    books = _component("books", [100, 110, 120, 130], dates=["2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01"])
    watches = _component("watches", [50, 60, 72], dates=["2024-04-01", "2024-07-01", "2024-10-01"])

    result = simulate_component_portfolio([books, watches], rebalance_frequency="none")

    assert result.series["date"].min() == pd.Timestamp("2024-04-01")
    assert result.series["growth_value"].tolist() == pytest.approx([100, 114.5454545, 131.0909091])

    sparse_watches = _component("watches", [50, 72], dates=["2024-04-01", "2024-10-01"])
    sparse = simulate_component_portfolio([books, sparse_watches], rebalance_frequency="none")
    assert sparse.series["date"].tolist() == [pd.Timestamp("2024-04-01"), pd.Timestamp("2024-10-01")]


def test_zero_eligible_preamble_is_not_treated_as_investable_history():
    books = _component("books", [100, 110, 121], weight=0.5)
    watches = _component("watches", [100, 100, 120], weight=0.5)
    watches = PortfolioComponent(
        component_id=watches.component_id,
        component_type=watches.component_type,
        label=watches.label,
        target_weight=watches.target_weight,
        series=watches.series.assign(eligible_constituent_count=[0, 1, 1]),
    )

    result = simulate_component_portfolio([books, watches], rebalance_frequency="none")

    assert result.series["date"].tolist() == [pd.Timestamp("2024-04-01"), pd.Timestamp("2024-07-01")]
    assert result.series["growth_value"].tolist() == pytest.approx([100, 115])


def test_duplicate_components_and_non_overlapping_histories_are_flagged():
    duplicate = _component("books", [100, 110, 120])
    assert "Duplicate" in simulate_component_portfolio([duplicate, duplicate]).warnings[0]
    later = _component("watches", [100, 110], dates=["2025-01-01", "2025-04-01"])
    result = simulate_component_portfolio([duplicate, later])
    assert result.series.empty
    assert "common observation dates" in result.warnings[0]

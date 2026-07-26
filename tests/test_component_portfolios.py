import pandas as pd
import pytest

from alt_asset_explorer.component_portfolios import (
    PortfolioComponent,
    equal_component_weights,
    expand_component,
    infer_periods_per_year,
    inverse_volatility_weights,
    look_through_exposure,
    normalize_component_weights,
    portfolio_risk_metrics,
    remove_and_redistribute,
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


def test_builder_weight_controls_are_deterministic():
    assert equal_component_weights(["a", "b", "c"]) == pytest.approx({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})
    assert normalize_component_weights({"a": 60, "b": 30}) == pytest.approx({"a": 2 / 3, "b": 1 / 3})


def test_expansion_preserves_sleeve_weight_and_removal_redistributes_pro_rata():
    expanded = expand_component("category:books", {"category:books": 0.4, "category:watches": 0.6}, {"book-a": 0.75, "book-b": 0.25})
    assert expanded == pytest.approx({"category:watches": 0.6, "asset:book-a": 0.3, "asset:book-b": 0.1})
    removed = remove_and_redistribute(expanded, ["asset:book-a", "asset:book-b"], policy="pro_rata")
    assert removed == pytest.approx({"category:watches": 1.0})


def test_mixed_index_and_asset_portfolio_and_lookthrough_overlap():
    books = PortfolioComponent("category:books", "category_index", "Books Index", 0.75, pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3, freq="QS"), "index_level": [100, 110, 121]}), {"book-a": 0.5, "book-b": 0.5})
    direct = PortfolioComponent("asset:book-a", "individual_asset", "BOOK-A", 0.25, pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3, freq="QS"), "index_level": [10, 12, 15]}), {"book-a": 1.0})
    result = simulate_component_portfolio([books, direct], rebalance_frequency="none")
    assert result.series.iloc[-1]["growth_value"] == pytest.approx(128.25)
    assert result.series.filter(like="contribution_").iloc[1:].sum().sum() == pytest.approx(result.series.iloc[-1]["cumulative_return"])
    exposure = look_through_exposure([books, direct])
    assert exposure["total_weight"].sum() == pytest.approx(1)
    assert exposure.set_index("asset_id").loc["book-a", "overlap"]


def test_frequency_aware_risk_metrics_and_drawdown_duration():
    dates = pd.date_range("2023-03-31", periods=6, freq="QE")
    returns = [0.0, 0.10, -0.05, -0.05, 0.12, 0.02]
    levels = 100 * pd.Series([1 + value for value in returns]).cumprod()
    series = pd.DataFrame({"date": dates, "period_return": returns, "growth_value": levels})
    metrics = portfolio_risk_metrics(series)
    expected = pd.Series(returns[1:]).std(ddof=1) * 2
    assert infer_periods_per_year(dates) == 4
    assert metrics["annualized_volatility"] == pytest.approx(expected)
    assert metrics["sharpe_ratio"] == pytest.approx(pd.Series(returns[1:]).mean() / pd.Series(returns[1:]).std(ddof=1) * 2)
    downside = pd.Series(returns[1:])[pd.Series(returns[1:]) < 0]
    expected_downside = ((downside.pow(2).sum() / 5) ** 0.5) * 2
    assert metrics["downside_deviation"] == pytest.approx(expected_downside)
    assert metrics["maximum_drawdown_duration_periods"] == 2


def test_inverse_volatility_is_long_only_and_uses_common_sample():
    dates = pd.date_range("2023-03-31", periods=6, freq="QE")
    frames = {
        "a": pd.DataFrame({"date": dates, "index_level": [100, 110, 100, 115, 105, 120]}),
        "b": pd.DataFrame({"date": dates, "index_level": [100, 102, 101, 103, 102, 104]}),
    }
    weights = inverse_volatility_weights(frames, minimum_observations=3)
    assert sum(weights.values()) == pytest.approx(1)
    assert all(value > 0 for value in weights.values())
    with pytest.raises(ValueError, match="shared levels"):
        inverse_volatility_weights({"a": frames["a"].iloc[:3], "b": frames["b"].iloc[-3:]}, minimum_observations=3)

import math

import pandas as pd

from alt_asset_explorer.integer_replication import (
    annualized_tracking_error,
    budget_allocation,
    homepage_summary,
    minimum_capital_for_tolerance,
    normalize_target_weights,
    one_share_each_capital,
    select_prices_asof,
    simple_anchor_allocation,
    simulate_buy_and_hold,
    weight_error_metrics,
)


def fixture_history():
    return pd.DataFrame(
        [
            ("a", "2020-01-01", 10.0, 100.0), ("a", "2020-04-01", 12.0, 120.0), ("a", "2020-07-01", 11.0, 110.0),
            ("b", "2020-02-01", 25.0, 250.0), ("b", "2020-04-01", 20.0, 200.0), ("b", "2020-07-01", 30.0, 300.0),
        ], columns=["asset_id", "date", "last", "market_cap_usd"]
    )


def test_one_share_anchor_weights_and_integer_constraints():
    prices = pd.Series({"a": 10.0, "b": 25.0})
    assert one_share_each_capital(prices) == 35.0
    result = simple_anchor_allocation(prices)
    assert result.quantities.to_dict() == {"a": 2, "b": 1}
    assert result.invested == 45.0
    assert all(isinstance(value, int) for value in result.quantities.tolist())
    assert math.isclose(result.metrics["absolute"], 1 / 9)


def test_budget_feasibility_allocation_and_residual_cash():
    prices = pd.Series({"a": 10.0, "b": 25.0})
    assert not budget_allocation(prices, 34.0, require_all=True).feasible
    result = budget_allocation(prices, 60.0, require_all=True, reserve=5.0)
    assert result.feasible
    assert (result.quantities >= 1).all()
    assert result.invested <= 55.0
    assert result.residual_cash == 60.0 - result.invested


def test_minimum_capital_search_meets_tolerance_and_improves_error():
    prices = pd.Series({"a": 10.0, "b": 25.0})
    loose = minimum_capital_for_tolerance(prices, 0.06, metric="maximum")
    tight = minimum_capital_for_tolerance(prices, 0.01, metric="maximum")
    assert loose.feasible and loose.metrics["maximum"] <= 0.06
    assert tight.feasible and tight.metrics["maximum"] <= 0.01
    assert tight.invested >= loose.invested


def test_asof_selection_has_no_lookahead_and_common_universe_delays_start():
    history = fixture_history()
    launch_rows, launch_date = select_prices_asof(history, ["a", "b"], "2020-01-15", mode="launch_aware")
    assert launch_date == pd.Timestamp("2020-01-15")
    assert launch_rows["asset_id"].tolist() == ["a"]
    common_rows, common_date = select_prices_asof(history, ["a", "b"], "2020-01-15", mode="common")
    assert common_date == pd.Timestamp("2020-02-01")
    assert common_rows.set_index("asset_id").loc["a", "date"] == pd.Timestamp("2020-01-01")
    assert common_rows.set_index("asset_id").loc["b", "date"] == pd.Timestamp("2020-02-01")


def test_missing_prices_dynamic_assets_and_exited_metadata():
    history = fixture_history()
    rows, _ = select_prices_asof(history, ["a", "b", "new"], "2020-03-01", mode="launch_aware")
    assert set(rows["asset_id"]) == {"a", "b"}
    extended = pd.concat([history, pd.DataFrame([{"asset_id": "new", "date": "2020-02-15", "last": 5.0}])], ignore_index=True)
    rows, _ = select_prices_asof(extended, ["a", "b", "new"], "2020-03-01", mode="launch_aware")
    assert set(rows["asset_id"]) == {"a", "b", "new"}
    metadata = pd.DataFrame([{"asset_id":"a","status":"exited"},{"asset_id":"b","status":"trading"}])
    allocation = budget_allocation(pd.Series({"a":10.0,"b":25.0}), 60.0)
    simulation = simulate_buy_and_hold(history, allocation, normalize_target_weights(None,["a","b"]), start_date="2020-02-01", metadata=metadata)
    assert simulation.constituents.set_index("asset_id").loc["a","status"] == "exited"


def test_pnl_cash_drawdown_and_tracking_error_reconcile():
    prices = pd.Series({"a":10.0,"b":25.0}); allocation=budget_allocation(prices,60.0)
    result=simulate_buy_and_hold(fixture_history(),allocation,normalize_target_weights(None,prices.index),start_date="2020-02-01")
    assert result.metrics["latest_value"] == result.history.iloc[-1]["portfolio_value"]
    assert result.metrics["pnl"] == result.metrics["latest_value"] - 60.0
    assert (result.history["cash"] == allocation.residual_cash).all()
    assert result.metrics["maximum_drawdown"] <= 0
    assert not math.isnan(result.metrics["annualized_tracking_error"])
    assert math.isclose(annualized_tracking_error(pd.Series([100,110,121]),pd.Series([100,105,110]),pd.date_range("2020",periods=3,freq="QE")), 0.003367175148507357, rel_tol=1e-9)


def test_homepage_summary_uses_same_public_lab_calculation():
    assets=pd.DataFrame([{"asset_id":"a","status":"trading"},{"asset_id":"b","status":"trading"},{"asset_id":"x","status":"exited"}])
    summary=homepage_summary(assets,fixture_history(),tolerance=.06)
    prices=pd.Series({"a":11.0,"b":30.0}); expected=minimum_capital_for_tolerance(prices,.06)
    assert summary["constituent_count"] == 2
    assert summary["minimum_capital"] == expected.invested


def test_total_portfolio_weights_include_cash_in_denominator():
    prices=pd.Series({"a":10.0,"b":25.0}); q=pd.Series({"a":1,"b":1})
    metrics=weight_error_metrics(prices,q,normalize_target_weights(None,prices.index),denominator=50)
    assert metrics["cash_weight"] == .3

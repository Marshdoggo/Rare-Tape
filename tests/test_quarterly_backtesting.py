import math

import pandas as pd
import pytest

from alt_asset_explorer.component_portfolios import PortfolioComponent, simulate_component_portfolio
from alt_asset_explorer.quarterly_backtesting import (
    QuarterlyBacktestRequest,
    QuarterlyStrategy,
    ThresholdRule,
    run_quarterly_backtest,
)


DATES = pd.to_datetime(["2024-03-31", "2024-06-30", "2024-09-30"])


def component(component_id: str, levels: list[float], weight: float = 0.5, dates=DATES) -> PortfolioComponent:
    return PortfolioComponent(
        component_id=component_id,
        component_type="individual_asset",
        label=component_id.upper(),
        target_weight=weight,
        series=pd.DataFrame({"date": dates, "index_level": levels, "available_at": dates}),
    )


def run(components, strategy=QuarterlyStrategy()):
    return run_quarterly_backtest(QuarterlyBacktestRequest(components=components, strategy=strategy))


def test_no_rules_matches_existing_buy_and_hold_simulator():
    components = [component("a", [100, 120, 108]), component("b", [100, 100, 110])]
    result = run(components)
    existing = simulate_component_portfolio(components, rebalance_frequency="none")

    assert result.strategy_series["growth_value"].tolist() == pytest.approx(existing.series["growth_value"])
    assert result.baseline.series["growth_value"].tolist() == pytest.approx(existing.series["growth_value"])


def test_quarterly_original_weight_rebalance_is_mathematically_correct():
    components = [component("a", [100, 200, 200]), component("b", [100, 100, 200])]
    result = run(components, QuarterlyStrategy(rebalance="original_weights"))

    assert result.strategy_series.iloc[-1]["growth_value"] == pytest.approx(225)
    q2 = result.positions[result.positions["date"].eq(pd.Timestamp("2024-06-30"))]
    assert q2.set_index("component_id")["weight_after"].to_dict() == pytest.approx({"a": 0.5, "b": 0.5})


def test_profit_signal_is_applied_after_gain_and_changes_only_next_holding_period():
    strategy = QuarterlyStrategy(profit_taking=ThresholdRule(True, 0.15, 0.50, "cash"))
    result = run([component("a", [100, 120, 120]), component("b", [100, 100, 100])], strategy)

    assert result.strategy_series["growth_value"].tolist()[:2] == pytest.approx([100, 110])
    event = result.events.iloc[0]
    assert event["date"] == pd.Timestamp("2024-06-30")
    assert event["decision_date"] == pd.Timestamp("2024-06-30")
    assert event["component_id"] == "a"
    assert result.cash_history.iloc[1]["cash_balance"] == pytest.approx(30)


def test_profit_rule_does_not_trigger_below_threshold():
    strategy = QuarterlyStrategy(profit_taking=ThresholdRule(True, 0.15, 0.50, "cash"))
    result = run([component("a", [100, 114, 120]), component("b", [100, 100, 100])], strategy)
    assert result.events.empty
    assert set(result.cash_history["cash_balance"]) == {0.0}


def test_loss_rule_reduces_only_after_completed_quarter():
    strategy = QuarterlyStrategy(loss_rule=ThresholdRule(True, 0.20, 1.0, "cash"))
    result = run([component("a", [100, 75, 150]), component("b", [100, 100, 100])], strategy)

    assert result.strategy_series.iloc[1]["growth_value"] == pytest.approx(87.5)
    assert result.events.iloc[0]["rule"] == "quarterly_loss"
    assert result.events.iloc[0]["date"] == pd.Timestamp("2024-06-30")
    assert result.positions.query("component_id == 'a'").iloc[1]["position_value_after"] == 0
    assert result.strategy_series.iloc[2]["growth_value"] == pytest.approx(87.5)


def test_half_reduction_and_cash_proceeds_reconcile():
    strategy = QuarterlyStrategy(profit_taking=ThresholdRule(True, 0.15, 0.50, "cash"))
    result = run([component("a", [100, 120, 120], weight=0.6), component("b", [100, 100, 100], weight=0.4)], strategy)
    q2 = result.positions[result.positions["date"].eq(pd.Timestamp("2024-06-30"))].set_index("component_id")

    assert q2.loc["a", "position_value_before"] == pytest.approx(72)
    assert q2.loc["a", "position_value_after"] == pytest.approx(36)
    assert result.cash_history.iloc[1]["cash_balance"] == pytest.approx(36)


def test_redistributed_proceeds_are_not_lost():
    strategy = QuarterlyStrategy(profit_taking=ThresholdRule(True, 0.15, 0.50, "remaining_holdings"))
    result = run([component("a", [100, 120, 120]), component("b", [100, 100, 100])], strategy)
    q2 = result.positions[result.positions["date"].eq(pd.Timestamp("2024-06-30"))].set_index("component_id")

    assert q2.loc["a", "position_value_after"] == pytest.approx(30)
    assert q2.loc["b", "position_value_after"] == pytest.approx(80)
    assert result.cash_history.iloc[1]["cash_balance"] == 0


def test_cash_has_zero_return_and_remains_in_total_value():
    strategy = QuarterlyStrategy(profit_taking=ThresholdRule(True, 0.15, 1.0, "cash"))
    result = run([component("a", [100, 120, 240]), component("b", [100, 100, 100])], strategy)

    assert result.cash_history.iloc[1]["cash_balance"] == pytest.approx(60)
    assert result.cash_history.iloc[2]["cash_balance"] == pytest.approx(60)
    assert result.strategy_series.iloc[-1]["growth_value"] == pytest.approx(110)


def test_missing_quarter_is_not_filled_or_used_as_quarterly_signal():
    sparse_dates = pd.to_datetime(["2024-03-31", "2024-09-30"])
    strategy = QuarterlyStrategy(profit_taking=ThresholdRule(True, 0.15, 0.50, "cash"))
    result = run([
        component("a", [100, 130], dates=sparse_dates),
        component("b", [100, 100], dates=sparse_dates),
    ], strategy)

    assert result.strategy_series["date"].tolist() == list(sparse_dates)
    assert result.strategy_series.iloc[1]["elapsed_quarters"] == 2
    assert math.isnan(result.strategy_series.iloc[1]["return_a"])
    assert result.events.empty


def test_actual_availability_date_is_retained_for_signal_audit():
    delayed = component("a", [100, 120, 120])
    delayed = PortfolioComponent(
        delayed.component_id, delayed.component_type, delayed.label, delayed.target_weight,
        delayed.series.assign(available_at=pd.to_datetime(["2024-03-31", "2024-07-02", "2024-09-30"])),
    )
    strategy = QuarterlyStrategy(profit_taking=ThresholdRule(True, 0.15, 0.50, "cash"))
    result = run([delayed, component("b", [100, 100, 100])], strategy)

    assert result.events.iloc[0]["date"] == pd.Timestamp("2024-06-30")
    assert result.events.iloc[0]["decision_date"] == pd.Timestamp("2024-07-02")


def test_final_value_reconciles_to_positions_and_cash():
    strategy = QuarterlyStrategy(
        rebalance="original_weights",
        profit_taking=ThresholdRule(True, 0.15, 0.25, "cash"),
        loss_rule=ThresholdRule(True, 0.10, 0.50, "target_weights"),
    )
    result = run([component("a", [100, 120, 90]), component("b", [100, 90, 110])], strategy)
    final_date = result.strategy_series.iloc[-1]["date"]
    positions = result.positions[result.positions["date"].eq(final_date)]["position_value_after"].sum()
    cash = result.cash_history[result.cash_history["date"].eq(final_date)]["cash_balance"].iloc[0]

    assert positions + cash == pytest.approx(result.strategy_series.iloc[-1]["growth_value"])
    assert result.summary_metrics["ending_value"] == pytest.approx(positions + cash)

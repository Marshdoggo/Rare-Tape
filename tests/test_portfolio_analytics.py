import pandas as pd
import pytest

from alt_asset_explorer.portfolio_analytics import (
    advanced_attribution_is_available,
    contribution_history,
    drawdown_history,
    portfolio_risk_metrics,
)


def test_drawdown_and_metrics_share_deterministic_growth_arithmetic():
    series = pd.DataFrame({
        "date": pd.date_range("2024-03-31", periods=4, freq="QE"),
        "growth_value": [100.0, 120.0, 90.0, 108.0],
        "period_return": [0.0, 0.2, -0.25, 0.2],
    })
    history = drawdown_history(series)
    metrics = portfolio_risk_metrics(series)
    assert history["drawdown"].tolist() == pytest.approx([0.0, 0.0, -0.25, -0.1])
    assert metrics["maximum_drawdown"] == pytest.approx(-0.25)


def test_contribution_history_reconciles_every_period_and_cumulatively():
    series = pd.DataFrame({
        "date": pd.to_datetime(["2024-03-31", "2024-06-30", "2024-09-30"]),
        "period_return": [0.0, 0.04, -0.01],
        "contribution_a": [0.0, 0.03, -0.02],
        "contribution_b": [0.0, 0.01, 0.01],
    })
    history = contribution_history(series, {"a": "A", "b": "B"})
    period = history.groupby("date")["period_contribution"].sum()
    assert period.tolist() == pytest.approx(series["period_return"].tolist())
    assert history.groupby("component_id")["period_contribution"].sum().to_dict() == pytest.approx({"a": 0.01, "b": 0.02})


def test_advanced_attribution_requires_named_reconciliation_fixtures():
    assert not advanced_attribution_is_available()
    assert advanced_attribution_is_available(["two_sleeve_exact_reconciliation_v1"])

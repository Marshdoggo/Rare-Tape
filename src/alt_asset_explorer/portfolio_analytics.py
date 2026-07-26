"""Deterministic analytics for component-portfolio accounting results.

This module owns derived metrics and histories.  It deliberately stops at
arithmetic sleeve contribution; risk contribution and advanced attribution
must not be published until committed deterministic reconciliation fixtures
exist for those methods.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import pandas as pd


def infer_periods_per_year(dates: Sequence[object]) -> int:
    """Infer a conventional annualization factor from median spacing."""
    index = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="coerce")).dropna().sort_values().unique()
    if len(index) < 2:
        return 1
    median_days = float(pd.Series(index).diff().dt.total_seconds().dropna().median() / 86400)
    if median_days <= 10:
        return 52
    if median_days <= 45:
        return 12
    if median_days <= 120:
        return 4
    return 1


def drawdown_history(series: pd.DataFrame) -> pd.DataFrame:
    """Return peak and drawdown evidence from an accounted growth series."""
    columns = ["date", "growth_value", "peak_value", "drawdown"]
    if series.empty or not {"date", "growth_value"}.issubset(series):
        return pd.DataFrame(columns=columns)
    result = series[["date", "growth_value"]].copy()
    result["peak_value"] = pd.to_numeric(result["growth_value"], errors="coerce").cummax()
    result["drawdown"] = result["growth_value"] / result["peak_value"] - 1
    return result[columns]


def contribution_history(series: pd.DataFrame, component_labels: Mapping[str, str]) -> pd.DataFrame:
    """Return long-form arithmetic sleeve contributions that reconcile by date."""
    columns = ["date", "component_id", "component", "period_contribution", "cumulative_contribution"]
    rows = []
    raw_columns = [f"contribution_{component_id}" for component_id in component_labels]
    raw = series.reindex(columns=raw_columns).apply(pd.to_numeric, errors="coerce").fillna(0.0)
    raw_total = raw.sum(axis=1)
    period_return = pd.to_numeric(series.get("period_return", pd.Series(0.0, index=series.index)), errors="coerce").fillna(0.0)
    # Accounting stores contribution to growth since inception. Rescale each
    # row by the common denominator so this public history reconciles to the
    # portfolio's period return while preserving each sleeve's share of P&L.
    scale = period_return.div(raw_total.where(raw_total.abs() > 1e-15, 1.0))
    period_contributions = raw.mul(scale, axis=0)
    period_contributions.loc[raw_total.abs() <= 1e-15, :] = 0.0
    for component_id, label in component_labels.items():
        column = f"contribution_{component_id}"
        if column not in series:
            continue
        values = period_contributions[column]
        for date, value, cumulative in zip(series["date"], values, values.cumsum()):
            rows.append({"date": date, "component_id": component_id, "component": label,
                         "period_contribution": float(value), "cumulative_contribution": float(cumulative)})
    return pd.DataFrame(rows, columns=columns)


def portfolio_risk_metrics(series: pd.DataFrame, *, annual_risk_free_rate: float = 0.0) -> dict[str, object]:
    """Calculate frequency-aware historical risk and drawdown statistics."""
    if series.empty or not {"date", "period_return"}.issubset(series):
        return {}
    frame = series[["date", "period_return"]].copy().sort_values("date")
    returns = pd.to_numeric(frame["period_return"], errors="coerce").dropna().iloc[1:]
    periods = infer_periods_per_year(frame["date"])
    if returns.empty:
        return {"periods_per_year": periods}
    annual_return = float((1 + returns).prod() ** (periods / len(returns)) - 1)
    volatility = float(returns.std(ddof=1) * math.sqrt(periods)) if len(returns) > 1 else 0.0
    periodic_rf = (1 + annual_risk_free_rate) ** (1 / periods) - 1
    excess = returns - periodic_rf
    sharpe = float(excess.mean() / returns.std(ddof=1) * math.sqrt(periods)) if len(returns) > 1 and returns.std(ddof=1) > 0 else math.nan
    downside = returns[returns < periodic_rf] - periodic_rf
    downside_deviation = float(math.sqrt(downside.pow(2).sum() / len(returns)) * math.sqrt(periods))
    sortino = float((returns.mean() - periodic_rf) * periods / downside_deviation) if downside_deviation > 0 else math.nan
    drawdowns = drawdown_history(frame.assign(growth_value=(1 + frame["period_return"]).cumprod()))["drawdown"].iloc[1:]
    max_drawdown = float(drawdowns.min())
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else math.nan
    duration = current = 0
    for value in drawdowns:
        current = current + 1 if value < 0 else 0
        duration = max(duration, current)
    trough = int(drawdowns.values.argmin())
    growth = (1 + returns).cumprod()
    peak = growth.iloc[: trough + 1].idxmax()
    recovered = growth.iloc[trough + 1:][lambda values: values >= growth.loc[peak]]
    recovery_date = frame.loc[recovered.index[0], "date"] if not recovered.empty else None
    return {"periods_per_year": periods, "annualized_return": annual_return,
            "annualized_volatility": volatility, "sharpe_ratio": sharpe, "sortino_ratio": sortino,
            "calmar_ratio": calmar, "downside_deviation": downside_deviation,
            "best_period_return": float(returns.max()), "worst_period_return": float(returns.min()),
            "positive_period_percentage": float((returns > 0).mean()), "maximum_drawdown": max_drawdown,
            "maximum_drawdown_duration_periods": duration, "recovery_date": recovery_date}


def advanced_attribution_is_available(reconciliation_fixture_ids: Sequence[str] = ()) -> bool:
    """Gate advanced attribution on explicit deterministic fixture identifiers."""
    return bool(tuple(reconciliation_fixture_ids))

"""Sequential, no-fill quarterly strategy backtesting for resolved components.

The engine deliberately operates at the top-level component boundary used by
``component_portfolios``.  A component may be a canonical index sleeve or one
direct asset, but it must expose observed levels; this module never invents an
intermediate price.  Signals observed for quarter T are applied only after the
T observation and therefore affect the T -> T+1 holding period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Literal, Mapping, Sequence

import pandas as pd

from alt_asset_explorer.component_portfolios import (
    PortfolioBacktestRequest,
    PortfolioBacktestResult,
    PortfolioComponent,
    backtest_component_portfolio,
    normalize_component_weights,
)
from alt_asset_explorer.components import ResolvedComponent
from alt_asset_explorer.portfolio_analytics import drawdown_history


ProceedsDestination = Literal["cash", "remaining_holdings", "target_weights"]
QuarterlyRebalance = Literal["none", "equal_weight", "original_weights"]


@dataclass(frozen=True)
class ThresholdRule:
    """A quarter-end return rule that reduces the signaled position."""

    enabled: bool = False
    threshold: float = 0.15
    reduction: float = 0.50
    proceeds: ProceedsDestination = "cash"

    def __post_init__(self) -> None:
        if self.threshold < 0:
            raise ValueError("Rule thresholds cannot be negative.")
        if not 0 <= self.reduction <= 1:
            raise ValueError("Position reduction must be between 0 and 1.")


@dataclass(frozen=True)
class QuarterlyStrategy:
    """Configurable strategy overlays evaluated once per common quarter."""

    rebalance: QuarterlyRebalance = "none"
    profit_taking: ThresholdRule = field(default_factory=ThresholdRule)
    loss_rule: ThresholdRule = field(default_factory=lambda: ThresholdRule(threshold=0.20, reduction=1.0))


@dataclass(frozen=True)
class QuarterlyBacktestRequest:
    components: Sequence[ResolvedComponent | PortfolioComponent]
    starting_value: float = 100.0
    strategy: QuarterlyStrategy = field(default_factory=QuarterlyStrategy)
    annual_risk_free_rate: float = 0.0
    as_of_cutoff: pd.Timestamp | str | None = None


@dataclass(frozen=True)
class QuarterlyBacktestResult:
    strategy_series: pd.DataFrame
    baseline: PortfolioBacktestResult
    positions: pd.DataFrame
    events: pd.DataFrame
    trades: pd.DataFrame
    turnover_history: pd.DataFrame
    cash_history: pd.DataFrame
    drawdown_history: pd.DataFrame
    summary_metrics: Mapping[str, object]
    methodology: Mapping[str, object]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _resolved(component: ResolvedComponent | PortfolioComponent) -> ResolvedComponent:
    return component if isinstance(component, ResolvedComponent) else component.resolved()


def _quarterly_component(component: ResolvedComponent, cutoff: object | None) -> ResolvedComponent:
    """Select one actually available level per canonical quarter, without fill."""

    if component.series.empty or not {"date", "index_level"}.issubset(component.series):
        clean = pd.DataFrame(columns=["date", "index_level", "available_at"])
    else:
        clean = component.series.copy()
        clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.normalize()
        clean["index_level"] = pd.to_numeric(clean["index_level"], errors="coerce")
        if "available_at" in clean:
            clean["available_at"] = pd.to_datetime(clean["available_at"], errors="coerce").dt.normalize()
        else:
            clean["available_at"] = clean["date"]
        clean = clean.dropna(subset=["date", "available_at", "index_level"])
        clean = clean[clean["index_level"] > 0]
        if cutoff is not None:
            clean = clean[clean["available_at"] <= pd.Timestamp(cutoff).normalize()]
        clean["date"] = clean["date"].dt.to_period("Q").dt.end_time.dt.normalize()
        clean = clean.sort_values(["date", "available_at"], kind="stable").drop_duplicates("date", keep="last")
        clean = clean[["date", "index_level", "available_at"]].reset_index(drop=True)
    return ResolvedComponent(
        definition=component.definition,
        series=clean,
        constituents=component.constituents,
        methodology=dict(component.methodology) | {"strategy_frequency": "quarterly", "quarterly_selection": "last_available_level_no_fill"},
        warnings=component.warnings,
    )


def prepare_quarterly_components(
    components: Sequence[ResolvedComponent | PortfolioComponent],
    *,
    as_of_cutoff: object | None = None,
) -> tuple[ResolvedComponent, ...]:
    """Public adapter shared by the baseline and sequential strategy engine."""

    return tuple(_quarterly_component(_resolved(component), as_of_cutoff) for component in components)


def _aligned_levels(components: Sequence[ResolvedComponent]) -> pd.DataFrame:
    aligned: pd.DataFrame | None = None
    for component in components:
        frame = component.series.rename(
            columns={"index_level": component.component_id, "available_at": f"available_at_{component.component_id}"}
        )
        frame = frame[["date", component.component_id, f"available_at_{component.component_id}"]]
        aligned = frame if aligned is None else aligned.merge(frame, on="date", how="inner", validate="one_to_one")
    if aligned is None:
        return pd.DataFrame()
    aligned = aligned.sort_values("date").reset_index(drop=True)
    availability = [column for column in aligned if column.startswith("available_at_")]
    aligned["decision_date"] = aligned[availability].max(axis=1)
    aligned["decision_date"] = aligned[["date", "decision_date"]].max(axis=1)
    return aligned


def _destination_allocations(
    proceeds: float,
    destination: ProceedsDestination,
    values: Mapping[str, float],
    target_weights: Mapping[str, float],
    excluded: set[str],
) -> tuple[dict[str, float], float]:
    recipients = [component_id for component_id in values if component_id not in excluded]
    if proceeds <= 0 or destination == "cash" or not recipients:
        return {}, proceeds
    if destination == "target_weights":
        raw = {component_id: target_weights[component_id] for component_id in recipients}
    else:
        raw = {component_id: max(values[component_id], 0.0) for component_id in recipients}
    total = sum(raw.values())
    if total <= 0:
        return {}, proceeds
    return ({component_id: proceeds * weight / total for component_id, weight in raw.items()}, 0.0)


def quarterly_performance_metrics(series: pd.DataFrame) -> dict[str, object]:
    """Return metrics that do not misstate a multi-quarter gap as one quarter."""

    if series.empty or not {"date", "growth_value", "period_return"}.issubset(series):
        return {}
    frame = series[["date", "growth_value", "period_return"]].copy().sort_values("date").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["growth_value"] = pd.to_numeric(frame["growth_value"], errors="coerce")
    frame["period_return"] = pd.to_numeric(frame["period_return"], errors="coerce")
    quarters = frame["date"].dt.to_period("Q").astype("int64")
    consecutive = quarters.diff().eq(1)
    quarterly_returns = frame.loc[consecutive, "period_return"].dropna()
    start, end = frame.iloc[0], frame.iloc[-1]
    years = max((end["date"] - start["date"]).days / 365.25, 0.0)
    cagr = (float(end["growth_value"]) / float(start["growth_value"])) ** (1 / years) - 1 if years > 0 else math.nan
    volatility = float(quarterly_returns.std(ddof=1) * 2) if len(quarterly_returns) > 1 else 0.0
    drawdowns = drawdown_history(frame)
    return {
        "periods_per_year": 4,
        "annualized_return": cagr,
        "annualized_volatility": volatility,
        "maximum_drawdown": float(drawdowns["drawdown"].min()) if not drawdowns.empty else math.nan,
        "best_period_return": float(quarterly_returns.max()) if not quarterly_returns.empty else math.nan,
        "worst_period_return": float(quarterly_returns.min()) if not quarterly_returns.empty else math.nan,
        "observed_quarter_count": int(len(quarterly_returns)),
    }


def run_quarterly_backtest(request: QuarterlyBacktestRequest) -> QuarterlyBacktestResult:
    """Run a common-history quarterly strategy and an equivalent buy-and-hold baseline."""

    components = prepare_quarterly_components(request.components, as_of_cutoff=request.as_of_cutoff)
    empty = pd.DataFrame()
    baseline = backtest_component_portfolio(PortfolioBacktestRequest(
        components=components,
        starting_value=request.starting_value,
        rebalance_schedule="none",
        annual_risk_free_rate=request.annual_risk_free_rate,
        as_of_cutoff=request.as_of_cutoff,
    ))
    errors: list[str] = []
    if request.starting_value <= 0:
        errors.append("Starting investment must be greater than zero.")
    ids = [component.component_id for component in components]
    if not ids:
        errors.append("Select at least one portfolio component.")
    elif len(ids) != len(set(ids)):
        errors.append("Duplicate portfolio components are not allowed.")
    short = [component.label for component in components if len(component.series) < 2]
    if short:
        errors.append("Components need at least two quarterly observations: " + ", ".join(short))
    aligned = _aligned_levels(components)
    if len(aligned) < 2:
        errors.append("Selected components do not have at least two common quarterly observations.")
    try:
        original_weights = normalize_component_weights({component.component_id: component.target_weight for component in components}) if components else {}
    except ValueError as exc:
        errors.append(str(exc))
        original_weights = {}
    methodology = {
        "frequency": "quarterly",
        "alignment": "common_quarter_intersection",
        "missing_observations": "drop_quarter_no_fill",
        "signal_timing": "quarter_T_signal_trades_after_observation_for_T_to_T_plus_1",
        "decision_date": "later_of_canonical_quarter_end_or_latest_component_availability",
        "cash_return": 0.0,
        "periodic_rebalance": request.strategy.rebalance,
        "profit_taking": request.strategy.profit_taking.__dict__,
        "loss_rule": request.strategy.loss_rule.__dict__,
    }
    if errors:
        return QuarterlyBacktestResult(empty, baseline, empty, empty, empty, empty, empty, empty, {}, methodology,
                                       warnings=tuple(baseline.warnings), errors=tuple(dict.fromkeys(errors)))

    labels = {component.component_id: component.label for component in components}
    first = aligned.iloc[0]
    units = {component_id: request.starting_value * original_weights[component_id] / float(first[component_id]) for component_id in ids}
    cash = 0.0
    prior_total: float | None = None
    prior_prices: dict[str, float] | None = None
    series_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    turnover_rows: list[dict[str, object]] = []
    cash_rows: list[dict[str, object]] = []

    for row_number, observation in aligned.iterrows():
        date = pd.Timestamp(observation["date"])
        decision_date = pd.Timestamp(observation["decision_date"])
        prices = {component_id: float(observation[component_id]) for component_id in ids}
        values = {component_id: units.get(component_id, 0.0) * prices[component_id] for component_id in ids}
        pre_trade_values = dict(values)
        total = float(sum(values.values()) + cash)
        period_return = 0.0 if prior_total is None else total / prior_total - 1
        elapsed_quarters = 0 if row_number == 0 else int(date.to_period("Q").ordinal - pd.Timestamp(aligned.iloc[row_number - 1]["date"]).to_period("Q").ordinal)
        component_returns = {
            component_id: (0.0 if prior_prices is None else
                           prices[component_id] / prior_prices[component_id] - 1 if elapsed_quarters == 1 else math.nan)
            for component_id in ids
        }
        cash_before = cash
        reasons: dict[str, list[str]] = {component_id: [] for component_id in ids}

        if row_number > 0 and request.strategy.rebalance != "none":
            targets = ({component_id: 1 / len(ids) for component_id in ids}
                       if request.strategy.rebalance == "equal_weight" else original_weights)
            values = {component_id: total * targets[component_id] for component_id in ids}
            cash = 0.0
            for component_id in ids:
                reasons[component_id].append(f"quarterly_{request.strategy.rebalance}_rebalance")

        triggered_by_destination: dict[ProceedsDestination, set[str]] = {}
        proceeds_by_destination: dict[ProceedsDestination, float] = {}
        if row_number > 0 and elapsed_quarters == 1:
            for component_id in ids:
                quarter_return = component_returns[component_id]
                selected_rule: tuple[str, ThresholdRule] | None = None
                if request.strategy.profit_taking.enabled and quarter_return > request.strategy.profit_taking.threshold:
                    selected_rule = ("profit_taking", request.strategy.profit_taking)
                elif request.strategy.loss_rule.enabled and quarter_return < -request.strategy.loss_rule.threshold:
                    selected_rule = ("quarterly_loss", request.strategy.loss_rule)
                if selected_rule is None:
                    continue
                rule_name, rule = selected_rule
                value_before_rule = values[component_id]
                sale = value_before_rule * rule.reduction
                values[component_id] -= sale
                triggered_by_destination.setdefault(rule.proceeds, set()).add(component_id)
                proceeds_by_destination[rule.proceeds] = proceeds_by_destination.get(rule.proceeds, 0.0) + sale
                reasons[component_id].append(rule_name)
                event_rows.append({
                    "date": date, "decision_date": decision_date, "quarter": str(date.to_period("Q")),
                    "component_id": component_id, "component": labels[component_id],
                    "quarterly_return": quarter_return, "rule": rule_name,
                    "threshold": rule.threshold, "reduction": rule.reduction,
                    "proceeds_destination": rule.proceeds, "sale_value": sale,
                    "weight_before": value_before_rule / total if total else 0.0,
                })

        all_triggered = set().union(*triggered_by_destination.values()) if triggered_by_destination else set()
        for destination, proceeds in proceeds_by_destination.items():
            additions, cash_addition = _destination_allocations(
                proceeds, destination, values, original_weights, all_triggered
            )
            for component_id, addition in additions.items():
                values[component_id] += addition
                reasons[component_id].append(f"receive_{destination}_proceeds")
            cash += cash_addition

        for component_id in ids:
            units[component_id] = values[component_id] / prices[component_id]
        deltas = {component_id: values[component_id] - pre_trade_values[component_id] for component_id in ids}
        cash_delta = cash - cash_before
        turnover = 0.5 * (sum(abs(value) for value in deltas.values()) + abs(cash_delta)) / total if total else 0.0
        traded = any(abs(value) > 1e-12 for value in deltas.values()) or abs(cash_delta) > 1e-12
        if traded:
            turnover_rows.append({"date": date, "decision_date": decision_date, "turnover": turnover,
                                  "traded_value": turnover * total})
            for component_id in ids:
                if abs(deltas[component_id]) > 1e-12:
                    trade_rows.append({
                        "date": date, "decision_date": decision_date, "component_id": component_id,
                        "component": labels[component_id], "trade_value": deltas[component_id],
                        "action": "Buy" if deltas[component_id] > 0 else "Sell",
                        "reason": "; ".join(reasons[component_id]),
                    })

        for event in event_rows:
            if event["date"] == date and "weight_after" not in event:
                event["weight_after"] = values[str(event["component_id"])] / total if total else 0.0

        for component_id in ids:
            position_rows.append({
                "date": date, "decision_date": decision_date, "quarter": str(date.to_period("Q")),
                "component_id": component_id, "component": labels[component_id],
                "quarterly_return": component_returns[component_id],
                "position_value_before": pre_trade_values[component_id],
                "position_value_after": values[component_id],
                "weight_before": pre_trade_values[component_id] / total if total else 0.0,
                "weight_after": values[component_id] / total if total else 0.0,
            })
        cash_rows.append({"date": date, "decision_date": decision_date, "cash_balance": cash,
                          "cash_weight": cash / total if total else 0.0, "cash_return": 0.0})
        series_rows.append({
            "date": date, "decision_date": decision_date, "growth_value": total,
            "period_return": period_return, "cumulative_return": total / request.starting_value - 1,
            "rebalance_flag": traded, "cash_value": cash, "elapsed_quarters": elapsed_quarters,
            **{f"value_{component_id}": values[component_id] for component_id in ids},
            **{f"return_{component_id}": component_returns[component_id] for component_id in ids},
        })
        prior_total = total
        prior_prices = prices

    strategy_series = pd.DataFrame(series_rows)
    turnover_history = pd.DataFrame(turnover_rows, columns=["date", "decision_date", "turnover", "traded_value"])
    metrics = quarterly_performance_metrics(strategy_series)
    metrics = dict(metrics) | {
        "starting_value": request.starting_value,
        "ending_value": float(strategy_series.iloc[-1]["growth_value"]),
        "total_return": float(strategy_series.iloc[-1]["cumulative_return"]),
        "rebalance_count": int(len(turnover_history)),
        "total_turnover": float(turnover_history["turnover"].sum()) if not turnover_history.empty else 0.0,
    }
    warnings = list(baseline.warnings)
    dropped = sum(max(len(component.series) - len(aligned), 0) for component in components)
    if dropped:
        warnings.append(f"Common-history alignment excluded {dropped} component-quarter observations; no values were filled.")
    gaps = strategy_series["elapsed_quarters"].gt(1).sum()
    if gaps:
        warnings.append(f"{int(gaps)} common-history interval(s) span missing quarters and are excluded from quarterly rule signals and quarter statistics.")
    return QuarterlyBacktestResult(
        strategy_series=strategy_series,
        baseline=baseline,
        positions=pd.DataFrame(position_rows),
        events=pd.DataFrame(event_rows),
        trades=pd.DataFrame(trade_rows),
        turnover_history=turnover_history,
        cash_history=pd.DataFrame(cash_rows),
        drawdown_history=drawdown_history(strategy_series),
        summary_metrics=metrics,
        methodology=methodology,
        warnings=tuple(dict.fromkeys(warnings)),
    )

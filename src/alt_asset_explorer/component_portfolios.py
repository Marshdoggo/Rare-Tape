from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

import pandas as pd

from alt_asset_explorer.custom_portfolios import RebalanceFrequency, _rebalance_dates
from alt_asset_explorer.components import ComponentDefinition, ResolvedComponent

ComponentType = Literal["full_market", "category_index", "individual_asset", "custom_basket", "factor_index"]
CalendarPolicy = Literal["observed_shared"]
AlignmentPolicy = Literal["common_inception"]
MissingObservationPolicy = Literal["drop_date"]
EligibilityPolicy = Literal["fixed_at_inception"]
ExitCashPolicy = Literal["component_series", "hold_cash", "reinvest_on_rebalance"]


@dataclass(frozen=True)
class PortfolioComponent:
    """An investable sleeve whose input series represents one unit of the sleeve."""

    component_id: str
    component_type: ComponentType
    label: str
    target_weight: float
    series: pd.DataFrame
    underlying_weights: Mapping[str, float] | None = None
    internal_method: str = "Direct position"

    def resolved(self) -> ResolvedComponent:
        """Adapt the legacy combined contract at the accounting boundary."""
        definition = ComponentDefinition(
            self.component_id, self.component_type, self.label, self.target_weight,
            internal_method=self.internal_method,
        )
        if self.underlying_weights:
            dates = pd.to_datetime(self.series.get("date"), errors="coerce").dropna().unique()
            constituents = pd.DataFrame(
                ({"date": date, "asset_id": asset_id, "portfolio_weight": weight}
                 for date in dates for asset_id, weight in self.underlying_weights.items())
            )
        else:
            constituents = pd.DataFrame()
        return ResolvedComponent(definition, self.series, constituents, {"resolver": "legacy_adapter"})


@dataclass(frozen=True)
class PortfolioBacktestRequest:
    """Complete, typed methodology input for a component portfolio backtest."""

    components: Sequence[ResolvedComponent | PortfolioComponent]
    starting_value: float = 100.0
    calendar: CalendarPolicy = "observed_shared"
    rebalance_schedule: RebalanceFrequency = "quarterly"
    alignment_policy: AlignmentPolicy = "common_inception"
    missing_observation_policy: MissingObservationPolicy = "drop_date"
    eligibility_policy: EligibilityPolicy = "fixed_at_inception"
    exit_cash_policy: ExitCashPolicy = "component_series"
    annual_risk_free_rate: float = 0.0
    as_of_cutoff: pd.Timestamp | str | None = None


@dataclass(frozen=True)
class PortfolioBacktestResult:
    """UI-ready output contract; views must not reconstruct methodology."""

    series: pd.DataFrame
    drawdown_series: pd.DataFrame
    composition: pd.DataFrame
    eligibility_history: pd.DataFrame
    rebalance_ledger: pd.DataFrame
    cash_ledger: pd.DataFrame
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    methodology: Mapping[str, object] | None = None
    configuration_fingerprint: str = ""
    summary_metrics: Mapping[str, object] | None = None
    look_through_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    overlap_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    reconciliation: pd.DataFrame = field(default_factory=pd.DataFrame)


# Compatibility name retained for callers that only annotated the former result.
ComponentPortfolioResult = PortfolioBacktestResult


def equal_component_weights(component_ids: Sequence[str]) -> dict[str, float]:
    """Assign equal weights to unique top-level components."""

    ids = list(dict.fromkeys(str(value) for value in component_ids))
    return {component_id: 1.0 / len(ids) for component_id in ids} if ids else {}


def remove_and_redistribute(
    weights: Mapping[str, float], removed_ids: Sequence[str], *, policy: Literal["pro_rata", "equal", "unallocated"] = "pro_rata"
) -> dict[str, float]:
    """Remove positions with a visible, deterministic redistribution policy."""

    removed = set(removed_ids)
    remaining = {key: float(value) for key, value in weights.items() if key not in removed}
    removed_weight = sum(float(value) for key, value in weights.items() if key in removed)
    if not remaining or policy == "unallocated" or removed_weight == 0:
        return remaining
    if policy == "equal":
        addition = removed_weight / len(remaining)
        return {key: value + addition for key, value in remaining.items()}
    base = sum(remaining.values())
    if base <= 0:
        addition = removed_weight / len(remaining)
        return {key: addition for key in remaining}
    return {key: value + removed_weight * value / base for key, value in remaining.items()}


def expand_component(
    component_id: str,
    portfolio_weights: Mapping[str, float],
    constituent_weights: Mapping[str, float],
    *,
    method: Literal["preserve", "equal", "market_cap"] = "preserve",
    market_caps: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Replace one sleeve with asset positions while preserving its allocation."""

    if component_id not in portfolio_weights:
        raise ValueError("The component to expand is not in the portfolio.")
    sleeve_weight = float(portfolio_weights[component_id])
    ids = list(dict.fromkeys(str(value) for value in constituent_weights))
    if not ids:
        raise ValueError("The selected sleeve has no eligible constituents.")
    if method == "equal":
        internal = equal_component_weights(ids)
    elif method == "market_cap":
        caps = {asset_id: max(float((market_caps or {}).get(asset_id, 0)), 0.0) for asset_id in ids}
        internal = normalize_component_weights(caps) if sum(caps.values()) > 0 and all(v > 0 for v in caps.values()) else equal_component_weights(ids)
    else:
        raw = {asset_id: float(constituent_weights[asset_id]) for asset_id in ids}
        internal = normalize_component_weights(raw)
    expanded = {key: float(value) for key, value in portfolio_weights.items() if key != component_id}
    expanded.update({f"asset:{asset_id}": sleeve_weight * weight for asset_id, weight in internal.items()})
    return expanded


def _as_resolved(component: ResolvedComponent | PortfolioComponent) -> ResolvedComponent:
    return component if isinstance(component, ResolvedComponent) else component.resolved()


def point_in_time_look_through(
    components: Sequence[ResolvedComponent | PortfolioComponent],
    *,
    as_of: pd.Timestamp | str,
    component_weights: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Aggregate the last known constituent snapshot on or before ``as_of``.

    There is no constituent backfill: a sleeve whose first snapshot is later
    than the requested date is reported as unresolved exposure.
    """

    resolved = [_as_resolved(component) for component in components]
    top = normalize_component_weights(component_weights or {c.component_id: c.target_weight for c in resolved})
    cutoff = pd.Timestamp(as_of).normalize()
    rows: list[dict[str, object]] = []
    for component in resolved:
        constituents = component.constituents.copy()
        if constituents.empty or not {"date", "asset_id", "portfolio_weight"}.issubset(constituents):
            continue
        constituents["date"] = pd.to_datetime(constituents["date"], errors="coerce").dt.normalize()
        eligible = constituents[constituents["date"].le(cutoff)].dropna(subset=["date"])
        if eligible.empty:
            continue
        snapshot_date = eligible["date"].max()
        snapshot = eligible[eligible["date"].eq(snapshot_date)].copy()
        internal = pd.to_numeric(snapshot["portfolio_weight"], errors="coerce").fillna(0.0)
        for (_, item), weight in zip(snapshot.iterrows(), internal):
            rows.append({
                "as_of": cutoff, "constituent_snapshot_date": snapshot_date,
                "asset_id": str(item["asset_id"]), "component_id": component.component_id,
                "source_component": component.label, "component_weight": top[component.component_id],
                "internal_weight": float(weight), "effective_weight": top[component.component_id] * float(weight),
                "is_direct": component.component_type == "individual_asset",
            })
    return pd.DataFrame(rows, columns=[
        "as_of", "constituent_snapshot_date", "asset_id", "component_id", "source_component",
        "component_weight", "internal_weight", "effective_weight", "is_direct",
    ])


def overlap_report(
    components: Sequence[ResolvedComponent | PortfolioComponent],
    *,
    as_of: pd.Timestamp | str,
    component_weights: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Point-in-time exposure and overlap with explicit reconciliation fields."""

    detail = point_in_time_look_through(components, as_of=as_of, component_weights=component_weights)
    if detail.empty:
        return pd.DataFrame(columns=["asset_id", "direct_weight", "indirect_weight", "total_weight", "source_components", "source_count", "overlap"])
    detail["direct_weight"] = detail["effective_weight"].where(detail["is_direct"], 0.0)
    detail["indirect_weight"] = detail["effective_weight"].where(~detail["is_direct"], 0.0)
    grouped = detail.groupby("asset_id", as_index=False).agg(
        direct_weight=("direct_weight", "sum"), indirect_weight=("indirect_weight", "sum"),
        source_components=("source_component", lambda values: ", ".join(dict.fromkeys(values))),
        source_count=("component_id", "nunique"),
    )
    grouped["total_weight"] = grouped["direct_weight"] + grouped["indirect_weight"]
    grouped["overlap"] = grouped["source_count"].gt(1)
    return grouped.sort_values("total_weight", ascending=False).reset_index(drop=True)


def look_through_exposure(components: Sequence[ResolvedComponent | PortfolioComponent]) -> pd.DataFrame:
    """Compatibility latest-date view; prefer :func:`overlap_report`."""

    resolved = [_as_resolved(component) for component in components]
    dates = [pd.to_datetime(c.constituents.get("date"), errors="coerce").max() for c in resolved if not c.constituents.empty]
    if dates:
        return overlap_report(resolved, as_of=max(dates)).drop(columns=["source_count"])

    rows: list[dict[str, object]] = []
    normalized = normalize_component_weights({c.component_id: c.target_weight for c in resolved}) if resolved else {}
    for component in resolved:
        if component.component_type == "individual_asset":
            underlying = component.component_id.removeprefix("asset:")
            rows.append({"asset_id": underlying, "direct_weight": normalized[component.component_id], "indirect_weight": 0.0, "source": component.label})
        else:
            for asset_id, internal_weight in {}.items():
                rows.append({"asset_id": str(asset_id), "direct_weight": 0.0, "indirect_weight": normalized[component.component_id] * float(internal_weight), "source": component.label})
    if not rows:
        return pd.DataFrame(columns=["asset_id", "direct_weight", "indirect_weight", "total_weight", "source_components", "overlap"])
    detail = pd.DataFrame(rows)
    grouped = detail.groupby("asset_id", as_index=False).agg(
        direct_weight=("direct_weight", "sum"), indirect_weight=("indirect_weight", "sum"),
        source_components=("source", lambda values: ", ".join(dict.fromkeys(values))),
    )
    grouped["total_weight"] = grouped["direct_weight"] + grouped["indirect_weight"]
    grouped["overlap"] = (grouped["direct_weight"] > 0) & (grouped["indirect_weight"] > 0)
    return grouped.sort_values("total_weight", ascending=False).reset_index(drop=True)


def infer_periods_per_year(dates: Sequence[object]) -> int:
    """Infer a conventional annualization factor from median observation spacing."""

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
    downside_deviation = float(math.sqrt((downside.pow(2).sum()) / len(returns)) * math.sqrt(periods))
    sortino = float((returns.mean() - periodic_rf) * periods / downside_deviation) if downside_deviation > 0 else math.nan
    growth = (1 + returns).cumprod()
    drawdown = growth / growth.cummax() - 1
    max_drawdown = float(drawdown.min())
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else math.nan
    duration = current = 0
    trough_position = int(drawdown.values.argmin())
    for value in drawdown:
        current = current + 1 if value < 0 else 0
        duration = max(duration, current)
    peak_before_trough = growth.iloc[: trough_position + 1].idxmax()
    later = growth.iloc[trough_position + 1 :]
    recovered = later[later >= growth.loc[peak_before_trough]]
    recovery_date = frame.loc[recovered.index[0], "date"] if not recovered.empty else None
    return {
        "periods_per_year": periods, "annualized_return": annual_return, "annualized_volatility": volatility,
        "sharpe_ratio": sharpe, "sortino_ratio": sortino, "calmar_ratio": calmar,
        "downside_deviation": downside_deviation, "best_period_return": float(returns.max()),
        "worst_period_return": float(returns.min()), "positive_period_percentage": float((returns > 0).mean()),
        "maximum_drawdown": max_drawdown, "maximum_drawdown_duration_periods": duration,
        "recovery_date": recovery_date,
    }


def inverse_volatility_weights(component_series: Mapping[str, pd.DataFrame], *, minimum_observations: int = 3) -> dict[str, float]:
    """Long-only inverse-volatility weights using shared historical observations."""

    merged: pd.DataFrame | None = None
    for key, frame in component_series.items():
        clean = frame[["date", "index_level"]].copy().rename(columns={"index_level": key})
        merged = clean if merged is None else merged.merge(clean, on="date", how="inner")
    if merged is None or len(merged) < minimum_observations + 1:
        raise ValueError(f"At least {minimum_observations + 1} shared levels are required.")
    returns = merged.set_index("date").pct_change().dropna()
    vol = returns.std(ddof=1)
    if (vol <= 0).any() or vol.isna().any():
        raise ValueError("Inverse-volatility allocation requires positive component volatility.")
    inverse = 1 / vol
    return {str(key): float(value) for key, value in (inverse / inverse.sum()).items()}


def normalize_component_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Return positive finite weights summing to one, rejecting invalid allocations."""

    if not weights:
        raise ValueError("At least one component weight is required.")
    numeric = pd.Series(weights, dtype="float64")
    if numeric.isna().any() or (~numeric.map(math.isfinite)).any():
        raise ValueError("Component weights must be finite numbers.")
    if (numeric <= 0).any():
        raise ValueError("Component weights must be greater than zero.")
    total = float(numeric.sum())
    if total <= 0:
        raise ValueError("Component weights must have a positive total.")
    return {str(key): float(value / total) for key, value in numeric.items()}


def _clean_component_series(component: ResolvedComponent) -> pd.DataFrame:
    required = {"date", "index_level"}
    if component.series.empty or not required.issubset(component.series.columns):
        return pd.DataFrame(columns=["date", component.component_id])
    cleaned = component.series.copy()
    if "eligible_constituent_count" in cleaned.columns:
        eligible_count = pd.to_numeric(cleaned["eligible_constituent_count"], errors="coerce")
        cleaned = cleaned[eligible_count > 0]
    cleaned = cleaned[["date", "index_level"]].copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce").dt.normalize()
    cleaned["index_level"] = pd.to_numeric(cleaned["index_level"], errors="coerce")
    cleaned = cleaned.dropna().query("index_level > 0").sort_values("date").drop_duplicates("date", keep="last")
    return cleaned.rename(columns={"index_level": component.component_id})


def backtest_component_portfolio(request: PortfolioBacktestRequest) -> PortfolioBacktestResult:
    """Combine sleeve index levels without flattening their underlying constituents.

    The portfolio starts on the first date shared by every component. Later dates are
    also restricted to shared observations: a missing sleeve observation is never
    silently forward-filled or treated as cash. Rebalancing trades sleeve units back
    to their target allocations on the selected schedule.
    """

    # This is the sole migration adapter. All accounting below consumes only
    # resolved components and never invokes component-internal methodology.
    components = tuple(_as_resolved(component) for component in request.components)
    starting_value = request.starting_value
    rebalance_frequency = request.rebalance_schedule
    empty = pd.DataFrame(columns=["date", "growth_value", "period_return", "cumulative_return", "rebalance_flag"])
    empty_result = lambda errors: PortfolioBacktestResult(
        series=empty, drawdown_series=pd.DataFrame(columns=["date", "drawdown"]), composition=pd.DataFrame(),
        eligibility_history=pd.DataFrame(), rebalance_ledger=pd.DataFrame(), cash_ledger=pd.DataFrame(),
        warnings=tuple(errors), errors=tuple(errors), methodology=_methodology(request), configuration_fingerprint=_fingerprint(request), summary_metrics={},
    )
    if not components:
        return empty_result(("Select at least one portfolio component.",))
    ids = [component.component_id for component in components]
    if len(ids) != len(set(ids)):
        return empty_result(("Duplicate portfolio components are not allowed.",))
    if starting_value <= 0:
        return empty_result(("Starting investment must be greater than zero.",))
    try:
        weights = normalize_component_weights({component.component_id: component.target_weight for component in components})
    except ValueError as exc:
        return empty_result((str(exc),))

    cleaned = {component.component_id: _clean_component_series(component) for component in components}
    if request.as_of_cutoff is not None:
        cutoff = pd.Timestamp(request.as_of_cutoff).normalize()
        cleaned = {key: frame[frame["date"] <= cutoff].copy() for key, frame in cleaned.items()}
    unavailable = [component.label for component in components if len(cleaned[component.component_id]) < 2]
    if unavailable:
        return empty_result(("Components need at least two valid observations: " + ", ".join(unavailable),))

    aligned: pd.DataFrame | None = None
    for component in components:
        frame = cleaned[component.component_id]
        aligned = frame if aligned is None else aligned.merge(frame, on="date", how="inner", validate="one_to_one")
    assert aligned is not None
    aligned = aligned.sort_values("date").reset_index(drop=True)
    if len(aligned) < 2:
        return empty_result(("Selected components do not have at least two common observation dates.",))

    dates = pd.DatetimeIndex(aligned["date"])
    rebalance_dates = _rebalance_dates(dates, rebalance_frequency)
    first = aligned.iloc[0]
    units = {
        component.component_id: starting_value * weights[component.component_id] / float(first[component.component_id])
        for component in components
    }
    rows: list[dict[str, object]] = []
    prior_value: float | None = None
    rebalance_count = 0
    for row_number, observation in aligned.iterrows():
        date = pd.Timestamp(observation["date"])
        values = {component_id: units[component_id] * float(observation[component_id]) for component_id in ids}
        total_value = float(sum(values.values()))
        prior_row = rows[-1] if rows else None
        contributions = {
            component_id: 0.0 if prior_row is None else (values[component_id] - float(prior_row[f"value_{component_id}"])) / starting_value
            for component_id in ids
        }
        is_rebalance = row_number > 0 and date in rebalance_dates
        if is_rebalance:
            units = {component_id: total_value * weights[component_id] / float(observation[component_id]) for component_id in ids}
            values = {component_id: total_value * weights[component_id] for component_id in ids}
            rebalance_count += 1
        period_return = 0.0 if prior_value is None else total_value / prior_value - 1
        rows.append(
            {
                "date": date,
                "growth_value": total_value,
                "period_return": period_return,
                "cumulative_return": total_value / starting_value - 1,
                "rebalance_flag": is_rebalance,
                **{f"value_{component_id}": value for component_id, value in values.items()},
                **{f"contribution_{component_id}": value for component_id, value in contributions.items()},
            }
        )
        prior_value = total_value

    result_series = pd.DataFrame(rows)
    final = result_series.iloc[-1]
    composition = pd.DataFrame(
        [
            {
                "component_id": component.component_id,
                "component": component.label,
                "component_type": component.component_type,
                "target_weight": weights[component.component_id],
                "effective_start_date": aligned.iloc[0]["date"],
                "ending_weight": float(final[f"value_{component.component_id}"]) / float(final["growth_value"]),
                "rebalance_count": rebalance_count,
                "standalone_return": float(aligned.iloc[-1][component.component_id]) / float(first[component.component_id]) - 1,
                "cumulative_contribution": float(result_series[f"contribution_{component.component_id}"].sum()),
            }
            for component in components
        ]
    )
    drawdown = result_series[["date", "growth_value"]].copy()
    drawdown["peak_value"] = drawdown["growth_value"].cummax()
    drawdown["drawdown"] = drawdown["growth_value"] / drawdown["peak_value"] - 1
    eligibility = pd.DataFrame(
        ({"date": date, "component_id": component.component_id, "eligible": True, "policy": request.eligibility_policy}
         for date in aligned["date"] for component in components)
    )
    rebalance_ledger = result_series.loc[result_series["rebalance_flag"], ["date", "growth_value"]].copy()
    if not rebalance_ledger.empty:
        rebalance_ledger["schedule"] = rebalance_frequency
        rebalance_ledger["target_weights"] = [dict(weights)] * len(rebalance_ledger)
    cash_ledger = result_series[["date"]].copy()
    cash_ledger["cash_balance"] = 0.0
    cash_ledger["cash_flow"] = 0.0
    cash_ledger["policy"] = request.exit_cash_policy
    metrics = portfolio_risk_metrics(result_series, annual_risk_free_rate=request.annual_risk_free_rate)
    metrics = dict(metrics) | {
        "starting_value": float(starting_value), "ending_value": float(result_series.iloc[-1]["growth_value"]),
        "total_return": float(result_series.iloc[-1]["cumulative_return"]),
    }
    look_rows: list[pd.DataFrame] = []
    overlap_rows: list[pd.DataFrame] = []
    reconciliation_rows: list[dict[str, object]] = []
    for _, portfolio_row in result_series.iterrows():
        date = pd.Timestamp(portfolio_row["date"])
        actual_weights = {
            component.component_id: float(portfolio_row[f"value_{component.component_id}"]) / float(portfolio_row["growth_value"])
            for component in components
        }
        detail = point_in_time_look_through(components, as_of=date, component_weights=actual_weights)
        overlap = overlap_report(components, as_of=date, component_weights=actual_weights)
        if not detail.empty:
            look_rows.append(detail)
        if not overlap.empty:
            overlap.insert(0, "date", date)
            overlap_rows.append(overlap)
        resolved_component_weight = 0.0
        internal_residual = 0.0
        for component in components:
            component_detail = detail[detail["component_id"].eq(component.component_id)] if not detail.empty else detail
            if component_detail.empty:
                continue
            resolved_component_weight += actual_weights[component.component_id]
            internal_residual += actual_weights[component.component_id] * (1 - float(component_detail["internal_weight"].sum()))
        effective = float(detail["effective_weight"].sum()) if not detail.empty else 0.0
        unresolved = 1.0 - resolved_component_weight
        difference = effective + internal_residual + unresolved - 1.0
        reconciliation_rows.append({
            "date": date, "portfolio_weight": 1.0, "look_through_weight": effective,
            "internal_cash_or_residual_weight": internal_residual,
            "unresolved_component_weight": unresolved, "reconciliation_difference": difference,
            "reconciled": abs(difference) <= 1e-10,
        })
    return PortfolioBacktestResult(
        series=result_series, drawdown_series=drawdown, composition=composition,
        eligibility_history=eligibility, rebalance_ledger=rebalance_ledger, cash_ledger=cash_ledger,
        methodology=_methodology(request), configuration_fingerprint=_fingerprint(request), summary_metrics=metrics,
        look_through_history=pd.concat(look_rows, ignore_index=True) if look_rows else pd.DataFrame(),
        overlap_history=pd.concat(overlap_rows, ignore_index=True) if overlap_rows else pd.DataFrame(),
        reconciliation=pd.DataFrame(reconciliation_rows),
    )


def _methodology(request: PortfolioBacktestRequest) -> dict[str, object]:
    return {
        "calendar": request.calendar, "top_level_rebalance_schedule": request.rebalance_schedule,
        "alignment_inception_policy": request.alignment_policy,
        "missing_observation_policy": request.missing_observation_policy,
        "eligibility_policy": request.eligibility_policy, "exit_cash_policy": request.exit_cash_policy,
        "annual_risk_free_rate": request.annual_risk_free_rate,
        "as_of_cutoff": str(pd.Timestamp(request.as_of_cutoff).date()) if request.as_of_cutoff is not None else None,
        "component_count": len(request.components),
    }


def _fingerprint(request: PortfolioBacktestRequest) -> str:
    payload = _methodology(request) | {
        "starting_value": request.starting_value,
        "components": [{"id": c.component_id, "type": c.component_type, "weight": c.target_weight,
                        "internal_method": c.internal_method} for c in request.components],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def simulate_component_portfolio(
    components: Sequence[PortfolioComponent], *, starting_value: float = 100.0,
    rebalance_frequency: RebalanceFrequency = "quarterly",
) -> PortfolioBacktestResult:
    """Backward-compatible convenience wrapper around the typed request API."""

    return backtest_component_portfolio(PortfolioBacktestRequest(
        components=components, starting_value=starting_value, rebalance_schedule=rebalance_frequency,
    ))

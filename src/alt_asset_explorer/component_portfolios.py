from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import pandas as pd

from alt_asset_explorer.custom_portfolios import RebalanceFrequency, _rebalance_dates

ComponentType = Literal["full_market", "category_index", "individual_asset", "custom_basket", "factor_index"]


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


@dataclass(frozen=True)
class ComponentPortfolioResult:
    series: pd.DataFrame
    composition: pd.DataFrame
    warnings: tuple[str, ...] = ()


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


def look_through_exposure(components: Sequence[PortfolioComponent]) -> pd.DataFrame:
    """Aggregate direct and sleeve exposure by canonical asset ID."""

    rows: list[dict[str, object]] = []
    normalized = normalize_component_weights({c.component_id: c.target_weight for c in components}) if components else {}
    for component in components:
        if component.component_type == "individual_asset":
            underlying = component.component_id.removeprefix("asset:")
            rows.append({"asset_id": underlying, "direct_weight": normalized[component.component_id], "indirect_weight": 0.0, "source": component.label})
        else:
            for asset_id, internal_weight in (component.underlying_weights or {}).items():
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


def _clean_component_series(component: PortfolioComponent) -> pd.DataFrame:
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


def simulate_component_portfolio(
    components: Sequence[PortfolioComponent],
    *,
    starting_value: float = 100.0,
    rebalance_frequency: RebalanceFrequency = "quarterly",
) -> ComponentPortfolioResult:
    """Combine sleeve index levels without flattening their underlying constituents.

    The portfolio starts on the first date shared by every component. Later dates are
    also restricted to shared observations: a missing sleeve observation is never
    silently forward-filled or treated as cash. Rebalancing trades sleeve units back
    to their target allocations on the selected schedule.
    """

    empty = pd.DataFrame(columns=["date", "growth_value", "period_return", "cumulative_return", "rebalance_flag"])
    if not components:
        return ComponentPortfolioResult(empty, pd.DataFrame(), ("Select at least one portfolio component.",))
    ids = [component.component_id for component in components]
    if len(ids) != len(set(ids)):
        return ComponentPortfolioResult(empty, pd.DataFrame(), ("Duplicate portfolio components are not allowed.",))
    if starting_value <= 0:
        return ComponentPortfolioResult(empty, pd.DataFrame(), ("Starting investment must be greater than zero.",))
    try:
        weights = normalize_component_weights({component.component_id: component.target_weight for component in components})
    except ValueError as exc:
        return ComponentPortfolioResult(empty, pd.DataFrame(), (str(exc),))

    cleaned = {component.component_id: _clean_component_series(component) for component in components}
    unavailable = [component.label for component in components if len(cleaned[component.component_id]) < 2]
    if unavailable:
        return ComponentPortfolioResult(empty, pd.DataFrame(), ("Components need at least two valid observations: " + ", ".join(unavailable),))

    aligned: pd.DataFrame | None = None
    for component in components:
        frame = cleaned[component.component_id]
        aligned = frame if aligned is None else aligned.merge(frame, on="date", how="inner", validate="one_to_one")
    assert aligned is not None
    aligned = aligned.sort_values("date").reset_index(drop=True)
    if len(aligned) < 2:
        return ComponentPortfolioResult(empty, pd.DataFrame(), ("Selected components do not have at least two common observation dates.",))

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
    return ComponentPortfolioResult(result_series, composition)

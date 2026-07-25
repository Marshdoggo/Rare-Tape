from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import pandas as pd

from alt_asset_explorer.custom_portfolios import RebalanceFrequency, _rebalance_dates

ComponentType = Literal["full_market", "category_index", "individual_asset", "custom_basket"]


@dataclass(frozen=True)
class PortfolioComponent:
    """An investable sleeve whose input series represents one unit of the sleeve."""

    component_id: str
    component_type: ComponentType
    label: str
    target_weight: float
    series: pd.DataFrame


@dataclass(frozen=True)
class ComponentPortfolioResult:
    series: pd.DataFrame
    composition: pd.DataFrame
    warnings: tuple[str, ...] = ()


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
            }
            for component in components
        ]
    )
    return ComponentPortfolioResult(result_series, composition)

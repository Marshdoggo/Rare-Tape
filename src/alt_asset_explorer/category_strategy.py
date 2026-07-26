"""Point-in-time category constituent strategy simulation.

The simulator deliberately composes the canonical observation resolver with the
existing exit normalizer.  It is not a second price-history or exit engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import pandas as pd

from alt_asset_explorer.portfolio_lab import resolve_canonical_history
from alt_asset_explorer.total_return import normalize_exit_events


StrategyWeighting = Literal["equal_weight", "market_cap_weight", "custom_weight"]
StrategyRebalance = Literal["none", "quarterly", "annual"]


@dataclass(frozen=True)
class CategoryStrategyDefinition:
    category: str
    weighting_method: StrategyWeighting = "equal_weight"
    rebalance_frequency: StrategyRebalance = "quarterly"
    selected_asset_ids: tuple[str, ...] | None = None
    custom_weights: Mapping[str, float] | None = None
    include_asset_ids: frozenset[str] = field(default_factory=frozenset)
    exclude_asset_ids: frozenset[str] = field(default_factory=frozenset)
    base_value: float = 100.0

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("category cannot be blank")
        if self.base_value <= 0:
            raise ValueError("base_value must be positive")
        if self.include_asset_ids & self.exclude_asset_ids:
            raise ValueError("an asset cannot be both included and excluded")
        if self.weighting_method == "custom_weight":
            if not self.custom_weights:
                raise ValueError("custom_weight requires custom_weights")
            weights = {str(k): float(v) for k, v in self.custom_weights.items()}
            if any(v < 0 for v in weights.values()) or sum(weights.values()) > 1 + 1e-12:
                raise ValueError("custom weights must be non-negative and sum to at most one")


@dataclass(frozen=True)
class CategoryStrategyResult:
    definition: CategoryStrategyDefinition
    series: pd.DataFrame
    constituents: pd.DataFrame
    terminal_events: pd.DataFrame
    eligible_asset_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _asset_contract(assets: pd.DataFrame) -> pd.DataFrame:
    """Adapt normalized master names to the canonical exit engine contract."""
    out = assets.copy()
    aliases = {
        "asset_name": "name", "shares_outstanding": "share_count",
        "offering_price_per_share": "offering_price_usd",
    }
    for source, target in aliases.items():
        if target not in out and source in out:
            out[target] = out[source]
    return out


def _exit_rows(assets: pd.DataFrame) -> pd.DataFrame:
    if "exit_date" not in assets:
        return pd.DataFrame()
    exited = assets[pd.to_datetime(assets["exit_date"], errors="coerce").notna()].copy()
    if exited.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "asset_id": exited["asset_id"],
        "sale_date": exited["exit_date"],
        "exit_price_per_share": pd.to_numeric(exited.get("exit_price_per_share"), errors="coerce"),
        "exit_total_value": pd.to_numeric(exited.get("exit_value_total"), errors="coerce"),
        "exit_type": exited.get("exit_type", "other"),
        "exit_status": "settled",
    })


def _is_rebalance(period: pd.Timestamp, first: pd.Timestamp, frequency: str) -> bool:
    if period == first:
        return True
    if frequency == "none":
        return False
    if frequency == "quarterly":
        return True
    return period.quarter == 4


def simulate_category_strategy(
    definition: CategoryStrategyDefinition,
    assets: pd.DataFrame,
    observations: pd.DataFrame,
    exits: pd.DataFrame | None = None,
    *,
    as_of_cutoff: object | None = None,
) -> CategoryStrategyResult:
    """Simulate a category basket over unioned canonical quarterly evidence.

    Assets are admitted only at a scheduled rebalance on or after their first
    canonical observation. Missing quarters are never manufactured; an existing
    position is valued at its last sourced price. Realized exit proceeds become
    explicit cash and may be reinvested only at a later scheduled rebalance.
    Custom target weights are absolute portfolio weights, so an allocation below
    100% intentionally leaves the remainder in cash.
    """
    required_assets = {"asset_id", "category"}
    if not required_assets.issubset(assets) or observations.empty:
        raise ValueError("category strategy requires asset_id/category assets and observations")
    master = _asset_contract(assets)
    category_ids = set(master.loc[master["category"].astype(str).str.casefold().eq(definition.category.casefold()), "asset_id"].astype(str))
    selected = set(map(str, definition.selected_asset_ids)) if definition.selected_asset_ids is not None else category_ids
    selected = ((selected & category_ids) | set(map(str, definition.include_asset_ids))) - set(map(str, definition.exclude_asset_ids))
    ordered_ids = tuple(aid for aid in master["asset_id"].astype(str) if aid in selected)
    warnings = []
    unresolved = sorted(selected - set(ordered_ids))
    if unresolved:
        warnings.append("Unknown included assets: " + ", ".join(unresolved))
    history = resolve_canonical_history(observations, ordered_ids, as_of_cutoff=as_of_cutoff)
    canonical = history.canonical_rows.copy()
    canonical["price_per_share"] = pd.to_numeric(canonical.get("price_per_share"), errors="coerce")
    canonical = canonical[canonical["price_per_share"].gt(0)]
    periods = pd.DatetimeIndex(sorted(canonical["canonical_period"].dropna().unique()))
    empty_series = pd.DataFrame(columns=["date", "portfolio_value", "index_level", "cash_value", "invested_asset_value", "period_return", "rebalance_flag", "active_constituent_count"])
    if not ordered_ids or periods.empty:
        return CategoryStrategyResult(definition, empty_series, pd.DataFrame(), pd.DataFrame(), ordered_ids, tuple(warnings or ["No canonical category history."]))

    price_rows = canonical.rename(columns={"source_observed_at": "date", "price_per_share": "last"})
    exit_input = exits if exits is not None else _exit_rows(master)
    normalized_exits = normalize_exit_events(master, exit_input, price_rows)
    if not normalized_exits.empty:
        exit_periods = (
            pd.to_datetime(normalized_exits["exit_effective_date"], errors="coerce")
            .dropna().dt.to_period("Q").dt.end_time.dt.normalize()
        )
        periods = pd.DatetimeIndex(sorted(set(periods).union(exit_periods)))
    exit_map = {str(row.asset_id): row for _, row in normalized_exits.iterrows()}
    shares = pd.to_numeric(master.set_index("asset_id")["share_count"], errors="coerce").to_dict()
    first_period = canonical.groupby(canonical["asset_id"].astype(str))["canonical_period"].min().to_dict()
    by_period = {(str(r.asset_id), r.canonical_period): float(r.price_per_share) for _, r in canonical.iterrows()}
    last_price: dict[str, float] = {}
    units: dict[str, float] = {}
    cash = float(definition.base_value)
    previous = None
    rows, holdings, terminal = [], [], []
    custom = {str(k): float(v) for k, v in (definition.custom_weights or {}).items()}
    for period in periods:
        period = pd.Timestamp(period)
        for aid in ordered_ids:
            if (aid, period) in by_period:
                last_price[aid] = by_period[(aid, period)]
        for aid in list(units):
            event = exit_map.get(aid)
            effective = event.exit_effective_date if event is not None else pd.NaT
            if pd.notna(effective) and pd.Timestamp(effective).to_period("Q").end_time.normalize() <= period and event.exit_status != "cancelled_exit":
                proceeds = units.pop(aid) * float(event.terminal_price if pd.notna(event.terminal_price) else 0)
                cash += proceeds
                terminal.append({"date": period, "asset_id": aid, "terminal_price": event.terminal_price, "terminal_proceeds": proceeds, "terminal_price_source": event.terminal_price_source})
        invested = sum(units[aid] * last_price[aid] for aid in units)
        total = cash + invested
        rebalance = _is_rebalance(period, periods[0], definition.rebalance_frequency)
        if rebalance:
            eligible = [aid for aid in ordered_ids if aid in last_price and first_period.get(aid) <= period and not (aid in exit_map and pd.notna(exit_map[aid].exit_effective_date) and pd.Timestamp(exit_map[aid].exit_effective_date).to_period("Q").end_time.normalize() <= period)]
            if eligible:
                if definition.weighting_method == "equal_weight":
                    targets = {aid: 1 / len(eligible) for aid in eligible}
                elif definition.weighting_method == "market_cap_weight":
                    caps = {aid: last_price[aid] * float(shares[aid]) for aid in eligible}
                    denominator = sum(caps.values())
                    targets = {aid: caps[aid] / denominator for aid in eligible}
                else:
                    targets = {aid: custom.get(aid, 0.0) for aid in eligible}
                units = {aid: total * weight / last_price[aid] for aid, weight in targets.items() if weight > 0}
                cash = total * max(0.0, 1 - sum(targets.values()))
                invested = sum(units[aid] * last_price[aid] for aid in units)
                total = cash + invested
        period_return = 0.0 if previous is None else total / previous - 1
        previous = total
        rows.append({"date": period, "portfolio_value": total, "index_level": total / definition.base_value * 100, "cash_value": cash, "invested_asset_value": invested, "period_return": period_return, "rebalance_flag": rebalance, "active_constituent_count": len(units)})
        for aid, quantity in units.items():
            value = quantity * last_price[aid]
            holdings.append({"date": period, "asset_id": aid, "units_held": quantity, "price": last_price[aid], "position_value": value, "portfolio_weight": value / total if total else 0, "source_observed_this_period": (aid, period) in by_period})
    series = pd.DataFrame(rows)
    series["cumulative_return"] = series["index_level"] / 100 - 1
    series["drawdown"] = series["index_level"] / series["index_level"].cummax() - 1
    return CategoryStrategyResult(definition, series, pd.DataFrame(holdings), pd.DataFrame(terminal), ordered_ids, tuple(warnings))

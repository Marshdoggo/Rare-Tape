"""Whole-share replication research for canonical Rally index universes.

The routines here are deterministic portfolio mathematics.  They do not imply
that an observed Rally quote was executable or that a portfolio can be traded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from alt_asset_explorer.portfolio_analytics import infer_periods_per_year

Objective = Literal["absolute", "squared", "maximum"]
ToleranceMetric = Literal["rmse", "absolute", "maximum"]


@dataclass(frozen=True)
class AllocationResult:
    quantities: pd.Series
    budget: float
    invested: float
    residual_cash: float
    feasible: bool
    metrics: dict[str, float]
    method: str


@dataclass(frozen=True)
class SimulationResult:
    history: pd.DataFrame
    constituents: pd.DataFrame
    metrics: dict[str, float]
    warnings: tuple[str, ...] = ()


def _prices(prices: pd.Series) -> pd.Series:
    out = pd.to_numeric(prices, errors="coerce").astype(float)
    if out.empty or out.isna().any() or (out <= 0).any():
        raise ValueError("Every included constituent requires a positive price.")
    return out


def normalize_target_weights(weights: pd.Series | None, asset_ids: Sequence[str]) -> pd.Series:
    ids = pd.Index([str(value) for value in asset_ids])
    if weights is None:
        return pd.Series(1.0 / len(ids), index=ids, dtype=float)
    out = pd.to_numeric(weights, errors="coerce").reindex(ids).fillna(0.0).astype(float)
    if (out < 0).any() or out.sum() <= 0:
        raise ValueError("Target weights must be non-negative and sum to a positive value.")
    return out / out.sum()


def one_share_each_capital(prices: pd.Series) -> float:
    return float(_prices(prices).sum())


def weight_error_metrics(prices: pd.Series, quantities: pd.Series, target_weights: pd.Series, *, denominator: float | None = None) -> dict[str, float]:
    prices = _prices(prices)
    quantities = pd.to_numeric(quantities, errors="coerce").reindex(prices.index).fillna(0).astype(int)
    invested = prices * quantities
    denominator = float(denominator if denominator is not None else invested.sum())
    actual = invested / denominator if denominator > 0 else invested * 0
    target = normalize_target_weights(target_weights, prices.index)
    deviation = actual - target
    return {
        "rmse": float(np.sqrt(np.mean(np.square(deviation)))),
        "absolute": float(deviation.abs().sum()),
        "maximum": float(deviation.abs().max()),
        "cash_weight": float(max(denominator - invested.sum(), 0.0) / denominator) if denominator else 0.0,
    }


def simple_anchor_allocation(prices: pd.Series, target_weights: pd.Series | None = None) -> AllocationResult:
    """Construct quantities near a max-price per-position anchor (heuristic)."""
    prices = _prices(prices)
    target = normalize_target_weights(target_weights, prices.index)
    # Scale the anchor by relative target weights, reducing to max(price) for equal weight.
    anchor_total = float(prices.max() / target.max())
    target_dollars = anchor_total * target
    raw = target_dollars / prices
    candidates = pd.DataFrame({"floor": np.floor(raw), "round": np.round(raw), "ceil": np.ceil(raw)}, index=prices.index).clip(lower=1).astype(int)
    quantities = pd.Series(index=prices.index, dtype=int)
    for asset_id in prices.index:
        deviations = (candidates.loc[asset_id] * prices.loc[asset_id] - target_dollars.loc[asset_id]).abs()
        quantities.loc[asset_id] = int(candidates.loc[asset_id, deviations.idxmin()])
    invested = float((prices * quantities).sum())
    return AllocationResult(quantities.astype(int), invested, invested, 0.0, True, weight_error_metrics(prices, quantities, target), "maximum-price anchor heuristic")


def budget_allocation(prices: pd.Series, budget: float, target_weights: pd.Series | None = None, *, require_all: bool = True, max_omitted: int | None = None, reserve: float = 0.0, objective: Objective = "absolute", max_iterations: int = 10_000) -> AllocationResult:
    """Deterministic bounded integer tracker using greedy starts and local search."""
    prices = _prices(prices)
    target = normalize_target_weights(target_weights, prices.index)
    available = float(budget) - float(reserve)
    minimum = one_share_each_capital(prices) if require_all else 0.0
    if available < minimum or budget <= 0:
        q = pd.Series(0, index=prices.index, dtype=int)
        return AllocationResult(q, float(budget), 0.0, float(budget), False, weight_error_metrics(prices, q, target, denominator=budget if budget > 0 else 1), "budget integer heuristic")
    q = np.floor(available * target / prices).astype(int)
    if require_all:
        q = q.clip(lower=1)
        if float((prices * q).sum()) > available:
            q = pd.Series(1, index=prices.index, dtype=int)
    omitted_limit = len(prices) if max_omitted is None else max(0, int(max_omitted))

    def score(candidate: pd.Series) -> float:
        m = weight_error_metrics(prices, candidate, target, denominator=budget)
        return {"absolute": m["absolute"], "squared": m["rmse"] ** 2, "maximum": m["maximum"]}[objective]

    # Add the share producing the largest objective improvement per dollar; if
    # all additions worsen the score, spend toward the largest underweight.
    for _ in range(min(max_iterations, max(len(prices), 25))):
        affordable = prices[prices <= available - float((prices * q).sum()) + 1e-9]
        if affordable.empty:
            break
        base = score(q)
        choices = []
        for asset_id, price in affordable.items():
            cand = q.copy(); cand.loc[asset_id] += 1
            choices.append((score(cand), price, str(asset_id), cand))
        best_score, _, _, best = min(choices, key=lambda item: (item[0], item[1], item[2]))
        if best_score >= base:
            actual = prices * q / budget
            under = (target - actual).loc[affordable.index]
            asset_id = sorted(affordable.index, key=lambda x: (-under.loc[x] / prices.loc[x], str(x)))[0]
            best = q.copy(); best.loc[asset_id] += 1
        q = best
    if not require_all and int((q == 0).sum()) > omitted_limit:
        for asset_id in prices[q == 0].sort_values().index[: int((q == 0).sum()) - omitted_limit]:
            if float((prices * q).sum() + prices.loc[asset_id]) <= available:
                q.loc[asset_id] = 1
    invested = float((prices * q).sum())
    feasible = invested <= available + 1e-8 and (not require_all or bool((q >= 1).all())) and int((q == 0).sum()) <= omitted_limit
    return AllocationResult(q, float(budget), invested, float(budget) - invested, feasible, weight_error_metrics(prices, q, target, denominator=budget), "budget integer heuristic")


def minimum_capital_for_tolerance(prices: pd.Series, tolerance: float, target_weights: pd.Series | None = None, *, metric: ToleranceMetric = "maximum", max_multiplier: float = 100.0) -> AllocationResult:
    """Bounded ascending anchor search; not a proof of global optimality."""
    prices = _prices(prices); target = normalize_target_weights(target_weights, prices.index)
    low = one_share_each_capital(prices)
    anchors = np.unique(np.geomspace(low, max(low, low * max_multiplier), 180).round(6))
    best: AllocationResult | None = None
    for budget in anchors:
        q = np.round(float(budget) * target / prices).clip(lower=1).astype(int)
        invested = float((prices * q).sum())
        candidate = AllocationResult(q, invested, invested, 0.0, True, weight_error_metrics(prices, q, target), "bounded minimum-capital search")
        if candidate.feasible and candidate.metrics[metric] <= tolerance:
            best = candidate
            break
    if best is None:
        fallback = budget_allocation(prices, float(anchors[-1]), target, require_all=True)
        return AllocationResult(fallback.quantities, fallback.budget, fallback.invested, fallback.residual_cash, False, fallback.metrics, "bounded minimum-capital search")
    # Report the smallest invested capital represented by this feasible integer vector.
    metrics = weight_error_metrics(prices, best.quantities, target)
    return AllocationResult(best.quantities, best.invested, best.invested, 0.0, True, metrics, "bounded minimum-capital search")


def select_prices_asof(history: pd.DataFrame, asset_ids: Sequence[str], requested_date: object, *, mode: Literal["common", "launch_aware"] = "common", max_staleness_days: int = 120) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Select latest observations on/before inception, never using future data."""
    h = history.copy(); h["date"] = pd.to_datetime(h["date"], errors="coerce"); h["last"] = pd.to_numeric(h["last"], errors="coerce")
    h = h[h["asset_id"].astype(str).isin(map(str, asset_ids)) & h["last"].gt(0)].dropna(subset=["date"])
    requested = pd.Timestamp(requested_date).normalize()
    if mode == "common":
        first = h.groupby("asset_id")["date"].min().reindex(list(map(str, asset_ids)))
        effective = max(requested, first.max()) if first.notna().all() else requested
    else:
        effective = requested
    rows = h[h["date"] <= effective].sort_values(["asset_id", "date"]).groupby("asset_id", as_index=False).tail(1)
    rows["requested_start_date"] = requested; rows["effective_start_date"] = effective
    rows["staleness_days"] = (effective - rows["date"]).dt.days; rows["is_stale"] = rows["staleness_days"] > max_staleness_days
    return rows.sort_values("asset_id").reset_index(drop=True), effective


def annualized_tracking_error(portfolio_values: pd.Series, benchmark_values: pd.Series, dates: Sequence[object]) -> float:
    aligned = pd.concat([pd.to_numeric(portfolio_values, errors="coerce"), pd.to_numeric(benchmark_values, errors="coerce")], axis=1).dropna()
    differences = aligned.iloc[:, 0].pct_change() - aligned.iloc[:, 1].pct_change()
    differences = differences.dropna()
    return float(differences.std(ddof=1) * np.sqrt(infer_periods_per_year(dates))) if len(differences) >= 2 else float("nan")


def simulate_buy_and_hold(history: pd.DataFrame, allocation: AllocationResult, target_weights: pd.Series, *, start_date: object, metadata: pd.DataFrame | None = None) -> SimulationResult:
    h = history.copy(); h["date"] = pd.to_datetime(h["date"], errors="coerce"); h["last"] = pd.to_numeric(h["last"], errors="coerce")
    h = h.dropna(subset=["date", "last"])
    # Carry only observations already known at each date; building the matrix
    # before slicing retains the valid as-of inception quote without look-ahead.
    wide = h.pivot_table(index="date", columns="asset_id", values="last", aggfunc="last").sort_index().reindex(columns=allocation.quantities.index).ffill()
    wide = wide[wide.index >= pd.Timestamp(start_date)]
    if wide.empty: return SimulationResult(pd.DataFrame(), pd.DataFrame(), {}, ("No history on or after the effective start date.",))
    initial = wide.iloc[0]; valid = initial.notna(); q = allocation.quantities.reindex(wide.columns).fillna(0).where(valid, 0)
    values = wide.mul(q, axis=1); holdings = values.sum(axis=1, min_count=1); total = holdings + allocation.residual_cash
    fractional_q = allocation.budget * normalize_target_weights(target_weights, wide.columns) / initial
    benchmark = wide.mul(fractional_q.where(valid, 0), axis=1).sum(axis=1, min_count=1)
    out = pd.DataFrame({"date": wide.index, "holdings_value": holdings.values, "cash": allocation.residual_cash, "portfolio_value": total.values, "benchmark_value": benchmark.values})
    out["portfolio_pnl"] = out["portfolio_value"] - allocation.budget; out["benchmark_pnl"] = out["benchmark_value"] - allocation.budget; out["replication_difference"] = out["portfolio_value"] - out["benchmark_value"]
    out["drawdown"] = out["portfolio_value"] / out["portfolio_value"].cummax() - 1
    latest = wide.iloc[-1]; invested = initial * q; latest_values = latest * q; actual = invested / allocation.budget
    table = pd.DataFrame({"asset_id": wide.columns, "price_date": pd.Timestamp(start_date), "share_price": initial.values, "target_weight": normalize_target_weights(target_weights, wide.columns).values, "integer_quantity": q.astype(int).values, "invested_amount": invested.values, "actual_weight": actual.values, "weight_deviation": (actual-normalize_target_weights(target_weights, wide.columns)).values, "latest_value": latest_values.values, "dollar_pnl": (latest_values-invested).values})
    table["return_contribution"] = table["dollar_pnl"] / allocation.budget; table["current_weight"] = table["latest_value"] / float(out.iloc[-1]["portfolio_value"])
    if metadata is not None and not metadata.empty: table = table.merge(metadata[[c for c in ["asset_id","ticker","name","category","status"] if c in metadata]].drop_duplicates("asset_id"), on="asset_id", how="left")
    metrics = {"starting_cash": allocation.budget, "invested_capital": allocation.invested, "residual_cash": allocation.residual_cash, "latest_value": float(total.iloc[-1]), "pnl": float(total.iloc[-1]-allocation.budget), "return": float(total.iloc[-1]/allocation.budget-1), "benchmark_return": float(benchmark.iloc[-1]/allocation.budget-1), "return_difference": float(total.iloc[-1]/allocation.budget-benchmark.iloc[-1]/allocation.budget), "annualized_tracking_error": annualized_tracking_error(total.reset_index(drop=True), benchmark.reset_index(drop=True), out["date"]), "maximum_drawdown": float(out["drawdown"].min()), "constituent_count": int((q>0).sum()), "herfindahl": float(np.square(table["current_weight"]).sum())}
    return SimulationResult(out, table, metrics)


def tracking_frontier(prices: pd.Series, target_weights: pd.Series, budgets: Sequence[float]) -> pd.DataFrame:
    rows=[]
    for budget in sorted(set(float(x) for x in budgets if x > 0)):
        target = normalize_target_weights(target_weights, prices.index)
        q = np.floor(budget * target / prices).astype(int)
        if budget >= one_share_each_capital(prices): q = q.clip(lower=1)
        invested = float((prices * q).sum())
        rows.append({"budget":budget,"invested":invested,"feasible":invested <= budget,"method":"bounded rounded frontier",**weight_error_metrics(prices,q,target,denominator=budget)})
    return pd.DataFrame(rows)


def homepage_summary(asset_master: pd.DataFrame, history: pd.DataFrame, *, tolerance: float = 0.01) -> dict[str, float]:
    ids = sorted(set(asset_master.loc[asset_master.get("status", "").astype(str).str.lower().eq("trading"), "asset_id"].astype(str)))
    if not ids: return {}
    latest = history[history["asset_id"].astype(str).isin(ids)].assign(date=lambda d: pd.to_datetime(d["date"],errors="coerce")).sort_values("date").groupby("asset_id").tail(1).set_index("asset_id")
    prices = pd.to_numeric(latest["last"],errors="coerce").dropna(); target=normalize_target_weights(None,prices.index)
    result=minimum_capital_for_tolerance(prices,tolerance,target)
    starts,effective=select_prices_asof(history,prices.index,pd.to_datetime(history["date"], errors="coerce").max(),mode="common")
    simulation=simulate_buy_and_hold(history,result,target,start_date=effective,metadata=asset_master)
    return {"constituent_count":len(prices),"minimum_capital":result.invested,"weight_rmse":result.metrics["rmse"],"latest_value":simulation.metrics.get("latest_value",float("nan")),"return":simulation.metrics.get("return",float("nan")),"pnl":simulation.metrics.get("pnl",float("nan"))}

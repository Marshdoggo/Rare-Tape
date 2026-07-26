"""Canonical index adapters used by the Portfolio Construction Laboratory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd


CANONICAL_INDEX_FREQUENCY = "quarterly"
INDEX_CONSTITUENT_REQUIRED_COLUMNS = {
    "asset_id",
    "category",
    "date",
    "portfolio_weight",
    "universe_scope",
    "weighting_method",
}

# Phase 0 deliberately reads the authored normalized contracts rather than one
# of the several derived price/index shapes used by the application.
NORMALIZED_ASSET_COLUMNS = (
    "asset_id", "ticker", "asset_name", "category", "subcategory", "status",
    "shares_outstanding", "offering_date", "offering_price_per_share",
    "offering_market_cap", "first_trade_date", "exit_date",
    "exit_price_per_share", "exit_value_total", "exit_type", "source_reference",
    "verified_at", "notes", "rally_url", "currency",
    "implied_offering_market_cap", "warning_reason",
)
NORMALIZED_OBSERVATION_COLUMNS = (
    "asset_id", "period_end", "observed_at", "price_per_share", "market_cap",
    "event_type", "source_type", "source_reference", "collected_at", "researcher",
    "precision_status", "notes", "volume", "frequency", "implied_market_cap",
    "warning_reason",
)


@dataclass(frozen=True)
class PortfolioPhaseZeroDiagnostic:
    """Auditable selection/alignment facts before a portfolio is simulated.

    ``observed_dates`` retain real quote dates. ``canonical_periods`` are a
    separate, quarterly research alignment and must not be described as quotes
    observed on those dates.
    """

    selected_asset_ids: tuple[str, ...]
    resolved_asset_ids: tuple[str, ...]
    missing_asset_ids: tuple[str, ...]
    observed_date_intersection: tuple[pd.Timestamp, ...]
    canonical_period_intersection: tuple[pd.Timestamp, ...]
    launch_ranges: pd.DataFrame
    raw_observation_rows: int
    unique_observation_rows: int
    duplicate_observation_rows_removed: int
    raw_canonical_rows: int
    unique_canonical_rows: int
    duplicate_canonical_rows_removed: int


def _assert_exact_columns(frame: pd.DataFrame, expected: tuple[str, ...], source: str) -> None:
    actual = tuple(str(column) for column in frame.columns)
    if actual != expected:
        missing = sorted(set(expected).difference(actual))
        extra = sorted(set(actual).difference(expected))
        raise ValueError(
            f"Invalid {source} schema: expected exact columns {list(expected)}; "
            f"actual columns {list(actual)}; missing {missing}; extra {extra}."
        )


def build_phase_zero_diagnostic(
    assets: pd.DataFrame,
    observations: pd.DataFrame,
    selected_asset_ids: Sequence[str],
) -> PortfolioPhaseZeroDiagnostic:
    """Resolve a selection and report its no-fill production-data alignment.

    Repeated requested IDs are collapsed in first-seen order. Exact duplicate
    observations (same asset and ``observed_at``) keep the last committed row.
    Quarterly collisions (same asset and ``period_end``) independently keep the
    latest actual ``observed_at``. Thus an offering and a later chart quote in
    one canonical quarter produce one canonical value without erasing either
    item of dated source evidence.
    """

    _assert_exact_columns(assets, NORMALIZED_ASSET_COLUMNS, "normalized asset")
    _assert_exact_columns(observations, NORMALIZED_OBSERVATION_COLUMNS, "normalized observation")
    selected = tuple(dict.fromkeys(str(value) for value in selected_asset_ids))
    available = set(assets["asset_id"].dropna().astype(str))
    resolved = tuple(asset_id for asset_id in selected if asset_id in available)
    missing = tuple(asset_id for asset_id in selected if asset_id not in available)

    selected_rows = observations[observations["asset_id"].astype(str).isin(resolved)].copy()
    selected_rows["observed_at"] = pd.to_datetime(selected_rows["observed_at"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    selected_rows["period_end"] = pd.to_datetime(selected_rows["period_end"], errors="coerce").dt.normalize()
    selected_rows = selected_rows.dropna(subset=["observed_at"])
    raw_observation_rows = len(selected_rows)
    observed = selected_rows.drop_duplicates(["asset_id", "observed_at"], keep="last")

    quarterly = observed[observed["frequency"].astype(str).str.lower().eq(CANONICAL_INDEX_FREQUENCY)].copy()
    raw_canonical_rows = len(quarterly)
    quarterly = quarterly.sort_values(["asset_id", "period_end", "observed_at"], kind="stable")
    canonical = quarterly.dropna(subset=["period_end"]).drop_duplicates(["asset_id", "period_end"], keep="last")

    def intersection(frame: pd.DataFrame, column: str) -> tuple[pd.Timestamp, ...]:
        if not resolved:
            return ()
        values = [set(frame.loc[frame["asset_id"].astype(str).eq(asset_id), column]) for asset_id in resolved]
        return tuple(sorted(set.intersection(*values))) if values else ()

    ranges = []
    for asset_id in resolved:
        dated = observed[observed["asset_id"].astype(str).eq(asset_id)]
        periods = canonical[canonical["asset_id"].astype(str).eq(asset_id)]
        ranges.append({
            "asset_id": asset_id,
            "first_observed_at": dated["observed_at"].min(),
            "last_observed_at": dated["observed_at"].max(),
            "first_canonical_period": periods["period_end"].min(),
            "last_canonical_period": periods["period_end"].max(),
        })
    launch_ranges = pd.DataFrame(ranges, columns=[
        "asset_id", "first_observed_at", "last_observed_at",
        "first_canonical_period", "last_canonical_period",
    ])
    return PortfolioPhaseZeroDiagnostic(
        selected_asset_ids=selected,
        resolved_asset_ids=resolved,
        missing_asset_ids=missing,
        observed_date_intersection=intersection(observed, "observed_at"),
        canonical_period_intersection=intersection(canonical, "period_end"),
        launch_ranges=launch_ranges,
        raw_observation_rows=raw_observation_rows,
        unique_observation_rows=len(observed),
        duplicate_observation_rows_removed=raw_observation_rows - len(observed),
        raw_canonical_rows=raw_canonical_rows,
        unique_canonical_rows=len(canonical),
        duplicate_canonical_rows_removed=raw_canonical_rows - len(canonical),
    )


def validate_index_constituent_schema(
    frame: pd.DataFrame, *, source: str = "canonical_market.total_return_constituents"
) -> None:
    """Raise a useful error when the canonical constituent contract is broken."""
    missing = sorted(INDEX_CONSTITUENT_REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        available = sorted(str(column) for column in frame.columns)
        raise ValueError(
            f"Invalid index constituent schema from {source}: missing columns {missing}; "
            f"available columns {available}."
        )


def canonical_index(
    index_portfolio: pd.DataFrame,
    index_constituents: pd.DataFrame,
    component_type: str,
    reference: str,
    method: str,
    scope: str,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Return the canonical quarterly index series and its latest constituents.

    The quarterly frequency here describes the underlying canonical index. It is
    deliberately independent from the rebalance schedule of a portfolio that
    owns this index as a sleeve.
    """
    validate_index_constituent_schema(index_constituents)
    category = "all" if component_type == "full_market" else reference
    selected = index_portfolio[
        index_portfolio["category"].astype(str).eq(category)
        & index_portfolio["weighting_method"].astype(str).eq(method)
        & index_portfolio["rebalance_frequency"].astype(str).eq(CANONICAL_INDEX_FREQUENCY)
        & index_portfolio["universe_scope"].astype(str).eq(scope)
    ].copy()
    holdings = index_constituents[
        index_constituents["category"].astype(str).eq(category)
        & index_constituents["weighting_method"].astype(str).eq(method)
        & index_constituents["universe_scope"].astype(str).eq(scope)
    ].copy()
    if holdings.empty:
        return selected, {}
    holdings["date"] = pd.to_datetime(holdings["date"], errors="coerce")
    latest = holdings[holdings["date"].eq(holdings["date"].max())].copy()
    raw = latest.groupby(latest["asset_id"].astype(str))["portfolio_weight"].sum().to_dict()
    total = sum(raw.values())
    return selected, ({key: float(value / total) for key, value in raw.items()} if total > 0 else {})

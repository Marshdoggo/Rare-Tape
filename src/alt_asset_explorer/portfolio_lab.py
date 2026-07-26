"""Canonical index adapters used by the Portfolio Construction Laboratory."""

from __future__ import annotations

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

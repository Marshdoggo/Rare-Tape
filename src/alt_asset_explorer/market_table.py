from __future__ import annotations

import pandas as pd

from alt_asset_explorer.asset_returns import build_asset_return_summary
from alt_asset_explorer.total_return import _price_date_frame


MARKET_TABLE_COLUMNS = [
    "asset_id",
    "ticker",
    "name",
    "category",
    "subcategory",
    "last_price",
    "return_1q",
    "return_1y",
    "return_full_history",
    "best_bid",
    "best_ask",
    "bid_ask_spread_pct",
    "shares_outstanding",
    "current_market_cap_usd",
    "offering_price_usd",
    "offering_valuation_usd",
    "experimental_estimated_fair_value_usd",
    "premium_discount_to_fair_value",
    "nav_confidence",
    "last_quote_observed_at",
    "status",
    "trading_state",
    "buyout_offer_price_per_share",
    "buyout_offer_total_value",
    "buyout_premium_pct",
    "buyout_vote_as_of",
    "buyout_vote_provisional",
    "buyout_notes",
    "source_type",
    "data_quality_status",
    "data_quality_warnings",
    "is_current_listed",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return float(parsed) if pd.notna(parsed) else None


def _latest_quotes(price_history: pd.DataFrame) -> pd.DataFrame:
    if price_history.empty or not {"asset_id", "date"}.issubset(price_history.columns):
        return pd.DataFrame(columns=["asset_id", "last_quote_observed_at", "last_price", "best_bid", "best_ask"])
    quotes = _price_date_frame(price_history)
    quotes = quotes.dropna(subset=["asset_id", "date"])
    if quotes.empty:
        return pd.DataFrame(columns=["asset_id", "last_quote_observed_at", "last_price", "best_bid", "best_ask"])
    latest = quotes.sort_values(["asset_id", "date"]).groupby("asset_id", as_index=False).tail(1)
    latest = latest.rename(columns={"last": "last_price", "bid": "best_bid", "ask": "best_ask"})
    for column in ("best_bid", "best_ask"):
        if column not in latest:
            latest[column] = None
    return latest[["asset_id", "date", "last_price", "best_bid", "best_ask"]].assign(last_quote_observed_at=lambda df: df["date"].dt.date.astype(str)).drop(columns=["date"])


def _column_or_null(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame:
        return frame[column]
    return pd.Series([None] * len(frame), index=frame.index)


def build_market_table(
    canonical_asset_master: pd.DataFrame,
    decision_universe: pd.DataFrame,
    price_history: pd.DataFrame,
    liquidity: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Prepare the homepage Rally market table from normalized outputs."""
    if canonical_asset_master.empty:
        return pd.DataFrame(columns=MARKET_TABLE_COLUMNS)

    master = canonical_asset_master.copy()
    decision_cols = [
        "asset_id",
        "current_market_cap_usd",
        "last_trade_price",
        "bid_price",
        "ask_price",
        "estimated_nav_usd",
        "nav_confidence",
    ]
    decision = decision_universe[[col for col in decision_cols if col in decision_universe.columns]].copy() if not decision_universe.empty else pd.DataFrame(columns=decision_cols)
    latest_quotes = _latest_quotes(price_history)
    return_summary = build_asset_return_summary(price_history)
    table = master.merge(decision, on="asset_id", how="left").merge(latest_quotes, on="asset_id", how="left", suffixes=("", "_quote")).merge(return_summary, on="asset_id", how="left")

    if liquidity is not None and not liquidity.empty and "asset_id" in liquidity:
        table = table.merge(liquidity[["asset_id", "bid_ask_spread_pct"]], on="asset_id", how="left")
    else:
        table["bid_ask_spread_pct"] = None

    table["last_price"] = _column_or_null(table, "last_price").combine_first(_column_or_null(table, "last_trade_price"))
    table["best_bid"] = _column_or_null(table, "best_bid").combine_first(_column_or_null(table, "bid_price"))
    table["best_ask"] = _column_or_null(table, "best_ask").combine_first(_column_or_null(table, "ask_price"))
    table["last_quote_observed_at"] = _column_or_null(table, "last_quote_observed_at_quote").combine_first(_column_or_null(table, "last_quote_observed_at"))
    table["shares_outstanding"] = _column_or_null(table, "share_count")
    table["experimental_estimated_fair_value_usd"] = _column_or_null(table, "estimated_nav_usd")

    premiums: list[float | None] = []
    for _, row in table.iterrows():
        fair_value = _num(row.get("experimental_estimated_fair_value_usd"))
        market_cap = _num(row.get("current_market_cap_usd"))
        premiums.append((market_cap / fair_value - 1) if fair_value and market_cap is not None else None)
    table["premium_discount_to_fair_value"] = premiums

    status = table["status"].fillna("").astype(str).str.lower()
    non_sec_source = ~table["source_type"].astype(str).eq("sec_synthesized")
    active_status = status.isin(["trading", "accepting_orders"])
    has_quote = table["last_quote_observed_at"].notna() & table["last_price"].notna()
    has_manual_listing_evidence = (
        table["shares_outstanding"].notna()
        & table["offering_price_usd"].notna()
        & table["offering_valuation_usd"].notna()
    )
    table["is_current_listed"] = active_status & non_sec_source & (has_quote | has_manual_listing_evidence)

    for column in MARKET_TABLE_COLUMNS:
        if column not in table.columns:
            table[column] = None
    return table[MARKET_TABLE_COLUMNS].sort_values(["is_current_listed", "ticker"], ascending=[False, True]).reset_index(drop=True)


def filter_market_table(
    table: pd.DataFrame,
    *,
    search: str = "",
    categories: list[str] | None = None,
    subcategories: list[str] | None = None,
    data_quality: list[str] | None = None,
    valuation_filter: str = "All",
    min_confidence: float = 0.0,
    current_listed_only: bool = True,
) -> pd.DataFrame:
    filtered = table.copy()
    if current_listed_only and "is_current_listed" in filtered:
        filtered = filtered[filtered["is_current_listed"].fillna(False)]
    if search:
        needle = search.strip().lower()
        filtered = filtered[
            filtered["ticker"].fillna("").astype(str).str.lower().str.contains(needle, regex=False)
            | filtered["name"].fillna("").astype(str).str.lower().str.contains(needle, regex=False)
        ]
    if categories:
        filtered = filtered[filtered["category"].astype(str).isin(categories)]
    if subcategories:
        filtered = filtered[filtered["subcategory"].astype(str).isin(subcategories)]
    if data_quality:
        filtered = filtered[filtered["data_quality_status"].astype(str).isin(data_quality)]
    if valuation_filter == "Above estimated fair value":
        filtered = filtered[pd.to_numeric(filtered["premium_discount_to_fair_value"], errors="coerce") > 0]
    elif valuation_filter == "Below estimated fair value":
        filtered = filtered[pd.to_numeric(filtered["premium_discount_to_fair_value"], errors="coerce") < 0]
    if min_confidence > 0:
        filtered = filtered[pd.to_numeric(filtered["nav_confidence"], errors="coerce").fillna(0) >= min_confidence]
    return filtered.reset_index(drop=True)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

CANONICAL_STALENESS_DAYS = 120
PRODUCTION_ENVIRONMENTS = {"", "nan", "none", "<na>", "production"}
FIXTURE_TERMS = ("fixture", "sample", "demo", "mock", "placeholder", "synthetic", "example")

Status = Literal[
    "announced", "offering_open", "offering_closed", "funded", "active_tradable",
    "trading_paused", "exit_announced", "pending_settlement", "exited", "cancelled",
    "withdrawn", "unknown",
]

@dataclass(frozen=True)
class CurrentUniverseConfig:
    max_staleness_days: int = CANONICAL_STALENESS_DAYS
    include_unverified: bool = True
    allow_offering_price_for_tradable: bool = False


def _norm_text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip().lower()


def normalize_asset_status(value: object) -> Status:
    raw = _norm_text(value).replace(" ", "_").replace("-", "_")
    if raw in {"trading", "active", "active_tradable", "accepting_orders", "listed", "live"}:
        return "active_tradable"
    if raw in {"paused", "trading_paused", "halted", "buyout_pending"}:
        return "trading_paused"
    if raw in {"sold", "redeemed", "liquidated", "exited", "delisted", "buyout"}:
        return "exited"
    if raw in {"pending_settlement", "pending_approval"}:
        return "pending_settlement"
    if raw in {"exit_announced", "sale_announced", "exit_pending"}:
        return "exit_announced"
    if raw in {"cancelled", "cancelled_exit"}:
        return "cancelled"
    if raw in {"withdrawn"}:
        return "withdrawn"
    if raw in {"funded", "sold_out"}:
        return "funded"
    if raw in {"offering_open", "accepting_investments"}:
        return "offering_open"
    if raw in {"offering_closed"}:
        return "offering_closed"
    if raw in {"announced"}:
        return "announced"
    return "unknown"


def is_fixture_or_sample(row: pd.Series) -> bool:
    env = _norm_text(row.get("record_environment"))
    if env in {"fixture", "demo", "test"}:
        return True
    haystack = " ".join(_norm_text(row.get(c)) for c in ["asset_id", "ticker", "name", "source_type", "source_notes", "source_url"])
    return any(term in haystack for term in FIXTURE_TERMS)


def is_production_asset(row: pd.Series) -> bool:
    env = _norm_text(row.get("record_environment"))
    platform = _norm_text(row.get("platform"))
    if is_fixture_or_sample(row):
        return False
    if env and env not in PRODUCTION_ENVIRONMENTS:
        return False
    if platform and platform != "rally":
        return False
    return True


def is_currently_tradable(row: pd.Series, *, config: CurrentUniverseConfig | None = None) -> bool:
    config = config or CurrentUniverseConfig()
    if not is_production_asset(row):
        return False
    if normalize_asset_status(row.get("canonical_status", row.get("status"))) != "active_tradable":
        return False
    age = pd.to_numeric(pd.Series([row.get("observation_age_days")]), errors="coerce").iloc[0]
    if pd.isna(age) or int(age) > config.max_staleness_days:
        return False
    if _norm_text(row.get("price_source")) == "offering_price" and not config.allow_offering_price_for_tradable:
        return False
    return pd.notna(pd.to_numeric(pd.Series([row.get("canonical_current_price", row.get("price"))]), errors="coerce").iloc[0]) and pd.notna(pd.to_numeric(pd.Series([row.get("canonical_shares", row.get("shares_outstanding"))]), errors="coerce").iloc[0])


def latest_exchange_rows(exchange_asset_history: pd.DataFrame, as_of_date: object | None = None) -> pd.DataFrame:
    if exchange_asset_history.empty:
        return pd.DataFrame()
    h = exchange_asset_history.copy()
    h["date"] = pd.to_datetime(h["date"], errors="coerce")
    h = h.dropna(subset=["date", "asset_id"])
    if as_of_date is not None:
        h = h[h["date"] <= pd.to_datetime(as_of_date)]
    if h.empty:
        return h
    asof = h["date"].max()
    return h[h["date"].eq(asof)].sort_values("asset_id").reset_index(drop=True)


def build_current_asset_universe(canonical_asset_master: pd.DataFrame, exchange_asset_history: pd.DataFrame, *, as_of_date: object | None = None, universe_type: Literal["tradable", "represented"] = "tradable", config: CurrentUniverseConfig | None = None) -> pd.DataFrame:
    config = config or CurrentUniverseConfig()
    latest = latest_exchange_rows(exchange_asset_history, as_of_date)
    if latest.empty:
        return pd.DataFrame()
    master_cols = [c for c in ["asset_id", "status", "source_type", "source_url", "source_notes", "record_environment", "platform", "data_quality_status"] if c in canonical_asset_master]
    out = latest.merge(canonical_asset_master[master_cols].drop_duplicates("asset_id"), on="asset_id", how="left", suffixes=("", "_master")) if master_cols else latest.copy()
    out["canonical_status"] = out.get("status", out.get("status_master", "")).map(normalize_asset_status) if "status" in out else out.get("status_master", pd.Series([""] * len(out))).map(normalize_asset_status)
    out["canonical_current_price"] = pd.to_numeric(out.get("price"), errors="coerce")
    out["canonical_shares"] = pd.to_numeric(out.get("shares_outstanding"), errors="coerce")
    out["canonical_market_cap"] = out["canonical_current_price"] * out["canonical_shares"]
    out["is_fixture_or_sample"] = out.apply(is_fixture_or_sample, axis=1)
    out["is_production_asset"] = out.apply(is_production_asset, axis=1)
    out["is_current_tradable"] = out.apply(lambda r: is_currently_tradable(r, config=config), axis=1)
    out["is_represented_asset"] = out["is_production_asset"] & out["canonical_status"].isin(["active_tradable", "trading_paused", "pending_settlement"])
    mask = out["is_current_tradable"] if universe_type == "tradable" else out["is_represented_asset"]
    return out[mask].sort_values("asset_id").reset_index(drop=True)


def calculate_current_universe_summary(current_universe: pd.DataFrame) -> dict[str, object]:
    if current_universe.empty:
        return {"as_of_date": None, "unique_asset_count": 0, "tradable_asset_count": 0, "tradable_market_cap": 0.0, "category_count": 0, "stale_value_count": 0, "missing_value_count": 0}
    return {
        "as_of_date": pd.to_datetime(current_universe["date"]).max().date().isoformat(),
        "unique_asset_count": int(current_universe["asset_id"].nunique()),
        "tradable_asset_count": int(current_universe.get("is_current_tradable", pd.Series([True]*len(current_universe))).sum()),
        "tradable_market_cap": float(pd.to_numeric(current_universe["canonical_market_cap"], errors="coerce").sum()),
        "category_count": int(current_universe["category"].nunique()),
        "direct_price_count": int(current_universe.get("is_direct_observation", pd.Series(dtype=bool)).fillna(False).sum()),
        "carried_forward_count": int(current_universe.get("price_source", pd.Series(dtype=str)).astype(str).eq("carried_forward").sum()),
        "stale_value_count": int(current_universe.get("is_stale", pd.Series(dtype=bool)).fillna(False).sum()),
        "missing_value_count": int(pd.to_numeric(current_universe["canonical_market_cap"], errors="coerce").isna().sum()),
    }

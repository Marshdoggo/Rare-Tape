from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from alt_asset_explorer.assets import build_canonical_asset_master
from alt_asset_explorer.connectors.rally_manual import (
    load_normalized_manual_assets,
    load_normalized_price_observations,
    load_quarterly_index_observations,
)
from alt_asset_explorer.current_universe import build_current_asset_universe, calculate_current_universe_summary
from alt_asset_explorer.exchange_history import ExchangeHistoryResult, rebuild_exchange_history
from alt_asset_explorer.paths import DATA_NORMALIZED
from alt_asset_explorer.total_return import TotalReturnConfig, build_total_return_indexes, normalize_exit_events


@dataclass(frozen=True)
class CanonicalMarketData:
    """In-memory Rally market model derived from authored manual inputs.

    The two principal source datasets are ``data/normalized/assets.csv`` and
    ``data/normalized/price_observations.csv``.  Exchange history, current
    universe, total-return indexes, and exit analytics are deterministic
    calculations over those sources, not persisted source-of-truth snapshots.
    """

    asset_master: pd.DataFrame
    quarterly_prices: pd.DataFrame
    secondary_prices: pd.DataFrame
    authored_price_observations: pd.DataFrame
    exchange_history: ExchangeHistoryResult
    current_universe: pd.DataFrame
    current_summary: pd.DataFrame
    total_return_portfolio: pd.DataFrame
    total_return_constituents: pd.DataFrame
    exit_events: pd.DataFrame
    exit_analytics: pd.DataFrame


def manual_exits_from_assets(manual_assets: pd.DataFrame) -> pd.DataFrame:
    if manual_assets.empty or "exit_date" not in manual_assets:
        return pd.DataFrame()
    rows = []
    for _, row in manual_assets.iterrows():
        exit_type = str(row.get("exit_type") or "").strip().lower()
        has_exit_date = pd.notna(row.get("exit_date"))
        has_exit_price = pd.notna(row.get("exit_price_per_share"))
        has_exit_value = pd.notna(row.get("exit_value_total"))
        if exit_type in {"buyout_offer", "pending_buyout"} or not has_exit_date or not (has_exit_price or has_exit_value):
            continue
        rows.append(
            {
                "asset_id": row.get("asset_id"),
                "ticker": row.get("ticker"),
                "exit_type": row.get("exit_type") or "other",
                "exit_status": "settled",
                "sale_date": row.get("exit_date"),
                "exit_effective_date": row.get("exit_date"),
                "settlement_date": row.get("exit_date"),
                "exit_price_per_share": row.get("exit_price_per_share"),
                "exit_total_value": row.get("exit_value_total"),
                "shares_at_exit": row.get("shares_outstanding"),
                "realized_return": (
                    float(row.get("exit_value_total"))
                    / float(row.get("shares_outstanding"))
                    / float(row.get("offering_price_per_share"))
                    - 1
                    if pd.notna(row.get("exit_value_total"))
                    and pd.notna(row.get("shares_outstanding"))
                    and pd.notna(row.get("offering_price_per_share"))
                    else pd.NA
                ),
                "source_reference": row.get("source_reference"),
                "notes": row.get("notes"),
                "is_confirmed": True,
            }
        )
    return pd.DataFrame(rows)


def load_asset_master() -> pd.DataFrame:
    """Load the manually maintained Rally asset master source."""
    assets = load_normalized_manual_assets()
    if assets.empty:
        return assets
    assets = assets.copy()
    if "share_count" not in assets and "shares" in assets:
        assets["share_count"] = assets["shares"]
    if "offering_market_cap_usd" not in assets:
        shares = pd.to_numeric(assets.get("shares"), errors="coerce")
        price = pd.to_numeric(assets.get("offering_price"), errors="coerce")
        assets["offering_market_cap_usd"] = shares * price
    assets["platform"] = "Rally"
    assets["record_environment"] = "production"
    return assets


def load_quarterly_prices() -> pd.DataFrame:
    """Load manually maintained Rally quarterly price observations."""
    return load_quarterly_index_observations()


def load_secondary_prices() -> pd.DataFrame:
    """Load manual secondary observations excluding offering-only rows."""
    return load_normalized_price_observations()


def load_authored_price_observations() -> pd.DataFrame:
    """Load authored price observations in the manual-import schema.

    This preserves event-specific fields such as ``price_per_share``,
    ``market_cap``, ``observed_at``, ``precision_status``, and ``period_end``
    for UI sections that need manual observation details instead of transformed
    index-ready price rows.
    """
    path = DATA_NORMALIZED / "price_observations.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_canonical_market_data(*, as_of: date | None = None) -> CanonicalMarketData:
    as_of = as_of or date.today()
    authored_assets = load_asset_master()
    quarterly_prices = load_quarterly_prices()
    secondary_prices = load_secondary_prices()
    authored_price_observations = load_authored_price_observations()
    master = build_canonical_asset_master(authored_assets, secondary_prices, as_of=as_of)
    manual_exits = manual_exits_from_assets(pd.read_csv(DATA_NORMALIZED / "assets.csv") if (DATA_NORMALIZED / "assets.csv").exists() else pd.DataFrame())
    exchange = rebuild_exchange_history(master, quarterly_prices, manual_exits, frequency="native", persist=False)
    current = build_current_asset_universe(master, exchange.asset_history, as_of_date=as_of)
    summary = pd.DataFrame([calculate_current_universe_summary(current)])
    portfolio_frames = []
    constituent_frames = []
    exit_events = pd.DataFrame()
    exit_analytics = pd.DataFrame()
    for rebalance_frequency in ("quarterly", "monthly", "weekly"):
        for include_exited in (True, False):
            portfolio_part, constituents_part, exit_events_part, exit_analytics_part = build_total_return_indexes(
                master,
                quarterly_prices,
                manual_exits,
                frequency="native",
                config=TotalReturnConfig(rebalance_frequency=rebalance_frequency),
                include_exited=include_exited,
                include_constituents=rebalance_frequency == "quarterly",
            )
            if not portfolio_part.empty:
                portfolio_frames.append(portfolio_part)
            # Constituents are the canonical quarterly index membership/weights.
            # Other portfolio series frequencies are source-series variants, not
            # separate constituent universes for the Portfolio Laboratory.
            if rebalance_frequency == "quarterly" and not constituents_part.empty:
                constituent_frames.append(constituents_part)
            if include_exited and exit_events.empty and not exit_events_part.empty:
                exit_events = exit_events_part
            if include_exited and exit_analytics.empty and not exit_analytics_part.empty:
                exit_analytics = exit_analytics_part
    portfolio = pd.concat(portfolio_frames, ignore_index=True) if portfolio_frames else pd.DataFrame()
    constituents = pd.concat(constituent_frames, ignore_index=True) if constituent_frames else pd.DataFrame()
    if exit_events.empty:
        exit_events = normalize_exit_events(master, manual_exits, quarterly_prices)
    return CanonicalMarketData(
        asset_master=master,
        quarterly_prices=quarterly_prices,
        secondary_prices=secondary_prices,
        authored_price_observations=authored_price_observations,
        exchange_history=exchange,
        current_universe=current,
        current_summary=summary,
        total_return_portfolio=portfolio,
        total_return_constituents=constituents,
        exit_events=exit_events,
        exit_analytics=exit_analytics,
    )

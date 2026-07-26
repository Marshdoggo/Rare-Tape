from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from alt_asset_explorer.paths import DATA_PROCESSED, ensure_dirs
from alt_asset_explorer.universe import build_asset_universe, eligible_asset_ids
from typing import Literal as _Literal

Frequency = _Literal["native", "weekly", "monthly", "quarterly"]
FREQUENCY_RULES = {"weekly": "W-FRI", "monthly": "ME", "quarterly": "QE"}
PRICE_EVENT_TYPES = {"chart_observation", "secondary_trade", "quote", "manual_observation", "unknown"}

def _price_date_frame(prices: pd.DataFrame) -> pd.DataFrame:
    source = prices.copy()
    if source.empty:
        return source
    if "date" not in source and "period_end" in source:
        source["date"] = source["period_end"]
    if "last" not in source and "price_per_share" in source:
        source["last"] = source["price_per_share"]
    source["date"] = pd.to_datetime(source["date"], errors="coerce").dt.normalize()
    source["last"] = pd.to_numeric(source.get("last"), errors="coerce")
    source = source.dropna(subset=["asset_id", "date", "last"])
    if "event_type" not in source:
        source["event_type"] = "chart_observation"
    source = source[source["last"] > 0]
    source["price_source"] = np.where(source["event_type"].eq("offering_price"), "offering_price", "observed_price")
    source["is_direct_observation"] = ~source["event_type"].eq("offering_price")
    source["_priority"] = source["event_type"].astype(str).map({"offering_price": 0, **{event: 1 for event in PRICE_EVENT_TYPES}, "buyout": 2, "asset_sale": 2, "distribution": 2}).fillna(1)
    return source.sort_values(["date", "asset_id", "_priority"]).drop_duplicates(["date", "asset_id"], keep="last")

EXIT_TYPES = {"buyout", "asset_sale", "redemption", "liquidation", "delisting", "issuer_repurchase", "auction_sale", "private_sale", "other", "distribution", "unknown"}
EXIT_STATUSES = {"active", "exit_announced", "pending_approval", "pending_settlement", "settled", "exited", "cancelled_exit", "unknown"}
REALIZED_STATUSES = {"settled", "exited"}
PENDING_STATUSES = {"pending_settlement"}
REINVESTMENT_POLICIES = {"scheduled_rebalance", "immediate_reinvestment", "hold_cash"}
CALCULATION_VERSION = "total_return_index_v1"


@dataclass(frozen=True)
class TotalReturnConfig:
    base_index_level: float = 100.0
    rebalance_frequency: Literal["weekly", "monthly", "quarterly"] = "quarterly"
    reinvestment_policy: str = "scheduled_rebalance"
    reconciliation_tolerance: float = 1e-6


def _coalesce(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    out = pd.Series([pd.NA] * len(frame), index=frame.index, dtype="object")
    for name in names:
        if name in frame:
            out = out.where(out.notna() & out.astype(str).ne(""), frame[name])
    return out


def _norm_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _norm_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def normalize_exit_events(assets: pd.DataFrame, exits: pd.DataFrame | None, prices: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return canonical exit events linked to asset IDs where possible."""
    cols = ["asset_id", "ticker", "exit_type", "exit_status", "exit_announcement_date", "last_trading_date", "exit_valuation_date", "exit_effective_date", "settlement_date", "exit_price_per_share", "exit_total_value", "shares_at_exit", "last_observed_price_before_exit", "last_observed_market_cap_before_exit", "payout_source", "source_reference", "notes", "is_confirmed", "data_quality_flag", "terminal_price", "terminal_value", "terminal_price_source", "terminal_price_quality", "terminal_return", "exit_premium_vs_last_trade", "exit_return_vs_offering", "annualized_exit_return"]
    if exits is None or exits.empty:
        return pd.DataFrame(columns=cols)
    e = exits.copy()
    a = assets.copy() if assets is not None else pd.DataFrame()
    if not a.empty:
        a["asset_id"] = a["asset_id"].astype(str)
        if "ticker" in a:
            a["_ticker_key"] = a["ticker"].astype(str).str.upper().str.replace("#", "", regex=False).str.strip()
    if "asset_id" not in e:
        e["asset_id"] = pd.NA
    e["asset_id"] = e["asset_id"].astype("string")
    e.loc[e["asset_id"].astype(str).str.lower().isin(["", "nan", "none", "<na>"]), "asset_id"] = pd.NA
    # Link SEC-style series_name to ticker if asset_id is missing.
    if "ticker" not in e:
        e["ticker"] = pd.NA
    if "series_name" in e:
        key = e["series_name"].astype(str).str.upper().str.replace("SERIES", "", regex=False).str.replace("#", "", regex=False).str.strip()
        e["_series_key"] = key
        if not a.empty and "_ticker_key" in a:
            lookup = a.dropna(subset=["_ticker_key"]).drop_duplicates("_ticker_key").set_index("_ticker_key")["asset_id"]
            missing = e["asset_id"].isna() | e["asset_id"].astype(str).isin(["", "nan", "<NA>"])
            e.loc[missing, "asset_id"] = e.loc[missing, "_series_key"].map(lookup)
            ticker_lookup = a.drop_duplicates("asset_id").set_index("asset_id")["ticker"] if "ticker" in a else pd.Series(dtype=object)
            e["ticker"] = e["ticker"].where(e["ticker"].notna(), e["asset_id"].map(ticker_lookup))
    e["exit_type"] = _coalesce(e, ["exit_type", "type"]).fillna("other").astype(str).str.lower().replace({"buyout_offer": "buyout", "sale": "asset_sale"})
    e.loc[~e["exit_type"].isin(EXIT_TYPES), "exit_type"] = "other"
    e["exit_status"] = _coalesce(e, ["exit_status", "status"]).fillna("settled").astype(str).str.lower()
    e.loc[~e["exit_status"].isin(EXIT_STATUSES), "exit_status"] = "unknown"
    e["exit_announcement_date"] = _norm_date(_coalesce(e, ["exit_announcement_date", "announcement_date", "sale_date"]))
    e["last_trading_date"] = _norm_date(_coalesce(e, ["last_trading_date", "sale_date"]))
    e["exit_valuation_date"] = _norm_date(_coalesce(e, ["exit_valuation_date", "valuation_date", "sale_date"]))
    e["exit_effective_date"] = _norm_date(_coalesce(e, ["exit_effective_date", "effective_date", "sale_date"]))
    e["settlement_date"] = _norm_date(_coalesce(e, ["settlement_date", "sale_date"]))
    e["exit_price_per_share"] = _norm_num(_coalesce(e, ["exit_price_per_share", "terminal_price", "payout_per_share"]))
    e["exit_total_value"] = _norm_num(_coalesce(e, ["exit_total_value", "exit_value_total", "sale_price", "terminal_value"]))
    share_lookup = a.drop_duplicates("asset_id").set_index("asset_id")["share_count"] if not a.empty and "share_count" in a else pd.Series(dtype=float)
    e["shares_at_exit"] = _norm_num(_coalesce(e, ["shares_at_exit", "share_count", "shares"]))
    e["shares_at_exit"] = e["shares_at_exit"].fillna(e["asset_id"].map(share_lookup))
    e["is_confirmed"] = _coalesce(e, ["is_confirmed"]).fillna(True).astype(str).str.lower().isin(["true", "1", "yes", "y"])
    e.loc[e["exit_status"].eq("cancelled_exit"), "is_confirmed"] = False
    e["payout_source"] = _coalesce(e, ["payout_source", "source_url", "source_reference"]).fillna("")
    e["source_reference"] = _coalesce(e, ["source_reference", "source_url"]).fillna("")
    e["notes"] = _coalesce(e, ["notes"]).fillna("")

    p = _price_date_frame(prices if prices is not None else pd.DataFrame())
    last_price = []
    for _, row in e.iterrows():
        ap = p[p["asset_id"].astype(str).eq(str(row.get("asset_id")))] if not p.empty else pd.DataFrame()
        cutoff = row.get("last_trading_date") if pd.notna(row.get("last_trading_date")) else row.get("exit_effective_date")
        if not ap.empty and pd.notna(cutoff):
            ap = ap[ap["date"] <= cutoff]
        last_price.append(float(ap.sort_values("date").iloc[-1]["last"]) if not ap.empty else np.nan)
    e["last_observed_price_before_exit"] = _norm_num(_coalesce(e, ["last_observed_price_before_exit"])).fillna(pd.Series(last_price, index=e.index))
    e["last_observed_market_cap_before_exit"] = e["last_observed_price_before_exit"] * e["shares_at_exit"]
    e["terminal_price"] = np.nan; e["terminal_price_source"] = "missing"; e["terminal_price_quality"] = "blocking"
    confirmed = e["is_confirmed"] & ~e["exit_status"].eq("cancelled_exit")
    m1 = confirmed & e["exit_price_per_share"].gt(0)
    e.loc[m1, ["terminal_price", "terminal_price_source", "terminal_price_quality"]] = [np.nan, "confirmed_per_share_payout", "confirmed"]
    e.loc[m1, "terminal_price"] = e.loc[m1, "exit_price_per_share"]
    m2 = confirmed & e["terminal_price"].isna() & e["exit_total_value"].gt(0) & e["shares_at_exit"].gt(0)
    e.loc[m2, "terminal_price"] = e.loc[m2, "exit_total_value"] / e.loc[m2, "shares_at_exit"]
    e.loc[m2, ["terminal_price_source", "terminal_price_quality"]] = ["confirmed_total_payout_divided_by_shares", "confirmed"]
    m5 = confirmed & e["terminal_price"].isna() & e["last_observed_price_before_exit"].gt(0)
    e.loc[m5, "terminal_price"] = e.loc[m5, "last_observed_price_before_exit"]
    e.loc[m5, ["terminal_price_source", "terminal_price_quality"]] = ["last_valid_secondary_market_price", "fallback"]
    e["terminal_value"] = e["terminal_price"] * e["shares_at_exit"]
    e["data_quality_flag"] = _coalesce(e, ["data_quality_flag"]).fillna("").astype(str)
    e.loc[e["terminal_price_source"].eq("last_valid_secondary_market_price"), "data_quality_flag"] += ";terminal_price_fallback_last_trade"
    offering_lookup = a.drop_duplicates("asset_id").set_index("asset_id")["offering_price_usd"] if not a.empty and "offering_price_usd" in a else pd.Series(dtype=float)
    offering_date = a.drop_duplicates("asset_id").set_index("asset_id")["offering_date"] if not a.empty and "offering_date" in a else pd.Series(dtype=object)
    e["terminal_return"] = e["terminal_price"] / e["last_observed_price_before_exit"] - 1
    e["exit_premium_vs_last_trade"] = e["terminal_return"]
    e["exit_return_vs_offering"] = e["terminal_price"] / e["asset_id"].map(offering_lookup).astype(float) - 1
    od = pd.to_datetime(e["asset_id"].map(offering_date), errors="coerce")
    years = (e["exit_effective_date"] - od).dt.days / 365.25
    e["annualized_exit_return"] = np.where(years > 0, (1 + e["exit_return_vs_offering"]) ** (1 / years) - 1, np.nan)
    return e[cols].sort_values(["exit_effective_date", "asset_id"], na_position="last").reset_index(drop=True)


def _date_grid(assets: pd.DataFrame, prices: pd.DataFrame, exits: pd.DataFrame, frequency: Frequency) -> pd.DatetimeIndex:
    dates = []
    for c in ["offering_date"]:
        if c in assets: dates.extend(pd.to_datetime(assets[c], errors="coerce").dropna().tolist())
    if not prices.empty: dates.extend(pd.to_datetime(prices["date"], errors="coerce").dropna().tolist())
    if not exits.empty:
        for c in ["exit_announcement_date", "last_trading_date", "exit_effective_date", "settlement_date"]:
            dates.extend(pd.to_datetime(exits[c], errors="coerce").dropna().tolist())
    if not dates: return pd.DatetimeIndex([])
    start, end = min(dates).normalize(), max(dates).normalize()
    if frequency == "native": return pd.DatetimeIndex(sorted({pd.Timestamp(d).normalize() for d in dates if pd.notna(d)}))
    return pd.DatetimeIndex(sorted(set([start, end, *pd.date_range(start, end, freq=FREQUENCY_RULES[frequency])])))


def scheduled_rebalance_dates(dates: pd.DatetimeIndex, frequency: str) -> set[pd.Timestamp]:
    if len(dates) == 0: return set()
    rule = {"weekly": "W-FRI", "monthly": "ME", "quarterly": "QE"}[frequency]
    scheduled = pd.date_range(dates.min(), dates.max(), freq=rule)
    out = {dates[dates >= d].min() for d in scheduled if (dates >= d).any()}
    out.add(dates.min())
    return {pd.Timestamp(d).normalize() for d in out}


def build_total_return_indexes(assets: pd.DataFrame, prices: pd.DataFrame, exits: pd.DataFrame | None = None, *, frequency: Frequency = "native", config: TotalReturnConfig | None = None, include_exited: bool = True, include_constituents: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = config or TotalReturnConfig()
    required = {"asset_id", "offering_date", "share_count", "offering_price_usd"}
    if assets is None or assets.empty or not required.issubset(assets.columns):
        empty = pd.DataFrame()
        return empty, empty, normalize_exit_events(pd.DataFrame(), exits, prices), empty
    a = assets.copy(); a["asset_id"] = a["asset_id"].astype(str); a["offering_date"] = pd.to_datetime(a["offering_date"], errors="coerce").dt.normalize(); a["share_count"] = pd.to_numeric(a["share_count"], errors="coerce"); a["offering_price_usd"] = pd.to_numeric(a["offering_price_usd"], errors="coerce")
    a = a.dropna(subset=["asset_id", "offering_date", "share_count", "offering_price_usd"])
    a = a[(a["share_count"] > 0) & (a["offering_price_usd"] > 0)]
    source_prices = _price_date_frame(prices)
    universe = build_asset_universe(a, source_prices, include_exited=include_exited, require_price_history=False)
    allowed_ids = set(eligible_asset_ids(universe)) if not universe.empty else set()
    if allowed_ids:
        a = a[a["asset_id"].astype(str).isin(allowed_ids)].copy()
    else:
        a = a.iloc[0:0].copy()
    p = source_prices[source_prices["asset_id"].astype(str).isin(set(a["asset_id"].astype(str)))] if not source_prices.empty else source_prices
    offer = a[["asset_id", "offering_date", "offering_price_usd"]].rename(columns={"offering_date":"date", "offering_price_usd":"last"}); offer["event_type"]="offering_price"; offer["price_source"]="offering_price"; offer["is_direct_observation"]=False; offer["_priority"]=0
    p = pd.concat([p, offer], ignore_index=True, sort=False).sort_values(["date","asset_id","_priority"]).drop_duplicates(["date","asset_id"], keep="last")
    e = normalize_exit_events(a, exits, prices)
    dates = _date_grid(a, p, e, frequency)
    if len(dates) == 0:
        empty = pd.DataFrame(); return empty, empty, e, empty
    price_wide = p.pivot_table(index="date", columns="asset_id", values="last", aggfunc="last").sort_index().reindex(dates).ffill()
    rebal_dates = scheduled_rebalance_dates(dates, config.rebalance_frequency)
    universes = [("full_market", None)] + [(str(c), str(c)) for c in sorted(a.get("category", pd.Series(dtype=str)).dropna().astype(str).unique())]
    port_rows=[]; const_rows=[]; analytics=[]
    for universe, cat in universes:
      aa = a if cat is None else a[a["category"].astype(str).eq(cat)]
      ids=set(aa["asset_id"]); ee=e[e["asset_id"].astype(str).isin(ids)] if not e.empty else e
      offer_map = aa.set_index("asset_id")["offering_date"].to_dict()
      exit_by_asset = {str(r["asset_id"]): r for _, r in ee.iterrows()}
      share_map = aa.set_index("asset_id")["share_count"].astype(float).to_dict()
      price0_map = aa.set_index("asset_id")["offering_price_usd"].astype(float).to_dict()
      category_map = aa.set_index("asset_id")["category"].to_dict() if "category" in aa else {}
      ticker_map = aa.set_index("asset_id")["ticker"].to_dict() if "ticker" in aa else {}
      for method in ["equal_weight", "market_cap_weight"]:
        units={}; cash=config.base_index_level; pending={}; prev_value=None; level=config.base_index_level
        for d in dates:
          d=pd.Timestamp(d).normalize(); is_rebal=d in rebal_dates
          # settle/removal
          for _, ex in ee.iterrows():
            aid=str(ex["asset_id"]); eff=ex["exit_effective_date"]; settle=ex["settlement_date"]
            if aid in units and pd.notna(eff) and d>=eff and ex["exit_status"] != "cancelled_exit":
              proceeds=units.pop(aid)*float(ex["terminal_price"] if pd.notna(ex["terminal_price"]) else 0.0)
              if ex["exit_status"] in PENDING_STATUSES and pd.notna(settle) and d < settle:
                pending[aid]=proceeds
              else:
                cash += proceeds
                analytics.append({"asset_id":aid,"ticker":ex.get("ticker"),"category":cat or category_map.get(aid),"offering_date":offer_map[aid],"offering_price":price0_map[aid],"exit_date":eff,"exit_price":ex["terminal_price"],"holding_period_days":(eff-offer_map[aid]).days if pd.notna(eff) else np.nan,"total_return":ex["exit_return_vs_offering"],"annualized_return":ex["annualized_exit_return"],"premium_vs_last_trade":ex["exit_premium_vs_last_trade"],"initial_market_cap":price0_map[aid]*share_map[aid],"exit_market_cap":ex["terminal_value"],"realized_pl":ex["terminal_value"]-price0_map[aid]*share_map[aid],"data_quality_flag":ex["data_quality_flag"]})
          for aid,val in list(pending.items()):
            ex=ee[ee["asset_id"].astype(str).eq(aid)].iloc[0]
            if pd.notna(ex["settlement_date"]) and d>=ex["settlement_date"]:
              cash += val; del pending[aid]
          row_prices = price_wide.loc[d] if d in price_wide.index else pd.Series(dtype=float)
          price_map={aid: float(row_prices.get(aid)) for aid in ids if pd.notna(row_prices.get(aid))}
          invested=sum(units.get(aid,0)*price_map.get(aid,0) for aid in list(units))
          pending_value=sum(pending.values())
          total_value=invested+cash+pending_value
          if is_rebal:
            eligible=[]
            for _, ar in aa.iterrows():
              aid=ar["asset_id"]
              if ar["offering_date"]<=d and aid in price_map:
                exrow=exit_by_asset.get(str(aid))
                removed=exrow is not None and pd.notna(exrow["exit_effective_date"]) and d>=exrow["exit_effective_date"] and exrow["exit_status"] != "cancelled_exit"
                if not removed: eligible.append(aid)
            if eligible:
              total_value=sum(units.get(aid,0)*price_map.get(aid,0) for aid in units)+cash+sum(pending.values())
              caps={aid: price_map[aid]*share_map[aid] for aid in eligible}
              denom=sum(caps.values()) if method=="market_cap_weight" else len(eligible)
              new_units={}
              for aid in eligible:
                target=total_value/len(eligible) if method=="equal_weight" else total_value*caps[aid]/denom
                new_units[aid]=target/price_map[aid]
              units=new_units; cash=0.0; pending={}
              invested=sum(units.get(aid,0)*price_map.get(aid,0) for aid in units); total_value=invested
          if prev_value is None:
            prev_value = total_value if total_value>0 else config.base_index_level
            period_return=0.0; level=config.base_index_level
          else:
            period_return=(total_value/prev_value-1) if prev_value else 0.0; level*=1+period_return; prev_value=total_value
          port_rows.append({"date":d,"universe":"full_market" if cat is None else "category","category":cat or "all","universe_scope":"include_exited" if include_exited else "active_only","weighting_method":method,"rebalance_frequency":config.rebalance_frequency,"index_level":level,"portfolio_value":total_value,"invested_asset_value":invested,"cash_value":cash,"pending_settlement_value":sum(pending.values()),"eligible_constituent_count":len([aid for aid in ids if offer_map[aid]<=d]),"active_constituent_count":len(units),"exited_constituent_count":len([1 for ex in exit_by_asset.values() if pd.notna(ex["exit_effective_date"]) and d>=ex["exit_effective_date"] and ex["exit_status"]!="cancelled_exit"]),"realized_exit_proceeds":cash,"period_return":period_return,"cumulative_return":level/config.base_index_level-1,"rebalance_flag":is_rebal,"calculation_version":CALCULATION_VERSION})
          if include_constituents:
            for aid,u in units.items():
              val=u*price_map.get(aid,0); const_rows.append({"date":d,"universe":"full_market" if cat is None else "category","category":cat or "all","universe_scope":"include_exited" if include_exited else "active_only","weighting_method":method,"asset_id":aid,"ticker":ticker_map.get(aid, aid),"constituent_status":"included_in_index","units_held":u,"price":price_map.get(aid),"price_source":"asof_observed_or_offering","position_value":val,"portfolio_weight":val/total_value if total_value else 0,"entry_date":offer_map[aid],"exit_date":pd.NaT,"terminal_proceeds":0.0,"realized_pl":0.0,"rebalance_trade_value":np.nan})
    portfolio=pd.DataFrame(port_rows)
    if not portfolio.empty:
      portfolio["drawdown"] = portfolio.groupby(["universe_scope","universe","category","weighting_method","rebalance_frequency"])["index_level"].transform(lambda s: s/s.cummax()-1)
      portfolio["calculated_at"] = datetime.now(timezone.utc).isoformat()
    analytics_columns = ["asset_id", "ticker", "category", "offering_date", "offering_price", "exit_date", "exit_price", "holding_period_days", "total_return", "annualized_return", "premium_vs_last_trade", "initial_market_cap", "exit_market_cap", "realized_pl", "data_quality_flag"]
    return portfolio, pd.DataFrame(const_rows), e, pd.DataFrame(analytics).drop_duplicates() if analytics else pd.DataFrame(columns=analytics_columns)


def rebuild_total_return_indexes(assets=None, prices=None, exits=None, *, frequency: Frequency="native", rebalance: str="quarterly", weighting: str="all", output_dir: Path|None=None, **_: object):
    output_dir = output_dir or DATA_PROCESSED
    if assets is None: assets = pd.read_csv(DATA_PROCESSED / "canonical_asset_master.csv") if (DATA_PROCESSED / "canonical_asset_master.csv").exists() else pd.DataFrame()
    if prices is None: prices = pd.read_csv(DATA_PROCESSED / "price_history.csv") if (DATA_PROCESSED / "price_history.csv").exists() else pd.DataFrame()
    if exits is None: exits = pd.read_csv(DATA_PROCESSED / "rally_exits.csv") if (DATA_PROCESSED / "rally_exits.csv").exists() else pd.DataFrame()
    portfolio, constituents, exit_events, analytics = build_total_return_indexes(assets, prices, exits, frequency=frequency, config=TotalReturnConfig(rebalance_frequency=rebalance))
    if weighting in {"equal", "equal_weight"}: portfolio=portfolio[portfolio.weighting_method.eq("equal_weight")]; constituents=constituents[constituents.weighting_method.eq("equal_weight")]
    if weighting in {"cap", "market_cap", "market_cap_weight"}: portfolio=portfolio[portfolio.weighting_method.eq("market_cap_weight")]; constituents=constituents[constituents.weighting_method.eq("market_cap_weight")]
    ensure_dirs(); output_dir.mkdir(parents=True, exist_ok=True)
    for name, df in [("rally_exit_events", exit_events), ("index_portfolio_history", portfolio), ("index_constituent_history", constituents), ("exit_analytics", analytics)]:
        df.to_csv(output_dir / f"{name}.csv", index=False)
    return portfolio, constituents, exit_events, analytics

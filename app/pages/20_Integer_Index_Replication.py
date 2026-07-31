from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app")); sys.path.insert(0, str(ROOT / "src"))

from app_data import get_canonical_market, render_data_diagnostics
from alt_asset_explorer.integer_replication import (
    budget_allocation, minimum_capital_for_tolerance, normalize_target_weights,
    one_share_each_capital, select_prices_asof, simple_anchor_allocation,
    simulate_buy_and_hold, tracking_frontier,
)

st.set_page_config(page_title="Integer Index Replication | Rally Terminal", layout="wide")
render_data_diagnostics()
st.title("Integer Index Replication")
st.caption("Whole-share portfolio research from canonical authored Rally observations — not an executable trading tool or appraisal.")

market = get_canonical_market(); assets = market.asset_master.copy(); history = market.quarterly_prices.copy()
if assets.empty or history.empty:
    st.warning("Canonical assets and price observations are required."); st.stop()
assets["asset_id"] = assets["asset_id"].astype(str); history["asset_id"] = history["asset_id"].astype(str)
categories = sorted(assets["category"].dropna().astype(str).unique())

with st.sidebar:
    st.header("Construction")
    universe = st.selectbox("Universe", ["Full Rally market", "Category", "Custom basket"])
    category = st.selectbox("Category", categories, disabled=universe != "Category")
    include_exited = st.checkbox("Include exited assets", False)
    status = assets["status"].astype(str).str.lower()
    eligible = assets[include_exited | status.eq("trading")].copy()
    if universe == "Category": eligible = eligible[eligible["category"].eq(category)]
    if universe == "Custom basket":
        chosen = st.multiselect("Constituents", eligible["asset_id"], format_func=lambda x: f"{eligible.set_index('asset_id').get('ticker', pd.Series()).get(x, x)} · {x}")
        eligible = eligible[eligible["asset_id"].isin(chosen)]
    weighting = st.selectbox("Target weighting", ["Equal weight", "Market-cap weight"])
    launch_mode = st.radio("Launch handling", ["Common-universe", "Launch-aware"], help="Common-universe delays inception until all selected assets have a quote. Launch-aware excludes not-yet-launched assets without fabricating prices.")
    all_dates = pd.to_datetime(history["date"], errors="coerce").dropna()
    requested = st.date_input("Requested start date", value=all_dates.max().date() if not all_dates.empty else pd.Timestamp.today().date(), min_value=all_dates.min().date(), max_value=all_dates.max().date())
    stale_days = st.number_input("Stale-price warning (days)", 1, 730, 120)
    tolerance_metric = st.selectbox("Minimum-capital tolerance", ["maximum", "rmse", "absolute"])
    tolerance = st.number_input("Tolerance", 0.0001, 0.50, 0.01, format="%.4f")

ids = eligible["asset_id"].tolist()
selected, effective = select_prices_asof(history, ids, requested, mode="common" if launch_mode == "Common-universe" else "launch_aware", max_staleness_days=int(stale_days))
excluded = sorted(set(ids) - set(selected["asset_id"]))
if selected.empty:
    st.info("No eligible observations exist on or before this start date."); st.stop()
prices = selected.set_index("asset_id")["last"].astype(float)
if weighting == "Market-cap weight":
    caps = selected.set_index("asset_id").get("market_cap_usd", pd.Series(index=prices.index, dtype=float))
    target = normalize_target_weights(pd.to_numeric(caps, errors="coerce").fillna(0), prices.index)
else: target = normalize_target_weights(None, prices.index)

st.info(f"Requested **{pd.Timestamp(requested).date()}** · effective **{effective.date()}** · {len(prices)} eligible constituents. " + (f"{len(excluded)} lack an as-of price or have not launched." if excluded else "No selected constituents were excluded."))
if selected["is_stale"].any(): st.warning(f"{int(selected['is_stale'].sum())} inception quote(s) exceed the {stale_days}-day warning threshold.")

anchor = simple_anchor_allocation(prices, target)
minimum = minimum_capital_for_tolerance(prices, float(tolerance), target, metric=tolerance_metric)
one_each = one_share_each_capital(prices)
default_budget = max(anchor.invested, minimum.invested)
budget = st.number_input("Available starting cash", min_value=0.0, value=float(round(default_budget, 2)), step=100.0)
reserve = st.number_input("Minimum cash reserve", min_value=0.0, value=0.0, step=10.0)
bc1,bc2,bc3 = st.columns(3)
require_all=bc1.checkbox("Require every constituent",True); max_omitted=bc2.number_input("Maximum omitted",0,len(prices),0,disabled=require_all); objective=bc3.selectbox("Budget objective",["absolute","squared","maximum"])
tracker=budget_allocation(prices,budget,target,require_all=require_all,max_omitted=int(max_omitted),reserve=reserve,objective=objective)

metrics=st.columns(5)
metrics[0].metric("One share each",f"${one_each:,.0f}"); metrics[1].metric("Anchor capital",f"${anchor.invested:,.0f}"); metrics[2].metric("Tolerance-search capital",f"${minimum.invested:,.0f}"); metrics[3].metric("Budget feasible","Yes" if tracker.feasible else "No"); metrics[4].metric("Budget residual cash",f"${tracker.residual_cash:,.0f}")
st.caption("One-share-each capital, the maximum-price anchor, tolerance-search capital, and fixed-budget tracking are distinct quantities. The anchor and bounded searches are heuristics, not proofs of global optimality.")

method_name=st.radio("Displayed integer portfolio",["Simple maximum-price anchor","Minimum-capital tolerance search","Budget-constrained tracker"],horizontal=True)
allocation={"Simple maximum-price anchor":anchor,"Minimum-capital tolerance search":minimum,"Budget-constrained tracker":tracker}[method_name]
if not allocation.feasible: st.error("The selected construction is infeasible under its constraints."); st.stop()
simulation=simulate_buy_and_hold(history,allocation,target,start_date=effective,metadata=assets)
m=simulation.metrics; cols=st.columns(8)
for col,(label,key,is_money) in zip(cols,[("Starting cash","starting_cash",True),("Invested","invested_capital",True),("Residual cash","residual_cash",True),("Latest value","latest_value",True),("P&L","pnl",True),("Return","return",False),("Benchmark return","benchmark_return",False),("Tracking error","annualized_tracking_error",False)]):
    value=m.get(key,np.nan); col.metric(label,(f"${value:,.0f}" if is_money else f"{value:.1%}") if pd.notna(value) else "Unavailable")

table=simulation.constituents.merge(selected[["asset_id","date","staleness_days","is_stale"]],on="asset_id",how="left")
table["target_amount"]=allocation.budget*table["target_weight"]; table["dollar_deviation"]=table["invested_amount"]-table["target_amount"]
st.subheader("Constituents")
st.dataframe(table,hide_index=True,use_container_width=True,column_config={c:st.column_config.NumberColumn(format="%.2f%%") for c in ["target_weight","actual_weight","weight_deviation","return_contribution","current_weight"]})

weights=table[["asset_id","target_weight","actual_weight"]].melt("asset_id",var_name="Weight",value_name="value")
chart1,chart2=st.columns(2)
chart1.plotly_chart(px.bar(weights,x="asset_id",y="value",color="Weight",barmode="group",title="Target vs whole-share initial weights"),use_container_width=True)
chart2.plotly_chart(px.histogram(table,x="weight_deviation",title="Weight-deviation distribution"),use_container_width=True)
hist=simulation.history.melt("date",value_vars=["benchmark_value","holdings_value","portfolio_value"],var_name="Series",value_name="Value")
st.plotly_chart(px.line(hist,x="date",y="Value",color="Series",title="Fractional benchmark, holdings, and cash-inclusive portfolio"),use_container_width=True)
pnl=simulation.history.melt("date",value_vars=["benchmark_pnl","portfolio_pnl","replication_difference"],var_name="Series",value_name="Value")
st.plotly_chart(px.line(pnl,x="date",y="Value",color="Series",title="Cumulative P&L and replication difference"),use_container_width=True)

st.subheader("Tracking-error frontier")
budgets=np.geomspace(max(prices.min(),one_each*.5),max(default_budget*5,one_each*2),24)
frontier=tracking_frontier(prices,target,budgets)
y=st.selectbox("Frontier metric",["rmse","absolute","maximum"])
fig=px.line(frontier,x="budget",y=y,markers=True,title="Replication quality by available capital"); fig.add_vline(x=one_each,line_dash="dot",annotation_text="one each"); fig.add_vline(x=anchor.invested,line_dash="dash",annotation_text="anchor"); fig.add_vline(x=budget,annotation_text="selected")
st.plotly_chart(fig,use_container_width=True)
st.plotly_chart(px.bar(table.sort_values("dollar_pnl"),x="asset_id",y="dollar_pnl",title="Contribution to ending P&L"),use_container_width=True)

with st.expander("Methodology, assumptions, and limitations"):
    st.markdown(r"""
Whole-share constraints cause actual weights $w_i=q_iP_i/C$ to differ from target weights. Buying one of each costs $C_{one\ each}=\sum_iP_i$. The anchor uses the most expensive share as an equal-weight per-position target and independently chooses floor, nearest, or ceiling quantities with at least one share. The tolerance method searches a bounded ascending grid of budgets; the fixed-budget method greedily improves the chosen initial-weight loss. Both are deterministic **heuristics**, not global nonlinear optima.

The fractional series is the reference, not investable. Residual cash is explicitly included at zero return; holdings-only and total-portfolio weights therefore differ. Prices are the latest authored observations on or before inception, never future observations. Common-universe mode delays inception; launch-aware mode admits only assets already observed at inception. Quotes may be sparse, stale, non-executable, or affected by survivorship bias. Exited assets retain historical evidence but do not imply current listings. This research ignores liquidity, spreads, fees, taxes, order availability, settlement, and market impact; a theoretical backtest is not evidence that its transactions were achievable.
""")
    st.write("The current release evaluates buy-and-hold integer quantities. Periodic integer rebalancing remains deliberately gated until exit settlement and expanding-membership cash ledgers can reconcile exactly with the canonical total-return engine.")

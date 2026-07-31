from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "src"))

from app_data import get_canonical_market, render_data_diagnostics
from alt_asset_explorer.exchange_history import performance_summary

st.set_page_config(page_title="Exchange Market Cap & Performance", layout="wide")
render_data_diagnostics()
st.title("Exchange Market Cap & Performance")
st.caption("Tradable Rally exchange capitalization is separated from exit-aware investor total-return indexes. Analytics are calculated from canonical authored Rally inputs, not live Rally listings or committed derived snapshots.")

@st.cache_data(show_spinner=False)
def load_exchange_data():
    canonical_market = get_canonical_market()
    exchange = canonical_market.exchange_history
    return (
        exchange.market_cap_history,
        exchange.category_history,
        exchange.asset_history,
        exchange.data_quality_report,
        exchange.reconciliation_report,
        canonical_market.total_return_portfolio,
        canonical_market.total_return_constituents,
        canonical_market.exit_analytics,
        canonical_market.current_summary,
        pd.DataFrame(),
        pd.DataFrame(),
    )

market, category, asset, quality, recon, portfolio, constituents, exit_analytics, current_summary, current_recon, current_contrib = load_exchange_data()
if market.empty:
    st.warning("Exchange history could not be calculated from canonical authored inputs. Check `data/normalized/assets.csv` and `data/normalized/price_observations.csv`.")
    st.stop()

for frame in [market, category, asset, quality, recon, portfolio, constituents, exit_analytics]:
    if not frame.empty and "date" in frame:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")

with st.sidebar:
    st.header("Controls")
    frequency_label = st.selectbox("Reporting frequency label", ["native", "weekly", "monthly", "quarterly"], index=0)
    min_date, max_date = market["date"].min().date(), market["date"].max().date()
    date_range = st.date_input("Date range", (min_date, max_date), min_value=min_date, max_value=max_date)
    categories = sorted(category["category"].dropna().astype(str).unique()) if not category.empty else []
    selected_categories = st.multiselect("Categories", categories, default=categories)
    composition_view = st.radio("Category chart", ["Absolute market capitalization", "Percentage composition", "Indexed category performance"])
    direct_only = st.checkbox("Direct observations only", value=False)
    with st.expander("Advanced controls"):
        max_staleness = st.slider("Maximum displayed price age (days)", 0, 730, 120)
        group_small = st.checkbox("Group small categories as Other", value=False)
        small_threshold = st.slider("Other threshold", 0.0, 0.10, 0.02, 0.005)
        include_exited = st.checkbox("Include exited assets when present", value=True)
        weighting = st.radio("Performance index", ["Market-cap weighted", "Equal weighted"], horizontal=True)

start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[-1])
market_f = market[(market["date"] >= start) & (market["date"] <= end)].copy()
category_f = category[(category["date"] >= start) & (category["date"] <= end) & (category["category"].astype(str).isin(selected_categories))].copy()
asset_f = asset[(asset["date"] >= start) & (asset["date"] <= end)].copy() if not asset.empty else asset
if direct_only and not asset_f.empty:
    eligible_assets = asset_f[asset_f["is_direct_observation"].fillna(False)][["date", "asset_id"]]
    asset_f = asset_f.merge(eligible_assets, on=["date", "asset_id"], how="inner")
if not asset_f.empty:
    asset_f = asset_f[pd.to_numeric(asset_f["observation_age_days"], errors="coerce").fillna(0) <= max_staleness]

latest = market_f.iloc[-1]
summary = performance_summary(market_f, frequency=frequency_label)
cols = st.columns(6)
canonical_cap = float(current_summary.iloc[0].get("tradable_market_cap", latest["total_market_cap"])) if not current_summary.empty else float(latest["total_market_cap"])
canonical_count = int(current_summary.iloc[0].get("tradable_asset_count", latest["active_asset_count"])) if not current_summary.empty else int(latest["active_asset_count"])
cols[0].metric("Tradable Exchange Market Cap", f"${canonical_cap:,.0f}", help="Canonical current tradable value excludes stale carried-forward and offering-only valuations.")
cols[1].metric("Issued capital", f"${latest['cumulative_invested_capital']:,.0f}")
cols[2].metric("Flow-adjusted P/L", f"${latest['cumulative_flow_adjusted_pl']:,.0f}")
cols[3].metric("Since inception", f"{summary.get('since_inception_return', 0):.1%}")
cols[4].metric("Max drawdown", f"{summary.get('max_drawdown', 0):.1%}")
cols[5].metric("Direct coverage", f"{latest['direct_coverage_pct']:.1%}")
cols2 = st.columns(5)
cols2[0].metric("Current tradable assets", f"{canonical_count:,}")
cols2[1].metric("Categories", f"{len(selected_categories):,}")
cols2[2].metric("Latest observation", latest["date"].date().isoformat())
cols2[3].metric("Annualized return", "n/a" if summary.get("annualized_return") is None else f"{summary['annualized_return']:.1%}")
cols2[4].metric("Carried coverage", f"{latest['carried_forward_coverage_pct']:.1%}")

st.subheader("Tradable Exchange Market Cap")
fig = px.line(
    market_f,
    x="date",
    y="total_market_cap",
    hover_data={
        "total_market_cap": ":$,.0f",
        "new_issuance": ":$,.0f",
        "assets_added_count": True,
        "assets_added_since_last_plot": True,
        "active_asset_count": True,
        "direct_observation_asset_count": True,
        "carried_forward_asset_count": True,
        "direct_coverage_pct": ":.1%",
        "carried_forward_coverage_pct": ":.1%",
    },
    markers=True,
)
fig.update_traces(hoverlabel_align="left")
fig.update_yaxes(tickprefix="$", title="Tradable market cap")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Exchange Size vs Total-Return Investment Indexes")
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=market_f["date"], y=market_f["total_market_cap"], name="Market cap", yaxis="y1"))
if not portfolio.empty:
    fullp = portfolio[(portfolio["category"].astype(str).eq("all")) & (portfolio["rebalance_frequency"].astype(str).eq("quarterly"))]
    for method, label in [("equal_weight", "Equal-weighted total return"), ("market_cap_weight", "Cap-weighted total return")]:
        mp = fullp[fullp["weighting_method"].eq(method)]
        fig2.add_trace(go.Scatter(x=mp["date"], y=mp["index_level"], name=label, yaxis="y2"))
else:
    index_col = "return_index" if weighting == "Market-cap weighted" else "equal_weighted_index"
    fig2.add_trace(go.Scatter(x=market_f["date"], y=market_f[index_col], name=weighting + " legacy flow-adjusted index", yaxis="y2"))
fig2.update_layout(yaxis=dict(title="Market cap", tickprefix="$"), yaxis2=dict(title="Index level", overlaying="y", side="right"), legend=dict(orientation="h"))
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Category Decomposition")
plot_cat = category_f.copy()
if group_small and not plot_cat.empty:
    small = plot_cat["category_weight"].fillna(0) < small_threshold
    plot_cat.loc[small, "category"] = "Other"
    plot_cat = plot_cat.groupby(["date", "category"], as_index=False).agg(category_market_cap=("category_market_cap", "sum"), category_weight=("category_weight", "sum"), active_asset_count=("active_asset_count", "sum"), return_index=("return_index", "mean"))
y_col = {"Absolute market capitalization": "category_market_cap", "Percentage composition": "category_weight", "Indexed category performance": "return_index"}[composition_view]
fig3 = px.area(plot_cat, x="date", y=y_col, color="category", hover_data=["category_market_cap", "category_weight", "active_asset_count"])
if y_col == "category_market_cap": fig3.update_yaxes(tickprefix="$")
if y_col == "category_weight": fig3.update_yaxes(tickformat=".0%")
st.plotly_chart(fig3, use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Latest Market-Cap Change Decomposition")
    period = market_f.iloc[-1]
    waterfall = pd.DataFrame({"component": ["Beginning", "Price effect", "New issuance", "Removed", "Adjustments", "Ending"], "value": [period["prior_market_cap"], period["price_effect"], period["new_issuance"], -period["removed_capital"], period["other_adjustments"], period["total_market_cap"]]})
    st.plotly_chart(px.bar(waterfall, x="component", y="value", text_auto=".2s"), use_container_width=True)
with right:
    st.subheader("Category Contributions")
    contrib = category_f.groupby("category", as_index=False).agg(price_effect=("price_effect", "sum"), new_issuance=("new_issuance", "sum"), market_cap_change=("category_market_cap", "last"))
    st.plotly_chart(px.bar(contrib.sort_values("price_effect"), x="price_effect", y="category", orientation="h", hover_data=["new_issuance", "market_cap_change"]), use_container_width=True)


if not portfolio.empty:
    tr_tab, exit_tab, audit_tab = st.tabs(["Total-Return Indexes", "Exit Activity", "Audit Trail"])
    with tr_tab:
        st.subheader("Exit-Aware Total-Return Indexes")
        tr_categories = ["all"] + sorted([c for c in portfolio["category"].dropna().astype(str).unique() if c != "all"])
        sel_cat = st.selectbox("Category", tr_categories, format_func=lambda v: "Full market" if v == "all" else v.replace("_", " ").title(), key="exchange_tr_category")
        if "universe_scope" not in portfolio:
            portfolio["universe_scope"] = "include_exited"
        scope_options = [scope for scope in ["include_exited", "active_only"] if scope in set(portfolio["universe_scope"].dropna().astype(str))]
        sel_scope = st.selectbox("Universe scope", scope_options or ["include_exited"], format_func=lambda v: "Include exited" if v == "include_exited" else "Active only", key="exchange_tr_scope")
        available_rebalances = [item for item in ["quarterly", "monthly", "weekly"] if item in set(portfolio["rebalance_frequency"].dropna().astype(str))]
        sel_rebal = st.selectbox("Rebalance", available_rebalances or sorted(portfolio["rebalance_frequency"].dropna().unique()), key="exchange_tr_rebal")
        tr = portfolio[portfolio["category"].astype(str).eq(sel_cat) & portfolio["rebalance_frequency"].astype(str).eq(sel_rebal) & portfolio["universe_scope"].astype(str).eq(sel_scope)].copy()
        wide = tr.pivot_table(index="date", columns="weighting_method", values="index_level", aggfunc="last").reset_index().rename(columns={"equal_weight":"Equal-weighted total return", "market_cap_weight":"Market-cap-weighted total return"})
        st.plotly_chart(px.line(wide, x="date", y=[c for c in wide.columns if c != "date"], markers=True), use_container_width=True)
        st.plotly_chart(px.area(tr, x="date", y=["cash_value", "pending_settlement_value"], facet_row="weighting_method", title="Cash and pending settlement balances"), use_container_width=True)
        st.plotly_chart(px.line(tr, x="date", y=["active_constituent_count", "eligible_constituent_count", "exited_constituent_count"], color="weighting_method", title="Constituent counts"), use_container_width=True)
    with exit_tab:
        st.subheader("Exit Activity")
        if exit_analytics.empty:
            st.info("No linked realized exit analytics are available in the current artifact.")
        else:
            st.plotly_chart(px.scatter(exit_analytics, x="exit_date", y="exit_price", color="category", size="exit_market_cap", hover_data=["asset_id", "total_return", "premium_vs_last_trade", "annualized_return"]), use_container_width=True)
            st.dataframe(exit_analytics, use_container_width=True)
    with audit_tab:
        st.subheader("Downloadable Portfolio and Constituent Audit")
        st.dataframe(tr.sort_values(["date", "weighting_method"]).tail(200), use_container_width=True)
        st.download_button("Download portfolio history", portfolio.to_csv(index=False), "index_portfolio_history.csv")
        st.download_button("Download constituent history", constituents.to_csv(index=False), "index_constituent_history.csv")
        st.download_button("Download exit analytics", exit_analytics.to_csv(index=False), "exit_analytics.csv")

with st.expander("Data quality and current-universe reconciliation", expanded=False):
    st.dataframe(quality[(quality["date"] >= start) & (quality["date"] <= end)], use_container_width=True)
    if not current_contrib.empty:
        st.write("Top current market-cap differences between legacy homepage and exchange-history universes")
        st.dataframe(current_contrib.head(20), use_container_width=True)
        st.download_button("Download full current-universe reconciliation", current_recon.to_csv(index=False), "current_universe_reconciliation.csv")
        st.download_button("Download market-cap difference contributors", current_contrib.to_csv(index=False), "current_market_cap_difference_contributors.csv")
    st.plotly_chart(px.bar(market_f, x="date", y=["direct_observation_market_cap", "carried_forward_market_cap"], title="Direct vs carried-forward market cap"), use_container_width=True)

with st.expander("Methodology", expanded=False):
    st.markdown("""
* **Tradable exchange market cap** is price × shares outstanding for assets active and tradable on each reporting date; it is exchange size, not investor return.
* **Total-return indexes** start at 100, hold constituent units, preserve terminal proceeds, hold pending settlement separately, and reinvest cash at the next scheduled rebalance.
* **Price selection** uses same-date observations first, then prior observations only; offering price is used on the offering date when no secondary observation exists. Future observations are never used.
* **Staleness** is flagged when the carried observation age exceeds the configured threshold.
* **New issuance** is the first reconstructed market cap for assets entering the series.
* **Price effect** is the period price change for assets already present, multiplied by shares outstanding.
* **Removed capital** is reserved for terminal-event removals; current committed exit linkage is sparse.
* **Flow-adjusted return** removes net external flows from ending market value before comparing with prior market cap and chains the result from 100.
* **Equal-weighted index** averages active asset returns; **market-cap-weighted index** uses the flow-adjusted exchange return.
* **Category decomposition** dynamically groups by the canonical category field and reconciles back to total market cap.
""")

with st.expander("Exports", expanded=False):
    st.download_button("Download total exchange history", market_f.to_csv(index=False), "exchange_market_cap_history_filtered.csv")
    st.download_button("Download category history", category_f.to_csv(index=False), "exchange_category_history_filtered.csv")
    st.download_button("Download asset history", asset_f.to_csv(index=False), "exchange_asset_history_filtered.csv")
    st.download_button("Download data-quality report", quality.to_csv(index=False), "exchange_data_quality_report.csv")
    st.download_button("Download reconciliation report", recon.to_csv(index=False), "exchange_reconciliation_report.csv")

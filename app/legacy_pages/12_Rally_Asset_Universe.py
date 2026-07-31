from __future__ import annotations

import plotly.express as px
import streamlit as st

from app_data import empty_state, load_processed_csv, render_data_diagnostics


st.set_page_config(page_title="Rally Asset Universe", layout="wide")
st.title("Rally Asset Universe")
render_data_diagnostics()
st.caption("Research dashboard using Rally portfolio captures for live trading fields and SEC filings for offering/exited asset context. Not financial advice.")

decision = load_processed_csv("rally_asset_decision_universe", required=True)
matches = load_processed_csv("asset_comp_matches")
comps = load_processed_csv("comparable_sales_universe")
diagnostics = load_processed_csv("data_diagnostics")

if decision.empty:
    empty_state()
    st.stop()

for column in (
    "current_market_cap_usd",
    "estimated_nav_usd",
    "discount_to_secondary_nav",
    "premium_to_offering",
    "nav_confidence",
    "liquidity_score",
    "mispricing_score",
    "comp_count",
):
    if column in decision:
        decision[column] = decision[column].astype("float64", errors="ignore")

focus = st.query_params.get("focus", "")
if isinstance(focus, list):
    focus = focus[0] if focus else ""

with st.sidebar:
    st.subheader("Universe filters")
    category_options = sorted(decision["category"].dropna().astype(str).unique().tolist()) if "category" in decision else []
    subcategory_options = sorted(decision["subcategory"].dropna().astype(str).unique().tolist()) if "subcategory" in decision else []
    model_options = sorted(decision["model"].dropna().astype(str).unique().tolist()) if "model" in decision else []
    status_options = sorted(decision["status"].dropna().astype(str).unique().tolist()) if "status" in decision else []
    hermes_subcategories = [value for value in subcategory_options if value.startswith("hermes_")]
    default_categories = ["handbags"] if focus == "hermes" and "handbags" in category_options else category_options
    default_subcategories = hermes_subcategories if focus == "hermes" else subcategory_options
    selected_categories = st.multiselect("Category", category_options, default=default_categories)
    selected_subcategories = st.multiselect("Subcategory", subcategory_options, default=default_subcategories)
    selected_models = st.multiselect("Model", model_options, default=model_options)
    selected_statuses = st.multiselect("Status", status_options, default=status_options)

filtered = decision.copy()
if selected_categories:
    filtered = filtered[filtered["category"].astype(str).isin(selected_categories)]
if selected_subcategories:
    filtered = filtered[filtered["subcategory"].astype(str).isin(selected_subcategories)]
if selected_models:
    filtered = filtered[filtered["model"].fillna("").astype(str).isin(selected_models)]
if selected_statuses:
    filtered = filtered[filtered["status"].astype(str).isin(selected_statuses)]

if filtered.empty:
    st.info("No assets match the current filters.")
    st.stop()

metric_cols = st.columns(5)
metric_cols[0].metric("Rally assets", f"{len(filtered):,}")
metric_cols[1].metric("Comparable sales", f"{len(comps):,}")
metric_cols[2].metric("Assets without comps", f"{int((filtered['comp_count'].fillna(0) == 0).sum()):,}")
metric_cols[3].metric("Median NAV confidence", f"{filtered['nav_confidence'].fillna(0).median():.0%}")
metric_cols[4].metric("Best score", f"{filtered['mispricing_score'].fillna(0).max():.1f}")

st.subheader("MME-Style Opportunity Map")
scatter = filtered.copy()
scatter["plot_size"] = scatter["current_market_cap_usd"].fillna(scatter["offering_market_cap_usd"]).fillna(1).clip(lower=1)
if scatter["discount_to_secondary_nav"].notna().any():
    fig = px.scatter(
        scatter,
        x="discount_to_secondary_nav",
        y="nav_confidence",
        size="plot_size",
        color="subcategory",
        hover_name="name",
        hover_data={
            "ticker": True,
            "status": True,
            "estimated_nav_usd": ":,.0f",
            "current_market_cap_usd": ":,.0f",
            "comp_count": True,
            "liquidity_score": ":.2f",
            "plot_size": False,
        },
        symbol="status",
        labels={
            "discount_to_secondary_nav": "Discount / premium to secondary NAV",
            "nav_confidence": "NAV confidence",
            "subcategory": "subcategory",
        },
    )
    fig.add_vline(x=0, line_dash="dash", line_color="#666")
    fig.update_layout(yaxis_tickformat=".0%", xaxis_tickformat=".0%", height=520)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No estimated NAV values yet. Add matched realized-sale comps to populate the opportunity map.")

st.subheader("Rally Market Cap vs Estimated Secondary NAV")
nav_view = filtered.dropna(subset=["current_market_cap_usd", "estimated_nav_usd"]).copy()
if not nav_view.empty:
    nav_view["plot_size"] = nav_view["current_market_cap_usd"].fillna(nav_view["offering_market_cap_usd"]).fillna(1).clip(lower=1)
    fig = px.scatter(
        nav_view,
        x="estimated_nav_usd",
        y="current_market_cap_usd",
        color="category",
        size="plot_size",
        hover_name="name",
        hover_data=["ticker", "model", "size", "material", "comp_count", "nav_confidence"],
        labels={"estimated_nav_usd": "Estimated secondary NAV", "current_market_cap_usd": "Rally market cap"},
    )
    max_axis = max(nav_view["estimated_nav_usd"].max(), nav_view["current_market_cap_usd"].max())
    fig.add_shape(type="line", x0=0, x1=max_axis, y0=0, y1=max_axis, line={"dash": "dash", "color": "#666"})
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No Rally asset has both market cap and estimated NAV yet.")

st.subheader("Exited Assets: Offering Cap vs Exit Cap")
exit_view = filtered.dropna(subset=["offering_market_cap_usd", "exit_market_cap_usd"]).copy()
if not exit_view.empty:
    exit_view["exit_return_vs_offering"] = exit_view["exit_market_cap_usd"] / exit_view["offering_market_cap_usd"] - 1
    exit_view["plot_size"] = exit_view["exit_market_cap_usd"].clip(lower=1)
    fig = px.scatter(
        exit_view,
        x="offering_market_cap_usd",
        y="exit_market_cap_usd",
        color="subcategory",
        size="plot_size",
        hover_name="name",
        hover_data={"ticker": True, "exit_date": True, "exit_return_vs_offering": ":.1%", "plot_size": False},
        labels={"offering_market_cap_usd": "Offering market cap", "exit_market_cap_usd": "Exit market cap"},
    )
    max_axis = max(exit_view["offering_market_cap_usd"].max(), exit_view["exit_market_cap_usd"].max())
    fig.add_shape(type="line", x0=0, x1=max_axis, y0=0, y1=max_axis, line={"dash": "dash", "color": "#666"})
    fig.update_layout(height=460)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No filtered exited assets have both offering and exit values.")

left, right = st.columns([1.15, 0.85])

with left:
    st.subheader("Rally Asset Table")
    table_cols = [
        "ticker",
        "name",
        "status",
        "brand",
        "model",
        "size",
        "material",
        "current_market_cap_usd",
        "estimated_nav_usd",
        "discount_to_secondary_nav",
        "premium_to_offering",
        "comp_count",
        "nav_confidence",
        "mispricing_score",
    ]
    st.dataframe(
        filtered[[col for col in table_cols if col in filtered.columns]].sort_values("mispricing_score", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

with right:
    st.subheader("Active Discount / Premium Leaderboard")
    leaderboard_cols = ["ticker", "name", "discount_to_secondary_nav", "nav_confidence", "comp_count", "mispricing_score"]
    active = filtered[filtered["status"].astype(str) == "trading"]
    st.dataframe(
        active[[col for col in leaderboard_cols if col in active.columns]].sort_values("discount_to_secondary_nav", na_position="last"),
        use_container_width=True,
        hide_index=True,
    )

st.subheader("Exit Return Leaderboard")
if not exit_view.empty:
    exit_cols = ["ticker", "name", "exit_date", "offering_market_cap_usd", "exit_market_cap_usd", "exit_return_vs_offering"]
    st.dataframe(exit_view[exit_cols].sort_values("exit_return_vs_offering", ascending=False), use_container_width=True, hide_index=True)
else:
    st.info("No exited assets in the current filter.")

st.subheader("Data Coverage")
coverage = filtered[["ticker", "name", "category", "subcategory", "status"]].copy()
coverage["has_live_market_cap"] = filtered["current_market_cap_usd"].notna()
coverage["has_sec_fundamentals"] = filtered["sec_filing_url"].notna()
coverage["has_exit_data"] = filtered["exit_market_cap_usd"].notna()
coverage["has_comps"] = filtered["comp_count"].fillna(0) > 0
coverage["source_url"] = filtered["sec_filing_url"]
st.dataframe(coverage.sort_values(["category", "ticker"]), use_container_width=True, hide_index=True)

st.subheader("Best Matched Comps")
asset_options = filtered["ticker"].fillna(filtered["asset_id"]).tolist()
selected = st.selectbox("Rally asset", asset_options)
selected_asset = filtered[filtered["ticker"].fillna(filtered["asset_id"]) == selected].iloc[0]
asset_matches = matches[matches["ticker"] == selected].copy() if not matches.empty and "ticker" in matches else matches.iloc[0:0]
if asset_matches.empty:
    st.info("No matched realized-sale comps for this asset yet.")
else:
    detail = asset_matches.merge(
        comps[["comp_id", "brand", "model", "size", "material", "color", "hardware", "estimate_low_usd", "estimate_high_usd", "confidence_score"]],
        on="comp_id",
        how="left",
    )
    st.caption(
        f"{selected_asset['name']} | estimated NAV: {selected_asset.get('estimated_nav_usd', 0):,.0f} | "
        f"confidence: {selected_asset.get('nav_confidence', 0):.0%}"
    )
    st.dataframe(detail.sort_values("rank").head(20), use_container_width=True, hide_index=True)

st.subheader("Data Completeness Diagnostics")
if diagnostics.empty:
    st.info("Diagnostics have not been generated yet.")
else:
    st.dataframe(diagnostics, use_container_width=True, hide_index=True)

from __future__ import annotations

import plotly.express as px
import streamlit as st

from app_data import empty_state, load_processed_csv, render_data_diagnostics


st.set_page_config(page_title="Hermes Comparison", layout="wide")
st.title("Hermes Comparison")
render_data_diagnostics()
st.caption(
    "Expanded Rally Hermès view. Includes Birkin assets and adjacent Hermès context such as Picnic Kelly; "
    "research only, not financial advice. Rally source context links back to SEC filings where available."
)

decision = load_processed_csv("rally_asset_decision_universe", required=True)
matches = load_processed_csv("asset_comp_matches")
comps = load_processed_csv("comparable_sales_universe")

if decision.empty:
    empty_state()
    st.stop()

hermes = decision[
    decision["subcategory"].fillna("").astype(str).str.startswith("hermes_")
    | decision["brand"].fillna("").astype(str).str.lower().eq("hermes")
].copy()

if hermes.empty:
    st.info("No Hermès Rally assets are available yet. Rebuild the dataset after SEC and Rally imports.")
    st.stop()

for column in (
    "current_market_cap_usd",
    "offering_market_cap_usd",
    "exit_market_cap_usd",
    "estimated_nav_usd",
    "discount_to_secondary_nav",
    "nav_confidence",
    "mispricing_score",
    "comp_count",
):
    if column in hermes:
        hermes[column] = hermes[column].astype("float64", errors="ignore")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Hermès Rally assets", f"{len(hermes):,}")
c2.metric("Birkin rows", f"{int((hermes['model'].fillna('') == 'Birkin').sum()):,}")
c3.metric("Kelly/context rows", f"{int((hermes['model'].fillna('') != 'Birkin').sum()):,}")
c4.metric("Exited rows", f"{int((hermes['status'].fillna('') == 'exited').sum()):,}")

st.link_button("Open Hermès slice in Rally Asset Universe", "/Rally_Asset_Universe?focus=hermes")

st.subheader("Hermès Opportunity Map")
scatter = hermes.copy()
scatter["plot_size"] = scatter["current_market_cap_usd"].fillna(scatter["offering_market_cap_usd"]).fillna(scatter["exit_market_cap_usd"]).fillna(1).clip(lower=1)
if scatter["estimated_nav_usd"].notna().any():
    fig = px.scatter(
        scatter,
        x="estimated_nav_usd",
        y="current_market_cap_usd",
        color="model",
        symbol="status",
        size="plot_size",
        hover_name="name",
        hover_data={
            "ticker": True,
            "subcategory": True,
            "offering_market_cap_usd": ":,.0f",
            "exit_market_cap_usd": ":,.0f",
            "comp_count": True,
            "nav_confidence": ":.0%",
            "plot_size": False,
        },
        labels={"estimated_nav_usd": "Estimated secondary NAV", "current_market_cap_usd": "Current Rally market cap"},
    )
    live = scatter.dropna(subset=["current_market_cap_usd", "estimated_nav_usd"])
    if not live.empty:
        max_axis = max(live["estimated_nav_usd"].max(), live["current_market_cap_usd"].max())
        fig.add_shape(type="line", x0=0, x1=max_axis, y0=0, y1=max_axis, line={"dash": "dash", "color": "#666"})
    fig.update_layout(height=520)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No Hermès NAV estimates are available yet.")

st.subheader("Offering vs Exit Values")
exits = hermes.dropna(subset=["offering_market_cap_usd", "exit_market_cap_usd"]).copy()
if not exits.empty:
    exits["exit_return_vs_offering"] = exits["exit_market_cap_usd"] / exits["offering_market_cap_usd"] - 1
    exits["plot_size"] = exits["exit_market_cap_usd"].clip(lower=1)
    fig = px.scatter(
        exits,
        x="offering_market_cap_usd",
        y="exit_market_cap_usd",
        color="model",
        size="plot_size",
        hover_name="name",
        hover_data={"ticker": True, "exit_date": True, "exit_return_vs_offering": ":.1%", "plot_size": False},
        labels={"offering_market_cap_usd": "Offering market cap", "exit_market_cap_usd": "Exit market cap"},
    )
    max_axis = max(exits["offering_market_cap_usd"].max(), exits["exit_market_cap_usd"].max())
    fig.add_shape(type="line", x0=0, x1=max_axis, y0=0, y1=max_axis, line={"dash": "dash", "color": "#666"})
    fig.update_layout(height=460)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No Hermès exited assets with offering and exit values yet.")

left, right = st.columns([1.1, 0.9])
with left:
    st.subheader("Hermès Rally Rows")
    cols = [
        "ticker",
        "name",
        "status",
        "model",
        "size",
        "material",
        "color",
        "offering_market_cap_usd",
        "current_market_cap_usd",
        "exit_market_cap_usd",
        "estimated_nav_usd",
        "nav_confidence",
    ]
    st.dataframe(hermes[[col for col in cols if col in hermes]].sort_values(["model", "ticker"]), use_container_width=True, hide_index=True)

with right:
    st.subheader("Model Coverage")
    coverage = (
        hermes.groupby(["model", "status"], dropna=False, as_index=False)
        .agg(
            assets=("ticker", "count"),
            with_live_market_cap=("current_market_cap_usd", lambda values: int(values.notna().sum())),
            with_exits=("exit_market_cap_usd", lambda values: int(values.notna().sum())),
            median_nav_confidence=("nav_confidence", "median"),
        )
        .sort_values(["model", "status"])
    )
    st.dataframe(coverage, use_container_width=True, hide_index=True)

st.subheader("Best Matched Hermès Comps")
selected = st.selectbox("Hermès asset", hermes["ticker"].tolist())
asset_matches = matches[matches["ticker"] == selected].copy() if not matches.empty and "ticker" in matches else matches.iloc[0:0]
if asset_matches.empty:
    st.info("No matched realized-sale comps for this Hermès asset yet.")
else:
    detail = asset_matches.merge(
        comps[["comp_id", "brand", "model", "size", "material", "color", "hardware", "realized_price_usd", "confidence_score"]],
        on="comp_id",
        how="left",
    )
    st.dataframe(detail.sort_values("rank").head(20), use_container_width=True, hide_index=True)

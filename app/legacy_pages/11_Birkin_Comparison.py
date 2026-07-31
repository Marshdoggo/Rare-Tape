from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import empty_state, load_processed_csv, render_data_diagnostics

st.set_page_config(page_title="Birkin Comparison", layout="wide")
render_data_diagnostics()
st.title("Birkin Comparison")
st.caption("Birkin-only Rally vs Sotheby's view. Picnic/Kelly context lives in the Hermès Comparison page. Research only, not financial advice.")

comparison = load_processed_csv("birkin_comparison")
summary = load_processed_csv("birkin_summary")

if comparison.empty:
    empty_state()
else:
    rally = comparison[comparison["record_type"].isin(["rally_asset", "rally_sec_series"])].copy()
    comps = comparison[comparison["record_type"] == "sothebys_comp"].copy()
    sothebys = comps[comps["price_usd"].notna()].copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rally/SEC Birkin Rows", len(rally))
    c2.metric("Sotheby's Birkin Comps", len(sothebys))
    c3.metric("Avg Sotheby's Sale", f"${sothebys['price_usd'].mean():,.0f}" if not sothebys.empty else "n/a")
    c4.metric("Newest Comp", str(sothebys["date"].max()) if not sothebys.empty else "n/a")

    if not summary.empty and pd.notna(summary.iloc[0].get("secondary_nav_usd")):
        nav = float(summary.iloc[0]["secondary_nav_usd"])
        confidence = float(summary.iloc[0].get("nav_confidence") or 0)
        st.subheader("Simple Secondary NAV Heuristic")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Secondary NAV", f"${nav:,.0f}")
        m2.metric("NAV Low", f"${float(summary.iloc[0]['nav_low_usd']):,.0f}")
        m3.metric("NAV High", f"${float(summary.iloc[0]['nav_high_usd']):,.0f}")
        m4.metric("Confidence", f"{confidence:.0%}")

        rally_assets = rally[rally["record_type"] == "rally_asset"].dropna(subset=["market_cap_usd"])
        if not rally_assets.empty:
            discounts = rally_assets[["ticker", "name", "market_cap_usd"]].copy()
            discounts["secondary_nav_usd"] = nav
            discounts["discount_to_secondary_nav"] = (nav - discounts["market_cap_usd"]) / nav
            st.dataframe(discounts, use_container_width=True, hide_index=True)

        if int(summary.iloc[0].get("comp_count") or 0) < 5:
            st.warning("Sparse comp set: use this as a visualization and sanity check, not a robust valuation model.")
    else:
        st.info("Not enough realized Sotheby's Birkin comps yet to estimate secondary NAV.")

    st.subheader("Rally Market Cap vs Sotheby's Realized Sales")
    if not sothebys.empty:
        fig = px.scatter(
            sothebys,
            x="date",
            y="price_usd",
            color="size",
            symbol="is_exotic",
            hover_name="name",
            hover_data={
                "material": True,
                "year": True,
                "lot_id": True,
                "auction_name": True,
                "estimate_low_usd": ":$,.0f",
                "estimate_high_usd": ":$,.0f",
                "source_confidence": ":.0%",
            },
            title="Sotheby's Birkin Realized Sales",
            labels={"price_usd": "realized sale price", "date": "sale date", "is_exotic": "exotic material"},
        )
        for _, row in rally[rally["record_type"] == "rally_asset"].dropna(subset=["market_cap_usd"]).iterrows():
            fig.add_trace(
                go.Scatter(
                    x=[sothebys["date"].min(), sothebys["date"].max()],
                    y=[row["market_cap_usd"], row["market_cap_usd"]],
                    mode="lines",
                    name=f"Rally market cap: {row.get('ticker') or row.get('name')}",
                    line={"dash": "dash"},
                )
            )
        st.plotly_chart(fig, use_container_width=True)

        fig_box = px.box(
            sothebys,
            x="size",
            y="price_usd",
            color="is_exotic",
            points="all",
            hover_name="name",
            title="Sotheby's Birkin Sale Distribution by Size",
            labels={"price_usd": "realized sale price", "size": "Birkin size", "is_exotic": "exotic material"},
        )
        st.plotly_chart(fig_box, use_container_width=True)
    else:
        st.info("No realized Sotheby's Birkin comps processed yet.")

    st.subheader("Comp Coverage")
    if not sothebys.empty:
        coverage = (
            sothebys.groupby(["size", "material", "is_exotic"], dropna=False, as_index=False)
            .agg(
                comps=("price_usd", "count"),
                avg_price_usd=("price_usd", "mean"),
                min_price_usd=("price_usd", "min"),
                max_price_usd=("price_usd", "max"),
                newest_sale=("date", "max"),
                avg_confidence=("source_confidence", "mean"),
            )
            .sort_values(["comps", "avg_price_usd"], ascending=[False, False])
        )
        st.dataframe(coverage, use_container_width=True, hide_index=True)

    st.subheader("Birkin Comparison Rows")
    st.dataframe(comparison, use_container_width=True, hide_index=True)

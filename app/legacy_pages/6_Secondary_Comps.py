from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import empty_state, load_processed_csv, render_data_diagnostics

st.set_page_config(page_title="Secondary Comps", layout="wide")
render_data_diagnostics()
st.title("Secondary Comps")
comps = load_processed_csv("comps_normalized", required=True)
market_context = load_processed_csv("market_context")
if not comps.empty:
    category = st.selectbox("Category", ["all"] + sorted(comps["category"].dropna().unique().tolist()))
    if category != "all":
        comps = comps[comps["category"] == category]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Comparable Sales", len(comps))
    c2.metric("Sources", comps["source"].nunique() if "source" in comps else 0)
    c3.metric("Avg Match Quality", f"{comps['exactness_score'].mean():.0%}" if "exactness_score" in comps and not comps.empty else "n/a")
    c4.metric("Avg Source Confidence", f"{comps['source_confidence'].mean():.0%}" if "source_confidence" in comps and not comps.empty else "n/a")

    if not comps.empty:
        group_cols = [col for col in ["category", "source", "source_access", "price_type"] if col in comps.columns]
        source_summary = (
            comps.groupby(group_cols, as_index=False)
            .agg(
                comps=("comp_id", "count"),
                avg_price_usd=("price_usd", "mean"),
                avg_exactness=("exactness_score", "mean"),
                avg_source_confidence=("source_confidence", "mean"),
            )
            .sort_values(["category", "comps"], ascending=[True, False])
        )
        st.subheader("Source Coverage")
        st.dataframe(source_summary, use_container_width=True, hide_index=True)

    st.subheader("Comparable Sales")
    st.dataframe(comps, use_container_width=True, hide_index=True)
else:
    empty_state()

st.subheader("Market Context")
if market_context.empty:
    st.info("No Chrono24 or other market context rows processed yet.")
else:
    st.dataframe(market_context, use_container_width=True, hide_index=True)

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import empty_state, load_processed_csv, render_data_diagnostics

st.set_page_config(page_title="Rally Assets", layout="wide")
render_data_diagnostics()
st.title("Rally Assets")
assets = load_processed_csv("assets", required=True)
navs = load_processed_csv("nav_estimates")
scores = load_processed_csv("scores")
sec_series = load_processed_csv("rally_sec_series")
if assets.empty:
    empty_state()
else:
    category = st.selectbox("Category", ["all"] + sorted(assets["category"].unique().tolist()))
    view = assets.merge(navs, on="asset_id", how="left").merge(scores, on=["asset_id", "ticker"], how="left")
    if category != "all":
        view = view[view["category"] == category]
    st.dataframe(view, use_container_width=True, hide_index=True)

st.subheader("SEC Filing Coverage")
if sec_series.empty:
    st.info("No cached SEC filing rows yet. Run `SEC_USER_AGENT=\"YourApp/0.1 email@example.com\" python3 scripts/fetch_sec_data.py --max-filings 40`.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SEC Rows", len(sec_series))
    c2.metric("Forms", sec_series["filing_type"].nunique())
    c3.metric("Series Names", sec_series["series_name"].dropna().nunique())
    c4.metric("Exit-Flagged Rows", int((sec_series["status"] == "exit").sum()) if "status" in sec_series else 0)
    st.dataframe(sec_series.sort_values("filing_date", ascending=False), use_container_width=True, hide_index=True)

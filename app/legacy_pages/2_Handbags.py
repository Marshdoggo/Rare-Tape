from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import empty_state, load_processed_csv, render_data_diagnostics

st.set_page_config(page_title="Handbags", layout="wide")
render_data_diagnostics()
st.title("Handbags")
assets = load_processed_csv("assets", required=True)
comps = load_processed_csv("comps_normalized")
navs = load_processed_csv("nav_estimates")
if assets.empty:
    empty_state()
else:
    handbags = assets[assets["category"] == "handbags"].merge(navs, on="asset_id", how="left")
    st.dataframe(handbags, use_container_width=True, hide_index=True)
    st.plotly_chart(px.scatter(handbags, x="market_cap_usd", y="estimated_nav_usd", color="subcategory", hover_name="ticker", title="Market Cap vs Estimated NAV"), use_container_width=True)
    st.subheader("Handbag Comps")
    if comps.empty:
        st.info("No handbag comps processed yet.")
    else:
        st.dataframe(comps[comps["category"] == "handbags"], use_container_width=True, hide_index=True)

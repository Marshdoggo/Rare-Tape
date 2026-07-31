from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import empty_state, load_processed_csv, render_data_diagnostics

st.set_page_config(page_title="Liquidity", layout="wide")
render_data_diagnostics()
st.title("Liquidity")
liquidity = load_processed_csv("liquidity_metrics", required=True)
prices = load_processed_csv("price_history")
if liquidity.empty:
    empty_state()
else:
    st.dataframe(liquidity, use_container_width=True, hide_index=True)
    if prices.empty:
        st.info("No price history processed yet.")
    else:
        st.plotly_chart(px.line(prices, x="date", y="last", color="asset_id", title="Price History"), use_container_width=True)

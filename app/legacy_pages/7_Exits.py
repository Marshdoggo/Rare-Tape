from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import load_processed_csv, render_data_diagnostics

st.set_page_config(page_title="Exits", layout="wide")
render_data_diagnostics()
st.title("Exits")
exits = load_processed_csv("rally_exits")
if exits.empty:
    st.info("No processed exit events yet. SEC parser output will appear here when available.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Exit Events", len(exits))
    c2.metric("Total Reported Sale Price", f"${exits['sale_price'].sum():,.0f}" if "sale_price" in exits else "n/a")
    c3.metric("Unique Series", exits["series_name"].dropna().nunique() if "series_name" in exits else 0)
    st.dataframe(exits, use_container_width=True, hide_index=True)
    if "realized_return" in exits:
        st.plotly_chart(px.histogram(exits, x="realized_return", title="Exit IRR / Realized Return Histogram"), use_container_width=True)

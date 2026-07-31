from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import empty_state, load_processed_csv, render_data_diagnostics

st.set_page_config(page_title="Watches", layout="wide")
render_data_diagnostics()
st.title("Watches")
assets = load_processed_csv("assets", required=True)
comps = load_processed_csv("comps_normalized")
if assets.empty:
    empty_state()
else:
    st.dataframe(assets[assets["category"] == "watches"], use_container_width=True, hide_index=True)
    st.subheader("Watch Comps")
    if comps.empty:
        st.info("No watch comps processed yet.")
    else:
        st.dataframe(comps[comps["category"] == "watches"], use_container_width=True, hide_index=True)

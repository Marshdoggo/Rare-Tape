from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import DATA_PROCESSED, empty_state, render_data_diagnostics

st.set_page_config(page_title="MME Export", layout="wide")
render_data_diagnostics()
st.title("MME Export")
path = DATA_PROCESSED / "universe_export.csv"
if path.exists():
    export = pd.read_csv(path)
    st.dataframe(export, use_container_width=True, hide_index=True)
    st.download_button("Download universe_export.csv", path.read_bytes(), file_name="universe_export.csv")
else:
    empty_state()

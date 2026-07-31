import streamlit as st
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import render_data_diagnostics

st.set_page_config(page_title="Cards & Memorabilia", layout="wide")
render_data_diagnostics()
st.title("Cards & Memorabilia")
st.info("Manual card and memorabilia comps can be added to `data/raw/comps_seed.csv`; permitted downloadable sources should be normalized into the standard comps table.")

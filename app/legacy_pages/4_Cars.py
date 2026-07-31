import streamlit as st
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import render_data_diagnostics

st.set_page_config(page_title="Cars", layout="wide")
render_data_diagnostics()
st.title("Cars")
st.info("Manual car comp template is available through `alt_asset_explorer.connectors.cars.load_manual_template()`. Add rows to `data/raw/comps_seed.csv` and rebuild.")

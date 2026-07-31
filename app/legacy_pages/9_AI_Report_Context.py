from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from app_data import DATA_PROCESSED, empty_state, render_data_diagnostics

st.set_page_config(page_title="AI Report Context", layout="wide")
render_data_diagnostics()
st.title("AI Report Context")
path = DATA_PROCESSED / "ai_context.json"
if path.exists():
    st.json(json.loads(path.read_text(encoding="utf-8")))
else:
    empty_state()

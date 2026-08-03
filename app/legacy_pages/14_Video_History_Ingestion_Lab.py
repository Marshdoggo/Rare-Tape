from __future__ import annotations

import re
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from alt_asset_explorer.video_ingestion import ExtractionConfig, diagnostics_csv, evaluate_against_ground_truth, extract_video, reviewed_csv
from alt_asset_explorer.video_ingestion.schemas import CropRegion
from alt_asset_explorer.video_ingestion.video_reader import VideoReader

st.set_page_config(page_title="Video History Ingestion Lab", layout="wide")
st.title("Video History Ingestion Lab")
st.warning("Local experimental ingestion only. Downloads are review artifacts and are never appended to canonical Rally data.")

assets = pd.read_csv(ROOT / "data/normalized/assets.csv")
assets["label"] = assets["ticker"].fillna(assets["asset_id"]) + " — " + assets["asset_name"].fillna("")
mode = st.radio("Asset identity", ["Select existing asset", "Enter asset ID"], horizontal=True)
if mode == "Select existing asset":
    selected = st.selectbox("Rally asset", assets.index, format_func=lambda index: assets.loc[index, "label"])
    asset_id = str(assets.loc[selected, "asset_id"]); shares = pd.to_numeric(assets.loc[selected, "shares_outstanding"], errors="coerce")
else:
    asset_id = st.text_input("Asset ID"); shares = None

upload = st.file_uploader("Rally screen recording", type=["mp4", "mov", "m4v"])
if upload:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(upload.name).name)
    if "video_workspace" not in st.session_state:
        st.session_state.video_workspace = tempfile.mkdtemp(prefix="rally_video_lab_")
    video_path = Path(st.session_state.video_workspace) / safe_name
    video_path.write_bytes(upload.getbuffer())
    with VideoReader(video_path) as reader:
        metadata = reader.metadata
        preview_number = st.slider("Preview frame", 0, max(0, metadata.frame_count - 1), metadata.frame_count // 2)
        preview = reader.frame(preview_number)
    st.caption(f"{metadata.width}×{metadata.height} · {metadata.fps:.2f} FPS · {metadata.duration_seconds:.1f} seconds")
    st.image(preview, caption=f"Frame {preview_number}. Configure the normalized crop below to include only the tooltip.")
    crop_cols = st.columns(4)
    x = crop_cols[0].number_input("Crop x", 0.0, 1.0, .05, .01)
    y = crop_cols[1].number_input("Crop y", 0.0, 1.0, .10, .01)
    width = crop_cols[2].number_input("Crop width", .01, 1.0, .90, .01)
    height = crop_cols[3].number_input("Crop height", .01, 1.0, .30, .01)
    settings = st.columns(3)
    sample_fps = settings[0].slider("Sampling FPS", 1, 15, 10)
    threshold = settings[1].slider("State similarity threshold", .80, .99, .94, .01)
    date_order = settings[2].selectbox("Numeric date order", ["Reject ambiguous", "Month first", "Day first"])
    diagnostics = st.checkbox("Save diagnostic tooltip crops in this temporary session")
    if st.button("Run extraction", type="primary", disabled=not asset_id):
        try:
            region = CropRegion(x, y, width, height)
            day_first = {"Reject ambiguous": None, "Month first": False, "Day first": True}[date_order]
            diagnostic_dir = Path(st.session_state.video_workspace) / "diagnostic_crops" if diagnostics else None
            with st.spinner("Sampling changed tooltip states and running local OCR…"):
                observations, _ = extract_video(video_path, ExtractionConfig(region, sample_fps, threshold, day_first, None if pd.isna(shares) else float(shares), diagnostic_dir))
            st.session_state.video_observations = observations
        except Exception as error:
            st.error(str(error))

if st.session_state.get("video_observations"):
    observations = st.session_state.video_observations
    rows = [{key: value for key, value in asdict(item).items() if key != "alternatives"} for item in observations]
    table = pd.DataFrame(rows)
    table["observation_date"] = pd.to_datetime(table["observation_date"], errors="coerce").dt.date
    filter_name = st.selectbox("Review filter", ["All", "Accepted", "Low confidence", "Validation failures", "Conflicts"])
    masks = {"All": pd.Series(True, index=table.index), "Accepted": table.accept, "Low confidence": table.overall_confidence.lt(.7), "Validation failures": table.validation_status.ne("pass"), "Conflicts": table.conflict}
    edited = st.data_editor(table[masks[filter_name]], hide_index=True, use_container_width=True, disabled=[column for column in table.columns if column != "accept"])
    for index, accept in edited["accept"].items(): observations[index].accept = bool(accept)
    crop_choices = [(index, item) for index, item in enumerate(observations) if item.tooltip_crop_path]
    if crop_choices:
        crop_index = st.selectbox("Inspect source tooltip crop", [item[0] for item in crop_choices], format_func=lambda index: f"{observations[index].observation_date} · frame {observations[index].source_frame}")
        st.image(observations[crop_index].tooltip_crop_path)
    export = reviewed_csv(observations, asset_id, safe_name)
    st.download_button("Download reviewed CSV", export, f"{asset_id}_video_history.csv", "text/csv")
    st.download_button("Download diagnostics CSV", diagnostics_csv(observations), f"{asset_id}_video_diagnostics.csv", "text/csv")
    truth_upload = st.file_uploader("Optional ground-truth CSV", type=["csv"], key="truth")
    if truth_upload:
        metrics, comparison = evaluate_against_ground_truth(pd.read_csv(__import__('io').StringIO(export)), pd.read_csv(truth_upload))
        st.subheader("Ground-truth evaluation"); st.dataframe(pd.DataFrame([metrics]), hide_index=True); st.dataframe(comparison, hide_index=True)

from __future__ import annotations

# ruff: noqa: E402 -- Streamlit pages establish repository paths before local imports.

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.cluster.hierarchy import dendrogram

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

from app_data import (
    get_total_return_index,
    load_normalized_csv,
    load_processed_csv,
    render_data_diagnostics,
)
from alt_asset_explorer.benchmark_lab import BENCHMARKS, load_persisted_benchmarks
from alt_asset_explorer.correlation_lab import (
    align_values,
    calculate_returns,
    cluster,
    complete_subset,
    correlation_distance,
    correlation_matrices,
    matrix_csv,
    ordered_matrix,
    pairwise_table,
    period_grid,
)
from alt_asset_explorer.correlation_subjects import collect_subjects

st.set_page_config(page_title="Correlation Structure Lab", layout="wide")
render_data_diagnostics()
st.title("Correlation Structure Lab")
st.caption(
    "Research clustering of sparse Rally observations, existing Rally index prototypes, exit-aware full-market indexes, and persisted public benchmarks. This is not a live listing feed or appraisal."
)


@st.cache_data(show_spinner=False)
def load_universe():
    assets = load_normalized_csv("assets")
    observations = load_normalized_csv("price_observations")
    indices = load_processed_csv("rally_quarterly_indices")
    portfolio, _ = get_total_return_index()
    local = load_persisted_benchmarks()
    series, metadata = collect_subjects(
        assets, observations, indices, portfolio, local.data
    )
    return series, metadata, local


series, metadata, local = load_universe()
if metadata.empty:
    st.info("No local subjects are available.")
    st.stop()

with st.sidebar:
    st.header("Research controls")
    type_options = list(metadata["subject_type"].dropna().unique())
    types = st.multiselect("Subject types", type_options, default=type_options)
    categories = st.multiselect(
        "Categories",
        sorted(metadata["category"].dropna().astype(str).unique()),
        default=[],
    )
    statuses = st.multiselect(
        "Statuses", sorted(metadata["status"].dropna().astype(str).unique()), default=[]
    )
    include_exited = st.toggle("Include exited assets", value=True)
    benchmark_choices = st.multiselect(
        "External benchmarks", list(BENCHMARKS), default=list(BENCHMARKS)
    )
    date_preset = st.selectbox(
        "Date range",
        [
            "Maximum available",
            "Since 2020",
            "Last 3 years",
            "Last 5 years",
            "Custom dates",
        ],
    )
    all_start = pd.to_datetime(metadata["effective_start"]).min().date()
    all_end = pd.to_datetime(metadata["effective_end"]).max().date()
    start, end = pd.Timestamp(all_start), pd.Timestamp(all_end)
    if date_preset == "Since 2020":
        start = pd.Timestamp("2020-01-01")
    elif date_preset.startswith("Last"):
        start = end - pd.DateOffset(years=int(date_preset.split()[1]))
    elif date_preset == "Custom dates":
        chosen = st.date_input("Custom range", (all_start, all_end))
        if len(chosen) == 2:
            start, end = map(pd.Timestamp, chosen)
    frequency = st.selectbox(
        "Frequency", ["Quarterly", "Monthly", "Annual"], index=0
    ).lower()
    alignment_label = st.selectbox(
        "Alignment", ["Previous available value", "Exact period-end observation"]
    )
    alignment = "previous" if alignment_label.startswith("Previous") else "exact"
    staleness = st.number_input(
        "Maximum staleness (days)", min_value=1, max_value=1095, value=180
    )
    return_method = st.selectbox("Returns", ["Simple", "Log"]).lower()
    corr_method = st.selectbox("Correlation", ["Pearson", "Spearman"]).lower()
    minimum_overlap = st.selectbox(
        "Minimum overlapping returns", [4, 6, 8, 12], index=1
    )
    linkage_method = st.selectbox("Linkage", ["Average", "Complete", "Single"]).lower()
    distance_label = st.selectbox(
        "Correlation distance", ["sqrt(0.5 × (1 − correlation))", "1 − correlation"]
    )
    distance_method = "sqrt" if distance_label.startswith("sqrt") else "one_minus"
    orientation = st.selectbox("Dendrogram orientation", ["Left", "Top"])
    heat_order = st.selectbox(
        "Heatmap order", ["Clustered", "Alphabetical", "Subject type / category"]
    )
    maximum = st.slider("Maximum subjects (quality-ranked)", 10, 150, 100, 5)

selected = metadata[metadata["subject_type"].isin(types)].copy()
if categories:
    selected = selected[selected["category"].astype(str).isin(categories)]
if statuses:
    selected = selected[selected["status"].astype(str).isin(statuses)]
if not include_exited:
    selected = selected[
        ~selected["status"]
        .astype(str)
        .str.lower()
        .isin(["exited", "sold", "redeemed", "liquidated"])
    ]
selected = selected[
    ~selected["subject_id"].str.startswith("benchmark:")
    | selected["subject_id"].str.removeprefix("benchmark:").isin(benchmark_choices)
]
if len(selected) > maximum:
    st.warning(
        f"The filters selected {len(selected)} subjects. The explicit {maximum}-subject quality limit retains those with the most authored/index observations; increase the control to include more."
    )
    selected = selected.sort_values(
        ["observation_count", "subject_id"], ascending=[False, True]
    ).head(maximum)
selected_series = {sid: series[sid] for sid in selected["subject_id"] if sid in series}
grid = period_grid(start, end, frequency)
values, effective_dates = align_values(
    selected_series, grid, method=alignment, max_staleness_days=int(staleness)
)
returns = calculate_returns(values, return_method)
result = correlation_matrices(
    returns, method=corr_method, minimum_overlap=minimum_overlap
)
clustered_ids, exclusions = complete_subset(result.correlations)
cluster_corr = result.correlations.loc[clustered_ids, clustered_ids]
distances = correlation_distance(cluster_corr, distance_method)
tree, leaf_ids = cluster(distances, linkage_method) if clustered_ids else (None, [])
labels = selected.set_index("subject_id")["display_label"].to_dict()
leaf_labels = [labels.get(x, x) for x in leaf_ids]

off_diag = (
    result.overlaps.to_numpy()[np.triu_indices(len(result.overlaps), 1)]
    if len(result.overlaps) > 1
    else np.array([])
)
metrics = st.columns(6)
metrics[0].metric("Selected", len(selected))
metrics[1].metric("Clustered", len(clustered_ids))
metrics[2].metric("Excluded", len(selected) - len(clustered_ids))
metrics[3].metric(
    "Median overlap", f"{np.median(off_diag):.0f}" if len(off_diag) else "—"
)
metrics[4].metric(
    "Overlap range", f"{off_diag.min()}–{off_diag.max()}" if len(off_diag) else "—"
)
missing_pairs = (
    int(
        result.correlations.isna()
        .to_numpy()[np.triu_indices(len(result.correlations), 1)]
        .sum()
    )
    if len(result.correlations) > 1
    else 0
)
metrics[5].metric("Unavailable pairs", missing_pairs)

if tree is None:
    st.warning(
        "At least two mutually correlatable subjects are required for a dendrogram. Review the exclusion diagnostics or reduce minimum overlap."
    )
else:
    info = dendrogram(tree, labels=leaf_labels, no_plot=True)
    fig = go.Figure()
    for xs, ys in zip(info["icoord"], info["dcoord"]):
        if orientation == "Top":
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    line={"color": "#4978a8"},
                    hovertemplate="Distance %{y:.3f}<extra></extra>",
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=ys,
                    y=xs,
                    mode="lines",
                    line={"color": "#4978a8"},
                    hovertemplate="Distance %{x:.3f}<extra></extra>",
                )
            )
    ticks = [5 + 10 * i for i in range(len(info["ivl"]))]
    if orientation == "Top":
        fig.update_xaxes(
            tickmode="array", tickvals=ticks, ticktext=info["ivl"], tickangle=45
        )
        fig.update_yaxes(title="Correlation distance")
    else:
        fig.update_yaxes(tickmode="array", tickvals=ticks, ticktext=info["ivl"])
        fig.update_xaxes(title="Correlation distance", autorange="reversed")
    fig.update_layout(
        showlegend=False,
        height=max(500, 24 * len(leaf_ids)) if orientation == "Left" else 650,
        title=f"{corr_method.title()} correlation · {frequency} · {start.date()} to {end.date()}",
        margin={
            "l": 220 if orientation == "Left" else 40,
            "r": 20,
            "t": 70,
            "b": 150 if orientation == "Top" else 40,
        },
    )
    st.plotly_chart(
        fig, use_container_width=True, config={"scrollZoom": True, "displaylogo": False}
    )

st.subheader("Correlation heatmap")
if heat_order == "Clustered":
    order = leaf_ids + [x for x in result.correlations if x not in leaf_ids]
elif heat_order == "Alphabetical":
    order = sorted(result.correlations, key=lambda x: labels.get(x, x))
else:
    sort_meta = selected.set_index("subject_id")
    order = sorted(
        result.correlations,
        key=lambda x: (
            str(sort_meta.loc[x, "subject_type"]),
            str(sort_meta.loc[x, "category"]),
            labels.get(x, x),
        ),
    )
heat = ordered_matrix(result.correlations, order)
overlap_heat = ordered_matrix(result.overlaps, order)
heat_labels = [labels.get(x, x) for x in order]
text = np.round(heat.to_numpy(), 2).astype(str) if len(heat) <= 20 else None
heat_fig = go.Figure(
    go.Heatmap(
        z=heat,
        x=heat_labels,
        y=heat_labels,
        zmin=-1,
        zmax=1,
        zmid=0,
        colorscale="RdBu",
        reversescale=True,
        customdata=overlap_heat,
        text=text,
        texttemplate="%{text}" if text is not None else None,
        hovertemplate="A: %{y}<br>B: %{x}<br>Correlation: %{z:.3f}<br>Overlap: %{customdata}<extra></extra>",
        hoverongaps=False,
    )
)
heat_fig.update_layout(
    height=max(550, 16 * len(order)), margin={"l": 180, "b": 180, "t": 30, "r": 20}
)
st.plotly_chart(
    heat_fig,
    use_container_width=True,
    config={"scrollZoom": True, "displaylogo": False},
)

st.subheader("Pairwise-correlation explorer")
pairs = pairwise_table(result, selected, distance_method)
f1, f2, f3 = st.columns(3)
pair_filter = f1.selectbox(
    "Pair filter",
    [
        "All pairs",
        "Cross-category",
        "Asset versus benchmark",
        "Asset versus index",
        "Negative correlations",
    ],
)
threshold = f2.slider("Absolute correlation at least", 0.0, 1.0, 0.0, 0.05)
sort_mode = f3.selectbox(
    "Sort",
    [
        "Highest correlation",
        "Lowest correlation",
        "Closest distance",
        "Largest overlap",
    ],
)
if not pairs.empty:
    if pair_filter == "Cross-category":
        pairs = pairs[pairs["Category A"] != pairs["Category B"]]
    elif pair_filter == "Asset versus benchmark":
        pairs = pairs[
            (
                (pairs["Subject type A"] == "Individual Rally asset")
                & (pairs["Subject type B"] == "External benchmark")
            )
            | (
                (pairs["Subject type B"] == "Individual Rally asset")
                & (pairs["Subject type A"] == "External benchmark")
            )
        ]
    elif pair_filter == "Asset versus index":
        pairs = pairs[
            (
                pairs["Subject type A"].eq("Individual Rally asset")
                & pairs["Subject type B"].str.contains("index", case=False, na=False)
            )
            | (
                pairs["Subject type B"].eq("Individual Rally asset")
                & pairs["Subject type A"].str.contains("index", case=False, na=False)
            )
        ]
    elif pair_filter == "Negative correlations":
        pairs = pairs[pairs["Correlation"] < 0]
    pairs = pairs[pairs["Correlation"].abs().ge(threshold)]
    sort_col, ascending = {
        "Highest correlation": ("Correlation", False),
        "Lowest correlation": ("Correlation", True),
        "Closest distance": ("Distance", True),
        "Largest overlap": ("Overlap count", False),
    }[sort_mode]
    pairs = pairs.sort_values(sort_col, ascending=ascending, na_position="last")
st.dataframe(pairs, use_container_width=True, hide_index=True)

st.subheader("Downloads")
stem = f"correlation_lab_{frequency}_{start.date()}_{end.date()}"
cols = st.columns(5)
for col, label, frame, suffix in zip(
    cols,
    [
        "Aligned values",
        "Aligned returns",
        "Correlation matrix",
        "Overlap matrix",
        "Subject metadata",
    ],
    [values, returns, result.correlations, result.overlaps, selected],
    ["values", "returns", "correlations", "overlaps", "subjects"],
):
    data = (
        matrix_csv(frame)
        if suffix != "subjects"
        else frame.to_csv(index=False).encode()
    )
    col.download_button(label, data, f"{stem}_{suffix}.csv", "text/csv")

with st.expander("Data quality, exclusions, and methodology"):
    actual = returns.dropna(how="all").index
    st.write(
        f"**Frequency:** {frequency.title()} · **Alignment:** {alignment_label} · **Returns:** {return_method.title()} · **Correlation:** {corr_method.title()}  \
**Distance:** {distance_label} · **Linkage:** {linkage_method.title()} · **Minimum overlap:** {minimum_overlap}  \
**Requested range:** {start.date()} to {end.date()} · **Effective return range:** {actual.min().date() if len(actual) else 'Unavailable'} to {actual.max().date() if len(actual) else 'Unavailable'}  \
**Staleness:** values older than {staleness} days at a grid date are missing; no interpolation or future observations are used."
    )
    exclusion_rows = []
    for sid in selected["subject_id"]:
        reason = exclusions.get(sid)
        if sid not in clustered_ids and not reason:
            reason = "Insufficient return observations or no complete clustering subset"
        if reason:
            m = selected[selected["subject_id"].eq(sid)].iloc[0]
            exclusion_rows.append(
                {
                    "Subject": m["display_label"],
                    "Subject type": m["subject_type"],
                    "Category": m["category"],
                    "Reason excluded": reason,
                    "Return observation count": int(returns[sid].notna().sum()),
                    "Valid pairwise correlations": int(
                        result.correlations[sid].notna().sum()
                        - int(pd.notna(result.correlations.loc[sid, sid]))
                    ),
                    "Latest observation date": m["latest_observation_date"],
                }
            )
    st.dataframe(
        pd.DataFrame(exclusion_rows), use_container_width=True, hide_index=True
    )
    st.caption(
        f"Benchmarks: {local.source or 'unavailable'} ({local.path or 'no local file'}). Latest market date: {local.data['date'].max() if not local.data.empty else 'unavailable'}. Updated: {local.data['fetched_at'].max() if not local.data.empty else 'unavailable'}."
    )
    st.warning(
        "Correlations are descriptive and sample-sensitive. Rally values may be sparse, stale, event-driven, or valuation-driven and differ materially in liquidity and price discovery from daily public markets. Missing correlations remain missing; they are never replaced with zero. The dendrogram iteratively removes the least-connected subject (deterministic ID tie-break) until its matrix is complete."
    )

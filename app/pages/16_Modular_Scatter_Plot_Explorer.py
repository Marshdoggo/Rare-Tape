from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "src"))

from app_data import get_canonical_market, render_data_diagnostics  # noqa: E402
from alt_asset_explorer.scatter_explorer import (  # noqa: E402
    AXIS_METRICS,
    COLOR_METRICS,
    METRICS,
    SIZE_METRICS,
    build_asset_metric_table,
    export_scatter_csv,
    filter_universe,
    prepare_scatter_data,
)

st.set_page_config(
    page_title="Modular Scatter Plot Explorer | Rally Terminal", layout="wide"
)
render_data_diagnostics()
st.title("Modular Scatter Plot Explorer")
st.caption(
    "Cross-sectional research over authored Rally observations. Points are historical research subjects, not live listings or appraisals."
)

market = get_canonical_market()
assets, observations = (
    market.asset_master.copy(),
    market.authored_price_observations.copy(),
)
if assets.empty or observations.empty:
    st.error("Canonical Rally assets or authored observations are unavailable.")
    st.stop()

universe = st.selectbox(
    "Subject universe",
    ["Individual Rally assets"],
    help="Canonical index subjects are not yet exposed here because their reusable cross-sectional metadata contract is incomplete.",
)
controls = st.columns(4)


def label(key: str) -> str:
    return METRICS[key].display_name


x_metric = controls[0].selectbox(
    "X-axis metric",
    AXIS_METRICS,
    index=AXIS_METRICS.index("annualized_mean_return"),
    format_func=label,
)
y_metric = controls[1].selectbox(
    "Y-axis metric",
    AXIS_METRICS,
    index=AXIS_METRICS.index("annualized_volatility"),
    format_func=label,
)
size_metric = controls[2].selectbox(
    "Dot-size metric",
    SIZE_METRICS,
    format_func=lambda k: "Equal size / none" if k == "equal_size" else label(k),
)
color_metric = controls[3].selectbox(
    "Dot-color dimension",
    COLOR_METRICS,
    format_func=lambda k: "Single color / none" if k == "single_color" else label(k),
)

latest = (
    pd.to_datetime(observations["observed_at"], errors="coerce", utc=True)
    .dt.tz_localize(None)
    .max()
    .normalize()
)
earliest = (
    pd.to_datetime(observations["observed_at"], errors="coerce", utc=True)
    .dt.tz_localize(None)
    .min()
    .normalize()
)
period_col, filter_col = st.columns([1, 3])
preset = period_col.selectbox(
    "Analysis period",
    [
        "Maximum available",
        "Last 1 year",
        "Last 3 years",
        "Last 5 years",
        "Since 2020",
        "Custom dates",
    ],
)
start, end = None, latest
if preset.startswith("Last"):
    start = latest - pd.DateOffset(years=int(preset.split()[1]))
elif preset == "Since 2020":
    start = pd.Timestamp("2020-01-01")
elif preset == "Custom dates":
    chosen = period_col.date_input(
        "Custom range",
        value=(earliest.date(), latest.date()),
        min_value=earliest.date(),
        max_value=latest.date(),
    )
    if len(chosen) == 2:
        start, end = pd.Timestamp(chosen[0]), pd.Timestamp(chosen[1])

with filter_col.expander("Universe and quality filters", expanded=True):
    a, b, c = st.columns(3)
    categories_all = sorted(assets["category"].dropna().astype(str).unique())
    categories = a.multiselect("Categories", categories_all, default=categories_all)
    subcategories = a.multiselect(
        "Subcategories", sorted(assets["subcategory"].dropna().astype(str).unique())
    )
    include_exited = b.toggle("Include exited / sold / other statuses", value=False)
    statuses_all = sorted(assets["status"].dropna().astype(str).unique())
    statuses = b.multiselect(
        "Trading statuses",
        statuses_all,
        default=statuses_all
        if include_exited
        else [s for s in statuses_all if s == "trading"],
    )
    minimum_returns = c.number_input("Minimum valid return observations", 1, 40, 4)
    minimum_history = c.number_input(
        "Minimum history length (years)", 0.0, 10.0, 0.0, 0.25
    )
    search = a.text_input("Search ticker or asset name")
    include_missing_cap = b.toggle("Include assets with missing market cap", value=True)
    include_stale = b.toggle(
        "Include stale last observations",
        value=True,
        help="Stale means more than 180 days before the latest authored observation in this dataset.",
    )
    offering_years = pd.to_datetime(
        assets["offering_date"], errors="coerce"
    ).dt.year.dropna()
    year_range = c.slider(
        "Offering-year range",
        int(offering_years.min()),
        int(offering_years.max()),
        (int(offering_years.min()), int(offering_years.max())),
    )
    risk_free = c.number_input(
        "Annual risk-free rate",
        value=0.0,
        step=0.005,
        format="%.3f",
        help="Used only in Sharpe and Sortino calculations.",
    )


@st.cache_data(show_spinner=False)
def metric_table(
    asset_frame: pd.DataFrame,
    observation_frame: pd.DataFrame,
    start_value: str | None,
    end_value: str,
    minimum: int,
    risk_free_rate: float,
) -> pd.DataFrame:
    return build_asset_metric_table(
        asset_frame,
        observation_frame,
        start=start_value,
        end=end_value,
        minimum_returns=minimum,
        annual_risk_free_rate=risk_free_rate,
    )


table = metric_table(
    assets,
    observations,
    str(start.date()) if start is not None else None,
    str(end.date()),
    int(minimum_returns),
    float(risk_free),
)
eligible_before_observations = len(table)
table = table[table["offering_year"].between(*year_range, inclusive="both")]
if subcategories:
    table = table[table["subcategory"].isin(subcategories)]
filtered = filter_universe(
    table,
    categories=categories,
    statuses=statuses,
    include_exited=include_exited,
    search=search,
    minimum_observations=int(minimum_returns),
    minimum_history_years=float(minimum_history),
    include_missing_market_cap=include_missing_cap,
)
if not include_stale:
    filtered = filtered[
        pd.to_datetime(filtered["effective_end"], errors="coerce").ge(
            latest - pd.Timedelta(days=180)
        )
    ]

scatter, counts = prepare_scatter_data(
    filtered, x_metric, y_metric, size_metric, color_metric
)
insufficient = int(
    (
        pd.to_numeric(table["return_observation_count"], errors="coerce").fillna(0)
        < minimum_returns
    ).sum()
)
summary = st.columns(4)
summary[0].metric("Eligible subjects", counts["eligible"])
summary[1].metric("Plotted subjects", counts["plotted"])
summary[2].metric("Excluded subjects", eligible_before_observations - counts["plotted"])
summary[3].metric("Insufficient observations", insufficient)

options = st.columns(4)
x_log = options[0].toggle("Log X-axis", disabled=not METRICS[x_metric].log_allowed)
y_log = options[1].toggle("Log Y-axis", disabled=not METRICS[y_metric].log_allowed)
show_labels = options[2].toggle("Show ticker labels")
robust_color = options[3].toggle(
    "Robust color clipping",
    value=True,
    disabled=color_metric in {"single_color"}
    or METRICS[color_metric].metric_type != "numeric",
    help="Clips display colors to the 5th–95th percentiles; raw values remain in hover and CSV.",
)

if scatter.empty:
    st.warning(
        "No valid points match the selected universe, filters, and axis metrics."
    )
else:
    color_continuous = (
        color_metric not in {"single_color"}
        and METRICS[color_metric].metric_type == "numeric"
    )
    range_color = None
    if robust_color and color_continuous:
        valid_color = pd.to_numeric(scatter["display_color"], errors="coerce").dropna()
        if len(valid_color) > 1:
            range_color = tuple(valid_color.quantile([0.05, 0.95]))
    figure = px.scatter(
        scatter,
        x=x_metric,
        y=y_metric,
        size="marker_size",
        size_max=42,
        color="display_color",
        text="ticker" if show_labels else None,
        range_color=range_color,
        color_continuous_scale="RdYlGn" if color_continuous else None,
        labels={
            x_metric: label(x_metric),
            y_metric: label(y_metric),
            "display_color": "All assets"
            if color_metric == "single_color"
            else label(color_metric),
        },
        hover_name="asset_name",
        hover_data={
            "ticker": True,
            "category": True,
            "subcategory": True,
            "status": True,
            x_metric: ":.3f",
            y_metric: ":.3f",
            "market_cap": ":,.0f",
            "effective_start": True,
            "effective_end": True,
            "observation_count": True,
            "marker_size": False,
        },
    )
    figure.update_traces(
        marker={"sizemode": "diameter", "line": {"width": 0.5, "color": "white"}},
        textposition="top center",
    )
    figure.update_xaxes(type="log" if x_log else "linear")
    figure.update_yaxes(type="log" if y_log else "linear")
    figure.update_layout(
        height=680,
        legend_title_text=label(color_metric) if color_metric != "single_color" else "",
    )
    st.plotly_chart(figure, use_container_width=True)

if x_metric == "annualized_mean_return" and y_metric == "annualized_volatility":
    st.info(
        "Higher and farther left generally indicates higher return with lower volatility. A ray from the risk-free-rate intercept would represent an equal approximate Sharpe ratio; the coordinates are not themselves Sharpe ratios. Sparse collectible valuations may understate true economic volatility."
    )
st.caption(
    "Subjects use their individual available histories inside the selected range, so effective windows can differ and are not perfectly apples-to-apples. Marker area is bounded for readability; hover and downloads retain raw values."
)

st.subheader("Plotted-subject statistics")
columns = ["asset_name", "ticker", "category", "status", x_metric, y_metric]
for candidate in (
    size_metric,
    color_metric,
    "annualized_mean_return",
    "annualized_volatility",
    "sharpe_ratio",
    "cagr",
    "maximum_drawdown",
    "market_cap",
    "observation_count",
    "effective_start",
    "effective_end",
):
    if candidate not in {"equal_size", "single_color"} and candidate not in columns:
        columns.append(candidate)
display = scatter.reindex(columns=columns)
st.dataframe(display, use_container_width=True, hide_index=True)
st.download_button(
    "Download filtered scatter CSV",
    export_scatter_csv(scatter),
    "modular_scatter_explorer.csv",
    "text/csv",
    disabled=scatter.empty,
)

with st.expander("Methodology, data quality, and exclusions"):
    st.markdown(f"""
**Returns and annualization.** Simple returns are calculated only between actual authored positive-price observations. Regular histories use a conventional frequency inferred from median spacing; irregular histories use observed return intervals per elapsed year. Arithmetic mean return and sample volatility use the same periods-per-year value. CAGR independently uses exact elapsed calendar time. The annual risk-free rate is converted to that same periodic frequency.

**Selected minimum.** At least **{minimum_returns} valid returns** ({minimum_returns + 1} prices) are required for calculated performance metrics. There are {insufficient} subjects below that threshold before the remaining filters. Missing X or Y values exclude a point; missing size values receive the minimum marker size. Raw values, not marker transformations or robust color clipping, are exported.

**Statuses and histories.** Canonical statuses are {", ".join(statuses_all)}. Exited/sold/exit-announced subjects are excluded by default. Each point reports its own effective start and end; strict common-history mode is not offered because canonical assets do not share actual observation dates and Rally observations are never forward-filled.

**Market capitalization.** The latest authored observation market cap is preferred; otherwise current price is multiplied by canonical authored shares outstanding. It is a historical research observation, not a live Rally listing. Staleness is a 180-day display filter relative to the dataset's latest authored observation.

**Limitations.** Sparse, irregular, stale, event-driven collectible observations can make annualized statistics sample-sensitive and can understate economic volatility. Offering and terminal events can be present in authored history. This module performs no interpolation, appraisal, liquidity adjustment, or transaction-cost assumption.
""")

from __future__ import annotations

import sys
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app")); sys.path.insert(0, str(ROOT / "src"))

from app_data import get_canonical_market, render_data_diagnostics
from alt_asset_explorer.benchmark_lab import (BENCHMARKS, BenchmarkDataError, align_series,
    comparison_dataset, download_benchmark, load_persisted_benchmarks, normalize_to_100,
    relative_metrics, select_local_benchmark, series_metrics)

st.set_page_config(page_title="Benchmark Lab | Rare Tape", layout="wide")
render_data_diagnostics()
st.title("Benchmark Lab")
st.caption("Compare sparse Rally research observations with liquid public-market proxies. Normalized levels are analytical indexes, not investable dollar portfolios or appraisals.")

market = get_canonical_market()
assets, prices, total_return = market.asset_master.copy(), market.quarterly_prices.copy(), market.total_return_portfolio.copy()
subjects: dict[str, tuple[pd.Series, str]] = {}
if not prices.empty:
    prices["date"] = pd.to_datetime(prices.get("date", prices.get("period_end")), errors="coerce")
    value_col = "last" if "last" in prices else "price_per_share"
    for asset_id, group in prices.groupby("asset_id"):
        meta = assets[assets["asset_id"].astype(str).eq(str(asset_id))]
        label = (str(meta.iloc[0].get("ticker", asset_id)) + " — " + str(meta.iloc[0].get("asset_name", asset_id))) if not meta.empty else str(asset_id)
        subjects[f"Asset | {label}"] = (group.set_index("date")[value_col], "Individual authored Rally per-share observations")
if not total_return.empty:
    total_return["date"] = pd.to_datetime(total_return["date"], errors="coerce")
    subset = total_return.copy()
    for column, default in (("rebalance_frequency", "quarterly"), ("universe_scope", "include_exited")):
        if column in subset: subset = subset[subset[column].astype(str).eq(default)]
    for keys, group in subset.groupby(["category", "weighting_method"]):
        category, weighting = keys
        label = f"Index | {'Full market' if category == 'all' else str(category).title()} — {str(weighting).replace('_', ' ')}"
        subjects[label] = (group.sort_values("date").set_index("date")["index_level"],
                           "Canonical exit-aware quarterly total-return simulation; offering entry, explicit exits, and scheduled reinvestment")

if not subjects:
    st.error("No reusable Rally histories are available."); st.stop()
left, right = st.columns([1.5, 1])
subject_label = left.selectbox("Rally comparison subject", sorted(subjects))
benchmark_labels = right.multiselect("External benchmarks", list(BENCHMARKS), default=["SPY"],
    format_func=lambda ticker: f"{BENCHMARKS[ticker].name} — {ticker}")
custom = st.text_input("Optional custom ticker", placeholder="For example: VT")
if custom.strip(): benchmark_labels = list(dict.fromkeys([*benchmark_labels, custom.strip().upper()]))
if not benchmark_labels: st.info("Select at least one benchmark."); st.stop()
primary = st.selectbox("Primary benchmark", benchmark_labels)
alignment_label = st.selectbox("Alignment method", ["Previous available benchmark close", "Exact common dates", "Quarter end", "Month end"],
    help="Previous-close uses the last public-market close on or before each actual Rally observation. It never looks forward or fills Rally history.")
method = {"Previous available benchmark close":"previous", "Exact common dates":"exact", "Quarter end":"quarter_end", "Month end":"month_end"}[alignment_label]

rally, methodology = subjects[subject_label]; rally = rally.dropna().sort_index()
end = pd.Timestamp.utcnow().tz_localize(None).normalize(); start = rally.index.min() - pd.Timedelta(days=10)
@st.cache_data(ttl=86400, show_spinner="Downloading benchmark history…")
def cached_download(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    return download_benchmark(ticker, start_date, end_date)

@st.cache_data(show_spinner=False)
def cached_local_history():
    return load_persisted_benchmarks()

benchmarks = {}
errors = []
benchmark_sources = {}
local = cached_local_history()
allow_live = os.getenv("RALLY_ALLOW_LIVE_BENCHMARK_FALLBACK", "false").strip().lower() in {"1", "true", "yes"}
if local.source is None:
    st.info("Benchmark history has not been initialized. Run `python scripts/update_benchmark_data.py`.")
for ticker in benchmark_labels:
    frame = select_local_benchmark(local.data, ticker, start, end)
    if not frame.empty:
        benchmarks[ticker] = frame.set_index("date")["raw_value"]
        benchmark_sources[ticker] = local.source
        continue
    if not allow_live:
        errors.append(f"No local benchmark history is available for {ticker}. Live fallback is disabled.")
        continue
    try:
        frame = cached_download(ticker, str(start.date()), str(end.date()))
        benchmarks[ticker] = frame.set_index("date")["raw_value"]
        benchmark_sources[ticker] = "live Yahoo fallback"
    except BenchmarkDataError as error:
        errors.append(str(error))
for error in errors: st.warning(error)
if not benchmarks: st.error("No selected benchmark returned usable data."); st.stop()
latest_market_date = max(series.index.max() for series in benchmarks.values())
source_labels = ", ".join(sorted(set(str(value) for value in benchmark_sources.values())))
updated = ""
if not local.data.empty and local.data["fetched_at"].notna().any():
    updated = f" · updated: {local.data['fetched_at'].max().strftime('%Y-%m-%d %H:%M UTC')}"
st.caption(f"Benchmark data: {source_labels} · latest market date: {latest_market_date.date()}{updated}")
aligned = align_series(rally, benchmarks, method)
if len(aligned) < 2:
    st.warning("Fewer than two common observations exist. Performance statistics are unavailable for this selection and alignment method.")
    st.dataframe(aligned); st.stop()
if len(aligned) < 8: st.warning(f"Only {len(aligned)} overlapping observations are available; risk statistics are highly sample-sensitive.")

preset = st.selectbox("Analysis period", ["Maximum available", "Last 1 year", "Last 3 years", "Last 5 years", "Custom dates"])
if preset.startswith("Last"):
    years = int(preset.split()[1]); candidate = aligned[aligned.index >= aligned.index.max() - pd.DateOffset(years=years)]
    if len(candidate) >= 2: aligned = candidate
    else: st.warning("That preset has fewer than two observations; maximum available is shown.")
elif preset == "Custom dates":
    chosen = st.date_input("Custom range", value=(aligned.index.min().date(), aligned.index.max().date()))
    if len(chosen) == 2: aligned = aligned[(aligned.index.date >= chosen[0]) & (aligned.index.date <= chosen[1])]

dataset = comparison_dataset(aligned); normalized = aligned.apply(normalize_to_100)
st.subheader("Growth of 100")
log_scale = st.toggle("Log scale")
figure = px.line(normalized.rename_axis("date").reset_index(), x="date", y=list(normalized.columns), log_y=log_scale,
                 labels={"value":"Normalized level", "variable":"Series"})
st.plotly_chart(figure, use_container_width=True)
primary_col = primary if primary in aligned else next(iter(benchmarks))
relative = normalized["Rally subject"] / normalized[primary_col]
tabs = st.tabs(["Summary", "Relative wealth", "Rolling excess", "Period returns", "Drawdowns", "Aligned data"])
metrics = {column: series_metrics(aligned[column]) for column in aligned}
with tabs[0]:
    st.dataframe(pd.DataFrame(metrics).T, use_container_width=True)
    rel = relative_metrics(aligned["Rally subject"], aligned[primary_col]); st.markdown(f"**Relative to {primary_col}**"); st.dataframe(pd.DataFrame([rel]))
    difference = metrics["Rally subject"]["total_return"] - metrics[primary_col]["total_return"]
    st.info(f"The Rally subject {'outperformed' if difference > 0 else 'underperformed'} {primary_col} by {difference:.1%} in total return across {len(aligned)} usable observations. This is descriptive research, not investment advice.")
with tabs[1]: st.plotly_chart(px.line(relative.rename("Relative wealth").reset_index(), x="date", y="Relative wealth"), use_container_width=True)
with tabs[2]:
    window = max(2, min(4, len(aligned)//3)); rolling = (aligned["Rally subject"].pct_change()-aligned[primary_col].pct_change()).rolling(window).sum()
    st.caption(f"Rolling {window}-observation arithmetic excess return."); st.line_chart(rolling)
with tabs[3]: st.dataframe(aligned.pct_change().groupby(aligned.index.year).apply(lambda x: (1+x).prod()-1))
with tabs[4]: st.line_chart(normalized[["Rally subject", primary_col]] / normalized[["Rally subject", primary_col]].cummax() - 1)
with tabs[5]: st.dataframe(dataset, use_container_width=True)

st.download_button("Download aligned comparison CSV", dataset.to_csv(index=False).encode(), "benchmark_lab_aligned.csv", "text/csv")
with st.expander("Methodology, data quality, and reproducibility"):
    st.write(f"**Subject:** {subject_label}  \n**Subject methodology:** {methodology}  \n**Benchmarks:** {', '.join(benchmarks)}  \n**Primary:** {primary_col}  \n**Alignment:** {alignment_label}  \n**Effective range:** {aligned.index.min().date()} to {aligned.index.max().date()}  \n**Observations:** {len(aligned)}  \n**Inferred periods/year:** {series_metrics(aligned['Rally subject']).get('periods_per_year', 'Unavailable')}")
    st.write(f"Benchmark prices were loaded from {source_labels}. Committed local history is preferred; live Yahoo retrieval is used only when `RALLY_ALLOW_LIVE_BENCHMARK_FALLBACK=true` and a requested ticker is absent locally. Adjusted close is preferred when supplied. Availability and corrections are provider-dependent.")
    st.write("Returns are simple period returns on common observations. Annualization uses elapsed time for CAGR and median observation spacing for volatility and relative statistics. Missing rows are dropped; Rally values are never forward-filled. Previous-close alignment uses only information available on or before each Rally observation.")
    st.warning("Rally observations are manually researched, irregular valuation/trade events and may include offering or terminal exit values. They are neither a live Rally feed nor directly comparable in liquidity, price discovery, costs, or investability to exchange-traded securities.")

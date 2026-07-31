from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "src"))

from app_data import empty_state, get_canonical_market, load_processed_csv, load_report_csv, render_data_diagnostics
from alt_asset_explorer.custom_index_storage import (
    CombinedCustomIndexRegistry,
    CustomIndexStorageError,
    DuplicateCustomIndexError,
    JsonDirectoryCustomIndexStorage,
    custom_index_storage_is_read_only,
)
from alt_asset_explorer.custom_indices import build_custom_index, calculate_index_metrics, new_custom_index_definition
from alt_asset_explorer.custom_portfolios import PortfolioDefinition, simulate_portfolio
from alt_asset_explorer.component_portfolios import (
    PortfolioBacktestRequest,
    backtest_component_portfolio,
    expand_component,
    inverse_volatility_weights,
    look_through_exposure,
)
from alt_asset_explorer.components import (
    CanonicalIndexResolver,
    ComponentDefinition,
    ResolutionContext,
    ResolvedComponent,
)
from alt_asset_explorer.builder_state import (
    add_components,
    bulk_edit_weights,
    empty_builder_state,
    grouped_components,
    migrate_builder_state,
    normalize_weights,
    remove_components,
)
from alt_asset_explorer.contribution import attribution_from_index_result, attribution_from_portfolio_result, breadth_metrics, concentration_metrics
from alt_asset_explorer.indices import build_index_from_selection, prepare_quarterly_observations, summarize_contributions
from alt_asset_explorer.universe import build_asset_universe, eligible_asset_ids
from alt_asset_explorer.portfolio_lab import canonical_index, validate_index_constituent_schema
from alt_asset_explorer.market_table import build_market_table, filter_market_table
from alt_asset_explorer.research import calculate_sector_performance, completed_categories
from alt_asset_explorer.integer_replication import homepage_summary


st.set_page_config(page_title="Rally Terminal", layout="wide")
render_data_diagnostics()

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; max-width: 1500px;}
    [data-testid="stMetric"] {background: rgba(20, 28, 40, .55); border: 1px solid rgba(128, 145, 170, .18); border-radius: 10px; padding: .8rem 1rem;}
    [data-testid="stMetricLabel"] {letter-spacing: .02em;}
    div[data-testid="stVerticalBlockBorderWrapper"] {border-color: rgba(128, 145, 170, .24); border-radius: 12px;}
    .research-kicker {font-size: .72rem; text-transform: uppercase; letter-spacing: .12em; opacity: .62; margin-bottom: .2rem;}
    .coverage-list {line-height: 1.8; font-size: .9rem; opacity: .9;}
    .custom-badge {display:inline-block; padding:.15rem .48rem; border-radius:999px; background:rgba(88,166,255,.15); color:#58a6ff; font-size:.72rem; font-weight:700; letter-spacing:.04em;}
    </style>
    """,
    unsafe_allow_html=True,
)


def format_money(value: object) -> str:
    number = pd.to_numeric(value, errors="coerce")
    return "Unavailable" if pd.isna(number) else f"${number:,.0f}"


def format_pct(value: object) -> str:
    number = pd.to_numeric(value, errors="coerce")
    return "Unavailable" if pd.isna(number) else f"{number:.1%}"


canonical_market = get_canonical_market()
canonical = canonical_market.asset_master
decision = load_processed_csv("rally_asset_decision_universe", required=True)
prices = canonical_market.quarterly_prices
manual_price_observations = canonical_market.authored_price_observations
liquidity = load_processed_csv("liquidity_metrics")
coverage = load_report_csv("research_coverage")
index_portfolio = canonical_market.total_return_portfolio
index_constituents = canonical_market.total_return_constituents
try:
    validate_index_constituent_schema(index_constituents)
except ValueError as error:
    st.error(str(error))
    st.stop()
exit_analytics = canonical_market.exit_analytics
exchange_market_cap = canonical_market.exchange_history.market_cap_history
current_universe_artifact = canonical_market.current_universe
current_universe_summary = canonical_market.current_summary

st.title("Rally Terminal")
st.caption("Market intelligence for Rally collectibles. Research only, not financial advice.")

with st.expander("Data caveats", expanded=True):
    st.write(
        "Current tradable assets use the shared canonical universe: production Rally assets with active-tradable status, shares, and a non-stale secondary valuation. "
        "Experimental estimated fair value uses secondary comparable-sales logic and should not be read as a precise appraisal. "
        "Legacy interactive index diagnostics may differ from exit-aware total-return indexes when constituent, rebalance, or price-fill rules differ."
    )

with st.container(border=True):
    feature_copy, feature_link = st.columns([4, 1])
    with feature_copy:
        st.markdown('<div class="research-kicker">New Research Laboratory</div>', unsafe_allow_html=True)
        st.markdown("### Rally Derivatives Lab")
        st.write("Explore how conventional option-pricing models behave when applied to collectible assets and Rally Terminal indexes.")
    with feature_link:
        st.page_link("pages/6_Derivatives_Lab.py", label="Open Derivatives Lab →", icon="🧪")

if canonical.empty or decision.empty:
    empty_state()
    st.stop()

with st.container(border=True):
    replication_copy, replication_link = st.columns([4, 1])
    with replication_copy:
        st.markdown('<div class="research-kicker">Whole-Share Research</div>', unsafe_allow_html=True)
        st.markdown("### Integer Index Replication")
        replication = homepage_summary(canonical, prices)
        if replication:
            replication_metrics = st.columns(5)
            replication_metrics[0].metric("Eligible constituents", f"{int(replication['constituent_count']):,}")
            replication_metrics[1].metric("Tolerance-search capital", format_money(replication["minimum_capital"]))
            replication_metrics[2].metric("Initial weight RMSE", format_pct(replication["weight_rmse"]))
            replication_metrics[3].metric("Latest portfolio value", format_money(replication["latest_value"]))
            replication_metrics[4].metric("Cumulative return", format_pct(replication["return"]), delta=format_money(replication["pnl"]))
        else:
            st.caption("The summary appears when canonical active assets have valid authored price observations.")
    with replication_link:
        st.page_link("pages/7_Integer_Index_Replication.py", label="Open Replication Lab →", icon="🧮")

market = build_market_table(canonical, decision, prices, liquidity)
current = current_universe_artifact.copy() if not current_universe_artifact.empty else market[market["is_current_listed"].fillna(False)]
summary_row = current_universe_summary.iloc[0].to_dict() if not current_universe_summary.empty else {}
current_as_of = summary_row.get("as_of_date") or (pd.to_datetime(current["date"], errors="coerce").max().date().isoformat() if "date" in current and not current.empty else "Unavailable")

metric_cols = st.columns(4)
metric_cols[0].metric("Current Tradable Assets", f"{int(summary_row.get('tradable_asset_count', len(current))):,}", help=f"Canonical production Rally assets with active-tradable status and a non-stale current valuation as of {current_as_of}.")
metric_cols[1].metric("Research Universe Rows", f"{len(market):,}", help="Rows in the broader research table, including historical/SEC-context rows; this is not a unique current-asset count.")
metric_cols[2].metric("Tradable Exchange Market Cap", format_money(summary_row.get("tradable_market_cap", current.get("canonical_market_cap", current.get("current_market_cap_usd", pd.Series(dtype=float))).sum() if not current.empty else None)), help=f"Canonical current price × shares for current tradable assets as of {current_as_of}; stale carried-forward and offering-only values are excluded.")
metric_cols[3].metric("Assets With Experimental FV", f"{int(current.get('experimental_estimated_fair_value_usd', pd.Series(dtype=float)).notna().sum()):,}")

st.subheader("Market Size and Exit-Aware Total Return")
if not exchange_market_cap.empty:
    exchange_market_cap["date"] = pd.to_datetime(exchange_market_cap["date"], errors="coerce")
    latest_exchange = exchange_market_cap.sort_values("date").iloc[-1]
    size_cols = st.columns(6)
    size_cols[0].metric("Represented Exchange Value", format_money(latest_exchange.get("total_market_cap")), help="Broader reconstructed exchange-history value, including stale carried-forward observations; not the canonical tradable market cap.")
    size_cols[1].metric("Represented Assets", f"{int(latest_exchange.get('active_asset_count', 0)):,}")
    size_cols[2].metric("Active Categories", f"{int(exchange_market_cap.get('active_category_count', pd.Series([0])).iloc[-1] if 'active_category_count' in exchange_market_cap else current['category'].nunique()):,}")
    size_cols[3].metric("Pending Settlement Value", format_money(index_portfolio['pending_settlement_value'].max() if not index_portfolio.empty and 'pending_settlement_value' in index_portfolio else 0))
    size_cols[4].metric("New Issuance YTD", format_money(exchange_market_cap.loc[exchange_market_cap['date'].dt.year.eq(latest_exchange['date'].year), 'new_issuance'].sum() if 'new_issuance' in exchange_market_cap else 0))
    size_cols[5].metric("Capital Removed Through Exits YTD", format_money(exchange_market_cap.loc[exchange_market_cap['date'].dt.year.eq(latest_exchange['date'].year), 'removed_capital'].sum() if 'removed_capital' in exchange_market_cap else 0))
if not index_portfolio.empty:
    index_portfolio["date"] = pd.to_datetime(index_portfolio["date"], errors="coerce")
    tr_categories = ["all"] + sorted([c for c in index_portfolio["category"].dropna().astype(str).unique() if c != "all"])
    if "universe_scope" not in index_portfolio:
        index_portfolio["universe_scope"] = "include_exited"
    tr_cols = st.columns([1.8, 1.2, 1.2, 1.2])
    tr_category = tr_cols[0].selectbox("Total-return universe", tr_categories, format_func=lambda v: "Full market" if v == "all" else v.replace("_", " ").title(), key="home_tr_category")
    scope_options = [scope for scope in ["include_exited", "active_only"] if scope in set(index_portfolio["universe_scope"].dropna().astype(str))]
    tr_scope = tr_cols[1].selectbox("Universe scope", scope_options or ["include_exited"], format_func=lambda v: "Include exited" if v == "include_exited" else "Active only", key="home_tr_scope")
    available_rebalances = [item for item in ["quarterly", "monthly", "weekly"] if item in set(index_portfolio["rebalance_frequency"].dropna().astype(str))]
    tr_rebal = tr_cols[2].selectbox("Rebalance frequency", available_rebalances or sorted(index_portfolio["rebalance_frequency"].dropna().unique()), key="home_tr_rebalance")
    tr_range = tr_cols[3].selectbox("Total-return date range", ["Entire history", "Last 3 years", "Last year"], key="home_tr_range")
    tr = index_portfolio[index_portfolio["category"].astype(str).eq(tr_category) & index_portfolio["rebalance_frequency"].astype(str).eq(tr_rebal) & index_portfolio["universe_scope"].astype(str).eq(tr_scope)].copy()
    if tr_range != "Entire history" and not tr.empty:
        years = 3 if tr_range == "Last 3 years" else 1
        tr = tr[tr["date"] >= tr["date"].max() - pd.DateOffset(years=years)]
    tr_plot = tr.pivot_table(index="date", columns="weighting_method", values="index_level", aggfunc="last").reset_index().rename(columns={"equal_weight":"Equal-Weighted Total Return Index", "market_cap_weight":"Market-Cap-Weighted Total Return Index"})
    st.plotly_chart(px.line(tr_plot, x="date", y=[c for c in tr_plot.columns if c != "date"], title="What $100 Became (offering entries; exits reinvested on schedule)"), use_container_width=True)
    st.caption(
        f"Exit-aware portfolio simulation · {'includes exited assets' if tr_scope == 'include_exited' else 'active-tradable survivor universe'} · {tr_rebal} scheduled rebalance · offering prices are treated as investable entry prices · "
        "prices are carried forward between observations · cash from exits is reinvested at the next scheduled rebalance."
    )
    latest_tr = tr.sort_values("date").groupby("weighting_method").tail(1)
    ret_cols = st.columns(6)
    for idx, method in enumerate(["equal_weight", "market_cap_weight"]):
        row = latest_tr[latest_tr["weighting_method"].eq(method)]
        if not row.empty:
            r = row.iloc[0]; label = "Equal-weighted" if method == "equal_weight" else "Cap-weighted"
            ret_cols[idx*3].metric(label + " return", format_pct(r.get("cumulative_return")))
            ret_cols[idx*3+1].metric(label + " CAGR", format_pct((float(r.get("index_level", 100))/100) ** (365.25 / max((tr["date"].max()-tr["date"].min()).days, 1)) - 1))
            ret_cols[idx*3+2].metric(label + " max drawdown", format_pct(tr[tr["weighting_method"].eq(method)]["drawdown"].min()))
if not exit_analytics.empty:
    ex_cols = st.columns(6)
    ex_cols[0].metric("Total Exited Assets", f"{exit_analytics['asset_id'].nunique():,}")
    ex_cols[1].metric("Total Realized Exit Proceeds", format_money(exit_analytics.get("exit_market_cap", pd.Series(dtype=float)).sum()))
    ex_cols[2].metric("Realized Exit P/L", format_money(exit_analytics.get("realized_pl", pd.Series(dtype=float)).sum()))
    ex_cols[3].metric("Median Exit Return", format_pct(exit_analytics.get("total_return", pd.Series(dtype=float)).median()))
    ex_cols[4].metric("Median Holding Period", f"{pd.to_numeric(exit_analytics.get('holding_period_days'), errors='coerce').median():,.0f} days")
    ex_cols[5].metric("Premium vs Last Trade", format_pct(exit_analytics.get("premium_vs_last_trade", pd.Series(dtype=float)).median()))

quarterly_observations = prepare_quarterly_observations(prices, canonical)
complete_categories = completed_categories(coverage, canonical)
custom_index_read_only = custom_index_storage_is_read_only()
custom_index_registry = CombinedCustomIndexRegistry(
    JsonDirectoryCustomIndexStorage(ROOT / "data" / "custom_indices" / "curated", read_only=True),
    JsonDirectoryCustomIndexStorage(ROOT / "data" / "custom_indices" / "local", read_only=custom_index_read_only),
)
saved_custom_indices = custom_index_registry.list()

overview_col, coverage_col = st.columns([3.4, 1.2], gap="large")
with coverage_col:
    with st.container(border=True):
        st.markdown('<div class="research-kicker">Research Coverage</div>', unsafe_allow_html=True)
        researched_count = int(pd.to_numeric(coverage.get("observation_count"), errors="coerce").fillna(0).gt(0).sum()) if not coverage.empty else 0
        observation_count = int(pd.to_numeric(coverage.get("observation_count"), errors="coerce").fillna(0).sum()) if not coverage.empty else 0
        coverage_metrics = st.columns(3)
        coverage_metrics[0].metric("Assets", researched_count)
        coverage_metrics[1].metric("Complete", len(complete_categories))
        coverage_metrics[2].metric("Observations", observation_count)
        completed_html = "<br>".join(f"✅ {category.replace('_', ' ').title()}" for category in complete_categories) or "No categories complete"
        all_categories = sorted(canonical["category"].dropna().astype(str).unique())
        remaining = [category for category in all_categories if category not in complete_categories]
        remaining_html = " · ".join(category.replace("_", " ").title() for category in remaining[:5])
        if len(remaining) > 5:
            remaining_html += " · …"
        st.markdown(f'<div class="coverage-list"><b>Completed</b><br>{completed_html}</div>', unsafe_allow_html=True)
        if remaining_html:
            st.caption(f"Remaining · {remaining_html}")

with overview_col:
    st.subheader("Sector Performance")
    sector_categories = sorted(quarterly_observations["category"].dropna().astype(str).unique()) if not quarterly_observations.empty else []
    if not sector_categories:
        st.info("Sector statistics appear as categories gain at least two comparable observations.")
    else:
        # Keep this call compatible with already-running Streamlit processes that
        # may still have the previous research module cached during hot reload.
        sector_performance = calculate_sector_performance(quarterly_observations, canonical, sector_categories)
        coverage_by_category: dict[str, dict[str, int]] = {}
        if not coverage.empty and {"asset_id", "category", "observation_count"}.issubset(coverage.columns):
            coverage_targets = coverage.copy()
            if {"asset_id", "status"}.issubset(canonical.columns):
                coverage_targets = coverage_targets.merge(
                    canonical[["asset_id", "status"]].drop_duplicates("asset_id"),
                    on="asset_id",
                    how="left",
                )
                coverage_targets = coverage_targets[coverage_targets["status"].astype(str).str.lower().eq("trading")]
            coverage_targets["_researched"] = pd.to_numeric(
                coverage_targets["observation_count"], errors="coerce"
            ).fillna(0).gt(0)
            coverage_summary = coverage_targets.groupby("category").agg(
                target_asset_count=("asset_id", "nunique"),
                researched_asset_count=("_researched", "sum"),
            )
            coverage_by_category = coverage_summary.astype(int).to_dict("index")
        for row_index, row in sector_performance.iterrows():
            category_coverage = coverage_by_category.get(str(row["category"]))
            if category_coverage:
                researched = category_coverage["researched_asset_count"]
                target = category_coverage["target_asset_count"]
                sector_performance.loc[row_index, "researched_asset_count"] = researched
                sector_performance.loc[row_index, "target_asset_count"] = target
                sector_performance.loc[row_index, "coverage_pct"] = researched / target if target else None
                sector_performance.loc[row_index, "coverage_status"] = "Complete" if target and researched >= target else "Building"
        sector_display = sector_performance.copy()
        sector_display["category"] = sector_display["category"].str.replace("_", " ").str.title()
        for percentage_column in ["since_inception", "last_year", "annualized_volatility"]:
            sector_display[percentage_column] = pd.to_numeric(sector_display[percentage_column], errors="coerce") * 100
        sector_display["coverage"] = (
            sector_display["researched_asset_count"].astype("Int64").astype(str)
            + " / "
            + sector_display["target_asset_count"].astype("Int64").astype(str)
        )
        sector_display["coverage_status"] = sector_display["coverage_status"].map({"Complete": "✅ Complete", "Building": "🟡 Building"})
        sector_display = sector_display.rename(
            columns={
                "category": "Category",
                "since_inception": "Since inception",
                "last_year": "Last year",
                "annualized_volatility": "Volatility",
                "volatility_band": "Risk band",
                "constituent_count": "Assets",
                "coverage": "Coverage",
                "coverage_status": "Research status",
            }
        )
        st.dataframe(
            sector_display[["Category", "Since inception", "Last year", "Volatility", "Risk band", "Coverage", "Research status"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Since inception": st.column_config.NumberColumn(format="%+.1f%%"),
                "Last year": st.column_config.NumberColumn(format="%+.1f%%"),
                "Volatility": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption(
            "Sectors appear as soon as a return can be calculated. Returns use equal-weight quarterly indices; "
            "coverage shows researched assets versus the current trading universe, and volatility is annualized."
        )

st.subheader("Index Explorer")
if quarterly_observations.empty:
    st.info("No quarterly observations are available. Run `python3 scripts/build_dataset.py`.")
else:
    saved_options = {"Built-in market and category indexes": None}
    saved_options.update({f"🧰 {item.name} · Custom · {len(item.constituents)} assets": item for item in saved_custom_indices})
    selected_saved_label = st.selectbox(
        "Explore index",
        list(saved_options),
        key="explorer_saved_index",
        help="Saved workshop indexes appear here alongside the built-in market and category indexes.",
    )
    selected_saved_index = saved_options[selected_saved_label]
    observation_categories = set(quarterly_observations["category"].dropna().astype(str).unique())
    canonical_categories = set(canonical["category"].dropna().astype(str).unique()) if "category" in canonical else set()
    available_categories = sorted(observation_categories | canonical_categories)
    control_cols = st.columns([2.2, 1.5, 1.5, 1.4], gap="medium")
    selected_index_categories = control_cols[0].multiselect(
        "Categories",
        available_categories,
        default=available_categories,
        format_func=lambda value: value.replace("_", " ").title(),
        key="index_categories",
    )
    weighting_labels = control_cols[1].multiselect(
        "Weighting",
        ["Equal Weight", "Market-Cap Weight"],
        default=["Equal Weight"],
        key="index_weightings",
    )
    universe_label = control_cols[2].radio(
        "Universe",
        ["Current Survivors Only", "Include Exited Assets"],
        horizontal=False,
        key="index_universe",
    )
    range_label = control_cols[3].selectbox(
        "Date range",
        ["Entire history", "Last 3 years", "Last year", "Custom"],
        key="index_range",
    )

    observation_dates = pd.to_datetime(quarterly_observations["date"], errors="coerce").dropna()
    max_observation_date = observation_dates.max().date()
    min_observation_date = observation_dates.min().date()
    start_date = None
    end_date = max_observation_date
    if range_label == "Last 3 years":
        start_date = (pd.Timestamp(max_observation_date) - pd.DateOffset(years=3)).date()
    elif range_label == "Last year":
        start_date = (pd.Timestamp(max_observation_date) - pd.DateOffset(years=1)).date()
    elif range_label == "Custom":
        custom_dates = st.date_input(
            "Custom window",
            value=(min_observation_date, max_observation_date),
            min_value=min_observation_date,
            max_value=max_observation_date,
        )
        if isinstance(custom_dates, (tuple, list)) and len(custom_dates) == 2:
            start_date, end_date = custom_dates

    weighting_map = {"Equal Weight": "equal", "Market-Cap Weight": "market_cap"}
    selected_weightings = [weighting_map[label] for label in weighting_labels]
    include_exited_assets = universe_label == "Include Exited Assets"
    universe_diagnostics = build_asset_universe(
        canonical,
        quarterly_observations,
        categories=selected_index_categories,
        include_exited=include_exited_assets,
        require_price_history=True,
    )
    universe_assets = universe_diagnostics[universe_diagnostics["is_universe_eligible"]].copy()
    selected_asset_ids = eligible_asset_ids(universe_diagnostics)

    explorer_series: list[pd.DataFrame] = []
    primary_result = None
    selected_saved_result = None
    for weighting in selected_weightings:
        weighting_name = "Equal Weight" if weighting == "equal" else "Market Cap"
        combined = build_index_from_selection(
            quarterly_observations,
            asset_ids=selected_asset_ids,
            weighting_method=weighting,
            index_id=f"explorer_all_{weighting}",
            index_name=f"Selected Market · {weighting_name}",
            category="selected",
            start_date=start_date,
            end_date=end_date,
        )
        if primary_result is None:
            primary_result = combined
        combined_series = combined.series.copy()
        if not combined_series.empty:
            combined_series["universe_constituent_count"] = len(selected_asset_ids)
        explorer_series.append(combined_series)
        for category in selected_index_categories:
            category_ids = universe_assets.loc[universe_assets["category"].astype(str).eq(category), "asset_id"].astype(str).tolist()
            category_result = build_index_from_selection(
                quarterly_observations,
                asset_ids=category_ids,
                weighting_method=weighting,
                index_id=f"explorer_{category}_{weighting}",
                index_name=f"{category.replace('_', ' ').title()} · {weighting_name}",
                category=category,
                start_date=start_date,
                end_date=end_date,
            )
            category_series = category_result.series.copy()
            if not category_series.empty:
                category_series["universe_constituent_count"] = len(category_ids)
            explorer_series.append(category_series)

    if selected_saved_index is not None:
        saved_ids = [item.asset_id for item in selected_saved_index.constituents]
        saved_weights = {item.asset_id: item.weight for item in selected_saved_index.constituents}
        selected_saved_result = build_custom_index(
            quarterly_observations,
            asset_ids=saved_ids,
            weights=saved_weights,
            base_value=selected_saved_index.base_value,
            start_date=start_date or selected_saved_index.start_date,
            end_date=end_date or selected_saved_index.end_date,
        )
        st.markdown('<span class="custom-badge">CUSTOM INDEX</span>', unsafe_allow_html=True)
        st.markdown(f"### {selected_saved_index.name}")
        if selected_saved_index.description:
            st.write(selected_saved_index.description)
        st.caption(
            f"Created by {selected_saved_index.creator} · {selected_saved_index.created_at.date().isoformat()} · "
            f"{len(saved_ids)} constituents · {selected_saved_index.weighting_method.replace('_', ' ').title()}"
        )
        saved_composition = pd.DataFrame(
            [
                {
                    "Ticker": item.ticker or item.asset_id,
                    "Asset": item.display_name or item.asset_id,
                    "Asset ID": item.asset_id,
                    "Weight": item.weight,
                }
                for item in selected_saved_index.constituents
            ]
        )
        saved_composition["Weight"] = saved_composition["Weight"] * 100
        st.dataframe(
            saved_composition,
            use_container_width=True,
            hide_index=True,
            column_config={"Weight": st.column_config.NumberColumn(format="%.1f%%")},
        )
        st.download_button(
            "Download index definition (JSON)",
            selected_saved_index.model_dump_json(indent=2),
            file_name=f"{selected_saved_index.id}.json",
            mime="application/json",
            key="explorer_download_custom_json",
        )
        if selected_saved_result.series.empty:
            st.warning("This saved index cannot be calculated from the current local observations.")
        else:
            saved_chart = selected_saved_result.series.rename(columns={"return_period": "return_1d"}).copy()
            saved_chart["index_id"] = selected_saved_index.id
            saved_chart["index_name"] = f"{selected_saved_index.name} · Custom"
            saved_chart["category"] = "custom"
            saved_chart["universe_constituent_count"] = len(saved_ids)
            explorer_series.insert(0, saved_chart)
            saved_metrics = calculate_index_metrics(selected_saved_result.series)
            custom_metric_cols = st.columns(5)
            custom_metric_cols[0].metric("Total Return", format_pct(saved_metrics["total_return"]))
            custom_metric_cols[1].metric("CAGR", format_pct(saved_metrics["cagr"]))
            custom_metric_cols[2].metric("Volatility", format_pct(saved_metrics["annualized_volatility"]))
            custom_metric_cols[3].metric("Sharpe", "N/A" if saved_metrics["sharpe_ratio"] is None else f"{saved_metrics['sharpe_ratio']:.2f}")
            custom_metric_cols[4].metric("Max Drawdown", format_pct(saved_metrics["maximum_drawdown"]))
            st.caption(
                f"Effective history: {selected_saved_result.effective_start_date} through {selected_saved_result.effective_end_date}. "
                "Constant-weight normalized composite; common observed quarter-ends only; no price imputation."
            )

    chart_data = pd.concat(explorer_series, ignore_index=True) if explorer_series else pd.DataFrame()
    if chart_data.empty:
        st.warning("No observations match this selection. Add categories, weightings, or broaden the universe/date range.")
    else:
        latest_combined = chart_data[chart_data["category"].eq("selected")].sort_values("date").groupby("index_id", as_index=False).tail(1)
        metric_columns = st.columns(max(1, len(latest_combined)))
        for metric_column, (_, row) in zip(metric_columns, latest_combined.iterrows()):
            metric_column.metric(row["index_name"], f"{float(row['index_level']):,.2f}", format_pct(row.get("return_1d")))
            universe_count = row.get("universe_constituent_count", row["constituent_count"])
            metric_column.caption(f"{int(row['constituent_count'])} observed constituents at date · {int(universe_count)} assets in selected history · through {row['date']}")

        explorer_figure = go.Figure()
        palette = ["#58a6ff", "#3fb950", "#d29922", "#f778ba", "#a371f7", "#ff7b72", "#79c0ff", "#56d4dd"]
        for color_index, (series_name, frame) in enumerate(chart_data.groupby("index_name", sort=False)):
            explorer_figure.add_trace(
                go.Scatter(
                    x=frame["date"],
                    y=frame["index_level"],
                    name=series_name,
                    mode="lines+markers",
                    line={"width": 3 if str(series_name).startswith("Selected Market") else 1.8, "color": palette[color_index % len(palette)]},
                    marker={"size": 5},
                    customdata=frame[["constituent_count", "universe_constituent_count", "return_1d"]],
                    hovertemplate="%{x}<br><b>%{y:.2f}</b><br>%{customdata[0]} observed constituents at date<br>%{customdata[1]} assets in selected history<br>Period return %{customdata[2]:+.1%}<extra>%{fullData.name}</extra>",
                )
            )
        explorer_figure.update_layout(
            height=510,
            hovermode="x unified",
            dragmode="zoom",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.03, "x": 0},
            margin={"t": 76, "r": 24, "b": 48, "l": 52},
            xaxis={"title": "Quarter end", "rangeslider": {"visible": True}},
            yaxis={"title": "Index level", "fixedrange": False},
        )
        st.plotly_chart(
            explorer_figure,
            use_container_width=True,
            config={"scrollZoom": True, "displaylogo": False, "modeBarButtonsToAdd": ["drawline", "eraseshape"]},
        )
        st.caption("Click legend entries to isolate series. Drag to zoom, scroll to zoom, double-click to reset, and use the range slider to pan.")
        st.caption(
            "Index Explorer is a descriptive quarterly observed-price prototype. Equal-weight returns use only assets with both prior and current "
            "quarter-end observations; missing prices are not forward-filled and exits/cash proceeds are not modeled. "
            "Hover counts show observed constituents at that date plus the selected historical universe size. "
            "Current Survivors Only uses the canonical active-tradable status and applies that list retroactively."
        )

        if selected_saved_result is not None and not selected_saved_result.contributions.empty:
            st.markdown("#### Saved Custom Index Contribution Analysis")
            saved_contributions = selected_saved_result.contributions.merge(
                canonical[["asset_id", "ticker", "name", "category"]].drop_duplicates("asset_id"),
                on="asset_id",
                how="left",
            )
            for percentage_column in ["starting_weight", "asset_return", "contribution_return", "share_of_total_move"]:
                saved_contributions[percentage_column] = pd.to_numeric(saved_contributions[percentage_column], errors="coerce") * 100
            st.dataframe(
                saved_contributions.rename(
                    columns={
                        "ticker": "Ticker", "name": "Asset", "category": "Category",
                        "starting_weight": "Starting weight", "asset_return": "Asset return",
                        "contribution_return": "Weighted contribution", "contribution_points": "Contribution points",
                        "share_of_total_move": "Share of total move",
                    }
                )[["Ticker", "Asset", "Category", "Starting weight", "Asset return", "Weighted contribution", "Contribution points", "Share of total move"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Starting weight": st.column_config.NumberColumn(format="%.1f%%"),
                    "Asset return": st.column_config.NumberColumn(format="%+.1f%%"),
                    "Weighted contribution": st.column_config.NumberColumn(format="%+.1f%%"),
                    "Contribution points": st.column_config.NumberColumn(format="%+.2f"),
                    "Share of total move": st.column_config.NumberColumn(format="%+.1f%%"),
                },
            )

        st.subheader("Contribution Analysis")
        if primary_result is None or primary_result.contributions.empty:
            st.info("Attribution appears after the selection contains at least two comparable observations.")
        else:
            contribution_summary = summarize_contributions(primary_result.contributions, canonical)
            positive = contribution_summary[contribution_summary["contribution_points"] > 0].head(5)
            negative = contribution_summary[contribution_summary["contribution_points"] < 0].sort_values("contribution_points").head(5)
            positive_col, negative_col = st.columns(2, gap="large")

            def render_contributors(container: object, title: str, frame: pd.DataFrame) -> None:
                with container:
                    st.markdown(f"**{title}**")
                    if frame.empty:
                        st.caption("No contributors in this direction.")
                    for _, contributor in frame.iterrows():
                        label = contributor.get("ticker") if pd.notna(contributor.get("ticker")) else contributor.get("name")
                        if pd.isna(label):
                            label = contributor["asset_id"]
                        st.metric(str(label), f"{float(contributor['contribution_points']):+.2f} pts")

            render_contributors(positive_col, "Largest Positive Contributors", positive)
            render_contributors(negative_col, "Largest Negative Contributors", negative)
            primary_series = primary_result.series.sort_values("date")
            total_move = float(primary_series.iloc[-1]["index_level"] - primary_series.iloc[0]["index_level"])
            leaders = positive.head(2)
            laggards = negative.head(1)
            leader_names = [str(row["ticker"] if pd.notna(row["ticker"]) else row["name"]) for _, row in leaders.iterrows()]
            laggard_names = [str(row["ticker"] if pd.notna(row["ticker"]) else row["name"]) for _, row in laggards.iterrows()]
            direction = "rose" if total_move >= 0 else "fell"
            commentary = f"The selected index {direction} {abs(total_move):.1f} points over this window"
            if leader_names:
                commentary += f", led by {' and '.join(leader_names)}"
            if laggard_names:
                commentary += f", while weakness in {' and '.join(laggard_names)} offset part of the move"
            st.info(commentary + ".")

st.subheader("Rally Market Table")

with st.sidebar:
    st.subheader("Market filters")
    current_only = st.toggle("Current listed assets only", value=True)
    search = st.text_input("Search name or ticker", value="")
    category_options = sorted(market["category"].dropna().astype(str).unique().tolist())
    selected_categories = st.multiselect("Category", category_options, default=category_options)
    subcategory_base = market[market["category"].astype(str).isin(selected_categories)] if selected_categories else market
    subcategory_options = sorted(subcategory_base["subcategory"].dropna().astype(str).unique().tolist())
    selected_subcategories = st.multiselect("Subcategory", subcategory_options, default=subcategory_options)
    quality_options = sorted(market["data_quality_status"].dropna().astype(str).unique().tolist())
    selected_quality = st.multiselect("Data quality", quality_options, default=quality_options)
    valuation_filter = st.selectbox("Fair value position", ["All", "Below estimated fair value", "Above estimated fair value"])
    min_confidence = st.slider("Minimum FV confidence", 0.0, 1.0, 0.0, 0.05)

filtered = filter_market_table(
    market,
    search=search,
    categories=selected_categories,
    subcategories=selected_subcategories,
    data_quality=selected_quality,
    valuation_filter=valuation_filter,
    min_confidence=min_confidence,
    current_listed_only=current_only,
)

if filtered.empty:
    st.info("No assets match the current filters.")
else:
    display = filtered.rename(
        columns={
            "name": "Asset name",
            "ticker": "Ticker",
            "asset_id": "Asset ID",
            "category": "Category",
            "subcategory": "Subcategory",
            "last_price": "Last price",
            "return_1q": "1Q Return",
            "return_1y": "1Y Return",
            "return_full_history": "Full Return",
            "best_bid": "Best bid",
            "best_ask": "Best ask",
            "bid_ask_spread_pct": "Bid-ask spread",
            "shares_outstanding": "Shares outstanding",
            "current_market_cap_usd": "Market cap",
            "offering_price_usd": "Offering price",
            "offering_valuation_usd": "Offering valuation",
            "experimental_estimated_fair_value_usd": "Experimental estimated fair value",
            "premium_discount_to_fair_value": "Premium / discount to FV",
            "nav_confidence": "FV confidence",
            "last_quote_observed_at": "Last quote update",
            "status": "Status",
            "trading_state": "Trading state",
            "buyout_offer_price_per_share": "Offer price",
            "buyout_offer_total_value": "Total offer value",
            "buyout_premium_pct": "Offer premium / discount",
            "buyout_vote_as_of": "Vote snapshot as of",
            "buyout_notes": "Buyout notes",
            "data_quality_status": "Data quality",
            "data_quality_warnings": "Data warnings",
        }
    )
    columns = [
        "Ticker",
        "Asset name",
        "Last price",
        "Status",
        "Trading state",
        "Offer price",
        "Offer premium / discount",
        "Total offer value",
        "1Q Return",
        "1Y Return",
        "Full Return",
        "Category",
        "Subcategory",
        "Asset ID",
        "Best bid",
        "Best ask",
        "Bid-ask spread",
        "Shares outstanding",
        "Market cap",
        "Offering price",
        "Offering valuation",
        "Experimental estimated fair value",
        "Premium / discount to FV",
        "FV confidence",
        "Last quote update",
        "Data quality",
        "Data warnings",
    ]
    for percent_col in ("1Q Return", "1Y Return", "Full Return", "Bid-ask spread", "Premium / discount to FV", "FV confidence", "Offer premium / discount"):
        if percent_col in display:
            display[percent_col] = pd.to_numeric(display[percent_col], errors="coerce") * 100
    market_display = display[[col for col in columns if col in display.columns]].sort_values("Ticker").reset_index(drop=True)
    market_selection = st.dataframe(
        market_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Last price": st.column_config.NumberColumn(format="$%.2f"),
            "Best bid": st.column_config.NumberColumn(format="$%.2f"),
            "Best ask": st.column_config.NumberColumn(format="$%.2f"),
            "1Q Return": st.column_config.NumberColumn(format="%+.1f%%"),
            "1Y Return": st.column_config.NumberColumn(format="%+.1f%%"),
            "Full Return": st.column_config.NumberColumn(format="%+.1f%%"),
            "Bid-ask spread": st.column_config.NumberColumn(format="%.1f%%"),
            "Shares outstanding": st.column_config.NumberColumn(format="%.0f"),
            "Market cap": st.column_config.NumberColumn(format="$%.0f"),
            "Offering price": st.column_config.NumberColumn(format="$%.2f"),
            "Offering valuation": st.column_config.NumberColumn(format="$%.0f"),
            "Offer price": st.column_config.NumberColumn(format="$%.2f"),
            "Total offer value": st.column_config.NumberColumn(format="$%.0f"),
            "Offer premium / discount": st.column_config.NumberColumn(format="%+.2f%%"),
            "Experimental estimated fair value": st.column_config.NumberColumn(format="$%.0f"),
            "Premium / discount to FV": st.column_config.NumberColumn(format="%.1f%%"),
            "FV confidence": st.column_config.NumberColumn(format="%.0f%%"),
        },
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_rows = market_selection.selection.rows if market_selection is not None else []
    if selected_rows:
        selected_asset = market_display.iloc[selected_rows[0]]
        selected_asset_id_for_history = str(selected_asset["Asset ID"])
        if st.session_state.get("asset_explorer_selected_asset_id") != selected_asset_id_for_history:
            st.session_state["asset_explorer_selected_asset_id"] = selected_asset_id_for_history
            st.rerun()

    st.caption(
        "Unavailable values are intentionally left blank. SEC-synthesized rows remain research context and are hidden by default unless current-listing filtering is turned off."
    )



st.subheader("Portfolio Construction Laboratory")
st.caption("Combine canonical index sleeves and editable underlying assets in one top-level portfolio. Research only; historical results are not forecasts.")


def _asset_level_series(asset_id: str) -> pd.DataFrame:
    """Return observed quarterly levels only; never fill a missing asset observation."""
    frame = prices[prices["asset_id"].astype(str).eq(asset_id)].copy()
    value_column = "last" if "last" in frame else "price_usd"
    if frame.empty or value_column not in frame:
        return pd.DataFrame(columns=["date", "index_level"])
    date_column = "period" if "period" in frame else "date"
    frame = frame[[date_column, value_column]].rename(columns={date_column: "date", value_column: "index_level"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["index_level"] = pd.to_numeric(frame["index_level"], errors="coerce")
    return frame.dropna().query("index_level > 0").sort_values("date").drop_duplicates("date", keep="last")


def _canonical_index(component_type: str, reference: str, method: str, scope: str) -> tuple[pd.DataFrame, dict[str, float]]:
    return canonical_index(index_portfolio, index_constituents, component_type, reference, method, scope)


if index_portfolio.empty:
    st.info("Portfolio construction is unavailable until canonical total-return artifacts exist.")
else:
    control_cols = st.columns(4)
    sim_starting_value = control_cols[0].number_input("Starting investment", min_value=1.0, value=100.0, step=25.0, format="%.2f", key="lab_start")
    sim_rebalance_label = control_cols[1].selectbox("Portfolio rebalance frequency", ["None / Buy & Hold", "Monthly", "Quarterly", "Annual"], index=2, key="lab_rebalance")
    sim_universe_label = control_cols[2].selectbox("Universe", ["Include Exited Assets", "Exclude Exited Assets"], key="lab_universe")
    annual_rf = control_cols[3].number_input("Annual risk-free rate (%)", value=0.0, step=0.25, key="lab_rf") / 100
    rebalance_map = {"None / Buy & Hold": "none", "Monthly": "monthly", "Quarterly": "quarterly", "Annual": "annual"}
    universe_map = {"Include Exited Assets": "include_exited", "Exclude Exited Assets": "active_only"}
    scope = universe_map[sim_universe_label]
    portfolio_rebalance = rebalance_map[sim_rebalance_label]
    builder_state, migrated_builder = migrate_builder_state(st.session_state.get("portfolio_lab_components"))
    st.session_state["portfolio_lab_components"] = builder_state
    builder = builder_state["components"]
    if migrated_builder:
        st.info("Portfolio builder state was upgraded to the current version. Unknown legacy state is reset once for safety.")

    def save_builder(state: dict) -> None:
        st.session_state["portfolio_lab_components"] = state

    st.markdown("#### Add Exposure")
    add_cols = st.columns([1.2, 2.2, 1.5, 1])
    exposure_type = add_cols[0].selectbox("Exposure type", ["Full Market Index", "Category Index", "Category Constituents", "Individual Asset"], key="lab_add_type")
    category_options = sorted(c for c in index_portfolio["category"].dropna().astype(str).unique() if c != "all")
    metadata_columns = [column for column in ["asset_id", "ticker", "name", "category", "offering_market_cap_usd"] if column in canonical]
    metadata = canonical[metadata_columns].drop_duplicates("asset_id").copy()
    metadata["label"] = metadata["ticker"].fillna(metadata["asset_id"]).astype(str) + " | " + metadata["name"].fillna(metadata["asset_id"]).astype(str)
    asset_labels = dict(zip(metadata["label"], metadata["asset_id"].astype(str)))
    selection = None
    if exposure_type == "Full Market Index":
        add_cols[1].text_input("Selection", value="Full Rally Market", disabled=True, key="lab_full_label")
    elif exposure_type in {"Category Index", "Category Constituents"}:
        selection = add_cols[1].selectbox("Selection", category_options, format_func=lambda x: x.replace("_", " ").title(), key="lab_category") if category_options else None
    else:
        selected_label = add_cols[1].selectbox("Selection", sorted(asset_labels), key="lab_asset") if asset_labels else None
        selection = asset_labels.get(selected_label) if selected_label else None
    internal_label = add_cols[2].selectbox("Internal index weighting", ["Equal Weight", "Market-Cap Weight"], disabled=exposure_type == "Individual Asset", key="lab_internal")
    internal_method = "equal_weight" if internal_label == "Equal Weight" else "market_cap_weight"
    if add_cols[3].button("Add to Portfolio", type="primary", use_container_width=True, key="lab_add"):
        if exposure_type == "Full Market Index":
            component_id, reference, ctype, label = f"full_market:{internal_method}", "all", "full_market", "Full Rally Market Index"
            save_builder(add_components(builder_state, [{"component_id": component_id, "type": ctype, "reference": reference, "label": label, "weight": 0.0, "method": internal_method}]))
        elif exposure_type == "Category Index" and selection:
            component_id = f"category:{selection}:{internal_method}"
            save_builder(add_components(builder_state, [{"component_id": component_id, "type": "category_index", "reference": selection, "label": f"{selection.replace('_', ' ').title()} Index", "weight": 0.0, "method": internal_method}]))
        elif exposure_type == "Individual Asset" and selection:
            meta = metadata[metadata["asset_id"].astype(str).eq(selection)].iloc[0]
            component_id = f"asset:{selection}"
            save_builder(add_components(builder_state, [{"component_id": component_id, "type": "individual_asset", "reference": selection, "label": str(meta["ticker"]), "weight": 0.0, "method": "direct"}]))
        elif exposure_type == "Category Constituents" and selection:
            _, constituent_weights = _canonical_index("category_index", selection, internal_method, scope)
            available = {asset_id: weight for asset_id, weight in constituent_weights.items() if len(_asset_level_series(asset_id)) >= 2}
            new_weights = expand_component("temporary", {"temporary": 1.0}, available, method="preserve") if available else {}
            additions = []
            remaining = max(0.0, 1 - sum(float(v["weight"]) for v in builder.values()))
            for asset_component_id, weight in new_weights.items():
                asset_id = asset_component_id.removeprefix("asset:")
                meta = metadata[metadata["asset_id"].astype(str).eq(asset_id)]
                label = str(meta.iloc[0]["ticker"]) if not meta.empty else asset_id
                additions.append({"component_id": asset_component_id, "type": "individual_asset", "reference": asset_id, "label": label, "weight": weight * remaining, "method": "expanded", "origin": selection})
            save_builder(add_components(builder_state, additions))
        st.rerun()

    st.markdown("#### Current Portfolio")
    action_cols = st.columns([1, 1, 1, 2])
    if action_cols[0].button("Equal Weight Components", disabled=not builder, help="Assigns 100 / N to every top-level component."):
        save_builder(normalize_weights(builder_state, equal=True))
        st.rerun()
    raw_total = sum(float(item["weight"]) for item in builder.values())
    if action_cols[1].button("Normalize to 100%", disabled=not builder or raw_total <= 0, help="Preserves relative ratios and rescales to 100%; this is not optimization."):
        save_builder(normalize_weights(builder_state))
        st.rerun()
    if action_cols[2].button("Clear Portfolio", disabled=not builder):
        save_builder(empty_builder_state())
        st.rerun()
    removal_policy = action_cols[3].selectbox("Removal weight policy", ["Redistribute pro rata", "Redistribute equally", "Leave unallocated"], help="Applied whenever a top-level component or expanded asset is removed.")
    policy_map = {"Redistribute pro rata": "pro_rata", "Redistribute equally": "equal", "Leave unallocated": "unallocated"}

    groups = grouped_components(builder_state)
    for group_name, component_ids in groups.items():
        title = "Top-level components" if group_name == "top_level" else f"{group_name.removeprefix('category:').replace('_', ' ').title()} strategy constituents"
        st.markdown(f"##### {title}")
        st.caption("Portfolio allocation sleeves and direct positions." if group_name == "top_level" else "Assets expanded from this category strategy; edit or remove constituents individually.")
        for component_id in component_ids:
            item = builder[component_id]
            row = st.columns([2.4, 1, 1.3, 1, 1])
            row[0].markdown(f"**{item['label']}**  \n{'Sleeve' if item['type'] != 'individual_asset' else 'Asset'} · {item['method'].replace('_', ' ')}")
            new_weight = row[1].number_input("Portfolio allocation weight (%)", 0.0, 100.0, value=float(item["weight"]) * 100, step=0.5, key=f"lab_weight_{component_id}", label_visibility="collapsed") / 100
            if new_weight != float(item["weight"]):
                save_builder(bulk_edit_weights(builder_state, {component_id: new_weight}))
                st.rerun()
            if item["type"] == "category_index":
                expansion_method = row[2].selectbox("Expansion", ["Preserve index weights", "Equal weight assets", "Market-cap weight assets"], key=f"lab_expand_method_{component_id}", label_visibility="collapsed")
                if row[3].button("Expand", key=f"lab_expand_{component_id}"):
                    _, underlying = _canonical_index(item["type"], item["reference"], item["method"], scope)
                    caps = metadata.set_index("asset_id").get("offering_market_cap_usd", pd.Series(dtype=float)).to_dict() if "offering_market_cap_usd" in metadata else {}
                    method = {"Preserve index weights": "preserve", "Equal weight assets": "equal", "Market-cap weight assets": "market_cap"}[expansion_method]
                    expanded = expand_component(component_id, {key: value["weight"] for key, value in builder.items()}, underlying, method=method, market_caps=caps)
                    next_state = remove_components(builder_state, [component_id])
                    additions = []
                    for key, weight in expanded.items():
                        if key not in next_state["components"] and key.startswith("asset:"):
                            aid = key.removeprefix("asset:")
                            meta = metadata[metadata["asset_id"].astype(str).eq(aid)]
                            additions.append({"component_id": key, "type": "individual_asset", "reference": aid, "label": str(meta.iloc[0]["ticker"]) if not meta.empty else aid, "weight": weight, "method": "expanded", "origin": item["reference"]})
                    next_state = add_components(next_state, additions)
                    save_builder(bulk_edit_weights(next_state, expanded))
                    st.rerun()
            else:
                row[2].caption("Direct position" if item["method"] == "direct" else f"Expanded from {item.get('origin', 'category')}")
            if row[4].button("Remove", key=f"lab_remove_{component_id}"):
                save_builder(remove_components(builder_state, [component_id], policy=policy_map[removal_policy]))
                st.rerun()

    allocated = sum(float(item["weight"]) for item in builder.values())
    status_cols = st.columns(5)
    status_cols[0].metric("Allocated", f"{allocated:.2%}")
    status_cols[1].metric("Unallocated", f"{max(0.0, 1 - allocated):.2%}")
    status_cols[2].metric("Valid", "Yes" if builder and abs(allocated - 1) <= 0.0001 and all(float(x["weight"]) > 0 for x in builder.values()) else "No")
    status_cols[3].metric("Top-level sleeves", sum(item["type"] != "individual_asset" for item in builder.values()))

    components: list[ResolvedComponent] = []
    canonical_resolver = CanonicalIndexResolver(index_portfolio, index_constituents)
    for item in builder.values():
        definition = ComponentDefinition(
            item["component_id"], item["type"], item["label"], item["weight"], item["reference"],
            "Direct position" if item["type"] == "individual_asset" else item["method"],
            {"universe_scope": scope} if item["type"] != "individual_asset" else {},
        )
        if item["type"] == "individual_asset":
            series = _asset_level_series(item["reference"])
            constituents = pd.DataFrame({"date": series["date"], "asset_id": item["reference"], "portfolio_weight": 1.0})
            components.append(ResolvedComponent(definition, series, constituents, {"resolver": "HomeDirectAssetAdapter", "missing_price_policy": "no_fill"}))
        else:
            components.append(canonical_resolver.resolve(definition, ResolutionContext()))
    lookthrough = look_through_exposure(components) if components and all(c.target_weight > 0 for c in components) else pd.DataFrame()
    status_cols[4].metric("Unique assets", len(lookthrough))
    valid = bool(components) and abs(allocated - 1) <= 0.0001 and all(c.target_weight > 0 for c in components)
    if builder and not valid:
        st.warning("Portfolio allocation weights must be positive and total 100% before simulation.")

    backtest_request = PortfolioBacktestRequest(
        components=components,
        starting_value=sim_starting_value,
        calendar="observed_shared",
        rebalance_schedule=portfolio_rebalance,
        alignment_policy="common_inception",
        missing_observation_policy="drop_date",
        eligibility_policy="fixed_at_inception",
        exit_cash_policy="component_series",
        annual_risk_free_rate=annual_rf,
        as_of_cutoff=pd.Timestamp.utcnow().tz_localize(None).normalize(),
    )
    component_result = backtest_component_portfolio(backtest_request) if valid else None
    if component_result:
        for warning in component_result.warnings:
            st.warning(warning)
    if component_result and not component_result.series.empty:
        result = component_result.series
        risk = component_result.summary_metrics
        total_return = float(risk["total_return"])
        metric_rows = st.columns(6)
        metric_rows[0].metric("Ending value", f"${result.iloc[-1]['growth_value']:,.2f}")
        metric_rows[1].metric("Total return", f"{total_return:.2%}")
        metric_rows[2].metric("Annualized volatility", f"{risk['annualized_volatility']:.2%}")
        metric_rows[3].metric("Sharpe", f"{risk['sharpe_ratio']:.2f}")
        metric_rows[4].metric("Sortino", f"{risk['sortino_ratio']:.2f}")
        metric_rows[5].metric("Calmar", f"{risk['calmar_ratio']:.2f}")
        growth_chart = result[["date", "growth_value"]].rename(columns={"growth_value": "Portfolio"}).set_index("date")
        st.line_chart(growth_chart)
        with st.expander("Risk and drawdown analytics", expanded=True):
            risk_display = pd.DataFrame({"Metric": ["Annualization frequency", "Downside deviation", "Best observed period", "Worst observed period", "Positive periods", "Maximum drawdown", "Maximum drawdown duration", "Recovery date"], "Value": [f"{risk['periods_per_year']} periods/year", f"{risk['downside_deviation']:.2%}", f"{risk['best_period_return']:.2%}", f"{risk['worst_period_return']:.2%}", f"{risk['positive_period_percentage']:.2%}", f"{risk['maximum_drawdown']:.2%}", f"{risk['maximum_drawdown_duration_periods']} observed periods", str(risk['recovery_date'].date()) if risk['recovery_date'] is not None else "Not yet recovered"]})
            st.dataframe(risk_display, hide_index=True, use_container_width=True)
            st.line_chart(component_result.drawdown_series.set_index("date")[["drawdown"]])
        composition = component_result.composition.copy()
        st.markdown("##### Component Attribution")
        display = composition.rename(columns={"component": "Component", "target_weight": "Starting Target Weight", "ending_weight": "Ending Drifted Weight", "standalone_return": "Standalone Return", "cumulative_contribution": "Arithmetic Period Contribution", "rebalance_count": "Rebalances"})
        st.dataframe(display[["Component", "Starting Target Weight", "Ending Drifted Weight", "Standalone Return", "Arithmetic Period Contribution", "Rebalances"]], hide_index=True, use_container_width=True, column_config={key: st.column_config.NumberColumn(format="%.2f%%") for key in ["Starting Target Weight", "Ending Drifted Weight", "Standalone Return", "Arithmetic Period Contribution"]})

        st.markdown("##### Look-Through Exposure")
        if not lookthrough.empty:
            enriched = lookthrough.merge(metadata[["asset_id", "ticker", "name"]], on="asset_id", how="left")
            if enriched["overlap"].any():
                st.warning(f"Direct and indirect overlap detected in {int(enriched['overlap'].sum())} underlying asset(s). Overlap is allowed and quantified below.")
            st.dataframe(enriched[["asset_id", "ticker", "name", "direct_weight", "indirect_weight", "total_weight", "source_components", "overlap"]], hide_index=True, use_container_width=True, column_config={key: st.column_config.NumberColumn(format="%.2f%%") for key in ["direct_weight", "indirect_weight", "total_weight"]})

        st.markdown("##### Diversification and Allocation Research")
        cleaned_returns = {}
        for component in components:
            frame = component.series[["date", "index_level"]].copy().set_index("date").pct_change().rename(columns={"index_level": component.label})
            cleaned_returns[component.component_id] = frame
        aligned_returns = pd.concat(cleaned_returns.values(), axis=1, join="inner").dropna()
        st.caption(f"Correlation uses {len(aligned_returns)} shared return observations.")
        if len(aligned_returns) >= 3:
            st.dataframe(aligned_returns.corr().style.format("{:.2f}"), use_container_width=True)
            try:
                inverse = inverse_volatility_weights({c.component_id: c.series for c in components}, minimum_observations=3)
                comparison = pd.DataFrame({"Component": [c.label for c in components], "Current manual": [c.target_weight for c in components], "Equal weight": [1 / len(components)] * len(components), "Inverse volatility": [inverse[c.component_id] for c in components]})
                st.dataframe(comparison, hide_index=True, use_container_width=True, column_config={key: st.column_config.NumberColumn(format="%.2f%%") for key in ["Current manual", "Equal weight", "Inverse volatility"]})
                st.caption("Inverse volatility is a long-only, 100%-invested descriptive allocation estimated from the displayed common historical sample. It is in-sample research, not a forecast or prospective performance claim.")
            except ValueError as exc:
                st.warning(str(exc))
        else:
            st.warning("At least three shared return observations are required for correlation and inverse-volatility research.")

        with st.expander("Backtest audit contract"):
            st.caption(f"Configuration fingerprint: `{component_result.configuration_fingerprint}`")
            st.json(component_result.methodology)
            st.markdown("**Eligibility history**")
            st.dataframe(component_result.eligibility_history, hide_index=True, use_container_width=True)
            st.markdown("**Rebalance ledger**")
            st.dataframe(component_result.rebalance_history, hide_index=True, use_container_width=True)
            st.markdown("**Turnover history**")
            st.dataframe(component_result.turnover_history, hide_index=True, use_container_width=True)
            st.markdown("**Cash history**")
            st.dataframe(component_result.cash_history, hide_index=True, use_container_width=True)
            st.markdown("**Arithmetic contribution history**")
            st.dataframe(component_result.contribution_history, hide_index=True, use_container_width=True)
            st.markdown("**Drawdown history**")
            st.dataframe(component_result.drawdown_history, hide_index=True, use_container_width=True)
            st.markdown("**Look-through history**")
            st.dataframe(component_result.look_through_history, hide_index=True, use_container_width=True)
            st.markdown("**Overlap history**")
            st.dataframe(component_result.overlap_history, hide_index=True, use_container_width=True)
            st.markdown("**Weight reconciliation**")
            st.dataframe(component_result.reconciliation, hide_index=True, use_container_width=True)
            st.caption("Risk contribution and advanced attribution are intentionally unavailable until deterministic reconciliation fixtures are committed and pass exactly.")

    # Simulation methodology and ledgers are rendered from PortfolioBacktestResult above.

st.subheader("Contribution Explorer")
st.caption("Explain what moved a market, category, custom portfolio, or compatible custom basket using reconciling contribution math.")
category_targets = sorted(canonical["category"].dropna().astype(str).unique()) if "category" in canonical else []
target_options = ["Full Rally Market"] + [f"Category: {category.replace('_', ' ').title()}" for category in category_targets]
if st.session_state.get("active_custom_portfolio_definition") is not None:
    target_options.append("Active Custom Portfolio")
if st.session_state.get("workshop_constituent_ids"):
    target_options.append("Active Custom Index Basket")

ce_cols = st.columns([1.8, 1.1, 1.1, 1.1])
ce_target = ce_cols[0].selectbox("Analyze", target_options, key="contrib_target")
ce_weighting = ce_cols[1].selectbox("Weighting", ["Equal Weight", "Market Cap Weight"], key="contrib_weighting")
ce_universe = ce_cols[2].selectbox("Universe", ["Include Exited Assets", "Current Survivors Only"], key="contrib_universe")
ce_range = ce_cols[3].selectbox("Date Range", ["Entire History", "Last Quarter / 3M", "Last 1 Year", "Year to Date", "Custom Date Range"], key="contrib_range")

all_dates = pd.to_datetime(quarterly_observations.get("date", pd.Series(dtype=object)), errors="coerce").dropna()
def _window_dates(dates: pd.Series) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if dates.empty:
        return None, None
    end = pd.Timestamp(dates.max()).normalize()
    if ce_range == "Entire History":
        start = None
    elif ce_range == "Last Quarter / 3M":
        start = end - pd.DateOffset(months=3)
    elif ce_range == "Last 1 Year":
        start = end - pd.DateOffset(years=1)
    elif ce_range == "Year to Date":
        start = pd.Timestamp(year=end.year, month=1, day=1)
    else:
        left, right = st.columns(2)
        min_d = pd.Timestamp(dates.min()).date(); max_d = end.date()
        start = pd.Timestamp(left.date_input("Custom start", value=min_d, min_value=min_d, max_value=max_d, key="contrib_start"))
        end = pd.Timestamp(right.date_input("Custom end", value=max_d, min_value=min_d, max_value=max_d, key="contrib_end"))
    return start, end
ce_start, ce_end = _window_dates(all_dates)

contribution_result = None
try:
    if ce_target == "Active Custom Portfolio":
        definition = st.session_state.get("active_custom_portfolio_definition")
        if definition is None:
            st.info("Build a Custom Portfolio in Portfolio Simulator first, then return here.")
        else:
            if ce_start is not None or ce_end is not None:
                definition = PortfolioDefinition(name=definition.name, asset_ids=definition.asset_ids, methodology=definition.methodology, custom_weights=definition.custom_weights, base_value=definition.base_value, start_date=ce_start, end_date=ce_end, benchmark_category=definition.benchmark_category)
            pr = simulate_portfolio(definition, canonical, prices, canonical_market.exit_events)
            contribution_result = attribution_from_portfolio_result(pr, canonical, target_name=definition.name, start_date=ce_start, end_date=ce_end)
    elif ce_target == "Active Custom Index Basket":
        ids = list(st.session_state.get("workshop_constituent_ids", []))
        raw_weights = st.session_state.get("workshop_weights", {})
        weights = {aid: float(raw_weights.get(aid, 0)) / 100 for aid in ids} if raw_weights else None
        ci = build_custom_index(quarterly_observations, asset_ids=ids, weights=weights, start_date=ce_start, end_date=ce_end)
        idx = SimpleNamespace(series=ci.series.rename(columns={"return_period": "return_1d"}), contributions=ci.contributions.assign(date=ci.effective_end_date, weight=ci.contributions.get("starting_weight", 0)))
        contribution_result = attribution_from_index_result(idx, canonical, target_name="Active Custom Index Basket", target_type="Custom Index", unit_label="index points", methodology={"weighting": "custom basket", "rebalance": "constant-weight normalized composite", "missing_prices": "common observed dates only"})
    else:
        asset_ids = None
        category_name = "all"
        if ce_target.startswith("Category: "):
            label = ce_target.removeprefix("Category: ").lower().replace(" ", "_")
            matches = [c for c in category_targets if c.lower() == label or c.replace("_", " ").lower() == ce_target.removeprefix("Category: ").lower()]
            category_name = matches[0] if matches else label
            asset_ids = canonical.loc[canonical["category"].astype(str).eq(category_name), "asset_id"].astype(str).tolist()
        if ce_universe == "Current Survivors Only":
            survivor_ids = set(current.get("asset_id", pd.Series(dtype=str)).astype(str))
            asset_ids = list(survivor_ids if asset_ids is None else survivor_ids.intersection(asset_ids))
        weighting_method = "equal" if ce_weighting == "Equal Weight" else "market_cap"
        idx_result = build_index_from_selection(quarterly_observations, asset_ids=asset_ids, weighting_method=weighting_method, index_id="contribution_explorer", index_name=ce_target, category=category_name, start_date=ce_start, end_date=ce_end)
        contribution_result = attribution_from_index_result(idx_result, canonical, target_name=ce_target, target_type="Index", unit_label="index points", methodology={"weighting": weighting_method, "rebalance": "observed-period dynamic weights", "universe": ce_universe, "missing_prices": "no imputation; require paired observations"})
except Exception as exc:
    st.error(f"Contribution Explorer could not calculate this target: {exc}")

if contribution_result is not None:
    for warning in contribution_result.warnings:
        st.warning(warning)
    if contribution_result.starting_value is not None:
        unit = contribution_result.unit_label
        metrics = st.columns(6)
        metrics[0].metric("Start", f"{contribution_result.starting_value:,.2f}")
        metrics[1].metric("End", f"{contribution_result.ending_value:,.2f}")
        metrics[2].metric("Total Change", f"{contribution_result.total_change:+,.2f} {unit}")
        metrics[3].metric("Total Return", format_pct(contribution_result.total_return))
        metrics[4].metric("Constituents", f"{len(contribution_result.constituent_contributions):,}")
        metrics[5].metric("Residual", f"{contribution_result.residual:+.6f} {unit}")
        st.caption(f"{contribution_result.target_name} · {contribution_result.start_date.date()} → {contribution_result.end_date.date()} · reconciliation tolerance {contribution_result.reconciliation_metadata.get('tolerance')}")
        contrib_table = contribution_result.constituent_contributions.copy()
        pos = contrib_table[contrib_table["contribution"] > 0].head(10)
        neg = contrib_table[contrib_table["contribution"] < 0].sort_values("contribution").head(10)
        top_n = st.slider("Top N contributors to highlight", 3, 15, 5, key="contrib_top_n")
        left, right = st.columns(2)
        for container, title, frame, share_col in [(left, "Largest Positive Contributors", pos.head(top_n), "gross_positive_share"), (right, "Largest Negative Contributors", neg.head(top_n), "gross_negative_share")]:
            with container:
                st.markdown(f"**{title}**")
                if frame.empty:
                    st.caption("No contributors in this direction.")
                else:
                    show = frame[["ticker", "name", "category", "contribution", share_col]].rename(columns={"ticker": "Ticker", "name": "Asset", "category": "Category", "contribution": f"Contribution ({unit})", share_col: "Share"})
                    show["Share"] = pd.to_numeric(show["Share"], errors="coerce") * 100
                    st.dataframe(show, use_container_width=True, hide_index=True, column_config={f"Contribution ({unit})": st.column_config.NumberColumn(format="%+.2f"), "Share": st.column_config.NumberColumn(format="%.1f%%")})
        st.markdown("#### Reconciliation Waterfall")
        ranked = contrib_table.reindex(contrib_table["contribution"].abs().sort_values(ascending=False).index)
        shown = ranked.head(top_n)
        other = float(ranked.iloc[top_n:]["contribution"].sum()) if len(ranked) > top_n else 0.0
        labels = ["Start"] + [str(r.get("ticker") or r.get("asset_id")) for _, r in shown.iterrows()] + ["Other assets", "Cash", "Residual", "End"]
        measures = ["absolute"] + ["relative"] * len(shown) + ["relative", "relative", "relative", "total"]
        yvals = [contribution_result.starting_value] + shown["contribution"].astype(float).tolist() + [other, contribution_result.cash_contribution, contribution_result.residual, contribution_result.ending_value]
        st.plotly_chart(go.Figure(go.Waterfall(name="Contribution", orientation="v", measure=measures, x=labels, y=yvals)).update_layout(height=390, yaxis_title=unit), use_container_width=True)
        conc = concentration_metrics(contrib_table); breadth = breadth_metrics(contrib_table)
        c1, c2 = st.columns(2)
        c1.markdown("#### Contribution Concentration")
        c1.write(f"Top 1 / Top 3 / Top 5 share of gross positive contribution: {format_pct(conc['positive_top_1'])} · {format_pct(conc['positive_top_3'])} · {format_pct(conc['positive_top_5'])}")
        c1.write(f"Top 1 / Top 3 / Top 5 share of absolute contribution: {format_pct(conc['absolute_top_1'])} · {format_pct(conc['absolute_top_3'])} · {format_pct(conc['absolute_top_5'])}")
        c2.markdown("#### Contribution Breadth")
        c2.write(f"Positive: {breadth['positive_count']} · Negative: {breadth['negative_count']} · Flat: {breadth['flat_count']} · Percent positive: {format_pct(breadth['percent_positive'])}")
        st.markdown("#### Contribution Over Time")
        if contribution_result.contribution_series.empty:
            st.caption("Cumulative contribution series is unavailable for this target/window.")
        else:
            keep_ids = set(shown["asset_id"].astype(str))
            ts = contribution_result.contribution_series.copy()
            ts["Contributor"] = ts["asset_id"].where(ts["asset_id"].astype(str).isin(keep_ids), "Other")
            ts = ts.groupby(["date", "Contributor"], as_index=False)["contribution"].sum().sort_values("date")
            ts["cumulative_contribution"] = ts.groupby("Contributor")["contribution"].cumsum()
            st.plotly_chart(px.line(ts, x="date", y="cumulative_contribution", color="Contributor", markers=True, labels={"cumulative_contribution": unit}), use_container_width=True)
        leader = contrib_table.iloc[0] if not contrib_table.empty else None
        laggard = contrib_table.sort_values("contribution").iloc[0] if not contrib_table.empty else None
        direction = "gained" if contribution_result.total_change >= 0 else "declined"
        summary = f"{contribution_result.target_name} {direction} {abs(contribution_result.total_change):.1f} {unit} over the selected period."
        if leader is not None:
            summary += f" {leader.get('ticker') or leader.get('asset_id')} was the largest contributor at {leader['contribution']:+.1f} {unit}."
        if laggard is not None and laggard['contribution'] < 0:
            summary += f" {laggard.get('ticker') or laggard.get('asset_id')} was the largest detractor at {laggard['contribution']:+.1f} {unit}."
        summary += f" {breadth['positive_count']} of {breadth['total_count']} constituents contributed positively."
        st.info(summary)
        st.markdown("#### Full Contribution Table")
        search_term = st.text_input("Search contributors", key="contrib_search")
        display_contrib = contrib_table.copy()
        if search_term:
            mask = display_contrib[["asset_id", "ticker", "name", "category"]].fillna("").astype(str).apply(lambda col: col.str.contains(search_term, case=False, regex=False)).any(axis=1)
            display_contrib = display_contrib[mask]
        export_cols = display_contrib.rename(columns={"ticker": "Ticker", "name": "Asset", "category": "Category", "start_weight": "Start Weight", "end_weight": "End Weight", "average_weight": "Average Weight", "asset_return": "Asset Return", "contribution": f"Contribution ({unit})", "contribution_share": "Contribution Share", "status": "Status", "exit_indicator": "Exit Indicator"})
        for pct_col in ["Start Weight", "End Weight", "Average Weight", "Asset Return", "Contribution Share"]:
            if pct_col in export_cols:
                export_cols[pct_col] = pd.to_numeric(export_cols[pct_col], errors="coerce") * 100
        st.dataframe(export_cols[[c for c in ["Ticker", "Asset", "Category", "Start Weight", "End Weight", "Asset Return", f"Contribution ({unit})", "Contribution Share", "Status", "Exit Indicator"] if c in export_cols]], use_container_width=True, hide_index=True)
        drill_options = {f"{row.get('ticker') or row['asset_id']} | {row.get('name') or row['asset_id']}": row["asset_id"] for _, row in contrib_table.iterrows()}
        drill_label = st.selectbox("Send contributor to Asset Price History", ["—"] + list(drill_options), key="contrib_drill")
        if drill_label != "—" and st.button("Open in Asset Price History", key="contrib_open_asset"):
            st.session_state["asset_explorer_selected_asset_id"] = str(drill_options[drill_label])
            st.session_state["asset_history_mode"] = "Single Asset"
            st.rerun()
        with st.expander("Methodology Used"):
            st.json(contribution_result.methodology | {"cash": "explicit cash delta shown separately", "reconciliation": "start + asset contributions + cash + rebalance/entry-exit + residual = end"})

st.subheader("Asset Price History")
if prices.empty:
    st.info("No asset price observations are available yet.")
else:
    price_assets = prices.dropna(subset=["asset_id", "last"]).copy()
    price_assets["date"] = pd.to_datetime(price_assets["date"], errors="coerce").dt.tz_localize(None)
    price_assets = price_assets.dropna(subset=["date"])
    if not manual_price_observations.empty:
        offering_rows = manual_price_observations[
            manual_price_observations["event_type"].astype(str).eq("offering_price")
            & manual_price_observations["price_per_share"].notna()
        ].copy()
        if not offering_rows.empty:
            offering_rows["date"] = pd.to_datetime(offering_rows["observed_at"], errors="coerce", utc=True).dt.tz_localize(None)
            offering_rows["last"] = pd.to_numeric(offering_rows["price_per_share"], errors="coerce")
            offering_rows["market_cap_usd"] = pd.to_numeric(offering_rows["market_cap"], errors="coerce")
            offering_rows["source"] = "manual:" + offering_rows["event_type"].astype(str) + ":" + offering_rows["precision_status"].astype(str)
            offering_display = offering_rows[
                ["date", "asset_id", "last", "market_cap_usd", "source", "event_type", "precision_status", "period_end"]
            ].dropna(subset=["asset_id", "date", "last"])
            price_assets = pd.concat([price_assets, offering_display], ignore_index=True)
            price_assets = price_assets.sort_values(["asset_id", "date", "event_type"]).drop_duplicates(
                subset=["asset_id", "date", "last", "event_type"], keep="last"
            )
    asset_names = market[["asset_id", "ticker", "name", "category", "subcategory"]].drop_duplicates("asset_id")
    price_assets = price_assets.merge(asset_names, on="asset_id", how="left")
    price_assets["ticker"] = price_assets["ticker"].fillna(price_assets["asset_id"]).astype(str)
    price_assets["name"] = price_assets["name"].fillna(price_assets["asset_id"]).astype(str)
    price_assets["asset_label"] = price_assets["ticker"] + " | " + price_assets["name"]
    options = price_assets[["asset_id", "asset_label"]].drop_duplicates().sort_values("asset_label").reset_index(drop=True)

    history_mode = st.radio(
        "Mode",
        ["Single Asset", "Custom Index Workshop"],
        horizontal=True,
        key="asset_history_mode",
    )
    if options.empty:
        st.info("No asset price observations are available yet.")
    elif history_mode == "Single Asset":
        default_idx = 0
        explorer_asset_id = st.session_state.get("asset_explorer_selected_asset_id")
        explorer_match = options.index[options["asset_id"].astype(str).eq(str(explorer_asset_id))].tolist() if explorer_asset_id else []
        mosasaur_match = options.index[options["asset_id"].eq("rally-mosasaur")].tolist()
        if explorer_match:
            default_idx = explorer_match[0]
        elif mosasaur_match:
            default_idx = mosasaur_match[0]
        selected_label = st.selectbox("Asset", options["asset_label"].tolist(), index=default_idx, key="single_asset")
        selected_asset_id = options.loc[options["asset_label"].eq(selected_label), "asset_id"].iloc[0]
        asset_prices = price_assets[price_assets["asset_id"].eq(selected_asset_id)].sort_values("date").copy()
        hover_columns = [column for column in ["period_end", "market_cap_usd", "event_type", "source", "precision_status"] if column in asset_prices.columns]
        asset_fig = px.line(asset_prices, x="date", y="last", markers=True, hover_data=hover_columns, labels={"date": "Observed date", "last": "Price per share"})
        asset_fig.update_layout(height=320)
        st.plotly_chart(asset_fig, use_container_width=True)
        detail_columns = [column for column in ["date", "period_end", "last", "market_cap_usd", "event_type", "source", "precision_status"] if column in asset_prices.columns]
        st.dataframe(
            asset_prices[detail_columns].rename(columns={"date": "Observed date", "period_end": "Period end", "last": "Price per share", "market_cap_usd": "Market cap", "event_type": "Event type", "source": "Source", "precision_status": "Precision"}),
            use_container_width=True,
            hide_index=True,
            column_config={"Price per share": st.column_config.NumberColumn(format="$%.2f"), "Market cap": st.column_config.NumberColumn(format="$%.0f")},
        )
    else:
        st.markdown("### Custom Index Workshop")
        st.caption("Build a basket, tune its allocation, and save it for comparison in Index Explorer.")
        workshop_metadata = canonical[["asset_id", "ticker", "name", "category", "subcategory"]].drop_duplicates("asset_id")
        workshop_metadata = workshop_metadata[workshop_metadata["asset_id"].astype(str).isin(quarterly_observations["asset_id"].astype(str).unique())].copy()
        workshop_metadata["label"] = (
            workshop_metadata["ticker"].fillna(workshop_metadata["asset_id"]).astype(str)
            + " | " + workshop_metadata["name"].fillna(workshop_metadata["asset_id"]).astype(str)
            + " · " + workshop_metadata["category"].fillna("other").astype(str).str.replace("_", " ").str.title()
        )
        label_to_id = dict(zip(workshop_metadata["label"], workshop_metadata["asset_id"].astype(str)))
        id_to_label = {value: key for key, value in label_to_id.items()}
        prior_ids = st.session_state.get("workshop_constituent_ids", [])
        default_labels = [id_to_label[item] for item in prior_ids if item in id_to_label]
        selected_labels = st.multiselect(
            "Build a Basket",
            sorted(label_to_id),
            default=default_labels,
            placeholder="Search by ticker, asset, or category",
            key="workshop_asset_labels",
        )
        selected_ids = [label_to_id[label] for label in selected_labels]
        if selected_ids != prior_ids:
            st.session_state["workshop_constituent_ids"] = selected_ids
            equal_pct = 100.0 / len(selected_ids) if selected_ids else 0.0
            st.session_state["workshop_weights"] = {asset_id: equal_pct for asset_id in selected_ids}
        workshop_weights = st.session_state.setdefault("workshop_weights", {})

        def reset_workshop() -> None:
            for key in ["workshop_asset_labels", "workshop_constituent_ids", "workshop_weights", "workshop_name", "workshop_description", "workshop_saved"]:
                st.session_state.pop(key, None)

        st.button("Reset Workshop", key="workshop_reset", on_click=reset_workshop)

        if not selected_ids:
            st.info("Choose at least one asset to start your custom index at 100.")
        else:
            allocation_mode = st.radio("Allocation", ["Equal Weight", "Custom Weight"], horizontal=True, key="workshop_allocation_mode")
            if allocation_mode == "Equal Weight":
                workshop_weights = {asset_id: 100.0 / len(selected_ids) for asset_id in selected_ids}
                st.session_state["workshop_weights"] = workshop_weights
            else:
                weight_columns = st.columns(min(4, len(selected_ids)))
                for position, asset_id in enumerate(selected_ids):
                    meta = workshop_metadata[workshop_metadata["asset_id"].astype(str).eq(asset_id)].iloc[0]
                    workshop_weights[asset_id] = weight_columns[position % len(weight_columns)].number_input(
                        str(meta["ticker"]),
                        min_value=0.01,
                        max_value=100.0,
                        value=float(workshop_weights.get(asset_id, 100.0 / len(selected_ids))),
                        step=0.5,
                        format="%.2f",
                        key=f"workshop_weight_{asset_id}",
                    )
                def normalize_workshop_weights() -> None:
                    total_raw = sum(workshop_weights.values())
                    if total_raw > 0:
                        st.session_state["workshop_weights"] = {key: value / total_raw * 100 for key, value in workshop_weights.items()}
                        for asset_id, value in st.session_state["workshop_weights"].items():
                            st.session_state[f"workshop_weight_{asset_id}"] = value

                def equalize_workshop_weights() -> None:
                    equal_pct = 100.0 / len(selected_ids)
                    st.session_state["workshop_weights"] = {asset_id: equal_pct for asset_id in selected_ids}
                    for asset_id in selected_ids:
                        st.session_state[f"workshop_weight_{asset_id}"] = equal_pct

                normalize_col, equal_col = st.columns(2)
                normalize_col.button("Normalize to 100%", key="workshop_normalize", on_click=normalize_workshop_weights)
                equal_col.button("Reset to Equal Weight", key="workshop_equal", on_click=equalize_workshop_weights)

            total_weight = sum(workshop_weights.get(asset_id, 0) for asset_id in selected_ids)
            weight_valid = abs(total_weight - 100.0) <= 0.01
            (st.success if weight_valid else st.warning)(f"Total allocation: {total_weight:.2f}%" + ("" if weight_valid else " · Normalize or edit weights to continue."))
            normalized_workshop_weights = {asset_id: workshop_weights[asset_id] / 100 for asset_id in selected_ids}
            workshop_result = build_custom_index(quarterly_observations, asset_ids=selected_ids, weights=normalized_workshop_weights)
            for warning in workshop_result.warnings:
                st.warning(warning)
            if workshop_result.series.empty:
                st.error("These assets do not have enough overlapping valid price history to form an index.")
            elif weight_valid:
                workshop_metrics = calculate_index_metrics(workshop_result.series)
                workshop_figure = px.line(workshop_result.series, x="date", y="index_level", markers=True, labels={"date": "Quarter end", "index_level": "Custom index level"})
                workshop_figure.update_traces(line={"width": 3, "color": "#58a6ff"})
                workshop_figure.update_layout(height=390, hovermode="x unified")
                st.plotly_chart(workshop_figure, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})
                scorecard = st.columns(5)
                scorecard[0].metric("Total Return", format_pct(workshop_metrics["total_return"]))
                scorecard[1].metric("CAGR", format_pct(workshop_metrics["cagr"]))
                scorecard[2].metric("Volatility", format_pct(workshop_metrics["annualized_volatility"]))
                scorecard[3].metric("Sharpe", "N/A" if workshop_metrics["sharpe_ratio"] is None else f"{workshop_metrics['sharpe_ratio']:.2f}")
                scorecard[4].metric("Max Drawdown", format_pct(workshop_metrics["maximum_drawdown"]))
                st.caption(f"{len(selected_ids)} constituents · effective history {workshop_result.effective_start_date} through {workshop_result.effective_end_date} · risk band {workshop_metrics['risk_band']}")

                composition = workshop_metadata[workshop_metadata["asset_id"].astype(str).isin(selected_ids)].copy()
                composition["Weight"] = composition["asset_id"].map(normalized_workshop_weights)
                first_dates = workshop_result.aligned_prices.apply(lambda column: column.first_valid_index().date().isoformat() if column.first_valid_index() is not None else None)
                last_dates = workshop_result.aligned_prices.apply(lambda column: column.last_valid_index().date().isoformat() if column.last_valid_index() is not None else None)
                composition["Available start"] = composition["asset_id"].map(first_dates)
                composition["Available end"] = composition["asset_id"].map(last_dates)
                composition = composition.merge(workshop_result.contributions, on="asset_id", how="left")
                composition_display = composition.rename(columns={"ticker": "Ticker", "name": "Asset", "category": "Category", "asset_return": "Asset return", "contribution_points": "Contribution points"})
                composition_display["Weight"] *= 100
                composition_display["Asset return"] = pd.to_numeric(composition_display["Asset return"], errors="coerce") * 100
                st.markdown("#### Constituents & Contribution Analysis")
                st.dataframe(
                    composition_display[["Ticker", "Asset", "Category", "Weight", "Available start", "Available end", "Asset return", "Contribution points"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={"Weight": st.column_config.NumberColumn(format="%.2f%%"), "Asset return": st.column_config.NumberColumn(format="%+.1f%%"), "Contribution points": st.column_config.NumberColumn(format="%+.2f pts")},
                )

                st.markdown("#### Name & Save")
                if custom_index_read_only:
                    st.info("Saving is disabled in this cloud deployment because its filesystem is not durable. You can still export the definition as JSON.")
                name_col, description_col = st.columns([1, 2])
                index_name = name_col.text_input("Index name", max_chars=100, key="workshop_name", placeholder="e.g. Jurassic Index")
                index_description = description_col.text_area("Description (optional)", max_chars=1000, key="workshop_description", height=90)
                pending_definition = None
                if index_name.strip():
                    constituents = []
                    for asset_id in selected_ids:
                        meta = workshop_metadata[workshop_metadata["asset_id"].astype(str).eq(asset_id)].iloc[0]
                        constituents.append({"asset_id": asset_id, "display_name": str(meta["name"]), "ticker": str(meta["ticker"]), "weight": normalized_workshop_weights[asset_id]})
                    pending_definition = new_custom_index_definition(
                        name=index_name,
                        description=index_description,
                        constituents=constituents,
                        weighting_method="equal" if allocation_mode == "Equal Weight" else "custom",
                        start_date=workshop_result.effective_start_date,
                        end_date=workshop_result.effective_end_date,
                        analytics_snapshot=workshop_metrics,
                    )
                if st.button("Save Custom Index", type="primary", key="workshop_save", disabled=pending_definition is None or custom_index_read_only):
                    try:
                        saved = custom_index_registry.save(pending_definition)
                        st.session_state["workshop_saved"] = saved.model_dump(mode="json")
                        st.success(f"Saved {saved.name}. Index ID: {saved.id}. It is now available in Index Explorer.")
                    except (DuplicateCustomIndexError, CustomIndexStorageError, ValueError) as exc:
                        st.error(str(exc))
                export_definition = st.session_state.get("workshop_saved")
                if pending_definition is not None and (custom_index_read_only or export_definition is None):
                    export_definition = pending_definition.model_dump(mode="json")
                if export_definition:
                    st.download_button("Export definition (JSON)", json.dumps(export_definition, indent=2), file_name=f"{export_definition['id']}.json", mime="application/json", key="workshop_export_json")

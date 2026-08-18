from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "src"))

from app_data import get_canonical_market, render_data_diagnostics
from alt_asset_explorer.components import (
    CanonicalIndexResolver,
    ComponentDefinition,
    DirectAssetResolver,
    ResolutionContext,
)
from alt_asset_explorer.quarterly_backtesting import (
    QuarterlyBacktestRequest,
    QuarterlyStrategy,
    ThresholdRule,
    quarterly_performance_metrics,
    run_quarterly_backtest,
)


st.set_page_config(page_title="Backtesting Suite | Rare Tape", layout="wide")
render_data_diagnostics()
st.title("Quarterly Backtesting Suite")
st.caption(
    "Test systematic rules only at Rare Tape's authored quarterly observation points. "
    "This is historical research—not an appraisal, live Rally listing feed, or evidence that a trade was executable."
)

market = get_canonical_market()
assets = market.asset_master.copy()
observations = market.authored_price_observations.copy()
index_series = market.total_return_portfolio.copy()
index_constituents = market.total_return_constituents.copy()
if assets.empty or observations.empty or index_series.empty:
    st.warning("Canonical assets, authored observations, and total-return index artifacts are required.")
    st.stop()

assets["asset_id"] = assets["asset_id"].astype(str)
metadata = assets.drop_duplicates("asset_id").set_index("asset_id")
asset_counts = (
    observations[observations["frequency"].astype(str).str.casefold().eq("quarterly")]
    .groupby(observations["asset_id"].astype(str)).size()
)
eligible_asset_ids = sorted(asset_id for asset_id, count in asset_counts.items() if count >= 2 and asset_id in metadata.index)


def asset_label(asset_id: str) -> str:
    row = metadata.loc[asset_id]
    ticker = row.get("ticker") or asset_id
    name = row.get("name") or asset_id
    return f"{ticker} · {name}"


categories = sorted(value for value in index_series["category"].dropna().astype(str).unique() if value != "all")
index_options = ["Full Rally Market"] + [f"Category · {value.replace('_', ' ').title()}" for value in categories]

with st.sidebar:
    st.header("Portfolio")
    starting_value = st.number_input("Starting investment", min_value=1.0, value=100.0, step=25.0)
    selected_assets = st.multiselect(
        "Individual assets", eligible_asset_ids, format_func=asset_label,
        help="Only assets with at least two authored quarterly observations are offered. Final history uses the common-quarter intersection.",
    )
    selected_indexes = st.multiselect("Index sleeves", index_options)
    index_weighting_label = st.selectbox("Index methodology", ["Equal weight", "Market-cap weight"])
    scope_label = st.selectbox("Index universe", ["Include exited assets", "Current survivors only"])
    allocation = st.radio("Initial allocation", ["Equal weight", "Custom weight"], horizontal=True)

    instrument_keys = [f"asset:{asset_id}" for asset_id in selected_assets]
    instrument_keys += ["index:all" if item == "Full Rally Market" else f"index:{categories[index_options.index(item) - 1]}" for item in selected_indexes]
    raw_weights: dict[str, float] = {}
    if allocation == "Custom weight":
        st.caption("Custom weights must total 100%.")
        default = 100 / len(instrument_keys) if instrument_keys else 0.0
        for key in instrument_keys:
            label = asset_label(key.removeprefix("asset:")) if key.startswith("asset:") else key.removeprefix("index:").replace("_", " ").title()
            raw_weights[key] = st.number_input(label + " (%)", 0.0, 100.0, default, 1.0, key=f"bt_weight_{key}") / 100
    elif instrument_keys:
        raw_weights = {key: 1 / len(instrument_keys) for key in instrument_keys}

    st.header("Quarterly strategy")
    mode = st.radio("Mode", ["Basic portfolio", "Strategy backtest"], horizontal=True)
    rebalance_label = st.selectbox(
        "Periodic rebalancing",
        ["None / buy and hold", "Quarterly equal weight", "Quarterly original weights"],
        disabled=mode == "Basic portfolio",
    )
    profit_enabled = st.toggle("Profit-taking rule", value=False, disabled=mode == "Basic portfolio")
    profit_threshold = st.number_input("Gain exceeds (%)", 0.0, 500.0, 15.0, 1.0, disabled=not profit_enabled) / 100
    profit_reduction = st.number_input("Reduce winner by (%)", 0.0, 100.0, 50.0, 5.0, disabled=not profit_enabled) / 100
    profit_destination_label = st.selectbox(
        "Profit-sale proceeds", ["Cash", "Remaining holdings pro rata", "Original target weights"], disabled=not profit_enabled
    )
    loss_enabled = st.toggle("Quarterly loss rule", value=False, disabled=mode == "Basic portfolio")
    loss_threshold = st.number_input("Loss exceeds (%)", 0.0, 100.0, 20.0, 1.0, disabled=not loss_enabled) / 100
    loss_reduction = st.number_input("Reduce loser by (%)", 0.0, 100.0, 100.0, 5.0, disabled=not loss_enabled) / 100
    loss_destination_label = st.selectbox(
        "Loss-sale proceeds", ["Cash", "Remaining holdings pro rata", "Original target weights"], disabled=not loss_enabled
    )

if not instrument_keys:
    st.info("Select at least one individual asset or canonical index sleeve to begin.")
    st.stop()
if any(weight <= 0 for weight in raw_weights.values()) or abs(sum(raw_weights.values()) - 1) > 0.0001:
    st.warning(f"Portfolio weights must be positive and total 100%. Current total: {sum(raw_weights.values()):.2%}.")
    st.stop()

method = "equal_weight" if index_weighting_label == "Equal weight" else "market_cap_weight"
scope = "include_exited" if scope_label == "Include exited assets" else "active_only"
index_resolver = CanonicalIndexResolver(index_series, index_constituents)
asset_resolver = DirectAssetResolver()
components = []
for key, weight in raw_weights.items():
    if key.startswith("asset:"):
        asset_id = key.removeprefix("asset:")
        definition = ComponentDefinition(key, "individual_asset", str(metadata.loc[asset_id].get("ticker") or asset_id), weight, asset_id)
        components.append(asset_resolver.resolve(definition, ResolutionContext(observations=observations)))
    else:
        category = key.removeprefix("index:")
        component_type = "full_market" if category == "all" else "category_index"
        label = "Full Rally Market" if category == "all" else f"{category.replace('_', ' ').title()} Index"
        definition = ComponentDefinition(
            key + ":" + method, component_type, label, weight, category, method,
            {"universe_scope": scope, "rebalance_frequency": "quarterly"},
        )
        components.append(index_resolver.resolve(definition, ResolutionContext()))

destination = {
    "Cash": "cash",
    "Remaining holdings pro rata": "remaining_holdings",
    "Original target weights": "target_weights",
}
rebalance = {
    "None / buy and hold": "none",
    "Quarterly equal weight": "equal_weight",
    "Quarterly original weights": "original_weights",
}[rebalance_label]
if mode == "Basic portfolio":
    rebalance = "none"
    profit_enabled = loss_enabled = False
strategy = QuarterlyStrategy(
    rebalance=rebalance,
    profit_taking=ThresholdRule(profit_enabled, profit_threshold, profit_reduction, destination[profit_destination_label]),
    loss_rule=ThresholdRule(loss_enabled, loss_threshold, loss_reduction, destination[loss_destination_label]),
)
result = run_quarterly_backtest(QuarterlyBacktestRequest(
    components=components,
    starting_value=starting_value,
    strategy=strategy,
    as_of_cutoff=pd.Timestamp.utcnow().tz_localize(None).normalize(),
))
for warning in result.warnings:
    st.warning(warning)
if result.errors:
    for error in result.errors:
        st.error(error)
    st.stop()

strategy_metrics = result.summary_metrics
baseline_metrics = quarterly_performance_metrics(result.baseline.series)
baseline_metrics |= {
    "ending_value": float(result.baseline.series.iloc[-1]["growth_value"]),
    "total_return": float(result.baseline.series.iloc[-1]["cumulative_return"]),
    "total_turnover": 0.0,
    "rebalance_count": 0,
}

start_date = result.strategy_series.iloc[0]["date"]
end_date = result.strategy_series.iloc[-1]["date"]
st.info(
    f"Effective common history: **{pd.Timestamp(start_date).date()} to {pd.Timestamp(end_date).date()}** · "
    f"{len(result.strategy_series)} common quarterly observations · no interpolation or forward-fill. "
    "Rules are evaluated only after each consecutive quarter is observed."
)

comparison = pd.DataFrame({
    "Metric": ["Ending value", "Total return", "CAGR", "Annualized volatility", "Maximum drawdown", "Best quarter", "Worst quarter", "Rebalance dates", "Total turnover"],
    "Strategy": [strategy_metrics.get("ending_value"), strategy_metrics.get("total_return"), strategy_metrics.get("annualized_return"),
                 strategy_metrics.get("annualized_volatility"), strategy_metrics.get("maximum_drawdown"),
                 strategy_metrics.get("best_period_return"), strategy_metrics.get("worst_period_return"),
                 strategy_metrics.get("rebalance_count"), strategy_metrics.get("total_turnover")],
    "Buy & Hold": [baseline_metrics.get("ending_value"), baseline_metrics.get("total_return"), baseline_metrics.get("annualized_return"),
                   baseline_metrics.get("annualized_volatility"), baseline_metrics.get("maximum_drawdown"),
                   baseline_metrics.get("best_period_return"), baseline_metrics.get("worst_period_return"), 0, 0.0],
})

metrics = st.columns(5)
metrics[0].metric("Strategy ending value", f"${strategy_metrics['ending_value']:,.2f}")
metrics[1].metric("Buy & hold ending value", f"${baseline_metrics['ending_value']:,.2f}")
metrics[2].metric("Strategy CAGR", f"{strategy_metrics['annualized_return']:.2%}" if math.isfinite(strategy_metrics["annualized_return"]) else "Unavailable")
metrics[3].metric("Maximum drawdown", f"{strategy_metrics['maximum_drawdown']:.2%}")
metrics[4].metric("Turnover", f"{strategy_metrics['total_turnover']:.2%}")

growth = result.strategy_series[["date", "growth_value"]].rename(columns={"growth_value": "Strategy"})
growth = growth.merge(result.baseline.series[["date", "growth_value"]].rename(columns={"growth_value": "Buy & Hold"}), on="date", how="inner")
growth_long = growth.melt("date", var_name="Portfolio", value_name="Value")
st.plotly_chart(px.line(growth_long, x="date", y="Value", color="Portfolio", markers=True,
                        title=f"What ${starting_value:,.0f} Became"), width="stretch")

st.subheader("Performance summary")
display = comparison.copy()
money_row = display["Metric"].eq("Ending value")
count_row = display["Metric"].eq("Rebalance dates")
for column in ["Strategy", "Buy & Hold"]:
    display[column] = [
        f"${value:,.2f}" if is_money else f"{int(value)}" if is_count else f"{value:.2%}" if pd.notna(value) else "Unavailable"
        for value, is_money, is_count in zip(display[column], money_row, count_row)
    ]
st.dataframe(display, hide_index=True, width="stretch")

st.subheader("Quarterly positions and returns")
st.caption("Position values and weights are after that quarter's rebalance. A blank return means the prior common quarter was missing, so no quarterly rule was evaluated.")
st.dataframe(
    result.positions,
    hide_index=True,
    width="stretch",
    column_config={column: st.column_config.NumberColumn(format="%.2f%%") for column in ["quarterly_return", "weight_before", "weight_after"]},
)

st.subheader("Strategy event and trade log")
if result.events.empty and result.trades.empty:
    st.info("No strategy rule or rebalance trade was triggered in the effective history.")
else:
    if not result.events.empty:
        st.markdown("#### Rule signals")
        st.dataframe(
            result.events,
            hide_index=True,
            width="stretch",
            column_config={column: st.column_config.NumberColumn(format="%.2f%%") for column in ["quarterly_return", "threshold", "reduction", "weight_before", "weight_after"]},
        )
    if not result.trades.empty:
        st.markdown("#### Executed rebalance actions")
        st.dataframe(result.trades, hide_index=True, width="stretch")

with st.expander("Methodology, cash, turnover, and limitations", expanded=False):
    st.json(result.methodology)
    st.markdown("**Cash ledger**")
    st.dataframe(result.cash_history, hide_index=True, width="stretch")
    st.markdown("**Turnover ledger**")
    st.dataframe(result.turnover_history, hide_index=True, width="stretch")
    st.write(
        "The selected instruments are fixed at inception and aligned on their common canonical quarters. Missing observations remove that quarter from the shared panel; they are never treated as zero returns or filled. "
        "A return spanning a missing quarter remains in portfolio growth but is not labeled a quarterly return and cannot trigger a rule. Signals use Quarter T's completed return and trade at the later of quarter-end or the latest selected instrument's observation availability, affecting the next holding period. "
        "Cash earns 0%. The model excludes transaction costs, taxes, spreads, liquidity, and market impact. Rules applied to an index sleeve act on that sleeve, not invisibly on its underlying constituents."
    )

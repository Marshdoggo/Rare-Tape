from __future__ import annotations

# ruff: noqa: E402
from datetime import date, timedelta
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "app")]
from app_data import get_canonical_market, load_processed_csv, render_data_diagnostics
from alt_asset_explorer.derivatives import (
    DISCLAIMER,
    black_scholes_merton,
    bootstrap_probability_of_profit,
    contract_capacity,
    crr_price,
    default_underlying_id,
    discover_underlyings,
    expiration_from_days,
    historical_volatility,
    hypothetical_spread,
    implied_volatility,
    liquidity_score,
    model_confidence_score,
    numerical_greeks,
    reset_underlying_state,
    risk_neutral_itm_probability,
    strategy_analytics,
    strategy_profit,
    underlying_availability,
    underlying_by_id,
    year_fraction,
)

st.set_page_config(page_title="Derivatives Lab 2.0", layout="wide")
render_data_diagnostics()
st.title("Rally Derivatives Lab 2.0")
st.caption(
    "A modular laboratory for hypothetical, educational option research—not a Rally options offering."
)
st.error(
    "**Research-only and non-executable.** No live quotes, orders, counterparties, payments, brokerage, legal contracts, or Rally-supported options are provided."
)


@st.cache_data(show_spinner=False)
def load_underlyings():
    m = get_canonical_market()
    indices = load_processed_csv("rally_quarterly_indices")
    underlyings, discovery_warnings = discover_underlyings(
        m.asset_master,
        m.authored_price_observations,
        indices,
    )
    availability = underlying_availability(
        m.asset_master, m.authored_price_observations, indices, underlyings
    )
    return underlyings, discovery_warnings, availability


items, warnings, availability = load_underlyings()
for warning in warnings:
    st.warning(warning)
if not items:
    st.stop()
ids = [item.underlying_id for item in items]
if len(ids) != len(set(ids)):
    st.error(
        "Underlying discovery returned duplicate canonical IDs; selection is disabled."
    )
    st.stop()

st.subheader("Underlying")
label_lookup = {item.underlying_id: item.selector_label for item in items}
selected_id = st.selectbox(
    "Search eligible assets and synthetic indexes",
    options=ids,
    index=ids.index(default_underlying_id(items)),
    format_func=label_lookup.__getitem__,
    key="derivatives_underlying_id",
    help="Type to search by display name, ticker, canonical ID, category, or type.",
)
underlying_changed = reset_underlying_state(st.session_state, selected_id)
selected = underlying_by_id(items, selected_id)
if underlying_changed:
    st.toast(
        "Underlying changed; price-, volatility-, strike-, and term-dependent defaults were refreshed."
    )
if len(items) == 1:
    st.warning(
        "Only one eligible underlying was discovered. Review Underlying availability below; this is not an intentional MARX-only catalog."
    )
with st.expander("Underlying availability", expanded=False):
    st.write(
        f"**{availability.eligible_assets} eligible assets · "
        f"{availability.eligible_indices} eligible indexes · "
        f"{len(availability.excluded)} excluded**"
    )
    if availability.exclusion_reasons:
        st.caption(
            "Common reasons: "
            + "; ".join(
                f"{reason} ({count})"
                for reason, count in sorted(
                    availability.exclusion_reasons.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            )
        )
        st.dataframe(
            pd.DataFrame(availability.excluded, columns=["Underlying", "Reason"]),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No cataloged assets or registered indexes were excluded.")

history = selected.history
latest = history.date.max().date()
earliest = history.date.min().date()
stale = max((date.today() - latest).days, 0)

st.info(selected.instrument_label)
meta = st.columns(7)
meta[0].metric(
    "Latest level" if selected.is_synthetic else "Latest price",
    f"${history.iloc[-1].value:,.2f}",
)
meta[1].metric("Observation", str(latest))
meta[2].metric("Observations", len(history))
initial_est = historical_volatility(history)
meta[3].metric("Frequency", initial_est.frequency_label)
meta[4].metric("Category", selected.category.title())
meta[5].metric(
    "Market cap",
    "Not available"
    if selected.is_synthetic or selected.market_cap is None
    else f"${selected.market_cap:,.0f}",
)
meta[6].metric(
    "Shares",
    "Not available"
    if selected.is_synthetic or selected.shares_outstanding is None
    else f"{selected.shares_outstanding:,.0f}",
)
with st.sidebar:
    st.header("Contract Design")
    valuation = st.date_input(
        "Valuation date",
        latest,
        min_value=earliest,
        max_value=max(date.today(), latest),
        key="derivatives_valuation",
    )
    observed = history[history.date.dt.date <= valuation]
    spot = float((observed if len(observed) else history).iloc[-1].value)
    option_type = st.radio(
        "Option type", ["call", "put"], horizontal=True, format_func=str.title
    )
    style = st.radio(
        "Exercise style",
        ["european", "american"],
        horizontal=True,
        format_func=str.title,
    )
    strategies = ["long_call", "long_put", "covered_call", "protective_put"]
    strategy = st.selectbox(
        "Strategy view",
        strategies,
        index=0 if option_type == "call" else 1,
        format_func=lambda x: x.replace("_", " ").title(),
    )
    required = "call" if strategy in {"long_call", "covered_call"} else "put"
    if option_type != required:
        st.info(
            f"{strategy.replace('_', ' ').title()} uses a {required}; option type synchronized."
        )
        option_type = required
    multiplier = st.radio(
        "Hypothetical multiplier (shares)",
        [10, 100],
        horizontal=True,
        help="Rally does not publish standardized option contracts here.",
    )
    contracts = st.number_input("Contracts", 1, 10000, 1)
    spot = st.number_input(
        "Spot / level",
        0.0001,
        value=spot,
        format="%.4f",
        key="derivatives_spot",
    )
    preset = st.selectbox(
        "Strike preset",
        [0.8, 0.9, 1.0, 1.1, 1.2, "Custom"],
        index=2,
        format_func=lambda x: "Custom" if x == "Custom" else f"{x:.0%} of spot",
        key="derivatives_strike_preset",
    )
    strike = st.number_input(
        "Strike",
        0.0001,
        value=float(spot if preset == "Custom" else spot * float(preset)),
        format="%.4f",
        key="derivatives_strike",
    )
    horizon = st.selectbox(
        "Duration", [30, 60, 90, 180, 365], index=2, key="derivatives_duration"
    )
    expiration = st.date_input(
        "Expiration",
        expiration_from_days(valuation, horizon),
        min_value=valuation,
        max_value=valuation + timedelta(days=3650),
        key="derivatives_expiration",
    )
    time = year_fraction(valuation, expiration)
    rate = st.number_input("Risk-free rate", -1.0, 2.0, 0.04, 0.0025, format="%.4f")
    yield_rate = st.number_input(
        "Carrying / distribution yield", -1.0, 2.0, 0.0, 0.0025, format="%.4f"
    )
    steps = st.slider("CRR steps", 50, 1000, 300, 50)
est = historical_volatility(observed)
if selected.is_synthetic:
    st.warning(
        "Synthetic, non-tradable Rally Terminal research underlying; share capacity and physical hedging are unavailable."
    )
if stale > 120:
    st.warning(
        f"Latest observation is {stale} days old; spot and volatility may be stale."
    )
st.subheader("Volatility Workbench")
vc = st.columns(3)
mode = vc[0].selectbox(
    "Volatility source", ["Historical", "Manual", "Implied from hypothetical premium"]
)
manual = vc[1].number_input(
    "Manual volatility",
    0.0,
    5.0,
    float(est.annualized_volatility or 0.30),
    0.01,
    format="%.4f",
    key="derivatives_manual_volatility",
)
entered = vc[2].number_input(
    "Hypothetical premium / share",
    0.0,
    value=0.0,
    step=0.01,
    help="Required for implied volatility; never inferred from price history.",
    key="derivatives_hypothetical_premium",
)
solved = None
try:
    if entered > 0:
        solved = implied_volatility(
            option_type,
            entered,
            spot,
            strike,
            time,
            rate,
            yield_rate,
            exercise_style=style,
            steps=steps,
        )
except ValueError as e:
    st.warning(f"Implied volatility unavailable: {e}")
vol = (
    float(est.annualized_volatility or manual)
    if mode == "Historical"
    else (solved if mode.startswith("Implied") and solved is not None else manual)
)
if mode.startswith("Implied") and entered <= 0:
    st.warning(
        "Enter a hypothetical option premium to solve implied volatility; the manual assumption is used meanwhile."
    )
vm = st.columns(7)
vm[0].metric(
    "Periodic vol",
    "N/A" if est.periodic_volatility is None else f"{est.periodic_volatility:.1%}",
)
vm[1].metric(
    "Historical vol",
    "N/A" if est.annualized_volatility is None else f"{est.annualized_volatility:.1%}",
)
vm[2].metric("Pricing vol", f"{vol:.1%}")
vm[3].metric("Implied vol", "N/A" if solved is None else f"{solved:.1%}")
vm[4].metric("Returns", est.return_count)
vm[5].metric(
    "Annualization",
    f"{est.annualization_factor:.2f}" if est.annualization_factor else "N/A",
)
vm[6].metric("Lookback", f"{est.start_date} → {est.end_date}")
if est.warning:
    st.warning(est.warning)
try:
    bsm = black_scholes_merton(option_type, spot, strike, time, rate, vol, yield_rate)
    eu = crr_price(
        option_type, spot, strike, time, rate, vol, yield_rate, steps, "european"
    )
    am = crr_price(
        option_type, spot, strike, time, rate, vol, yield_rate, steps, "american"
    )
except ValueError as e:
    st.error(str(e))
    st.stop()
premium = am if style == "american" else bsm.price
analytics = strategy_analytics(
    strategy, spot, strike, premium, multiplier, int(contracts)
)
greek = (
    numerical_greeks(option_type, spot, strike, time, rate, vol, yield_rate, steps)
    if style == "american"
    else bsm
)
liq = liquidity_score(
    history,
    as_of=date.today(),
    market_cap=selected.market_cap,
    shares_outstanding=selected.shares_outstanding,
    status=selected.status,
)
conf = model_confidence_score(
    history,
    stale_days=stale,
    irregular="irregular" in est.frequency_label.lower(),
    historical_volatility_available=est.annualized_volatility is not None,
    bsm_crr_difference_pct=(eu - bsm.price) / max(bsm.price, 0.01),
    is_synthetic=selected.is_synthetic,
    capacity_available=selected.shares_outstanding is not None,
)
capacity = contract_capacity(
    None if selected.is_synthetic else selected.shares_outstanding,
    multiplier,
    int(contracts),
)
spread = hypothetical_spread(
    premium,
    bsm.intrinsic_value,
    liquidity_score_value=liq.score,
    confidence_score_value=conf.score,
    time=time,
    moneyness=spot / strike,
    volatility=vol,
    multiplier=multiplier,
    stale=stale > 120,
    hedge_infeasible=selected.is_synthetic,
)
st.subheader("Valuation & Strategy Analytics")
cards = st.columns(8)
cards[0].metric("Primary value / share", f"${premium:,.4f}")
cards[1].metric("Total premium", f"${analytics.premium_total:,.2f}")
cards[2].metric("Break-even / share", f"${analytics.breakeven:,.2f}")
cards[3].metric(
    "Maximum loss",
    "Unlimited"
    if analytics.maximum_loss is None
    else f"${analytics.maximum_loss:,.2f}",
)
cards[4].metric("BSM European", f"${bsm.price:,.4f}")
cards[5].metric("CRR European", f"${eu:,.4f}")
cards[6].metric("CRR American", f"${am:,.4f}")
cards[7].metric("Early exercise premium", f"${am - eu:,.4f}")
st.caption(
    "American style uses CRR—not BSM—as its primary value. Early exercise often adds little to non-distribution-paying calls, but can matter for puts, yield, distributions, or unusual conditions."
)
rn = risk_neutral_itm_probability(
    option_type, spot, strike, time, rate, vol, yield_rate
)
hp = bootstrap_probability_of_profit(
    history,
    strategy,
    spot,
    strike,
    premium,
    time,
    multiplier=multiplier,
    contracts=int(contracts),
    simulations=5000,
    seed=42,
)
pc = st.columns(2)
pc[0].metric("Risk-neutral probability of ITM", "N/A" if rn is None else f"{rn:.1%}")
pc[1].metric(
    "Historical bootstrap probability of profit",
    "Suppressed—insufficient evidence" if hp is None else f"{hp:.1%}",
)
st.caption(
    "These are distinct uncertain estimates, not certainties: risk-neutral ITM probability is model-implied; probability of profit bootstraps 5,000 paths from actual observation-to-observation returns at the inferred frequency (seed 42) and is suppressed with fewer than eight returns."
)
gcols = st.columns(5)
for c, (n, v) in zip(
    gcols,
    [
        ("Delta", greek.delta),
        ("Gamma", greek.gamma),
        ("Vega / 1%", greek.vega),
        ("Theta / day", greek.theta),
        ("Rho / 1%", greek.rho),
    ],
):
    c.metric(
        n,
        f"{v:,.6f}",
        delta=f"contract {v * multiplier:,.4f} · position {v * multiplier * contracts:,.4f}",
        delta_color="off",
    )
st.subheader("Payoff & Scenarios")
grid = np.linspace(max(0.01, spot * 0.2), spot * 2, 121)
profits = strategy_profit(
    strategy, grid, spot, strike, premium, multiplier, int(contracts)
)
fig = go.Figure(go.Scatter(x=grid, y=profits, name="Profit / loss"))
fig.add_hline(y=0, line_dash="dot")
fig.add_vline(x=spot, line_dash="dot", annotation_text="Spot")
fig.add_vline(x=strike, line_dash="dash", annotation_text="Strike")
fig.add_vline(x=analytics.breakeven, line_dash="dash", annotation_text="Break-even")
fig.update_layout(
    xaxis_title="Terminal underlying price / level",
    yaxis_title=f"Profit / loss ({contracts} × {multiplier})",
)
st.plotly_chart(fig, width="stretch")
scenario = pd.DataFrame({"Terminal price": grid[::10], "Strategy P/L": profits[::10]})
st.dataframe(
    scenario.style.format({"Terminal price": "${:,.2f}", "Strategy P/L": "${:,.2f}"}),
    width="stretch",
)
times = np.linspace(0, time, 20)
surface = np.array(
    [
        [
            crr_price(
                option_type, s, strike, t, rate, vol, yield_rate, min(steps, 300), style
            )
            for s in grid[::4]
        ]
        for t in times
    ]
)
st.plotly_chart(
    px.imshow(
        surface,
        x=np.round(grid[::4], 2),
        y=np.round(times * 365).astype(int),
        aspect="auto",
        labels={
            "x": "Underlying price / level",
            "y": "Days to expiration",
            "color": "Option value",
        },
        title="Underlying × time option-value surface",
    ),
    width="stretch",
)
st.subheader("Liquidity, Confidence & Hypothetical Spread")
sc = st.columns(6)
sc[0].metric("Liquidity score", f"{liq.score}/100 · {liq.label}")
sc[1].metric("Model confidence", f"{conf.score}/100 · {conf.label}")
sc[2].metric("Model midpoint", f"${spread.midpoint:,.3f}")
sc[3].metric("Hypothetical bid", f"${spread.bid:,.3f}")
sc[4].metric("Hypothetical ask", f"${spread.ask:,.3f}")
sc[5].metric(
    "Spread", f"${spread.absolute_spread:,.3f} ({spread.percentage_spread:.1%})"
)
st.caption(
    "Transparent Rally Terminal research diagnostics—not live quotes, credit ratings, suitability determinations, or regulatory classifications. Deductions: "
    + ", ".join(set(liq.deductions + conf.deductions))
)
st.subheader("Contract Capacity")
cc = st.columns(5)
cc[0].metric(
    "Shares outstanding",
    "Not available"
    if selected.shares_outstanding is None
    else f"{selected.shares_outstanding:,.0f}",
)
cc[1].metric("Shares required", f"{capacity.shares_required:,.0f}")
cc[2].metric(
    "Maximum covered contracts",
    "Not available"
    if capacity.maximum_contracts is None
    else f"{capacity.maximum_contracts:,}",
)
cc[3].metric(
    "Utilization",
    "Not available"
    if capacity.utilization_pct is None
    else f"{capacity.utilization_pct:.4f}%",
)
cc[4].metric(
    "Remaining capacity",
    "Not available"
    if capacity.remaining_contracts is None
    else f"{capacity.remaining_contracts:,}",
)
st.caption(capacity.explanation)
with st.expander("Hypothetical research term sheet", expanded=False):
    st.markdown(
        f"""### Illustrative, non-signable term sheet\n- **Underlying:** {selected.display_name} (`{selected.underlying_id}`), {"Synthetic Index" if selected.is_synthetic else "Asset"}\n- **Contract:** {style.title()} {option_type.title()}, {strategy.replace("_", " ").title()}, {contracts} × {multiplier} hypothetical shares\n- **Strike / expiration:** ${strike:,.4f} / {expiration}\n- **Primary model:** {"CRR American" if style == "american" else "Black-Scholes-Merton European"}\n- **Premium:** ${premium:,.4f} per share; ${analytics.premium_total:,.2f} total\n- **Historical / implied volatility:** {"N/A" if est.annualized_volatility is None else f"{est.annualized_volatility:.2%}"} / {"N/A" if solved is None else f"{solved:.2%}"}\n- **Liquidity / confidence:** {liq.score}/100 / {conf.score}/100\n- **Hypothetical bid / ask:** ${spread.bid:,.3f} / ${spread.ask:,.3f}\n- **Covered capacity:** {"N/A" if capacity.maximum_contracts is None else f"{capacity.maximum_contracts:,} contracts"}\n- **Settlement:** hypothetical cash settlement for modeling; feasibility unconfirmed\n- **Exercise:** {style.title()} convention; notices, assignment, share locking, collateral and defaults unresolved\n\n**Operational questions:** Rally approval; broker-dealer review; custody; share locking; collateral; transferability; settlement; assignment; exercise; defaults; surveillance; governing rules; customer eligibility; regulatory classification.\n\n**{DISCLAIMER}** This output is not signable, downloadable as an executable contract, or connected to payments or counterparties."""
    )
with st.expander("Methodology & limitations"):
    st.markdown(
        "Historical volatility uses consecutive authored observations and actual median spacing—no interpolation, forward filling, or manufactured daily data. Analytic European Greeks use per-share Delta/Gamma and Vega/Rho per one percentage point, Theta per calendar day. American Greeks use central differences (0.5% spot, 1 volatility/rate point, one day). Scores and spreads are inspectable heuristics. Collectible illiquidity, stale/irregular evidence, jumps, transfer restrictions, paused/exited assets, absent option markets, non-tradable indexes, hedge infeasibility, and unresolved settlement can invalidate conventional models."
    )

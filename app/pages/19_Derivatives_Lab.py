from __future__ import annotations

# ruff: noqa: E402 -- Streamlit pages establish repository paths before local imports.

from datetime import date, timedelta
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

from app_data import get_canonical_market, load_processed_csv, render_data_diagnostics
from alt_asset_explorer.derivatives import (
    DISCLAIMER,
    black_scholes_merton,
    crr_price,
    default_underlying_index,
    discover_underlyings,
    expiration_from_days,
    historical_volatility,
    term_sheet,
    year_fraction,
)

st.set_page_config(page_title="Derivatives Lab", layout="wide")
render_data_diagnostics()
st.title("Rally Derivatives Lab")
st.caption("Explore how conventional option-pricing models behave when applied to collectible securities and Rally Terminal indexes.")
st.error(
    "**Hypothetical research only.** These calculations do not describe Rally-supported options, an executable or legally enforceable contract, or investment, legal, tax, or regulatory advice. "
    "Any real derivative transaction would require independent legal review, counterparty documentation, and confirmation of settlement and transfer mechanics."
)


@st.cache_data(show_spinner=False)
def load_underlyings():
    market = get_canonical_market()
    index_registry = load_processed_csv("rally_quarterly_indices")
    return discover_underlyings(market.asset_master, market.authored_price_observations, index_registry)


underlyings, discovery_warnings = load_underlyings()
for warning in discovery_warnings:
    st.warning(warning)
if not underlyings:
    st.info("No assets or indexes currently have enough valid observations for the lab.")
    st.stop()

with st.sidebar:
    st.header("Contract assumptions")
    selected = st.selectbox(
        "Underlying", underlyings, index=default_underlying_index(underlyings),
        format_func=lambda item: item.short_label, key="derivative_underlying",
    )
    option_type = st.radio("European option", ["call", "put"], horizontal=True, format_func=str.title)

history = selected.history.copy()
latest_date = history["date"].max().date()
earliest_date = history["date"].min().date()
today = date.today()
st.info(selected.instrument_label)
if selected.is_synthetic:
    st.warning("This index is a Rally Terminal research series, not a directly transferable asset. Any option shown here is synthetic and theoretical.")

date_metrics = st.columns(3)
date_metrics[0].metric("Current calendar date", today.isoformat())
date_metrics[1].metric("Latest observation", latest_date.isoformat())
stale_days = max((today - latest_date).days, 0)
date_metrics[2].metric("Observation age", f"{stale_days} days")
if stale_days > 120:
    st.warning(f"The latest observation is {stale_days} days old. The displayed spot and historical volatility may be stale.")

with st.sidebar:
    valuation_date = st.date_input(
        "Valuation date", value=latest_date, min_value=earliest_date, max_value=max(today, latest_date),
        help="Defaults to the selected underlying's latest valid observation date.", key=f"valuation_{selected.underlying_id}",
    )
    eligible_history = history[history["date"].dt.date <= valuation_date]
    observed_spot = float(eligible_history.iloc[-1]["value"]) if not eligible_history.empty else float(history.iloc[0]["value"])
    spot = st.number_input("Spot price / index level", min_value=0.0001, value=observed_spot, step=max(observed_spot / 100, 0.01), format="%.4f")
    strike_choice = st.selectbox("Suggested strike", [0.8, 0.9, 1.0, 1.1, 1.2, "Custom"], index=2, format_func=lambda x: "Custom" if x == "Custom" else f"{x:.0%} of spot")
    strike_default = spot if strike_choice == "Custom" else spot * float(strike_choice)
    strike = st.number_input("Strike price", min_value=0.0001, value=float(strike_default), step=max(spot / 100, 0.01), format="%.4f")
    horizon = st.selectbox("Suggested expiration", [30, 60, 90, 180, 365, "Custom"], index=2, format_func=lambda x: "Custom" if x == "Custom" else f"{x} days")
    initial_days = 90 if horizon == "Custom" else int(horizon)
    days = st.number_input("Days to expiration", min_value=0, max_value=3650, value=initial_days, step=1)
    expiration_date = st.date_input("Expiration date", value=expiration_from_days(valuation_date, int(days)), min_value=valuation_date, max_value=valuation_date + timedelta(days=3650))
    synchronized_days = max((expiration_date - valuation_date).days, 0)
    if synchronized_days != days:
        st.caption(f"Expiration date controls the synchronized horizon: **{synchronized_days} days**.")
    days = synchronized_days
    time = year_fraction(valuation_date, expiration_date)
    rate = st.number_input("Risk-free rate", min_value=-1.0, max_value=2.0, value=0.04, step=0.0025, format="%.4f", help="Continuously compounded annual rate.")
    yield_rate = st.number_input("Dividend / carrying yield", min_value=-1.0, max_value=2.0, value=0.0, step=0.0025, format="%.4f")
    multiplier = st.number_input("Contract multiplier", min_value=0.0001, value=1.0, step=1.0, help="Editable research assumption; Rally does not publish a standard options multiplier here.")
    contracts = st.number_input("Number of contracts", min_value=1, max_value=1_000_000, value=1, step=1)

st.subheader("Volatility Lab")
vol_cols = st.columns(4)
lookback_options = ["Maximum available", 8, 12, 16, 20]
lookback_choice = vol_cols[0].selectbox("Price-observation lookback", lookback_options)
return_method = vol_cols[1].selectbox("Returns", ["log", "simple"], format_func=str.title)
preliminary = historical_volatility(
    history[history["date"].dt.date <= valuation_date],
    lookback_observations=None if lookback_choice == "Maximum available" else int(lookback_choice),
    return_method=return_method,
)
factor_mode = vol_cols[2].selectbox("Annualization", ["Inferred from actual spacing", "Custom"])
custom_factor = vol_cols[3].number_input(
    "Annualization factor", min_value=0.01, max_value=365.25,
    value=float(preliminary.inferred_annualization_factor or 4.0), step=0.25,
    disabled=factor_mode != "Custom",
)
estimate = historical_volatility(
    history[history["date"].dt.date <= valuation_date],
    lookback_observations=None if lookback_choice == "Maximum available" else int(lookback_choice),
    return_method=return_method,
    annualization_factor=custom_factor if factor_mode == "Custom" else None,
)
if estimate.warning:
    st.warning(estimate.warning)
method = st.radio("Pricing volatility", ["Historical estimate", "Manual assumption"], horizontal=True, index=0 if estimate.annualized_volatility is not None else 1)
manual_vol = st.number_input("Manual annualized volatility", min_value=0.0, max_value=5.0, value=float(estimate.annualized_volatility or 0.30), step=0.01, format="%.4f", disabled=method == "Historical estimate")
volatility = float(estimate.annualized_volatility) if method == "Historical estimate" and estimate.annualized_volatility is not None else float(manual_vol)

vm = st.columns(6)
vm[0].metric("Price observations", estimate.observation_count)
vm[1].metric("Valid returns", estimate.return_count)
vm[2].metric("Lookback", f"{estimate.start_date} → {estimate.end_date}")
vm[3].metric("Observed frequency", estimate.frequency_label)
vm[4].metric("Periodic volatility", "—" if estimate.periodic_volatility is None else f"{estimate.periodic_volatility:.2%}")
vm[5].metric("Selected volatility", f"{volatility:.2%}")
st.caption(
    f"Sample standard deviation (ddof=1) of {return_method} observation-to-observation returns × √{estimate.annualization_factor or 0:.3f}. "
    "The factor is inferred as 365.25 ÷ median actual spacing in days unless overridden. No observations are interpolated or forward-filled."
)

st.subheader("Theoretical valuation")
steps = st.slider("CRR binomial steps", 25, 1000, 200, 25)
try:
    result = black_scholes_merton(option_type, spot, strike, time, rate, volatility, yield_rate)
    binomial = crr_price(option_type, spot, strike, time, rate, volatility, yield_rate, steps)
except ValueError as error:
    st.error(str(error))
    st.stop()

premium = result.price
total_premium = premium * multiplier * int(contracts)
time_value = max(premium - result.intrinsic_value, 0.0)
moneyness = spot / strike if option_type == "call" else strike / spot
breakeven = strike + premium if option_type == "call" else strike - premium
summary = st.columns(6)
summary[0].metric("BSM premium / unit", f"${premium:,.4f}")
summary[1].metric("Total premium", f"${total_premium:,.2f}")
summary[2].metric("Intrinsic value", f"${result.intrinsic_value:,.4f}")
summary[3].metric("Time value", f"${time_value:,.4f}")
summary[4].metric("Moneyness ratio", f"{moneyness:.3f}×")
summary[5].metric("Expiration breakeven", f"${breakeven:,.4f}")
comparison = st.columns(3)
comparison[0].metric("CRR premium / unit", f"${binomial:,.4f}")
comparison[1].metric("CRR − BSM", f"${binomial - premium:+,.6f}")
comparison[2].metric("Actual/365 time", f"{time:.6f} years ({days} days)")
greeks = st.columns(5)
for column, (name, value, help_text) in zip(greeks, [
    ("Delta", result.delta, "Option value change per one-unit underlying move"),
    ("Gamma", result.gamma, "Delta change per one-unit underlying move"),
    ("Vega", result.vega, "Option value change per one percentage-point volatility move"),
    ("Theta / day", result.theta, "Option value change per calendar day, all else equal"),
    ("Rho", result.rho, "Option value change per one percentage-point rate move"),
]):
    column.metric(name, f"{value:,.6f}", help=help_text)

if option_type == "call":
    st.write(f"**Long-call payoff description:** maximum loss is the ${total_premium:,.2f} premium; theoretical maximum profit is unlimited; breakeven is ${breakeven:,.4f} at expiration.")
else:
    max_profit = max(strike - premium, 0) * multiplier * int(contracts)
    st.write(f"**Long-put payoff description:** maximum loss is the ${total_premium:,.2f} premium; maximum profit is ${max_profit:,.2f} if the underlying reaches zero; breakeven is ${breakeven:,.4f} at expiration.")

st.subheader("Scenario visualizations")
price_grid = np.linspace(max(spot * 0.2, 0.0001), spot * 2.0, 121)
gross = np.maximum(price_grid - strike, 0) if option_type == "call" else np.maximum(strike - price_grid, 0)
net = gross - premium
payoff_fig = go.Figure()
payoff_fig.add_trace(go.Scatter(x=price_grid, y=gross, name="Gross payoff"))
payoff_fig.add_trace(go.Scatter(x=price_grid, y=net, name="Net profit after premium"))
payoff_fig.add_hline(y=0, line_dash="dot")
payoff_fig.update_layout(title="Payoff at expiration (per underlying unit)", xaxis_title="Underlying at expiration", yaxis_title="Value / profit")

history_fig = px.line(history, x="date", y="value", markers=True, labels={"date": "Observation date", "value": "Price / index level"}, title="Underlying history (authored/index observations only)")
history_fig.add_hline(y=strike, line_dash="dash", annotation_text="Strike")
history_fig.add_vline(x=pd.Timestamp(valuation_date).timestamp() * 1000, line_dash="dot", annotation_text="Valuation")

value_grid = [black_scholes_merton(option_type, value, strike, time, rate, volatility, yield_rate).price for value in price_grid]
value_fig = px.line(x=price_grid, y=value_grid, labels={"x": "Underlying price / level", "y": "Theoretical option value"}, title="Option value versus underlying before expiration")

chart_left, chart_right = st.columns(2)
chart_left.plotly_chart(history_fig, width="stretch", config={"displaylogo": False})
chart_right.plotly_chart(payoff_fig, width="stretch", config={"displaylogo": False})
st.plotly_chart(value_fig, width="stretch", config={"displaylogo": False})

strike_grid = strike * np.array([0.8, 0.9, 1.0, 1.1, 1.2])
horizon_grid = [30, 60, 90, 180, 365]
matrix = np.array([[black_scholes_merton(option_type, spot, k, d / 365, rate, volatility, yield_rate).price for k in strike_grid] for d in horizon_grid])
heatmap = px.imshow(matrix, x=[f"${x:,.2f}" for x in strike_grid], y=[f"{x}d" for x in horizon_grid], text_auto=".3f", aspect="auto", color_continuous_scale="Blues", labels={"x": "Strike", "y": "Expiration horizon", "color": "Premium"}, title="Strike × expiration sensitivity")
vol_grid = np.linspace(max(volatility * 0.5, 0.001), max(volatility * 1.5, 0.01), 31)
vol_values = [black_scholes_merton(option_type, spot, strike, time, rate, value, yield_rate).price for value in vol_grid]
vol_fig = px.line(x=vol_grid, y=vol_values, labels={"x": "Annualized volatility", "y": "Theoretical option value"}, title="Volatility sensitivity")
vol_fig.update_xaxes(tickformat=".0%")
sense_left, sense_right = st.columns(2)
sense_left.plotly_chart(heatmap, width="stretch", config={"displaylogo": False})
sense_right.plotly_chart(vol_fig, width="stretch", config={"displaylogo": False})

with st.expander("Methodology, assumptions, and collectible-market model risk"):
    st.markdown(r"""
**Black-Scholes-Merton formulas**

\[d_1 = \frac{\ln(S/K) + (r-q+\sigma^2/2)T}{\sigma\sqrt{T}},\qquad d_2=d_1-\sigma\sqrt{T}\]
\[C = Se^{-qT}N(d_1)-Ke^{-rT}N(d_2),\qquad P=Ke^{-rT}N(-d_2)-Se^{-qT}N(-d_1)\]

Time is actual calendar days divided by 365. Rates and carrying yield are continuously compounded. Historical volatility is the sample standard deviation of consecutive valid simple or log returns, annualized by the square root of the chosen observations-per-year factor. CRR uses \(u=e^{\sigma\sqrt{\Delta t}}\), \(d=1/u\), and risk-neutral probability \(p=(e^{(r-q)\Delta t}-d)/(u-d)\).

BSM assumes frictionless continuous trading, continuous hedging, lognormal prices, constant volatility/rates/yield, no arbitrage, and known settlement. Collectible securities can violate every one of these assumptions through **illiquidity, irregular and stale observations, discrete trading windows, transfer restrictions, pauses and exits, lack of continuous hedging, and the absence of a liquid options market**. Index levels may be non-tradable. Results therefore contain substantial data, settlement, legal, and model risk and are not appraisals or forecasts.
""")
    st.write(f"Selected rate: {rate:.4%}; yield: {yield_rate:.4%}; volatility: {volatility:.4%}; time: {days}/365 = {time:.6f} years.")

st.subheader("Illustrative Option Term Sheet")
sheet = term_sheet(selected, option_type, multiplier, int(contracts), strike, premium, valuation_date, expiration_date, volatility, rate)
st.markdown(sheet)
st.caption(DISCLAIMER)

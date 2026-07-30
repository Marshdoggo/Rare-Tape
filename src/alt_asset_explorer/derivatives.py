"""Research-only derivative analytics over canonical Rally histories.

The functions in this module are deliberately independent of Streamlit.  They
price hypothetical European claims; they do not describe an available Rally
product, executable trade, or legal contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import norm

OptionType = Literal["call", "put"]
MINIMUM_PRICES = 4
DISCLAIMER = (
    "For research and discussion only — not an offer, solicitation, executable "
    "trade, or legal contract."
)


@dataclass(frozen=True)
class Underlying:
    underlying_id: str
    display_name: str
    short_label: str
    kind: Literal["asset", "index"]
    category: str
    weighting_method: str | None
    history: pd.DataFrame
    source: str

    @property
    def is_synthetic(self) -> bool:
        return self.kind == "index"

    @property
    def instrument_label(self) -> str:
        return (
            "Synthetic theoretical option on a non-tradable Rally Terminal index"
            if self.is_synthetic
            else "Theoretical option on a Rally share (transferability unconfirmed)"
        )


@dataclass(frozen=True)
class VolatilityEstimate:
    observation_count: int
    return_count: int
    start_date: date | None
    end_date: date | None
    frequency_label: str
    median_spacing_days: float | None
    inferred_annualization_factor: float | None
    annualization_factor: float | None
    periodic_volatility: float | None
    annualized_volatility: float | None
    return_method: str
    warning: str | None = None


@dataclass(frozen=True)
class OptionResult:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    intrinsic_value: float


def clean_history(frame: pd.DataFrame, *, date_column: str, value_column: str) -> pd.DataFrame:
    """Return valid, sorted observations without filling absent dates.

    When the source contains duplicate dates, the last source row wins.  This
    deterministic rule preserves an authored correction without inventing an
    observation between known dates.
    """
    if frame.empty or date_column not in frame or value_column not in frame:
        return pd.DataFrame(columns=["date", "value"])
    clean = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce", format="mixed"),
            "value": pd.to_numeric(frame[value_column], errors="coerce"),
        }
    )
    clean = clean.dropna().loc[lambda x: x["value"].gt(0)]
    return clean.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def discover_underlyings(
    assets: pd.DataFrame,
    observations: pd.DataFrame,
    indices: pd.DataFrame,
    *,
    minimum_prices: int = MINIMUM_PRICES,
) -> tuple[list[Underlying], list[str]]:
    """Discover supported canonical assets and registered index series."""
    results: list[Underlying] = []
    warnings: list[str] = []
    if not assets.empty and "asset_id" in assets and "asset_id" in observations:
        meta = assets.drop_duplicates("asset_id", keep="last").set_index("asset_id")
        date_col = "observed_at" if "observed_at" in observations else "date"
        value_col = "price_per_share" if "price_per_share" in observations else "last"
        for asset_id, rows in observations.groupby(observations["asset_id"].astype(str), sort=True):
            history = clean_history(rows, date_column=date_col, value_column=value_col)
            if len(history) < minimum_prices or asset_id not in meta.index:
                continue
            row = meta.loc[asset_id]
            ticker = str(row.get("ticker") or asset_id).lstrip("#")
            name = str(row.get("asset_name") or row.get("name") or ticker)
            category = str(row.get("category") or "Uncategorized")
            results.append(
                Underlying(
                    f"asset:{asset_id}", name, f"{ticker} — {name}", "asset",
                    category, None, history, "Canonical authored Rally observations",
                )
            )
    if not indices.empty and "index_id" in indices:
        for index_id, rows in indices.groupby(indices["index_id"].astype(str), sort=True):
            history = clean_history(rows, date_column="date", value_column="index_level")
            if len(history) < minimum_prices:
                continue
            row = rows.iloc[-1]
            name = str(row.get("index_name") or index_id)
            weighting = str(row.get("weighting_method") or "unknown")
            category = str(row.get("category") or "all")
            results.append(
                Underlying(
                    f"index:{index_id}", name, f"Synthetic index — {name}", "index",
                    category, weighting, history,
                    "Committed Rally Terminal quarterly index research artifact",
                )
            )
    if not results:
        warnings.append("No underlyings meet the minimum valid-price requirement.")
    elif not any(item.kind == "asset" and item.short_label.split(" — ", 1)[0].upper() == "MARX" for item in results):
        warnings.append("MARX is unavailable or lacks sufficient valid history; another eligible underlying is selected.")
    return sorted(results, key=lambda x: (x.kind != "asset", x.short_label.lower())), warnings


def default_underlying_index(underlyings: list[Underlying]) -> int:
    for position, item in enumerate(underlyings):
        if item.kind == "asset" and item.short_label.split(" — ", 1)[0].upper() == "MARX":
            return position
    return 0


def infer_frequency(dates: pd.Series) -> tuple[str, float | None, float | None]:
    values = pd.Series(pd.to_datetime(dates, errors="coerce")).dropna().drop_duplicates().sort_values()
    if len(values) < 2:
        return "Insufficient", None, None
    spacing = values.diff().dt.total_seconds().dropna() / 86400
    median = float(spacing.median())
    factor = 365.25 / median if median > 0 else None
    if median <= 2:
        label = "Daily"
    elif median <= 10:
        label = "Weekly"
    elif median <= 45:
        label = "Monthly"
    elif median <= 135:
        label = "Quarterly"
    elif median <= 270:
        label = "Semiannual"
    else:
        label = "Annual / sparse"
    irregularity = float(spacing.std(ddof=1) / median) if len(spacing) > 1 and median else 0
    if irregularity > 0.35:
        label += " (irregular)"
    return label, median, factor


def historical_volatility(
    history: pd.DataFrame,
    *,
    lookback_observations: int | None = None,
    return_method: Literal["simple", "log"] = "log",
    annualization_factor: float | None = None,
    minimum_returns: int = 3,
) -> VolatilityEstimate:
    clean = clean_history(history, date_column="date", value_column="value")
    if lookback_observations:
        clean = clean.tail(max(int(lookback_observations), 2))
    label, spacing, inferred = infer_frequency(clean["date"])
    returns = np.log(clean["value"] / clean["value"].shift()) if return_method == "log" else clean["value"].pct_change(fill_method=None)
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    factor = float(annualization_factor) if annualization_factor is not None else inferred
    periodic = float(returns.std(ddof=1)) if len(returns) >= 2 else None
    annualized = periodic * math.sqrt(factor) if periodic is not None and factor is not None and factor > 0 else None
    warning = None
    if len(returns) < minimum_returns:
        warning = f"Only {len(returns)} valid returns are available; at least {minimum_returns} are required for a defensible historical estimate."
        annualized = None
    elif len(returns) < 8:
        warning = "This volatility estimate is unstable because it uses fewer than eight returns."
    return VolatilityEstimate(
        len(clean), len(returns), clean["date"].min().date() if not clean.empty else None,
        clean["date"].max().date() if not clean.empty else None, label, spacing, inferred,
        factor, periodic, annualized, return_method, warning,
    )


def year_fraction(valuation_date: date, expiration_date: date) -> float:
    return max((expiration_date - valuation_date).days, 0) / 365.0


def expiration_from_days(valuation_date: date, days: int) -> date:
    return valuation_date + timedelta(days=max(int(days), 0))


def _validate_inputs(spot: float, strike: float, time: float, volatility: float) -> None:
    values = (spot, strike, time, volatility)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Spot, strike, time, and volatility must be finite.")
    if spot <= 0 or strike <= 0:
        raise ValueError("Spot and strike must be positive.")
    if time < 0 or volatility < 0:
        raise ValueError("Time and volatility cannot be negative.")


def black_scholes_merton(
    option_type: OptionType, spot: float, strike: float, time: float,
    rate: float, volatility: float, yield_rate: float = 0.0,
) -> OptionResult:
    """Price a European option and return Greeks (Vega/Rho per 1%, Theta/day)."""
    _validate_inputs(spot, strike, time, volatility)
    if option_type not in {"call", "put"}:
        raise ValueError("Option type must be 'call' or 'put'.")
    intrinsic = max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    if time <= 1e-12:
        delta = (1.0 if spot > strike else 0.0) if option_type == "call" else (-1.0 if spot < strike else 0.0)
        return OptionResult(intrinsic, delta, 0.0, 0.0, 0.0, 0.0, intrinsic)
    discounted_spot = spot * math.exp(-yield_rate * time)
    discounted_strike = strike * math.exp(-rate * time)
    if volatility <= 1e-12:
        deterministic = discounted_spot - discounted_strike
        price = max(deterministic, 0.0) if option_type == "call" else max(-deterministic, 0.0)
        call_itm = deterministic > 0
        delta = math.exp(-yield_rate * time) * (1.0 if call_itm else 0.0)
        if option_type == "put":
            delta = -math.exp(-yield_rate * time) * (0.0 if call_itm else 1.0)
        rho = (strike * time * math.exp(-rate * time) * (1 if option_type == "call" else -1) / 100) if price > 0 else 0.0
        return OptionResult(price, delta, 0.0, 0.0, 0.0, rho, intrinsic)
    root_t = math.sqrt(time)
    d1 = (math.log(spot / strike) + (rate - yield_rate + 0.5 * volatility**2) * time) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    density = norm.pdf(d1)
    if option_type == "call":
        price = discounted_spot * norm.cdf(d1) - discounted_strike * norm.cdf(d2)
        delta = math.exp(-yield_rate * time) * norm.cdf(d1)
        theta_year = (-discounted_spot * density * volatility / (2 * root_t) - rate * discounted_strike * norm.cdf(d2) + yield_rate * discounted_spot * norm.cdf(d1))
        rho = strike * time * math.exp(-rate * time) * norm.cdf(d2) / 100
    else:
        price = discounted_strike * norm.cdf(-d2) - discounted_spot * norm.cdf(-d1)
        delta = math.exp(-yield_rate * time) * (norm.cdf(d1) - 1)
        theta_year = (-discounted_spot * density * volatility / (2 * root_t) + rate * discounted_strike * norm.cdf(-d2) - yield_rate * discounted_spot * norm.cdf(-d1))
        rho = -strike * time * math.exp(-rate * time) * norm.cdf(-d2) / 100
    gamma = math.exp(-yield_rate * time) * density / (spot * volatility * root_t)
    vega = discounted_spot * density * root_t / 100
    return OptionResult(float(price), float(delta), float(gamma), float(vega), float(theta_year / 365), float(rho), intrinsic)


def crr_price(
    option_type: OptionType, spot: float, strike: float, time: float, rate: float,
    volatility: float, yield_rate: float = 0.0, steps: int = 200,
) -> float:
    """European Cox-Ross-Rubinstein value using backward induction."""
    _validate_inputs(spot, strike, time, volatility)
    if not 1 <= int(steps) <= 2000:
        raise ValueError("Binomial steps must be between 1 and 2,000.")
    if time <= 1e-12 or volatility <= 1e-12:
        return black_scholes_merton(option_type, spot, strike, time, rate, volatility, yield_rate).price
    dt = time / int(steps)
    up = math.exp(volatility * math.sqrt(dt))
    down = 1 / up
    probability = (math.exp((rate - yield_rate) * dt) - down) / (up - down)
    if not 0 <= probability <= 1:
        raise ValueError("The selected inputs do not produce a valid CRR probability; increase steps or revise assumptions.")
    nodes = np.arange(int(steps) + 1)
    terminal = spot * up**nodes * down ** (int(steps) - nodes)
    values = np.maximum(terminal - strike, 0) if option_type == "call" else np.maximum(strike - terminal, 0)
    discount = math.exp(-rate * dt)
    for _ in range(int(steps)):
        values = discount * (probability * values[1:] + (1 - probability) * values[:-1])
    return float(values[0])


def term_sheet(
    underlying: Underlying, option_type: OptionType, multiplier: float, contracts: int,
    strike: float, premium: float, valuation_date: date, expiration_date: date,
    volatility: float, rate: float, model: str = "Black-Scholes-Merton",
) -> str:
    questions = [
        "Whether Rally shares can be transferred directly between users and whether platform approval is required",
        "Whether physical or cash settlement would be possible",
        "Treatment if trading is paused or the asset exits",
        "Treatment of corporate-action-equivalent events",
        "Counterparty default and collateral arrangements",
        "Exercise notice procedure",
        "Governing law and regulatory classification",
    ]
    return "\n".join([
        "# Illustrative Option Term Sheet", f"**{DISCLAIMER}**", "",
        f"- **Underlying:** {underlying.display_name} (`{underlying.underlying_id}`)",
        f"- **Instrument characterization:** {underlying.instrument_label}",
        f"- **Option:** European {option_type.title()}",
        f"- **Quantity:** {contracts:,} illustrative contract(s) × {multiplier:,.4g} underlying units",
        f"- **Strike:** ${strike:,.4f}", f"- **Theoretical premium:** ${premium:,.4f} per underlying unit",
        f"- **Valuation date:** {valuation_date.isoformat()}", f"- **Expiration date:** {expiration_date.isoformat()}",
        "- **Settlement assumption:** Hypothetical cash settlement for modeling only; feasibility is unconfirmed",
        f"- **Data source:** {underlying.source}", f"- **Pricing model:** {model}",
        f"- **Volatility assumption:** {volatility:.2%}", f"- **Continuously compounded risk-free rate:** {rate:.2%}",
        "", "## Major unresolved legal and operational questions",
        *[f"- {question}" for question in questions],
    ])

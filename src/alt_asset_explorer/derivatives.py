"""Research-only derivative analytics over canonical Rally histories.

The functions in this module are deliberately independent of Streamlit.  They
price hypothetical European claims; they do not describe an available Rally
product, executable trade, or legal contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
from collections.abc import MutableMapping
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.stats import norm

OptionType = Literal["call", "put"]
ExerciseStyle = Literal["european", "american"]
Strategy = Literal["long_call", "long_put", "covered_call", "protective_put"]
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
    ticker: str | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    status: str | None = None
    trading_state: str | None = None

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

    @property
    def selector_label(self) -> str:
        """Human-readable label; canonical IDs remain the selector values."""
        identity = self.ticker or self.underlying_id.removeprefix("index:")
        kind = "Synthetic Index" if self.is_synthetic else "Asset"
        return f"{self.display_name} · {identity} · {self.category.title()} · {kind}"


@dataclass(frozen=True)
class UnderlyingAvailability:
    eligible_assets: int
    eligible_indices: int
    excluded: tuple[tuple[str, str], ...]

    @property
    def exclusion_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, reason in self.excluded:
            counts[reason] = counts.get(reason, 0) + 1
        return counts


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


def clean_history(
    frame: pd.DataFrame, *, date_column: str, value_column: str
) -> pd.DataFrame:
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
    return (
        clean.drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


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
        for asset_id, rows in observations.groupby(
            observations["asset_id"].astype(str), sort=True
        ):
            history = clean_history(rows, date_column=date_col, value_column=value_col)
            if len(history) < minimum_prices or asset_id not in meta.index:
                continue
            row = meta.loc[asset_id]
            ticker = str(row.get("ticker") or asset_id).lstrip("#")
            name = str(row.get("asset_name") or row.get("name") or ticker)
            category = str(row.get("category") or "Uncategorized")
            shares = pd.to_numeric(
                row.get("shares_outstanding", row.get("share_count")), errors="coerce"
            )
            market_cap = pd.to_numeric(
                row.get("offering_market_cap", row.get("offering_valuation_usd")),
                errors="coerce",
            )
            latest_cap = (
                float(history.iloc[-1]["value"] * shares)
                if pd.notna(shares) and shares > 0
                else market_cap
            )
            results.append(
                Underlying(
                    f"asset:{asset_id}",
                    name,
                    f"{ticker} — {name}",
                    "asset",
                    category,
                    None,
                    history,
                    "Canonical authored Rally observations",
                    ticker,
                    float(latest_cap) if pd.notna(latest_cap) else None,
                    float(shares) if pd.notna(shares) and shares > 0 else None,
                    str(row.get("status")) if pd.notna(row.get("status")) else None,
                    str(row.get("trading_state"))
                    if pd.notna(row.get("trading_state"))
                    else None,
                )
            )
    if not indices.empty and "index_id" in indices:
        for index_id, rows in indices.groupby(
            indices["index_id"].astype(str), sort=True
        ):
            history = clean_history(
                rows, date_column="date", value_column="index_level"
            )
            if len(history) < minimum_prices:
                continue
            row = rows.iloc[-1]
            name = str(row.get("index_name") or index_id)
            weighting = str(row.get("weighting_method") or "unknown")
            category = str(row.get("category") or "all")
            results.append(
                Underlying(
                    f"index:{index_id}",
                    name,
                    f"Synthetic index — {name}",
                    "index",
                    category,
                    weighting,
                    history,
                    "Committed Rally Terminal quarterly index research artifact",
                )
            )
    if not results:
        warnings.append("No underlyings meet the minimum valid-price requirement.")
    elif not any(
        item.kind == "asset" and item.short_label.split(" — ", 1)[0].upper() == "MARX"
        for item in results
    ):
        warnings.append(
            "MARX is unavailable or lacks sufficient valid history; another eligible underlying is selected."
        )
    return sorted(
        results, key=lambda x: (x.kind != "asset", x.short_label.lower())
    ), warnings


def underlying_availability(
    assets: pd.DataFrame,
    observations: pd.DataFrame,
    indices: pd.DataFrame,
    underlyings: list[Underlying],
    *,
    minimum_prices: int = MINIMUM_PRICES,
) -> UnderlyingAvailability:
    """Explain catalog exclusions without changing canonical eligibility policy."""
    eligible_ids = {item.underlying_id for item in underlyings}
    excluded: list[tuple[str, str]] = []
    date_col = "observed_at" if "observed_at" in observations else "date"
    value_col = "price_per_share" if "price_per_share" in observations else "last"
    observation_groups = (
        {
            str(key): value
            for key, value in observations.groupby(observations["asset_id"].astype(str))
        }
        if "asset_id" in observations
        else {}
    )
    if "asset_id" in assets:
        for _, row in assets.drop_duplicates("asset_id", keep="last").iterrows():
            asset_id = str(row["asset_id"])
            canonical_id = f"asset:{asset_id}"
            if canonical_id in eligible_ids:
                continue
            rows = observation_groups.get(asset_id, pd.DataFrame())
            history = clean_history(rows, date_column=date_col, value_column=value_col)
            label = str(row.get("ticker") or asset_id).lstrip("#")
            if rows.empty:
                reason = "missing canonical price series"
            elif history.empty:
                reason = "no positive latest price"
            elif len(history) < minimum_prices:
                reason = f"fewer than {minimum_prices} valid observations"
            else:
                reason = "invalid or duplicate-only history"
            excluded.append((f"{label} ({asset_id})", reason))
    if "index_id" in indices:
        for index_id, rows in indices.groupby(indices["index_id"].astype(str)):
            if f"index:{index_id}" in eligible_ids:
                continue
            history = clean_history(
                rows, date_column="date", value_column="index_level"
            )
            reason = (
                "missing canonical price series"
                if history.empty
                else f"fewer than {minimum_prices} valid observations"
            )
            excluded.append((str(index_id), reason))
    return UnderlyingAvailability(
        sum(item.kind == "asset" for item in underlyings),
        sum(item.kind == "index" for item in underlyings),
        tuple(sorted(excluded)),
    )


def underlying_by_id(underlyings: list[Underlying], underlying_id: str) -> Underlying:
    """Resolve a stable canonical selector value, rejecting ambiguous catalogs."""
    matches = [item for item in underlyings if item.underlying_id == underlying_id]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one underlying for {underlying_id!r}; found {len(matches)}."
        )
    return matches[0]


def default_underlying_id(underlyings: list[Underlying]) -> str:
    if not underlyings:
        raise ValueError("No eligible underlyings are available.")
    return underlyings[default_underlying_index(underlyings)].underlying_id


UNDERLYING_SENSITIVE_STATE_KEYS = (
    "derivatives_valuation",
    "derivatives_spot",
    "derivatives_strike_preset",
    "derivatives_strike",
    "derivatives_duration",
    "derivatives_expiration",
    "derivatives_manual_volatility",
    "derivatives_hypothetical_premium",
)


def reset_underlying_state(state: MutableMapping[str, Any], selected_id: str) -> bool:
    """Clear only price/history-dependent controls when the underlying changes."""
    previous = state.get("derivatives_active_underlying_id")
    changed = previous is not None and previous != selected_id
    if changed:
        for key in UNDERLYING_SENSITIVE_STATE_KEYS:
            state.pop(key, None)
    state["derivatives_active_underlying_id"] = selected_id
    return changed


def default_underlying_index(underlyings: list[Underlying]) -> int:
    for position, item in enumerate(underlyings):
        if (
            item.kind == "asset"
            and item.short_label.split(" — ", 1)[0].upper() == "MARX"
        ):
            return position
    return 0


def infer_frequency(dates: pd.Series) -> tuple[str, float | None, float | None]:
    values = (
        pd.Series(pd.to_datetime(dates, errors="coerce"))
        .dropna()
        .drop_duplicates()
        .sort_values()
    )
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
    irregularity = (
        float(spacing.std(ddof=1) / median) if len(spacing) > 1 and median else 0
    )
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
    returns = (
        np.log(clean["value"] / clean["value"].shift())
        if return_method == "log"
        else clean["value"].pct_change(fill_method=None)
    )
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    factor = (
        float(annualization_factor) if annualization_factor is not None else inferred
    )
    periodic = float(returns.std(ddof=1)) if len(returns) >= 2 else None
    annualized = (
        periodic * math.sqrt(factor)
        if periodic is not None and factor is not None and factor > 0
        else None
    )
    warning = None
    if len(returns) < minimum_returns:
        warning = f"Only {len(returns)} valid returns are available; at least {minimum_returns} are required for a defensible historical estimate."
        annualized = None
    elif len(returns) < 8:
        warning = "This volatility estimate is unstable because it uses fewer than eight returns."
    return VolatilityEstimate(
        len(clean),
        len(returns),
        clean["date"].min().date() if not clean.empty else None,
        clean["date"].max().date() if not clean.empty else None,
        label,
        spacing,
        inferred,
        factor,
        periodic,
        annualized,
        return_method,
        warning,
    )


def year_fraction(valuation_date: date, expiration_date: date) -> float:
    return max((expiration_date - valuation_date).days, 0) / 365.0


def expiration_from_days(valuation_date: date, days: int) -> date:
    return valuation_date + timedelta(days=max(int(days), 0))


def _validate_inputs(
    spot: float, strike: float, time: float, volatility: float
) -> None:
    values = (spot, strike, time, volatility)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Spot, strike, time, and volatility must be finite.")
    if spot <= 0 or strike <= 0:
        raise ValueError("Spot and strike must be positive.")
    if time < 0 or volatility < 0:
        raise ValueError("Time and volatility cannot be negative.")


def black_scholes_merton(
    option_type: OptionType,
    spot: float,
    strike: float,
    time: float,
    rate: float,
    volatility: float,
    yield_rate: float = 0.0,
) -> OptionResult:
    """Price a European option and return Greeks (Vega/Rho per 1%, Theta/day)."""
    _validate_inputs(spot, strike, time, volatility)
    if option_type not in {"call", "put"}:
        raise ValueError("Option type must be 'call' or 'put'.")
    intrinsic = (
        max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    )
    if time <= 1e-12:
        delta = (
            (1.0 if spot > strike else 0.0)
            if option_type == "call"
            else (-1.0 if spot < strike else 0.0)
        )
        return OptionResult(intrinsic, delta, 0.0, 0.0, 0.0, 0.0, intrinsic)
    discounted_spot = spot * math.exp(-yield_rate * time)
    discounted_strike = strike * math.exp(-rate * time)
    if volatility <= 1e-12:
        deterministic = discounted_spot - discounted_strike
        price = (
            max(deterministic, 0.0)
            if option_type == "call"
            else max(-deterministic, 0.0)
        )
        call_itm = deterministic > 0
        delta = math.exp(-yield_rate * time) * (1.0 if call_itm else 0.0)
        if option_type == "put":
            delta = -math.exp(-yield_rate * time) * (0.0 if call_itm else 1.0)
        rho = (
            (
                strike
                * time
                * math.exp(-rate * time)
                * (1 if option_type == "call" else -1)
                / 100
            )
            if price > 0
            else 0.0
        )
        return OptionResult(price, delta, 0.0, 0.0, 0.0, rho, intrinsic)
    root_t = math.sqrt(time)
    d1 = (
        math.log(spot / strike) + (rate - yield_rate + 0.5 * volatility**2) * time
    ) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    density = norm.pdf(d1)
    if option_type == "call":
        price = discounted_spot * norm.cdf(d1) - discounted_strike * norm.cdf(d2)
        delta = math.exp(-yield_rate * time) * norm.cdf(d1)
        theta_year = (
            -discounted_spot * density * volatility / (2 * root_t)
            - rate * discounted_strike * norm.cdf(d2)
            + yield_rate * discounted_spot * norm.cdf(d1)
        )
        rho = strike * time * math.exp(-rate * time) * norm.cdf(d2) / 100
    else:
        price = discounted_strike * norm.cdf(-d2) - discounted_spot * norm.cdf(-d1)
        delta = math.exp(-yield_rate * time) * (norm.cdf(d1) - 1)
        theta_year = (
            -discounted_spot * density * volatility / (2 * root_t)
            + rate * discounted_strike * norm.cdf(-d2)
            - yield_rate * discounted_spot * norm.cdf(-d1)
        )
        rho = -strike * time * math.exp(-rate * time) * norm.cdf(-d2) / 100
    gamma = math.exp(-yield_rate * time) * density / (spot * volatility * root_t)
    vega = discounted_spot * density * root_t / 100
    return OptionResult(
        float(price),
        float(delta),
        float(gamma),
        float(vega),
        float(theta_year / 365),
        float(rho),
        intrinsic,
    )


def crr_price(
    option_type: OptionType,
    spot: float,
    strike: float,
    time: float,
    rate: float,
    volatility: float,
    yield_rate: float = 0.0,
    steps: int = 200,
    exercise_style: ExerciseStyle = "european",
) -> float:
    """CRR value with optional American early exercise at every tree node."""
    _validate_inputs(spot, strike, time, volatility)
    if option_type not in {"call", "put"}:
        raise ValueError("Option type must be 'call' or 'put'.")
    if exercise_style not in {"european", "american"}:
        raise ValueError("Exercise style must be 'european' or 'american'.")
    if not 1 <= int(steps) <= 2000:
        raise ValueError("Binomial steps must be between 1 and 2,000.")
    if time <= 1e-12:
        return black_scholes_merton(
            option_type, spot, strike, time, rate, volatility, yield_rate
        ).price
    if volatility <= 1e-12:
        european = black_scholes_merton(
            option_type, spot, strike, time, rate, volatility, yield_rate
        ).price
        if exercise_style == "european":
            return european
        # With deterministic carry, the best exercise date lies on this bounded grid.
        times = np.linspace(0.0, time, int(steps) + 1)
        spots = spot * np.exp((rate - yield_rate) * times)
        discounted = np.exp(-rate * times) * (
            np.maximum(spots - strike, 0)
            if option_type == "call"
            else np.maximum(strike - spots, 0)
        )
        return float(max(european, discounted.max()))
    dt = time / int(steps)
    up = math.exp(volatility * math.sqrt(dt))
    down = 1 / up
    probability = (math.exp((rate - yield_rate) * dt) - down) / (up - down)
    if not 0 <= probability <= 1:
        raise ValueError(
            "The selected inputs do not produce a valid CRR probability; increase steps or revise assumptions."
        )
    nodes = np.arange(int(steps) + 1)
    terminal = spot * up**nodes * down ** (int(steps) - nodes)
    values = (
        np.maximum(terminal - strike, 0)
        if option_type == "call"
        else np.maximum(strike - terminal, 0)
    )
    discount = math.exp(-rate * dt)
    for level in range(int(steps) - 1, -1, -1):
        values = discount * (probability * values[1:] + (1 - probability) * values[:-1])
        if exercise_style == "american":
            level_nodes = np.arange(level + 1)
            level_spots = spot * up**level_nodes * down ** (level - level_nodes)
            exercise = (
                np.maximum(level_spots - strike, 0)
                if option_type == "call"
                else np.maximum(strike - level_spots, 0)
            )
            values = np.maximum(values, exercise)
    return float(values[0])


def term_sheet(
    underlying: Underlying,
    option_type: OptionType,
    multiplier: float,
    contracts: int,
    strike: float,
    premium: float,
    valuation_date: date,
    expiration_date: date,
    volatility: float,
    rate: float,
    model: str = "Black-Scholes-Merton",
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
    return "\n".join(
        [
            "# Illustrative Option Term Sheet",
            f"**{DISCLAIMER}**",
            "",
            f"- **Underlying:** {underlying.display_name} (`{underlying.underlying_id}`)",
            f"- **Instrument characterization:** {underlying.instrument_label}",
            f"- **Option:** European {option_type.title()}",
            f"- **Quantity:** {contracts:,} illustrative contract(s) × {multiplier:,.4g} underlying units",
            f"- **Strike:** ${strike:,.4f}",
            f"- **Theoretical premium:** ${premium:,.4f} per underlying unit",
            f"- **Valuation date:** {valuation_date.isoformat()}",
            f"- **Expiration date:** {expiration_date.isoformat()}",
            "- **Settlement assumption:** Hypothetical cash settlement for modeling only; feasibility is unconfirmed",
            f"- **Data source:** {underlying.source}",
            f"- **Pricing model:** {model}",
            f"- **Volatility assumption:** {volatility:.2%}",
            f"- **Continuously compounded risk-free rate:** {rate:.2%}",
            "",
            "## Major unresolved legal and operational questions",
            *[f"- {question}" for question in questions],
        ]
    )


@dataclass(frozen=True)
class StrategyAnalytics:
    strategy: Strategy
    shares: float
    premium_total: float
    underlying_capital: float
    total_position_cost: float
    breakeven: float
    maximum_profit: float | None
    maximum_loss: float | None
    downside_buffer_pct: float | None


@dataclass(frozen=True)
class ResearchScore:
    score: int
    label: str
    components: dict[str, float]
    deductions: tuple[str, ...]


@dataclass(frozen=True)
class SpreadEstimate:
    midpoint: float
    bid: float
    ask: float
    absolute_spread: float
    percentage_spread: float
    components: dict[str, float]


@dataclass(frozen=True)
class CapacityEstimate:
    available: bool
    maximum_contracts: int | None
    selected_contracts: int
    shares_required: float
    utilization_pct: float | None
    remaining_contracts: int | None
    explanation: str


def strategy_analytics(
    strategy: Strategy,
    spot: float,
    strike: float,
    premium: float,
    multiplier: float = 10,
    contracts: int = 1,
    entry_price: float | None = None,
) -> StrategyAnalytics:
    """Scale expiration strategy economics to the hypothetical contract quantity."""
    _validate_inputs(spot, strike, 0, 0)
    if strategy not in {"long_call", "long_put", "covered_call", "protective_put"}:
        raise ValueError("Unsupported strategy view.")
    if multiplier <= 0 or contracts <= 0 or premium < 0:
        raise ValueError(
            "Multiplier/contracts must be positive and premium cannot be negative."
        )
    entry = float(spot if entry_price is None else entry_price)
    if entry <= 0:
        raise ValueError("Entry price must be positive.")
    shares = float(multiplier * contracts)
    premium_total = premium * shares
    capital = entry * shares if strategy in {"covered_call", "protective_put"} else 0.0
    if strategy == "long_call":
        breakeven, max_profit, max_loss = strike + premium, None, premium_total
    elif strategy == "long_put":
        breakeven, max_profit, max_loss = (
            strike - premium,
            max(strike - premium, 0) * shares,
            premium_total,
        )
    elif strategy == "covered_call":
        breakeven = entry - premium
        max_profit, max_loss = (
            (strike - entry + premium) * shares,
            max(entry - premium, 0) * shares,
        )
    else:
        breakeven = entry + premium
        max_profit, max_loss = None, max(entry + premium - strike, 0) * shares
    return StrategyAnalytics(
        strategy,
        shares,
        premium_total,
        capital,
        capital + (premium_total if strategy == "protective_put" else 0),
        breakeven,
        max_profit,
        max_loss,
        premium / entry,
    )


def strategy_profit(
    strategy: Strategy,
    terminal_price: float | np.ndarray,
    spot: float,
    strike: float,
    premium: float,
    multiplier: float = 10,
    contracts: int = 1,
    entry_price: float | None = None,
) -> np.ndarray:
    terminal = np.asarray(terminal_price, dtype=float)
    entry = spot if entry_price is None else entry_price
    scale = multiplier * contracts
    if strategy == "long_call":
        result = np.maximum(terminal - strike, 0) - premium
    elif strategy == "long_put":
        result = np.maximum(strike - terminal, 0) - premium
    elif strategy == "covered_call":
        result = terminal - entry + premium - np.maximum(terminal - strike, 0)
    elif strategy == "protective_put":
        result = terminal - entry - premium + np.maximum(strike - terminal, 0)
    else:
        raise ValueError("Unsupported strategy view.")
    return result * scale


def implied_volatility(
    option_type: OptionType,
    premium: float,
    spot: float,
    strike: float,
    time: float,
    rate: float,
    yield_rate: float = 0.0,
    *,
    exercise_style: ExerciseStyle = "european",
    steps: int = 300,
    lower: float = 1e-8,
    upper: float = 5.0,
    tolerance: float = 1e-7,
) -> float:
    """Solve volatility from a user-supplied hypothetical premium by bisection."""
    _validate_inputs(spot, strike, time, 0)
    if premium < 0 or not math.isfinite(premium):
        raise ValueError("Hypothetical premium must be finite and non-negative.")
    if time <= 1e-12:
        intrinsic = (
            max(spot - strike, 0) if option_type == "call" else max(strike - spot, 0)
        )
        if abs(premium - intrinsic) <= tolerance:
            return 0.0
        raise ValueError(
            "At expiration only intrinsic value is valid; implied volatility is not identifiable."
        )
    price = (
        (
            lambda v: (
                black_scholes_merton(
                    option_type, spot, strike, time, rate, v, yield_rate
                ).price
            )
        )
        if exercise_style == "european"
        else (
            lambda v: crr_price(
                option_type, spot, strike, time, rate, v, yield_rate, steps, "american"
            )
        )
    )
    low_price, high_price = price(lower), price(upper)
    if premium < low_price - tolerance or premium > high_price + tolerance:
        raise ValueError(
            f"Premium is outside model bounds [{low_price:.6g}, {high_price:.6g}] for the selected assumptions."
        )
    if abs(premium - low_price) <= tolerance:
        return 0.0
    lo, hi = lower, upper
    for _ in range(100):
        mid = (lo + hi) / 2
        value = price(mid)
        if abs(value - premium) <= tolerance:
            return mid
        if value < premium:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def numerical_greeks(
    option_type: OptionType,
    spot: float,
    strike: float,
    time: float,
    rate: float,
    volatility: float,
    yield_rate: float = 0.0,
    steps: int = 300,
    exercise_style: ExerciseStyle = "american",
) -> OptionResult:
    """Central-difference Greeks; Vega/Rho are per 1% and Theta per calendar day."""

    def fn(s: float, t: float, r: float, v: float) -> float:
        return crr_price(
            option_type,
            s,
            strike,
            max(t, 0),
            r,
            max(v, 0),
            yield_rate,
            steps,
            exercise_style,
        )

    p = fn(spot, time, rate, volatility)
    ds = max(spot * 0.005, 0.01)
    dv = 0.01
    dr = 0.01
    dt = 1 / 365
    delta = (
        fn(spot + ds, time, rate, volatility)
        - fn(max(spot - ds, 1e-8), time, rate, volatility)
    ) / (2 * ds)
    gamma = (
        fn(spot + ds, time, rate, volatility)
        - 2 * p
        + fn(max(spot - ds, 1e-8), time, rate, volatility)
    ) / ds**2
    vega = (
        fn(spot, time, rate, volatility + dv)
        - fn(spot, time, rate, max(volatility - dv, 0))
    ) / 2
    rho = (
        fn(spot, time, rate + dr, volatility) - fn(spot, time, rate - dr, volatility)
    ) / 2
    theta = fn(spot, max(time - dt, 0), rate, volatility) - p
    intrinsic = (
        max(spot - strike, 0) if option_type == "call" else max(strike - spot, 0)
    )
    return OptionResult(p, delta, gamma, vega, theta, rho, intrinsic)


def contract_capacity(
    shares_outstanding: float | None, multiplier: float, contracts: int
) -> CapacityEstimate:
    required = multiplier * contracts
    if multiplier <= 0 or contracts <= 0:
        raise ValueError("Multiplier and contracts must be positive.")
    if (
        shares_outstanding is None
        or not math.isfinite(shares_outstanding)
        or shares_outstanding <= 0
    ):
        return CapacityEstimate(
            False,
            None,
            contracts,
            required,
            None,
            None,
            "Not available: reliable total shares outstanding are absent or the underlying is synthetic.",
        )
    maximum = math.floor(shares_outstanding / multiplier)
    return CapacityEstimate(
        True,
        maximum,
        contracts,
        required,
        100 * required / shares_outstanding,
        max(maximum - contracts, 0),
        "Mechanical fully covered research estimate; transferability, availability, borrowing and collateral eligibility are unconfirmed.",
    )


def _score_label(score: int) -> str:
    return (
        "Very Low"
        if score < 25
        else "Low"
        if score < 50
        else "Moderate"
        if score < 75
        else "High"
    )


def liquidity_score(
    history: pd.DataFrame,
    *,
    as_of: date | None = None,
    market_cap: float | None = None,
    shares_outstanding: float | None = None,
    status: str | None = None,
) -> ResearchScore:
    clean = clean_history(history, date_column="date", value_column="value")
    label, spacing, _ = infer_frequency(clean["date"])
    age = (as_of or date.today()) - (
        clean["date"].max().date() if not clean.empty else date.min
    )
    components = {
        "history": min(len(clean) / 20, 1) * 30,
        "recency": max(0, 1 - age.days / 365) * 30,
        "regularity": 5 if "irregular" in label.lower() else 15,
        "market_cap": 10 if market_cap and market_cap > 0 else 0,
        "share_count": 10 if shares_outstanding and shares_outstanding > 0 else 0,
    }
    if status and status.lower() not in {"trading", "active", "active_tradable"}:
        components["status"] = -25
    score = max(0, min(100, round(sum(components.values()))))
    deductions = tuple(k.replace("_", " ") for k, v in components.items() if v <= 5)
    return ResearchScore(score, _score_label(score), components, deductions)


def model_confidence_score(
    history: pd.DataFrame,
    *,
    stale_days: int,
    irregular: bool,
    historical_volatility_available: bool,
    bsm_crr_difference_pct: float,
    is_synthetic: bool,
    capacity_available: bool,
) -> ResearchScore:
    components = {
        "sample_size": min(len(history) / 20, 1) * 25,
        "recency": max(0, 20 - stale_days / 18.25),
        "regularity": 5 if irregular else 15,
        "volatility_evidence": 15 if historical_volatility_available else 0,
        "model_agreement": max(0, 15 - min(abs(bsm_crr_difference_pct), 1) * 15),
        "hedge_and_capacity": 0 if is_synthetic else (10 if capacity_available else 4),
    }
    score = max(0, min(100, round(sum(components.values()))))
    deductions = tuple(k.replace("_", " ") for k, v in components.items() if v < 8)
    return ResearchScore(score, _score_label(score), components, deductions)


def hypothetical_spread(
    midpoint: float,
    intrinsic: float,
    *,
    liquidity_score_value: float,
    confidence_score_value: float,
    time: float,
    moneyness: float,
    volatility: float,
    multiplier: float,
    stale: bool = False,
    hedge_infeasible: bool = False,
) -> SpreadEstimate:
    if midpoint < 0 or intrinsic < 0:
        raise ValueError("Midpoint and intrinsic cannot be negative.")
    components = {
        "base": 0.04,
        "liquidity": 0.20 * (1 - liquidity_score_value / 100),
        "confidence": 0.16 * (1 - confidence_score_value / 100),
        "term": min(time, 2) * 0.015,
        "moneyness": min(abs(math.log(max(moneyness, 1e-9))), 1) * 0.04,
        "volatility": min(volatility, 3) * 0.02,
        "size": min(math.log10(max(multiplier, 1)), 3) * 0.01,
        "stale": 0.06 if stale else 0,
        "hedge": 0.08 if hedge_infeasible else 0,
    }
    pct = min(max(sum(components.values()), 0.02), 0.80)
    half = max(midpoint, 0.01) * pct / 2
    bid = max(intrinsic, midpoint - half, 0)
    ask = max(midpoint + half, bid)
    spread = ask - bid
    return SpreadEstimate(
        midpoint, bid, ask, spread, spread / midpoint if midpoint else 0, components
    )


def risk_neutral_itm_probability(
    option_type: OptionType,
    spot: float,
    strike: float,
    time: float,
    rate: float,
    volatility: float,
    yield_rate: float = 0.0,
) -> float | None:
    """BSM risk-neutral terminal ITM probability; this is not a forecast."""
    _validate_inputs(spot, strike, time, volatility)
    if time <= 0:
        return float(spot > strike) if option_type == "call" else float(spot < strike)
    if volatility <= 0:
        return None
    d2 = (
        math.log(spot / strike) + (rate - yield_rate - 0.5 * volatility**2) * time
    ) / (volatility * math.sqrt(time))
    return float(norm.cdf(d2) if option_type == "call" else norm.cdf(-d2))


def bootstrap_probability_of_profit(
    history: pd.DataFrame,
    strategy: Strategy,
    spot: float,
    strike: float,
    premium: float,
    time: float,
    *,
    multiplier: float = 10,
    contracts: int = 1,
    simulations: int = 5000,
    seed: int = 42,
) -> float | None:
    """Reproducible return bootstrap at the history's inferred observation frequency."""
    clean = clean_history(history, date_column="date", value_column="value")
    returns = (
        np.log(clean.value / clean.value.shift())
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .to_numpy()
    )
    _, _, factor = infer_frequency(clean.date)
    if len(returns) < 8 or not factor or time <= 0:
        return None
    simulations = max(100, min(int(simulations), 100_000))
    periods = max(1, round(time * factor))
    rng = np.random.default_rng(seed)
    terminal = spot * np.exp(
        rng.choice(returns, size=(simulations, periods), replace=True).sum(axis=1)
    )
    return float(
        np.mean(
            strategy_profit(
                strategy, terminal, spot, strike, premium, multiplier, contracts
            )
            > 0
        )
    )

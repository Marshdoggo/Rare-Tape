from datetime import date

import pandas as pd
import pytest

from alt_asset_explorer.derivatives import (
    DISCLAIMER,
    Underlying,
    black_scholes_merton,
    crr_price,
    default_underlying_index,
    discover_underlyings,
    expiration_from_days,
    historical_volatility,
    term_sheet,
    year_fraction,
)


def test_black_scholes_reference_call_and_put_prices_and_greeks():
    call = black_scholes_merton("call", 100, 100, 1, 0.05, 0.20)
    put = black_scholes_merton("put", 100, 100, 1, 0.05, 0.20)
    assert call.price == pytest.approx(10.4506, abs=1e-4)
    assert put.price == pytest.approx(5.5735, abs=1e-4)
    assert call.delta == pytest.approx(0.6368, abs=1e-4)
    assert put.delta == pytest.approx(-0.3632, abs=1e-4)
    assert call.gamma == pytest.approx(0.018762, abs=1e-6)
    assert call.vega == pytest.approx(0.37524, abs=1e-5)
    assert call.theta == pytest.approx(-0.017573, abs=1e-6)
    assert call.rho == pytest.approx(0.532325, abs=1e-6)


def test_put_call_parity_with_carrying_yield():
    inputs = dict(
        spot=87, strike=90, time=0.75, rate=0.04, volatility=0.31, yield_rate=0.015
    )
    call = black_scholes_merton("call", **inputs).price
    put = black_scholes_merton("put", **inputs).price
    expected = inputs["spot"] * __import__("math").exp(
        -inputs["yield_rate"] * inputs["time"]
    ) - inputs["strike"] * __import__("math").exp(-inputs["rate"] * inputs["time"])
    assert call - put == pytest.approx(expected, abs=1e-10)


def test_expiration_date_and_actual_365_time_handling():
    valuation = date(2024, 2, 29)
    expiration = expiration_from_days(valuation, 365)
    assert expiration == date(2025, 2, 28)
    assert year_fraction(valuation, expiration) == 1.0
    assert year_fraction(expiration, valuation) == 0.0


def test_zero_time_and_zero_volatility_have_safe_deterministic_values():
    expired_call = black_scholes_merton("call", 110, 100, 0, 0.05, 0.2)
    expired_put = black_scholes_merton("put", 90, 100, 0, 0.05, 0.2)
    assert expired_call.price == 10
    assert expired_put.price == 10
    deterministic = black_scholes_merton("call", 100, 100, 1, 0.05, 0)
    assert deterministic.price == pytest.approx(
        100 - 100 * __import__("math").exp(-0.05)
    )
    assert crr_price("call", 100, 100, 1, 0.05, 0) == pytest.approx(deterministic.price)


def test_irregular_volatility_uses_actual_spacing_without_filling():
    history = pd.DataFrame(
        {
            "date": [
                "2023-01-01",
                "2023-01-08",
                "2023-02-20",
                "2023-06-30",
                "2024-01-05",
            ],
            "value": [10, 11, 9, 12, 13],
        }
    )
    estimate = historical_volatility(history, return_method="simple")
    assert estimate.observation_count == 5
    assert estimate.return_count == 4
    assert "irregular" in estimate.frequency_label.lower()
    assert estimate.median_spacing_days == pytest.approx(86.5)
    assert estimate.inferred_annualization_factor == pytest.approx(365.25 / 86.5)
    assert estimate.periodic_volatility is not None
    assert estimate.annualized_volatility == pytest.approx(
        estimate.periodic_volatility * (365.25 / 86.5) ** 0.5
    )


def test_sparse_volatility_is_unavailable_but_reports_evidence():
    history = pd.DataFrame(
        {"date": ["2024-01-01", "2024-04-01", "2024-07-01"], "value": [10, 11, 12]}
    )
    estimate = historical_volatility(history)
    assert estimate.observation_count == 3
    assert estimate.return_count == 2
    assert estimate.annualized_volatility is None
    assert "at least 3" in estimate.warning


def test_dynamic_discovery_deduplicates_dates_and_labels_assets_and_indices():
    assets = pd.DataFrame(
        [
            {
                "asset_id": "rally-marx",
                "ticker": "MARX",
                "asset_name": "Das Kapital",
                "category": "books",
            },
            {
                "asset_id": "sparse",
                "ticker": "ONE",
                "asset_name": "Sparse",
                "category": "art",
            },
        ]
    )
    observations = pd.DataFrame(
        {
            "asset_id": ["rally-marx"] * 5 + ["sparse"],
            "observed_at": [
                "2023-01-01",
                "2023-04-01",
                "2023-04-01",
                "2023-07-01",
                "2023-10-01",
                "2023-01-01",
            ],
            "price_per_share": [10, 11, 12, 13, 14, 5],
        }
    )
    indices = pd.DataFrame(
        {
            "index_id": ["books_equal"] * 4,
            "index_name": ["Books Equal Index"] * 4,
            "date": ["2023-01-01", "2023-04-01", "2023-07-01", "2023-10-01"],
            "index_level": [100, 102, 99, 105],
            "weighting_method": ["equal"] * 4,
            "category": ["books"] * 4,
        }
    )
    underlyings, warnings = discover_underlyings(
        assets, observations, indices, minimum_prices=4
    )
    assert not warnings
    assert [item.kind for item in underlyings] == ["asset", "index"]
    assert len(underlyings[0].history) == 4
    assert underlyings[0].history.iloc[1]["value"] == 12
    assert default_underlying_index(underlyings) == 0
    assert "transferability unconfirmed" in underlyings[0].instrument_label
    assert "non-tradable" in underlyings[1].instrument_label


def test_discovery_handles_missing_and_sparse_data():
    assets = pd.DataFrame([{"asset_id": "a", "ticker": "A", "asset_name": "A"}])
    observations = pd.DataFrame(
        [{"asset_id": "a", "observed_at": "2024-01-01", "price_per_share": None}]
    )
    underlyings, warnings = discover_underlyings(assets, observations, pd.DataFrame())
    assert underlyings == []
    assert warnings == ["No underlyings meet the minimum valid-price requirement."]


def test_term_sheet_is_non_executable_and_contains_required_questions():
    underlying = Underlying(
        "index:test",
        "Test Index",
        "Synthetic index — Test",
        "index",
        "all",
        "equal",
        pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "value": [100]}),
        "Test source",
    )
    sheet = term_sheet(
        underlying,
        "put",
        10,
        2,
        95,
        4.25,
        date(2024, 1, 1),
        date(2024, 4, 1),
        0.3,
        0.04,
    )
    assert DISCLAIMER in sheet
    assert "Illustrative Option Term Sheet" in sheet
    assert "non-tradable" in sheet
    assert "platform approval" in sheet
    assert "physical or cash settlement" in sheet
    assert "Counterparty default" in sheet
    assert "Governing law and regulatory classification" in sheet


def test_american_crr_values_and_early_exercise_relationships():
    from alt_asset_explorer.derivatives import crr_price

    args = (100, 100, 1, 0.05, 0.2, 0)
    ec = crr_price("call", *args, steps=500, exercise_style="european")
    ac = crr_price("call", *args, steps=500, exercise_style="american")
    ep = crr_price("put", *args, steps=500, exercise_style="european")
    ap = crr_price("put", *args, steps=500, exercise_style="american")
    assert ac >= ec - 1e-10 and ap >= ep - 1e-10
    assert ac == pytest.approx(ec, abs=1e-8)
    assert ap > ep


def test_implied_volatility_round_trip_and_impossible_input():
    from alt_asset_explorer.derivatives import implied_volatility

    price = black_scholes_merton("put", 90, 100, 0.75, 0.03, 0.37, 0.01).price
    assert implied_volatility("put", price, 90, 100, 0.75, 0.03, 0.01) == pytest.approx(
        0.37, abs=1e-5
    )
    with pytest.raises(ValueError, match="outside model bounds"):
        implied_volatility("call", 1000, 100, 100, 1, 0.03)


def test_strategy_scaling_break_even_and_capacity():
    from alt_asset_explorer.derivatives import contract_capacity, strategy_analytics

    call = strategy_analytics("long_call", 100, 105, 4, 10, 2)
    covered = strategy_analytics("covered_call", 100, 105, 4, 100, 2)
    protected = strategy_analytics("protective_put", 100, 95, 3, 10, 1)
    assert call.premium_total == 80 and call.breakeven == 109
    assert (
        covered.shares == 200
        and covered.breakeven == 96
        and covered.maximum_profit == 1800
    )
    assert (
        protected.total_position_cost == 1030
        and protected.maximum_loss == 80
        and protected.breakeven == 103
    )
    capacity = contract_capacity(1005, 100, 3)
    assert capacity.maximum_contracts == 10 and capacity.remaining_contracts == 7
    assert not contract_capacity(None, 10, 1).available


def test_numerical_greeks_scores_spread_and_bootstrap_bounds():
    from alt_asset_explorer.derivatives import (
        bootstrap_probability_of_profit,
        hypothetical_spread,
        liquidity_score,
        model_confidence_score,
        numerical_greeks,
    )

    g = numerical_greeks("put", 100, 100, 0.5, 0.03, 0.25, steps=250)
    assert g.delta < 0 and g.gamma > 0 and g.vega > 0
    history = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=12, freq="30D"),
            "value": [100, 102, 99, 103, 105, 101, 108, 110, 107, 112, 115, 114],
        }
    )
    liq = liquidity_score(
        history,
        as_of=date(2024, 1, 1),
        market_cap=1e6,
        shares_outstanding=10000,
        status="trading",
    )
    confidence = model_confidence_score(
        history,
        stale_days=10,
        irregular=False,
        historical_volatility_available=True,
        bsm_crr_difference_pct=0.01,
        is_synthetic=False,
        capacity_available=True,
    )
    assert 0 <= liq.score <= 100 and 0 <= confidence.score <= 100
    spread = hypothetical_spread(
        5,
        1,
        liquidity_score_value=liq.score,
        confidence_score_value=confidence.score,
        time=0.5,
        moneyness=1,
        volatility=0.3,
        multiplier=10,
    )
    assert (
        0 <= spread.bid <= spread.midpoint <= spread.ask
        and spread.absolute_spread == pytest.approx(spread.ask - spread.bid)
    )
    probability = bootstrap_probability_of_profit(
        history, "long_call", 114, 110, 5, 0.5
    )
    assert probability is not None and 0 <= probability <= 1

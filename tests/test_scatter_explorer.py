import math

import pandas as pd
import pytest

from alt_asset_explorer.scatter_explorer import (
    AXIS_METRICS,
    COLOR_METRICS,
    METRICS,
    build_asset_metric_table,
    calculate_series_metrics,
    export_scatter_csv,
    filter_date_range,
    filter_universe,
    marker_sizes,
    prepare_scatter_data,
    validate_registry,
)


def prices(values, dates):
    return pd.Series(values, index=pd.to_datetime(dates))


def test_quarterly_annualized_arithmetic_return_and_volatility_are_consistent():
    series = prices(
        [100, 110, 99, 108.9, 108.9], pd.date_range("2020-03-31", periods=5, freq="QE")
    )
    result = calculate_series_metrics(series, minimum_returns=4)
    returns = series.pct_change().dropna()
    assert result["periods_per_year"] == 4
    assert result["annualized_mean_return"] == pytest.approx(returns.mean() * 4)
    assert result["annualized_volatility"] == pytest.approx(
        returns.std(ddof=1) * math.sqrt(4)
    )
    assert str(result["frequency_methodology"]).startswith("regular")


def test_irregular_history_uses_elapsed_observation_rate_not_daily_assumption():
    dates = ["2020-01-01", "2020-02-01", "2020-11-01", "2021-01-15", "2022-01-01"]
    result = calculate_series_metrics(
        prices([10, 11, 12, 10, 13], dates), minimum_returns=4
    )
    expected = 4 / ((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25)
    assert result["periods_per_year"] == pytest.approx(expected)
    assert "irregular" in result["frequency_methodology"]
    assert result["periods_per_year"] != 252


def test_insufficient_observations_are_unavailable_but_dates_are_reported():
    result = calculate_series_metrics(
        prices([10, 11, 12], ["2020-01-01", "2020-04-01", "2020-07-01"]),
        minimum_returns=4,
    )
    assert math.isnan(result["annualized_mean_return"])
    assert result["effective_start"] == pd.Timestamp("2020-01-01")
    assert result["effective_end"] == pd.Timestamp("2020-07-01")
    assert result["observation_count"] == 3


def fixtures():
    assets = pd.DataFrame(
        [
            {
                "asset_id": "a",
                "ticker": "A",
                "asset_name": "Alpha",
                "category": "cars",
                "subcategory": "sports",
                "status": "trading",
                "shares_outstanding": 100,
                "offering_date": "2020-01-01",
                "offering_price_per_share": 10,
                "offering_market_cap": 1000,
            },
            {
                "asset_id": "b",
                "ticker": "B",
                "asset_name": "Beta",
                "category": "books",
                "subcategory": "rare",
                "status": "sold",
                "shares_outstanding": 200,
                "offering_date": "2021-01-01",
                "offering_price_per_share": 20,
                "offering_market_cap": 4000,
            },
        ]
    )
    rows = []
    for asset_id, base in [("a", 10), ("b", 20)]:
        for i, date in enumerate(pd.date_range("2020-03-31", periods=5, freq="QE")):
            rows.append(
                {
                    "asset_id": asset_id,
                    "observed_at": date,
                    "price_per_share": base + i,
                    "market_cap": (base + i) * (100 if asset_id == "a" else 200),
                }
            )
    return assets, pd.DataFrame(rows)


def test_date_filter_metric_table_and_market_cap_extraction():
    assets, observations = fixtures()
    selected = filter_date_range(observations, "2020-06-01", "2020-12-31")
    assert selected["observed_at"].min() == pd.Timestamp("2020-06-30")
    table = build_asset_metric_table(assets, observations, minimum_returns=4)
    alpha = table.set_index("asset_id").loc["a"]
    assert alpha["market_cap"] == 1400
    assert alpha["effective_end"] == pd.Timestamp("2021-03-31")
    assert alpha["return_since_offering"] == pytest.approx(0.4)


def test_universe_category_active_exited_and_search_filters():
    assets, observations = fixtures()
    table = build_asset_metric_table(assets, observations, minimum_returns=4)
    assert filter_universe(table, categories=["cars"], minimum_observations=4)[
        "ticker"
    ].tolist() == ["A"]
    assert filter_universe(table, include_exited=False, minimum_observations=4)[
        "ticker"
    ].tolist() == ["A"]
    assert filter_universe(
        table,
        include_exited=True,
        statuses=["sold"],
        search="beta",
        minimum_observations=4,
    )["ticker"].tolist() == ["B"]


def test_marker_size_is_bounded_for_extremes_and_missing_values():
    result = marker_sizes(pd.Series([1, 100, 10**12, None]))
    assert result.between(9, 42).all()
    assert result.iloc[-1] == 9
    assert result.iloc[2] <= 42


def test_categorical_and_continuous_color_preparation_and_no_valid_points():
    assets, observations = fixtures()
    table = build_asset_metric_table(assets, observations, minimum_returns=4)
    categorical, counts = prepare_scatter_data(
        table,
        "annualized_mean_return",
        "annualized_volatility",
        "market_cap",
        "category",
    )
    assert (
        set(categorical["display_color"]) == {"cars", "books"}
        and counts["plotted"] == 2
    )
    continuous, _ = prepare_scatter_data(
        table,
        "annualized_mean_return",
        "annualized_volatility",
        "equal_size",
        "market_cap",
    )
    assert pd.api.types.is_numeric_dtype(continuous["display_color"])
    table["annualized_mean_return"] = math.nan
    empty, empty_counts = prepare_scatter_data(
        table,
        "annualized_mean_return",
        "annualized_volatility",
        "equal_size",
        "single_color",
    )
    assert empty.empty and empty_counts["missing_selected_metrics"] == 2


def test_registry_validation_and_selector_contracts():
    validate_registry()
    assert METRICS["annualized_mean_return"].annualized
    assert "market_cap" in AXIS_METRICS and "category" in COLOR_METRICS
    with pytest.raises(ValueError):
        validate_registry({"wrong": METRICS["cagr"]})


def test_csv_export_has_raw_values_not_visual_transforms():
    assets, observations = fixtures()
    table = build_asset_metric_table(assets, observations, minimum_returns=4)
    scatter, _ = prepare_scatter_data(
        table,
        "annualized_mean_return",
        "annualized_volatility",
        "market_cap",
        "category",
    )
    exported = pd.read_csv(pd.io.common.BytesIO(export_scatter_csv(scatter)))
    assert (
        "market_cap" in exported
        and "marker_size" not in exported
        and "display_color" not in exported
    )
    assert exported["market_cap"].tolist() == table["market_cap"].tolist()

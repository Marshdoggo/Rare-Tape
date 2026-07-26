import math

import pandas as pd
import pytest

from alt_asset_explorer.benchmark_lab import (BenchmarkDataError, align_series, comparison_dataset,
    normalize_to_100, parse_yahoo_chart, relative_metrics, series_metrics)


def series(values, dates=("2020-01-01", "2020-04-01", "2020-07-01", "2020-10-01", "2021-01-01")):
    return pd.Series(values, index=pd.to_datetime(dates[:len(values)]))


def test_normalization_total_return_cagr_volatility_and_drawdown():
    values = series([10, 12, 9, 15, 20])
    assert normalize_to_100(values).iloc[[0, -1]].tolist() == [100, 200]
    result = series_metrics(values)
    assert result["total_return"] == pytest.approx(1)
    assert result["annualized_return"] == pytest.approx(1, rel=.01)
    assert result["annualized_volatility"] > 0
    assert result["maximum_drawdown"] == pytest.approx(-.25)


def test_previous_close_alignment_never_looks_forward_and_handles_multiple_benchmarks():
    rally = series([10, 11, 12], ("2020-01-05", "2020-01-10", "2020-01-15"))
    a = series([100, 105, 110], ("2020-01-03", "2020-01-09", "2020-01-16"))
    aligned = align_series(rally, {"A": a, "B": a * 2}, "previous")
    assert aligned["A"].tolist() == [100, 105, 105]
    assert list(aligned) == ["Rally subject", "A", "B"]
    assert {"a_raw_value", "b_normalized_value"}.issubset(comparison_dataset(aligned))


def test_exact_alignment_and_no_overlap():
    rally = series([10, 11], ("2020-01-01", "2020-01-02"))
    benchmark = series([20, 21], ("2020-01-02", "2020-01-03"))
    assert align_series(rally, {"B": benchmark}, "exact").index.tolist() == [pd.Timestamp("2020-01-02")]
    assert align_series(rally, {"B": series([1], ("2021-01-01",))}, "exact").empty


def test_sparse_data_returns_unavailable_statistics():
    result = series_metrics(series([10]))
    assert result["observations"] == 1
    assert math.isnan(result["annualized_return"])
    assert all(math.isnan(value) for value in relative_metrics(series([1]), series([1])).values())


def test_alpha_beta_tracking_information_and_capture_ratios():
    benchmark_returns = pd.Series([.1, -.05, .08, -.02], index=pd.date_range("2020-04-01", periods=4, freq="QE"))
    subject_returns = benchmark_returns * 2 + .01
    benchmark = pd.concat([pd.Series([100.0], index=[pd.Timestamp("2019-12-31")]), 100*(1+benchmark_returns).cumprod()])
    subject = pd.concat([pd.Series([100.0], index=[pd.Timestamp("2019-12-31")]), 100*(1+subject_returns).cumprod()])
    result = relative_metrics(subject, benchmark)
    assert result["beta"] == pytest.approx(2)
    assert result["alpha"] == pytest.approx(.04)
    assert result["tracking_error"] > 0
    assert math.isfinite(result["information_ratio"])
    assert result["upside_capture"] > 1
    assert result["downside_capture"] > 1


def test_malformed_and_missing_external_data():
    with pytest.raises(BenchmarkDataError, match="Malformed"):
        parse_yahoo_chart({}, "BAD")
    payload = {"chart":{"result":[{"timestamp":[1], "indicators":{"quote":[{"close":[None]}]}}]}}
    with pytest.raises(BenchmarkDataError, match="No usable"):
        parse_yahoo_chart(payload, "EMPTY")

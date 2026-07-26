import math

import pandas as pd
import pytest

from alt_asset_explorer.benchmark_lab import (BENCHMARK_COLUMNS, BenchmarkDataError, align_series,
    comparison_dataset, download_benchmark, earliest_rally_observation_date, load_persisted_benchmarks,
    merge_benchmark_history, normalize_to_100, parse_yahoo_chart, relative_metrics,
    select_local_benchmark, series_metrics, validate_benchmark_history, write_benchmark_history_atomic)


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


def benchmark_rows(ticker="SPY", dates=("2020-01-02", "2020-01-03"), values=(100, 101)):
    return pd.DataFrame({"date": dates, "ticker": ticker, "display_name": "S&P 500",
        "asset_class": "U.S. equity", "adjusted_close": values, "data_source": "fixture",
        "fetched_at": "2026-07-26T00:00:00Z"})


def test_earliest_rally_date_ignores_invalid_and_placeholder_rows():
    observations = pd.DataFrame({"asset_id": ["a", "b", "c", "d"],
        "observed_at": ["bad", None, "2019-02-03", "2018-01-01"],
        "price_per_share": [10, 10, 2, 5], "source_type": ["rally_app", "rally_app", "rally_app", "synthetic_test"]})
    assert earliest_rally_observation_date(observations) == pd.Timestamp("2019-02-03")


def test_earliest_rally_date_errors_when_no_usable_rows():
    with pytest.raises(BenchmarkDataError, match="No valid"):
        earliest_rally_observation_date(pd.DataFrame({"asset_id": ["a"], "observed_at": ["bad"], "price_per_share": [-1]}))


def test_parquet_priority_csv_fallback_and_date_filter(tmp_path):
    parquet, csv = tmp_path / "history.parquet", tmp_path / "history.csv"
    benchmark_rows(values=(200, 201)).to_csv(csv, index=False)
    benchmark_rows().to_parquet(parquet, index=False)
    loaded = load_persisted_benchmarks(parquet, csv)
    assert loaded.source == "local Parquet"
    assert select_local_benchmark(loaded.data, "SPY", "2020-01-03", "2020-01-04")["raw_value"].tolist() == [101]
    parquet.unlink()
    loaded = load_persisted_benchmarks(parquet, csv)
    assert loaded.source == "local CSV"
    assert loaded.data["adjusted_close"].tolist() == [200, 201]


def test_missing_local_history_and_partial_ticker_availability(tmp_path):
    loaded = load_persisted_benchmarks(tmp_path / "none.parquet", tmp_path / "none.csv")
    assert loaded.source is None and list(loaded.data) == BENCHMARK_COLUMNS
    local = validate_benchmark_history(benchmark_rows())
    assert not select_local_benchmark(local, "SPY", "2019", "2021").empty
    assert select_local_benchmark(local, "QQQ", "2019", "2021").empty


def test_incremental_merge_deduplicates_with_newest_row_and_atomic_write(tmp_path):
    existing = benchmark_rows(values=(100, 101))
    addition = benchmark_rows(dates=("2020-01-03", "2020-01-04"), values=(999, 102))
    merged = merge_benchmark_history(existing, addition)
    assert merged[["date", "adjusted_close"]].values.tolist() == [[pd.Timestamp("2020-01-02"), 100], [pd.Timestamp("2020-01-03"), 999], [pd.Timestamp("2020-01-04"), 102]]
    output = write_benchmark_history_atomic(merged, tmp_path / "history.parquet")
    assert output.exists() and not (tmp_path / ".history.parquet.tmp").exists()
    assert len(pd.read_parquet(output)) == 3


def test_validation_rejects_bad_schema_and_prices():
    with pytest.raises(BenchmarkDataError, match="missing columns"):
        validate_benchmark_history(pd.DataFrame({"date": ["2020-01-01"]}))
    bad = benchmark_rows(values=(0, -1))
    with pytest.raises(BenchmarkDataError, match="no usable"):
        validate_benchmark_history(bad)


def test_provider_retries_and_reports_429_without_network():
    class Response:
        status_code = 429
        def raise_for_status(self): pass
    class Session:
        def __init__(self): self.calls = 0
        def get(self, *args, **kwargs): self.calls += 1; return Response()
    provider = Session()
    with pytest.raises(BenchmarkDataError, match="rate limited.*429"):
        download_benchmark("SPY", "2020-01-01", "2020-01-02", session=provider, attempts=3, sleep=lambda _: None)
    assert provider.calls == 3

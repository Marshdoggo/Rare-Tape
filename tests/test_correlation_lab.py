import numpy as np
import pandas as pd
import pytest

from alt_asset_explorer.benchmark_lab import load_persisted_benchmarks
from alt_asset_explorer.correlation_lab import (
    align_values,
    calculate_returns,
    cluster,
    complete_subset,
    correlation_distance,
    correlation_matrices,
    matrix_csv,
    ordered_matrix,
    pairwise_table,
    period_grid,
)
from alt_asset_explorer.correlation_subjects import collect_subjects


def test_monthly_and_quarterly_period_grids():
    assert list(period_grid("2024-01-10", "2024-04-10", "monthly")) == list(
        pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"])
    )
    assert list(period_grid("2024-01-10", "2024-07-01", "quarterly")) == list(
        pd.to_datetime(["2024-03-31", "2024-06-30"])
    )


def test_previous_alignment_no_future_leakage_missing_and_staleness():
    grid = pd.DatetimeIndex(pd.to_datetime(["2024-03-31", "2024-06-30", "2024-09-30"]))
    raw = pd.Series([10, 20], index=pd.to_datetime(["2024-04-01", "2024-06-29"]))
    values, dates = align_values({"x": raw}, grid, max_staleness_days=60)
    assert np.isnan(values.iloc[0, 0])
    assert values.iloc[1, 0] == 20 and dates.iloc[1, 0] == pd.Timestamp("2024-06-29")
    assert np.isnan(values.iloc[2, 0])


def test_exact_alignment_preserves_missing():
    grid = pd.DatetimeIndex(pd.to_datetime(["2024-03-31", "2024-06-30"]))
    values, _ = align_values(
        {"x": pd.Series([2], index=[pd.Timestamp("2024-03-31")])}, grid, method="exact"
    )
    assert values.iloc[0, 0] == 2 and pd.isna(values.iloc[1, 0])


def test_simple_and_log_returns():
    values = pd.DataFrame({"x": [100, 110, 121]})
    assert calculate_returns(values, "simple")["x"].dropna().tolist() == pytest.approx(
        [0.1, 0.1]
    )
    assert calculate_returns(values, "log")["x"].dropna().tolist() == pytest.approx(
        [np.log(1.1)] * 2
    )


def test_correlations_overlap_minimum_spearman_and_constant():
    returns = pd.DataFrame(
        {
            "a": [1, 2, 3, np.nan],
            "b": [2, 4, 6, 8],
            "c": [1, 1, 1, 1],
            "d": [3, 2, 1, 0],
        }
    )
    pearson = correlation_matrices(returns, minimum_overlap=3)
    assert pearson.overlaps.loc["a", "b"] == 3 and pearson.correlations.loc[
        "a", "b"
    ] == pytest.approx(1)
    assert pd.isna(pearson.correlations.loc["a", "c"])
    strict = correlation_matrices(returns, minimum_overlap=4)
    assert pd.isna(strict.correlations.loc["a", "b"])
    assert correlation_matrices(
        returns, method="spearman", minimum_overlap=3
    ).correlations.loc["a", "d"] == pytest.approx(-1)


def test_distance_clips_is_symmetric_and_zero_diagonal():
    corr = pd.DataFrame([[1 + 1e-12, 0], [0, 1]], index=["a", "b"], columns=["a", "b"])
    distance = correlation_distance(corr)
    assert (
        distance.loc["a", "a"] == 0 and distance.loc["a", "b"] == distance.loc["b", "a"]
    )
    assert distance.loc["a", "b"] == pytest.approx(np.sqrt(0.5))
    perfect = correlation_distance(pd.DataFrame([[1, -1], [-1, 1]]))
    assert perfect.iloc[0, 1] == 1


def test_complete_subset_and_average_linkage_are_deterministic():
    pytest.importorskip("scipy")
    corr = pd.DataFrame(
        [[1, 0.5, np.nan], [0.5, 1, 0.2], [np.nan, 0.2, 1]],
        index=list("abc"),
        columns=list("abc"),
    )
    keep, excluded = complete_subset(corr)
    assert keep == ["b", "c"] and excluded == {
        "a": "Incomplete clustering matrix / insufficient pairwise overlap"
    }
    tree, order = cluster(correlation_distance(corr.loc[keep, keep]), "average")
    assert tree.shape == (1, 4) and set(order) == set(keep)
    assert ordered_matrix(corr, order).index.tolist() == order


def test_pairwise_table_and_csv_exports():
    returns = pd.DataFrame({"a": [1, 2, 3], "b": [3, 2, 1]})
    result = correlation_matrices(returns, minimum_overlap=2)
    meta = pd.DataFrame(
        [
            {
                "subject_id": "a",
                "display_label": "A",
                "subject_type": "Asset",
                "category": "Books",
            },
            {
                "subject_id": "b",
                "display_label": "B",
                "subject_type": "Benchmark",
                "category": "Equity",
            },
        ]
    )
    table = pairwise_table(result, meta)
    assert (
        len(table) == 1
        and table.iloc[0]["Overlap count"] == 3
        and table.iloc[0]["Correlation"] == pytest.approx(-1)
    )
    assert b"subject_id" in matrix_csv(result.correlations)


def test_empty_one_two_and_large_universes():
    empty = correlation_matrices(pd.DataFrame(), minimum_overlap=2)
    assert empty.correlations.empty and complete_subset(empty.correlations) == ([], {})
    one = correlation_matrices(pd.DataFrame({"a": [1, 2]}), minimum_overlap=2)
    # A one-subject result needs no scipy linkage calculation.
    assert one.correlations.index.tolist() == ["a"]
    many = pd.DataFrame({f"s{i}": np.arange(20) + i for i in range(40)})
    result = correlation_matrices(many, minimum_overlap=6)
    keep, _ = complete_subset(result.correlations)
    assert len(keep) == 40


def test_subject_adapters_include_assets_ew_mcw_full_and_benchmarks():
    assets = pd.DataFrame(
        [
            {
                "asset_id": "x",
                "ticker": "X",
                "asset_name": "X",
                "category": "Books",
                "status": "trading",
            }
        ]
    )
    observations = pd.DataFrame(
        [{"asset_id": "x", "observed_at": "2024-01-01", "price_per_share": 10}]
    )
    indices = pd.DataFrame(
        [
            {
                "index_id": "ew",
                "index_name": "EW",
                "date": "2024-03-31",
                "index_level": 100,
                "weighting_method": "equal",
                "category": "Books",
            },
            {
                "index_id": "mcw",
                "index_name": "MCW",
                "date": "2024-03-31",
                "index_level": 100,
                "weighting_method": "market_cap",
                "category": "Books",
            },
            {
                "index_id": "full",
                "index_name": "Full",
                "date": "2024-03-31",
                "index_level": 100,
                "weighting_method": "equal",
                "category": "all",
            },
        ]
    )
    benchmarks = pd.DataFrame(
        [
            {
                "ticker": "SPY",
                "date": "2024-01-01",
                "adjusted_close": 400,
                "asset_class": "equity",
            }
        ]
    )
    series, meta = collect_subjects(
        assets, observations, indices, pd.DataFrame(), benchmarks
    )
    assert {
        "Individual Rally asset",
        "Equal-weight category index",
        "Market-cap-weighted category index",
        "Full-market index",
        "External benchmark",
    } == set(meta.subject_type)
    assert len(series) == 5


def test_local_parquet_benchmark_integration(tmp_path):
    path = tmp_path / "history.parquet"
    pd.DataFrame(
        [
            {
                "date": "2024-01-01",
                "ticker": "SPY",
                "display_name": "S&P 500",
                "asset_class": "equity",
                "adjusted_close": 400,
                "data_source": "fixture",
                "fetched_at": "2024-01-02T00:00:00Z",
            }
        ]
    ).to_parquet(path, index=False)
    loaded = load_persisted_benchmarks(path, tmp_path / "missing.csv")
    assert loaded.source == "local Parquet" and loaded.data.iloc[0].ticker == "SPY"

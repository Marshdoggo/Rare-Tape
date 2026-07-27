from pathlib import Path

import pandas as pd
import pytest

from alt_asset_explorer.leaderboards import (
    METRICS, METHODOLOGY_VERSION, build_archive, calculate_metrics,
    latest_completed_quarter, movement_table, quarter_ends, rank_history_data,
    rank_snapshot, truncate_as_of, validate_archive, write_archive_atomic,
)


def fixture_data():
    assets = pd.DataFrame([
        {"asset_id":"a","ticker":"A","asset_name":"Alpha","category":"cars","subcategory":"x","status":"trading","shares_outstanding":100,"offering_price_per_share":10,"offering_market_cap":1000},
        {"asset_id":"b","ticker":"B","asset_name":"Beta","category":"books","subcategory":"y","status":"exited","shares_outstanding":50,"offering_price_per_share":10,"offering_market_cap":500},
    ])
    observations = pd.DataFrame([
        {"asset_id":"a","observed_at":d,"price_per_share":p} for d,p in [("2020-03-15",10),("2020-06-15",11),("2020-09-15",12),("2020-12-15",13),("2021-03-15",15),("2021-06-15",14)]
    ] + [{"asset_id":"b","observed_at":d,"price_per_share":p} for d,p in [("2021-01-02",10),("2021-03-20",9),("2021-06-20",8)]])
    return assets, observations


def test_snapshot_generation_and_latest_completed_quarter():
    assert list(quarter_ends("2020-02-01", "2020-12-31")) == list(pd.to_datetime(["2020-03-31","2020-06-30","2020-09-30","2020-12-31"]))
    assert latest_completed_quarter("2026-07-27") == pd.Timestamp("2026-06-30")
    assert latest_completed_quarter("2026-06-30") == pd.Timestamp("2026-06-30")


def test_truncation_and_metrics_are_point_in_time_safe():
    series=pd.Series([10,11,12,13,15,999],index=pd.to_datetime(["2020-03-15","2020-06-15","2020-09-15","2020-12-15","2021-03-15","2022-01-01"]))
    truncated=truncate_as_of(series,"2021-03-31")
    assert truncated.max()==15 and truncated.index.max()==pd.Timestamp("2021-03-15")
    quarterly=pd.Series([10,11,12,13,15],index=pd.to_datetime(["2020-03-31","2020-06-30","2020-09-30","2020-12-31","2021-03-31"]))
    metrics=calculate_metrics(quarterly,"2021-03-31")
    assert metrics["latest_quarter_return"] == pytest.approx(15/13-1)
    assert metrics["trailing_1y_return"] == pytest.approx(.5)
    assert metrics["cagr"] > 0 and metrics["annualized_volatility"] > 0
    assert metrics["sharpe_ratio"] > 0 and metrics["maximum_drawdown"] == 0


def test_deterministic_ranking_direction_ties_and_percentiles():
    frame=pd.DataFrame({"subject_id":["b","a","c"],"metric_value":[1,1,0],"eligible":[True,True,True]})
    ranked=rank_snapshot(frame,METRICS["total_return"]).set_index("subject_id")
    assert ranked.loc["a","rank"]==1 and ranked.loc["b","rank"]==2
    assert ranked.loc["a","percentile_rank"]==1 and ranked.loc["c","percentile_rank"]==0
    low=rank_snapshot(frame,METRICS["annualized_volatility"]).set_index("subject_id")
    assert low.loc["c","rank"]==1
    one=rank_snapshot(frame.iloc[:1],METRICS["total_return"])
    assert one.iloc[0].percentile_rank==1


def test_full_archive_inception_staleness_movement_and_gaps(tmp_path: Path):
    assets, observations=fixture_data(); snapshots=pd.to_datetime(["2020-03-31","2020-06-30","2020-09-30","2020-12-31","2021-03-31","2021-06-30"])
    archive=build_archive(assets,observations,snapshots=snapshots,max_staleness_days=93,generated_at="2026-01-01",source_version="test")
    validate_archive(archive)
    early_b=archive[(archive.subject_id=="asset:b")&(archive.snapshot_date==pd.Timestamp("2020-12-31"))]
    assert not early_b.eligible.any() and set(early_b.exclusion_reason)=={"not_yet_launched"}
    late_a=archive[(archive.subject_id=="asset:a")&(archive.snapshot_date==pd.Timestamp("2021-06-30"))]
    assert (late_a.latest_observation_date <= late_a.snapshot_date).all()
    assert archive.methodology_version.eq(METHODOLOGY_VERSION).all()
    history=rank_history_data(archive,"latest_quarter_return",["asset:a","asset:b"])
    assert history.loc[~history.eligible,"rank"].isna().all()
    movement=movement_table(archive,"2021-03-31","2021-06-30","latest_quarter_return")
    assert "New entrant" in set(movement.eligibility_transition)
    output=write_archive_atomic(archive,tmp_path/"archive.parquet")
    assert output.exists()


def test_empty_and_missing_metrics():
    empty=pd.DataFrame(columns=["subject_id","metric_value","eligible"])
    assert rank_snapshot(empty,METRICS["total_return"]).empty
    frame=pd.DataFrame({"subject_id":["a"],"metric_value":[float("nan")],"eligible":[False]})
    assert rank_snapshot(frame,METRICS["total_return"])["rank"].isna().all()

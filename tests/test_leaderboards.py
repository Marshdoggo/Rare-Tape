from pathlib import Path

import pandas as pd
import pytest

from alt_asset_explorer.leaderboards import (
    METRICS, METHODOLOGY_VERSION, build_archive, calculate_metrics,
    latest_completed_quarter, load_archive, movement_table, quarter_ends, rank_history_data,
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


def test_individual_asset_categories_are_discovered_from_canonical_sources():
    """A category addition must not require a leaderboard registry change."""
    assets, observations = fixture_data()
    assets.loc[len(assets)] = {
        "asset_id": "new-1", "ticker": "NEW", "asset_name": "New category asset",
        "category": "category-added-today", "subcategory": "x", "status": "trading",
        "shares_outstanding": 10, "offering_price_per_share": 5, "offering_market_cap": 50,
    }
    observations = pd.concat([observations, pd.DataFrame([
        {"asset_id": "new-1", "observed_at": "2021-03-01", "price_per_share": 5},
        {"asset_id": "new-1", "observed_at": "2021-06-29", "price_per_share": 8},
    ])], ignore_index=True)
    archive = build_archive(assets, observations, snapshots=pd.to_datetime(["2021-06-30"]), generated_at="2026-01-01", source_version="test")
    row = archive[(archive.ticker == "NEW") & (archive.metric_key == "total_return")].iloc[0]
    assert row.subject_type == "Individual Rally asset"
    assert row.category == "category-added-today"
    assert bool(row.eligible)
    assert row.metric_value == pytest.approx(0.6)


def test_current_coin_assets_flow_into_latest_canonical_leaderboard():
    """Integration guard for the source/archive skew that omitted all Coins."""
    assets = pd.read_csv("data/normalized/assets.csv")
    observations = pd.read_csv("data/normalized/price_observations.csv")
    latest = latest_completed_quarter("2026-07-27")
    archive = build_archive(assets, observations, snapshots=pd.DatetimeIndex([latest]), generated_at="2026-07-27", source_version="integration")
    total = archive[(archive.snapshot_date == latest) & (archive.metric_key == "total_return")]
    coins = total[(total.subject_type == "Individual Rally asset") & (total.category == "coins")]
    assert set(coins.loc[coins.eligible, "ticker"]) >= {"1857COIN", "JUSTINIAN", "CROESUS"}
    coin_1857 = coins.set_index("ticker").loc["1857COIN"]
    assert coin_1857.metric_value == pytest.approx(16 / 5 - 1)
    assert coin_1857.effective_start_date == pd.Timestamp("2022-08-09")
    assert coin_1857.latest_observation_date == pd.Timestamp("2026-06-26")


def test_rebuild_adds_assets_absent_from_an_older_snapshot_and_is_deterministic():
    assets, observations = fixture_data()
    kwargs = {"snapshots": pd.to_datetime(["2021-06-30"]), "generated_at": "2026-01-01", "source_version": "same-inputs"}
    old = build_archive(assets.iloc[:1], observations[observations.asset_id == "a"], **kwargs)
    rebuilt_1 = build_archive(assets, observations, **kwargs)
    rebuilt_2 = build_archive(assets, observations, **kwargs)
    assert "asset:b" not in set(old.subject_id)
    assert "asset:b" in set(rebuilt_1.subject_id)
    pd.testing.assert_frame_equal(rebuilt_1, rebuilt_2)


def test_missing_default_cache_rebuilds_from_canonical_inputs(monkeypatch, tmp_path):
    expected = pd.DataFrame({"subject_id": ["asset:canonical"]})
    monkeypatch.setattr("alt_asset_explorer.leaderboards.ARCHIVE_PATH", tmp_path / "archive.parquet")
    monkeypatch.setattr("alt_asset_explorer.leaderboards.build_default_archive", lambda: expected)
    assert load_archive(tmp_path / "archive.parquet") is expected

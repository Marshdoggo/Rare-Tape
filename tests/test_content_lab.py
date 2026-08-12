import pandas as pd
import pytest

from alt_asset_explorer.content_lab import ContentLabEngine, ScoringConfig, StoryLead, deduplicate_and_rank, discover_quarters, score_lead
from alt_asset_explorer.valuation_library.temporal import load_dated_valuation


def fixtures():
    assets=pd.DataFrame([{"asset_id":"a","ticker":"A","asset_name":"Alpha","category":"watches"},{"asset_id":"b","ticker":"B","asset_name":"Beta","category":"watches"},{"asset_id":"c","ticker":"C","asset_name":"Gamma","category":"cars"},{"asset_id":"d","ticker":"D","asset_name":"Delta","category":"cars"}])
    rows=[]
    values={"a":[100,100,200,50],"b":[100,110,99,120],"c":[100,90,80,70],"d":[100,105,106,107]}
    for asset,prices in values.items():
        for date,price in zip(["2024-03-31","2024-06-30","2024-09-30","2024-12-31"],prices): rows.append({"asset_id":asset,"period_end":date,"observed_at":date,"price_per_share":price})
    return assets,pd.DataFrame(rows)


def test_quarter_detection_and_multiple_historical_generation():
    a,o=fixtures(); assert discover_quarters(o)==["2024Q1","2024Q2","2024Q3","2024Q4"]
    results=ContentLabEngine(a,o).discover_all(); assert [x.period for x in results]==discover_quarters(o); assert results[-1].raw_candidates>0


def test_as_of_filter_prevents_look_ahead_leakage():
    a,o=fixtures(); engine=ContentLabEngine(a,o)
    before=engine.discover("2024Q3").slate
    future=pd.DataFrame([{"asset_id":"a","period_end":"2025-03-31","observed_at":"2025-03-31","price_per_share":9999}])
    after=ContentLabEngine(a,pd.concat([o,future],ignore_index=True)).discover("2024Q3").slate
    assert [(x.story_id,x.thesis) for x in before]==[(x.story_id,x.thesis) for x in after]


def test_later_observation_with_old_period_label_is_not_moved_back():
    a,o=fixtures(); leaked={"asset_id":"a","period_end":"2024-06-30","observed_at":"2025-01-02","price_per_share":8000}
    result=ContentLabEngine(a,pd.concat([o,pd.DataFrame([leaked])],ignore_index=True)).discover("2024Q2")
    assert all("8,000" not in x.thesis for x in result.slate)


def test_return_drawdown_and_benchmark_detectors():
    a,o=fixtures(); dates=pd.date_range("2024-03-28","2024-09-30",freq="7D")
    bench=pd.DataFrame({"date":dates,"ticker":"SPY","display_name":"S&P 500","asset_class":"equity","adjusted_close":range(100,100+len(dates)),"data_source":"test","fetched_at":"2024-10-01"})
    engine=ContentLabEngine(a,o,benchmarks=bench)
    families={x.story_family for x in engine.discover("2024Q3",limit=None).slate}
    assert "extreme_movers" in families and "benchmark_divergence" in families
    assert any(x.story_family=="drawdown_recovery" for x in engine.discover("2024Q3",limit=None,families=["drawdown_recovery"]).slate)


def _lead(story_id="x",family="extreme_movers",quality=.8,subject="a"):
    return StoryLead(story_id,"2024Q1","2024-01-01","2024-03-31","2024-03-31","contemporaneous",family,"x","h","t","asset",subject,subject,scores={"magnitude":1,"extremeness":1,"narrative":1},data_quality_score=quality)


def test_score_quality_penalty_and_deduplication_are_deterministic():
    cfg=ScoringConfig(); high=_lead("high",quality=1); low=_lead("low",quality=.3)
    assert score_lead(high,cfg)>score_lead(low,cfg)
    leads=[_lead("b"),_lead("a"),_lead("other",family="category",subject="market")]
    first=deduplicate_and_rank(leads,cfg,None); second=deduplicate_and_rank(list(reversed(leads)),cfg,None)
    assert [x.story_id for x in first]==[x.story_id for x in second]; assert len(first)==2


def test_missing_valuation_and_insufficient_correlation_are_graceful():
    a,o=fixtures(); result=ContentLabEngine(a,o,valuations=[]).discover("2024Q4",families=["fair_value","correlation"])
    assert result.raw_candidates==0 and result.slate==[]


def test_benchmark_detector_requires_available_endpoints():
    a,o=fixtures(); result=ContentLabEngine(a,o,benchmarks=pd.DataFrame()).discover("2024Q3",families=["benchmark_divergence"])
    assert result.slate==[]


def test_valuation_effective_date_and_leakage(tmp_path):
    import json
    d=tmp_path/"a"; d.mkdir()
    (d/"valuation.json").write_text(json.dumps({"asset_id":"a","valuation_date":"2025-01-15","results":{"official_value_available":True,"base_value_usd":400,"conservative_value_usd":300,"optimistic_value_usd":500,"confidence_score":.8}}))
    v=load_dated_valuation(d); assert v and v.date_source=="valuation_date"
    a,o=fixtures(); a["share_count"]=1
    assert ContentLabEngine(a,o,valuations=[v]).discover("2024Q4",families=["fair_value"]).slate==[]


def test_valuation_without_defensible_date_fails_closed(tmp_path):
    import json
    d=tmp_path/"a"; d.mkdir()
    (d/"valuation.json").write_text(json.dumps({"asset_id":"a","results":{"official_value_available":True,"base_value_usd":400}}))
    assert load_dated_valuation(d) is None


def test_rank_and_correlation_future_rows_do_not_leak():
    a,o=fixtures(); lb=pd.DataFrame(columns=["snapshot_date","eligible","metric_key"])
    future_lb=pd.DataFrame([{"snapshot_date":"2025-03-31","eligible":True,"metric_key":"quarterly_return","subject_id":"asset:a","rank":1,"percentile_rank":1,"eligible_universe_size":4}])
    base=ContentLabEngine(a,o,leaderboards=lb).discover("2024Q4",families=["rank_history","correlation_regime"]).slate
    after=ContentLabEngine(a,pd.concat([o,pd.DataFrame([{"asset_id":"a","period_end":"2024-12-31","observed_at":"2025-02-01","price_per_share":999}])]),leaderboards=future_lb).discover("2024Q4",families=["rank_history","correlation_regime"]).slate
    assert [(x.story_id,x.thesis) for x in base]==[(x.story_id,x.thesis) for x in after]

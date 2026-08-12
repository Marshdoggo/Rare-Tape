from __future__ import annotations

import json
from pathlib import Path
import pytest

from alt_asset_explorer.intelligence import IntelligenceConfig, IntelligenceEngine, JsonReportCache, MissingAPIKeyError, OpenAIResponsesClient, evidence_hash, make_cache_key
from alt_asset_explorer.intelligence.models import StoryIntelligenceContent, TokenUsage
from alt_asset_explorer.intelligence.ui import report_state


def packet(value=.42):
    return {"story_id":"story-1","story_family":"benchmark_divergence","facts":[{"metric":"return","value":value}],"allowed_claims":["Asset returned 42%."]}


def content():
    return StoryIntelligenceContent(story_id="story-1",headline="A measured move",dek="Evidence first",executive_summary="The supplied result is notable.",what_happened="FACT: The packet records the move.",why_it_matters="It merits review.",historical_context="Unavailable.",market_context="Unavailable.",interpretation=["INTERPRETATION: magnitude may matter."],possible_explanations=["HYPOTHESIS: liquidity is worth testing."],counterarguments=["One observation can mislead."],caveats=["Limited evidence."],unknowns=["UNKNOWN: cause."],research_next=["Check transactions."],short_form_angles=["The measured move"],long_form_angles=["Evidence review"],core_thesis="A measured move.",strongest_hook="What the packet shows",alternate_hooks=["A","B","C"],youtube_angle="Explain limits",suggested_title="A measured move",key_chart="price history",research_gaps=["Cause"],article_markdown="# A measured move\n\nFACT: The packet records the move.",claim_audit={"supported_claims":[{"claim":"The packet records the move.","evidence_keys":["facts[0].value"]}],"interpretations":[],"hypotheses":[],"unknowns":["Cause"],"unsupported_claims_avoided":[]})


class FakeClient:
    def __init__(self): self.calls=0
    def generate(self,**kwargs): self.calls+=1; return content(),"resp_test",TokenUsage(input_tokens=10,total_tokens=20)


def test_canonical_evidence_hash_is_deterministic_and_sensitive():
    assert evidence_hash({"b":2,"a":1}) == evidence_hash({"a":1,"b":2})
    assert evidence_hash(packet()) != evidence_hash(packet(.43))


def test_cache_key_invalidates_dimensions():
    base=dict(story_id="x",evidence_digest="e",prompt_version="p",schema_version="s",model="m",report_type="research_brief")
    key=make_cache_key(**base)
    for field,value in [("evidence_digest","E"),("prompt_version","P"),("model","M"),("report_type","content_brief")]:
        assert make_cache_key(**(base|{field:value})) != key


def test_cache_hit_miss_and_force_revision(tmp_path):
    client=FakeClient(); cache=JsonReportCache(tmp_path); engine=IntelligenceEngine(client,cache,IntelligenceConfig())
    first=engine.generate_report(packet()); assert first.cache_status=="MISS" and client.calls==1
    second=engine.generate_report(packet()); assert second.cache_status=="HIT" and client.calls==1
    third=engine.generate_report(packet(),force=True); assert third.cache_status=="REGENERATED" and client.calls==2
    assert list((tmp_path/"story-1"/"revisions").glob("*.json"))
    assert report_state(None)=="missing" and report_state(third.report)=="cached"


def test_corrupt_cache_is_a_miss(tmp_path):
    cache=JsonReportCache(tmp_path); path=cache.path("story-1","key"); path.parent.mkdir(); path.write_text("not json")
    assert cache.load("story-1","key") is None


def test_structured_output_parsing_and_validation():
    assert StoryIntelligenceContent.model_validate_json(content().model_dump_json()).story_id=="story-1"
    bad=json.loads(content().model_dump_json()); bad["headline"]=""
    with pytest.raises(ValueError): StoryIntelligenceContent.model_validate(bad)


def test_mismatched_story_rejected_before_cache(tmp_path):
    class Wrong(FakeClient):
        def generate(self,**kwargs):
            item=content().model_copy(update={"story_id":"wrong"}); return item,None,TokenUsage()
    with pytest.raises(ValueError,match="does not match"):
        IntelligenceEngine(Wrong(),JsonReportCache(tmp_path)).generate_report(packet())


def test_missing_api_key():
    with pytest.raises(MissingAPIKeyError): OpenAIResponsesClient(None)

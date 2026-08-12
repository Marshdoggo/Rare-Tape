from __future__ import annotations

import re
from typing import Any

from .cache import JsonReportCache, canonical_json, evidence_hash, make_cache_key
from .client import ResponseClient
from .config import IntelligenceConfig
from .models import GenerationResult, ReportProvenance, ReportType, StoryIntelligenceReport
from .prompts import SYSTEM_INSTRUCTIONS, build_input


def _number_warnings(content: str, packet: dict[str, Any]) -> list[str]:
    """Conservative audit: warn only; years and simple prose counts can be legitimate."""
    evidence=canonical_json(packet)
    values=set(re.findall(r"[$]?[-+]?\d[\d,.]*%?",evidence))
    generated=set(re.findall(r"[$]?[-+]?\d[\d,.]*%",content))
    unknown=sorted(x for x in generated if x not in values)
    return (["Review numeric tokens not found verbatim in canonical evidence: "+", ".join(unknown)] if unknown else [])


class IntelligenceEngine:
    def __init__(self, client: ResponseClient, cache: JsonReportCache, config: IntelligenceConfig | None=None):
        self.client=client; self.cache=cache; self.config=config or IntelligenceConfig.from_env()

    def identity(self, packet: dict[str,Any], report_type: ReportType, model: str | None=None):
        digest=evidence_hash(packet); selected=model or self.config.model
        key=make_cache_key(story_id=str(packet["story_id"]),evidence_digest=digest,
            prompt_version=self.config.prompt_version,schema_version=self.config.schema_version,
            model=selected,report_type=report_type)
        return digest,selected,key

    def cached(self, packet, report_type: ReportType="research_brief", model=None):
        _,_,key=self.identity(packet,report_type,model); return self.cache.load(str(packet["story_id"]),key)

    def generate_report(self, packet: dict[str,Any], *, report_type: ReportType="research_brief",
                        model: str | None=None, force: bool=False, mode: str="internal_only") -> GenerationResult:
        if mode != "internal_only": raise ValueError("research_enhanced is scaffolded but intentionally disabled")
        digest,selected,key=self.identity(packet,report_type,model)
        existing=self.cache.load(str(packet["story_id"]),key)
        if existing is not None and not force: return GenerationResult(report=existing,cache_status="HIT",cache_key=key)
        content,response_id,usage=self.client.generate(model=selected,system=SYSTEM_INSTRUCTIONS,user=build_input(packet,report_type),
            max_output_tokens=self.config.max_output_tokens,reasoning_effort=self.config.reasoning_effort,verbosity=self.config.verbosity)
        if content.story_id != str(packet["story_id"]): raise ValueError("Structured report story_id does not match evidence")
        warnings=_number_warnings(content.article_markdown,packet)
        report=StoryIntelligenceReport(provenance=ReportProvenance(story_id=content.story_id,evidence_hash=digest,
            prompt_version=self.config.prompt_version,schema_version=self.config.schema_version,model=selected,
            openai_response_id=response_id,report_type=report_type,usage=usage,validation_warnings=warnings),report=content)
        self.cache.save(key,report)
        return GenerationResult(report=report,cache_status="REGENERATED" if force and existing else "MISS",cache_key=key)

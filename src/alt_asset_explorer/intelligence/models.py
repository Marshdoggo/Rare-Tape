"""Typed contracts for evidence-grounded story intelligence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReportType = Literal["research_brief", "content_brief"]


class SupportedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str
    evidence_keys: list[str] = Field(default_factory=list)


class ClaimAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported_claims: list[SupportedClaim] = Field(default_factory=list)
    interpretations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    unsupported_claims_avoided: list[str] = Field(default_factory=list)


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None


class StoryIntelligenceContent(BaseModel):
    """The SDK validates this model directly as a Structured Output."""
    model_config = ConfigDict(extra="forbid")
    story_id: str
    headline: str
    dek: str
    executive_summary: str
    what_happened: str
    why_it_matters: str
    historical_context: str
    market_context: str
    interpretation: list[str]
    possible_explanations: list[str]
    counterarguments: list[str]
    caveats: list[str]
    unknowns: list[str]
    research_next: list[str]
    short_form_angles: list[str]
    long_form_angles: list[str]
    core_thesis: str
    strongest_hook: str
    alternate_hooks: list[str]
    youtube_angle: str
    suggested_title: str
    key_chart: str
    research_gaps: list[str]
    article_markdown: str
    claim_audit: ClaimAudit

    @model_validator(mode="after")
    def required_prose(self):
        for name in ("headline", "executive_summary", "what_happened", "article_markdown"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        return self


class ReportProvenance(BaseModel):
    story_id: str
    evidence_hash: str
    prompt_version: str
    schema_version: str
    model: str
    openai_response_id: str | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    report_type: ReportType
    mode: Literal["internal_only"] = "internal_only"
    usage: TokenUsage = Field(default_factory=TokenUsage)
    validation_warnings: list[str] = Field(default_factory=list)


class StoryIntelligenceReport(BaseModel):
    provenance: ReportProvenance
    report: StoryIntelligenceContent


class GenerationResult(BaseModel):
    report: StoryIntelligenceReport
    cache_status: Literal["HIT", "MISS", "REGENERATED"]
    cache_key: str

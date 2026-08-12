from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StoryLead:
    story_id: str
    period: str
    period_start: str
    period_end: str
    as_of_date: str
    mode: str
    story_family: str
    story_type: str
    headline: str
    thesis: str
    primary_subject_type: str
    primary_subject_id: str
    primary_subject_name: str
    category: str = ""
    secondary_subjects: list[dict[str, str]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    sample_sizes: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    content_score: float = 0.0
    data_quality_score: float = 0.0
    why_interesting: str = ""
    counterpoint: str = ""
    caveats: list[str] = field(default_factory=list)
    allowed_claims: list[str] = field(default_factory=list)
    unsupported_questions: list[str] = field(default_factory=list)
    chart_suggestions: list[str] = field(default_factory=list)
    research_questions: list[str] = field(default_factory=list)
    content_formats: list[str] = field(default_factory=list)
    franchises: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    secondary_angles: list[str] = field(default_factory=list)
    primary_angle: str = ""
    temporal_validity: dict[str, Any] = field(default_factory=dict)
    comparison_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_evidence_packet(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id, "period": self.period, "as_of_date": self.as_of_date,
            "mode": self.mode, "story_family": self.story_family, "story_type": self.story_type,
            "subjects": [{"type": self.primary_subject_type, "id": self.primary_subject_id, "name": self.primary_subject_name}, *self.secondary_subjects],
            "thesis": self.thesis, "facts": self.facts,
            "historical_context": {k: v for k, v in self.metrics.items() if "percentile" in k or "rank" in k},
            "comparison_context": self.comparison_context,
            "sample_sizes": self.sample_sizes,
            "data_quality": {"score": self.data_quality_score, "caveats": self.caveats},
            "temporal_validity": self.temporal_validity or {"as_of_safe": True, "cutoff": self.as_of_date},
            "primary_angle": self.primary_angle or self.story_type,
            "secondary_angles": self.secondary_angles,
            "allowed_claims": self.allowed_claims or [self.thesis],
            "unsupported_questions": self.unsupported_questions or self.research_questions,
            "suggested_visuals": self.chart_suggestions,
            "data_sources": self.data_sources,
        }

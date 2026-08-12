from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import yaml

from .models import StoryLead


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, float] = field(default_factory=lambda: {"extremeness":.12,"magnitude":.10,"contrast":.10,"persistence":.07,"breadth":.06,"novelty":.05,"narrative":.06,"historical_rarity":.08,"regime_change":.08,"rank_change":.07,"valuation_gap":.06,"concentration":.07,"benchmark_excess":.04,"data_quality":.10})
    minimum_data_quality: float = .25
    max_per_subject: int = 2
    max_per_family: int = 5
    minimum_correlation_observations: int = 8
    stale_days: int = 186

    @classmethod
    def load(cls, path: Path) -> "ScoringConfig":
        if not path.exists(): return cls()
        raw = yaml.safe_load(path.read_text()) or {}
        return cls(weights=raw.get("weights", cls().weights), **{k: raw[k] for k in ("minimum_data_quality", "max_per_subject", "max_per_family", "minimum_correlation_observations", "stale_days") if k in raw})


def score_lead(lead: StoryLead, config: ScoringConfig) -> float:
    dimensions = dict(lead.scores)
    dimensions["data_quality"] = lead.data_quality_score
    weighted = sum(config.weights.get(k, 0) * min(1.0, max(0.0, float(dimensions.get(k, 0)))) for k in config.weights)
    # Quality is also a reliability gate: weak evidence cannot win on magnitude alone.
    lead.content_score = round(100 * weighted * (.65 + .35 * lead.data_quality_score), 2)
    return lead.content_score


def deduplicate_and_rank(leads: list[StoryLead], config: ScoringConfig, limit: int | None = 20) -> list[StoryLead]:
    eligible = [x for x in leads if x.data_quality_score >= config.minimum_data_quality]
    for lead in eligible: score_lead(lead, config)
    eligible.sort(key=lambda x: (-x.content_score, x.story_id))
    selected: list[StoryLead] = []; subjects: dict[str, int] = {}; families: dict[str, int] = {}; fingerprints: set[tuple] = set()
    for lead in eligible:
        fp = (lead.period, lead.primary_subject_id, lead.story_family)
        if fp in fingerprints: continue
        if subjects.get(lead.primary_subject_id, 0) >= config.max_per_subject or families.get(lead.story_family, 0) >= config.max_per_family:
            primary=next((x for x in selected if x.primary_subject_id==lead.primary_subject_id),None)
            if primary is not None and lead.story_type not in primary.secondary_angles: primary.secondary_angles.append(lead.story_type)
            continue
        selected.append(lead); fingerprints.add(fp)
        subjects[lead.primary_subject_id] = subjects.get(lead.primary_subject_id, 0) + 1
        families[lead.story_family] = families.get(lead.story_family, 0) + 1
    if limit is None or len(selected) <= limit: return selected
    # Seed a slate with each valid family before filling by score. This is a
    # transparent diversity rule, not a score adjustment or forced candidate.
    ambassadors=[]; seen=set()
    for lead in selected:
        if lead.story_family not in seen:
            ambassadors.append(lead); seen.add(lead.story_family)
    if len(ambassadors) >= limit: return ambassadors[:limit]
    chosen={x.story_id for x in ambassadors}
    return ambassadors + [x for x in selected if x.story_id not in chosen][:limit-len(ambassadors)]

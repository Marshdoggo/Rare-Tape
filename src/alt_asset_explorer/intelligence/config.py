from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class IntelligenceConfig:
    model: str = "gpt-5-mini"
    reasoning_effort: str = "low"
    verbosity: str = "medium"
    max_output_tokens: int = 6000
    prompt_version: str = "story_intelligence_v1"
    schema_version: str = "story_intelligence_schema_v1"
    default_report_type: str = "research_brief"

    @classmethod
    def from_env(cls, env=None) -> "IntelligenceConfig":
        source = os.environ if env is None else env
        return cls(model=source.get("RALLY_OPENAI_MODEL", cls.model))

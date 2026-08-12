"""Deterministic, point-in-time editorial story discovery."""

from .engine import ContentLabEngine, DiscoveryResult, discover_quarters
from .models import StoryLead
from .scoring import ScoringConfig, deduplicate_and_rank, score_lead

__all__ = ["ContentLabEngine", "DiscoveryResult", "StoryLead", "ScoringConfig", "deduplicate_and_rank", "discover_quarters", "score_lead"]

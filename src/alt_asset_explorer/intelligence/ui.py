from __future__ import annotations

from typing import Literal

from .models import StoryIntelligenceReport


def report_state(report: StoryIntelligenceReport | None) -> Literal["missing", "cached"]:
    """Pure presentation state used by Streamlit and unit tests."""
    return "cached" if report is not None else "missing"

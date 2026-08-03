from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class CropRegion:
    """Normalized coordinates, each constrained to the inclusive 0..1 canvas."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if not all(0 <= value <= 1 for value in (self.x, self.y, self.width, self.height)):
            raise ValueError("Crop coordinates must be between 0 and 1")
        if not self.width or not self.height or self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Crop must have positive dimensions and remain inside the frame")


@dataclass(frozen=True)
class VideoMetadata:
    fps: float
    width: int
    height: int
    frame_count: int
    duration_seconds: float


@dataclass
class CandidateReading:
    observation_date: date | None
    price_per_share: float | None
    market_cap: float | None
    raw_ocr_text: str
    source_frame: int
    source_timestamp_seconds: float
    ocr_confidence: float | None = None
    parse_confidence: float = 0.0
    crop_similarity: float | None = None
    tooltip_crop_path: Path | None = None
    validation_status: str = "unvalidated"
    validation_notes: list[str] = field(default_factory=list)


@dataclass
class ReconciledObservation:
    observation_date: date | None
    price_per_share: float | None
    market_cap: float | None
    supporting_frame_count: int
    overall_confidence: float
    validation_status: str
    validation_notes: str
    source_frame: int
    source_timestamp_seconds: float
    raw_ocr_text: str
    tooltip_crop_path: str | None
    conflict: bool = False
    accept: bool = True
    alternatives: list[CandidateReading] = field(default_factory=list)

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .field_parser import parse_ocr_text
from .image_preprocessor import crop_frame, preprocess
from .observation_reconciler import reconcile_observations
from .ocr_engine import OCREngine, TesseractEngine
from .schemas import CropRegion
from .tooltip_detector import is_material_change
from .validators import validate_reading
from .video_reader import VideoReader, _cv2


@dataclass(frozen=True)
class ExtractionConfig:
    crop: CropRegion
    sample_fps: float = 10
    similarity_threshold: float = .94
    day_first: bool | None = None
    shares_outstanding: float | None = None
    diagnostic_directory: Path | None = None


def extract_video(path: Path, config: ExtractionConfig, engine: OCREngine | None = None):
    engine = engine or TesseractEngine()
    readings, previous = [], None
    with VideoReader(path) as reader:
        for frame_number, timestamp, frame in reader.sampled_frames(config.sample_fps):
            crop = crop_frame(frame, config.crop); processed = preprocess(crop)
            changed, similarity = is_material_change(previous, processed, config.similarity_threshold)
            if not changed: continue
            previous = processed
            result = engine.recognize(processed)
            reading = parse_ocr_text(result.text, frame_number, timestamp, result.confidence, config.day_first)
            reading.crop_similarity = similarity
            if config.diagnostic_directory:
                config.diagnostic_directory.mkdir(parents=True, exist_ok=True)
                destination = config.diagnostic_directory / f"tooltip_{frame_number:08d}.png"
                _cv2().imwrite(str(destination), processed); reading.tooltip_crop_path = destination
            readings.append(validate_reading(reading, config.shares_outstanding))
    return reconcile_observations(readings), readings

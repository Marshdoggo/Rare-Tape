from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float | None


class OCREngine(ABC):
    @abstractmethod
    def recognize(self, image) -> OCRResult: ...


class TesseractEngine(OCREngine):
    """Thin adapter; the `tesseract` executable must be installed locally."""

    def recognize(self, image) -> OCRResult:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as exc:
            raise RuntimeError("Install the video-ingestion optional dependencies") from exc
        data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 6")
        tokens, confidences = [], []
        for text, confidence in zip(data["text"], data["conf"]):
            if text.strip():
                tokens.append(text.strip())
                if float(confidence) >= 0:
                    confidences.append(float(confidence) / 100)
        return OCRResult(" ".join(tokens), sum(confidences) / len(confidences) if confidences else None)

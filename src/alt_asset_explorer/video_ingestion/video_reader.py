from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .schemas import VideoMetadata


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Video ingestion requires the local 'video-ingestion' optional dependencies") from exc
    return cv2


class VideoReader:
    def __init__(self, path: Path):
        cv2 = _cv2()
        self.path = path
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            raise ValueError(f"Unable to open video: {path.name}")
        fps = float(self.capture.get(cv2.CAP_PROP_FPS))
        count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.metadata = VideoMetadata(
            fps=fps, width=int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)), frame_count=count,
            duration_seconds=count / fps if fps else 0,
        )

    def frame(self, frame_number: int):
        cv2 = _cv2()
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = self.capture.read()
        if not ok:
            raise ValueError(f"Could not decode frame {frame_number}")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def sampled_frames(self, sample_fps: float) -> Iterator[tuple[int, float, object]]:
        if sample_fps <= 0:
            raise ValueError("Sample rate must be positive")
        step = max(1, round(self.metadata.fps / sample_fps))
        for number in range(0, self.metadata.frame_count, step):
            yield number, number / self.metadata.fps, self.frame(number)

    def close(self) -> None:
        self.capture.release()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

from __future__ import annotations

import numpy as np

from .schemas import CropRegion
from .video_reader import _cv2


def crop_frame(frame: np.ndarray, region: CropRegion) -> np.ndarray:
    height, width = frame.shape[:2]
    x1, y1 = int(region.x * width), int(region.y * height)
    x2, y2 = int((region.x + region.width) * width), int((region.y + region.height) * height)
    return frame[y1:y2, x1:x2].copy()


def preprocess(crop: np.ndarray) -> np.ndarray:
    cv2 = _cv2()
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if crop.ndim == 3 else crop
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return cv2.adaptiveThreshold(cv2.equalizeHist(gray), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)

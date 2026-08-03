from __future__ import annotations

import numpy as np


def crop_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Return a simple normalized pixel similarity without requiring scikit-image."""
    if left.shape != right.shape:
        return 0.0
    return float(1.0 - np.mean(np.abs(left.astype(float) - right.astype(float))) / 255.0)


def is_material_change(previous: np.ndarray | None, current: np.ndarray, threshold: float = 0.94) -> tuple[bool, float | None]:
    if previous is None:
        return True, None
    similarity = crop_similarity(previous, current)
    return similarity < threshold, similarity

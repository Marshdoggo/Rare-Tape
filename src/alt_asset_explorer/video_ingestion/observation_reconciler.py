from __future__ import annotations

from collections import Counter, defaultdict

from .schemas import CandidateReading, ReconciledObservation


def reconcile_observations(readings: list[CandidateReading]) -> list[ReconciledObservation]:
    groups = defaultdict(list)
    for reading in readings:
        groups[reading.observation_date].append(reading)
    output = []
    for observed_date, candidates in groups.items():
        pairs = Counter((item.price_per_share, item.market_cap) for item in candidates)
        (price, cap), support = pairs.most_common(1)[0]
        agreeing = [item for item in candidates if (item.price_per_share, item.market_cap) == (price, cap)]
        representative = max(agreeing, key=lambda item: (item.ocr_confidence or 0, item.parse_confidence))
        conflict = len(pairs) > 1
        notes = sorted({note for item in candidates for note in item.validation_notes})
        if conflict: notes.append("conflicting_candidates")
        confidence = min(1.0, .45 * representative.parse_confidence + .35 * (representative.ocr_confidence or 0) + .2 * support / len(candidates))
        output.append(ReconciledObservation(observed_date, price, cap, support, confidence,
            "fail" if notes else "pass", "; ".join(notes), representative.source_frame,
            representative.source_timestamp_seconds, representative.raw_ocr_text,
            str(representative.tooltip_crop_path) if representative.tooltip_crop_path else None,
            conflict, observed_date is not None and not notes, candidates))
    return sorted(output, key=lambda item: (item.observation_date is None, item.observation_date or __import__('datetime').date.max))

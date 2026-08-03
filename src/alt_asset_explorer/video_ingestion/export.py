from __future__ import annotations

import csv
import io
from dataclasses import asdict

from .schemas import ReconciledObservation

EXPORT_COLUMNS = ["asset_id", "observation_date", "price_per_share", "market_cap", "source_type", "source_video_filename", "source_frame", "source_timestamp_seconds", "overall_confidence", "review_status"]


def reviewed_csv(observations: list[ReconciledObservation], asset_id: str, filename: str) -> str:
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS); writer.writeheader()
    for item in observations:
        if item.accept:
            writer.writerow({"asset_id": asset_id, "observation_date": item.observation_date.isoformat() if item.observation_date else "", "price_per_share": item.price_per_share, "market_cap": item.market_cap, "source_type": "rally_ios_screen_recording", "source_video_filename": filename, "source_frame": item.source_frame, "source_timestamp_seconds": item.source_timestamp_seconds, "overall_confidence": item.overall_confidence, "review_status": "accepted"})
    return stream.getvalue()


def diagnostics_csv(observations: list[ReconciledObservation]) -> str:
    rows = []
    for item in observations:
        for alternative in item.alternatives:
            row = asdict(alternative); row["observation_date"] = alternative.observation_date.isoformat() if alternative.observation_date else ""; row["tooltip_crop_path"] = str(alternative.tooltip_crop_path or ""); rows.append(row)
    if not rows: return ""
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows); return stream.getvalue()

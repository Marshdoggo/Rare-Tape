"""Point-in-time availability helpers for experimental valuation artifacts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DatedValuation:
    asset_id: str
    effective_date: pd.Timestamp
    date_source: str
    date_confidence: str
    payload: dict[str, Any]


def load_dated_valuation(asset_dir: Path) -> DatedValuation | None:
    """Load an official experimental valuation only when an authored date exists.

    ``valuation_date`` is authoritative.  A manifest's valuation-file timestamp is
    an availability timestamp, but deliberately low confidence. Filesystem mtimes
    are never consulted, so copied checkouts cannot rewrite history.
    """
    path = asset_dir / "valuation.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    if not payload.get("results", {}).get("official_value_available", False):
        return None
    raw, source, confidence = payload.get("valuation_date"), "valuation_date", "high"
    if not raw and (asset_dir / "manifest.json").exists():
        manifest = json.loads((asset_dir / "manifest.json").read_text())
        raw = manifest.get("last_modified", {}).get("valuation.json")
        source, confidence = "manifest_file_timestamp", "low"
    effective = pd.to_datetime(raw, errors="coerce", utc=True)
    if pd.isna(effective):
        return None
    return DatedValuation(str(payload.get("asset_id") or asset_dir.name), effective.tz_localize(None).normalize(), source, confidence, payload)


def load_dated_valuations(root: Path) -> list[DatedValuation]:
    return [v for directory in sorted(root.iterdir()) if directory.is_dir() if (v := load_dated_valuation(directory)) is not None] if root.exists() else []

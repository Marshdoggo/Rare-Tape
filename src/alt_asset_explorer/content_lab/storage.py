from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from .engine import DiscoveryResult


def write_archive(results: list[DiscoveryResult], output_dir: Path) -> tuple[Path, Path, Path]:
    """Write reviewable, deterministic runtime artifacts (never opaque binary caches)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    leads = [lead.to_dict() for result in results for lead in result.slate]
    packets = {lead.story_id: lead.to_evidence_packet() for result in results for lead in result.slate}
    summaries = [{"period": r.period, "raw_candidates": r.raw_candidates, "quality_candidates": r.quality_candidates,
                  "deduplicated_candidates": r.deduplicated_candidates, "story_ids": [x.story_id for x in r.slate]} for r in results]
    csv_path = output_dir / "story_leads.csv"
    scalar = [{k: v for k, v in row.items() if not isinstance(v, (list, dict))} | {"key_number": _key_number(row.get("facts", []))} for row in leads]
    pd.DataFrame(scalar).to_csv(csv_path, index=False)
    evidence_path = output_dir / "story_evidence.json"; evidence_path.write_text(json.dumps(packets, indent=2, sort_keys=True, allow_nan=False) + "\n")
    slate_path = output_dir / "quarterly_story_slates.json"; slate_path.write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n")
    return csv_path, evidence_path, slate_path


def _key_number(facts: list[dict]) -> str:
    if not facts: return ""
    value = facts[0].get("value")
    return f"{value:.1%}" if isinstance(value, float) else str(value)

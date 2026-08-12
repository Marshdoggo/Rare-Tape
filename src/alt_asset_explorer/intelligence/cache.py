from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from typing import Any

from .models import StoryIntelligenceReport


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def evidence_hash(packet: dict[str, Any]) -> str:
    return sha256(canonical_json(packet).encode()).hexdigest()


def make_cache_key(*, story_id: str, evidence_digest: str, prompt_version: str,
                   schema_version: str, model: str, report_type: str) -> str:
    return sha256(canonical_json({"story_id": story_id, "evidence_hash": evidence_digest,
        "prompt_version": prompt_version, "schema_version": schema_version,
        "model": model, "report_type": report_type}).encode()).hexdigest()


class JsonReportCache:
    def __init__(self, root: Path): self.root = Path(root)

    def _story_dir(self, story_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", story_id)
        return self.root / safe

    def path(self, story_id: str, key: str) -> Path: return self._story_dir(story_id) / f"{key}.json"

    def load(self, story_id: str, key: str) -> StoryIntelligenceReport | None:
        path = self.path(story_id, key)
        if not path.exists(): return None
        try: return StoryIntelligenceReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError): return None

    def save(self, key: str, value: StoryIntelligenceReport) -> Path:
        directory = self._story_dir(value.provenance.story_id); directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{key}.json"
        if target.exists():
            stamp = value.provenance.generated_at.replace(":", "-")
            revisions = directory / "revisions"
            revisions.mkdir(exist_ok=True)
            shutil.copy2(target, revisions / f"{key}-{stamp}.json")
        payload=value.model_dump_json(indent=2)
        temporary=target.with_suffix(".tmp"); temporary.write_text(payload+"\n",encoding="utf-8"); temporary.replace(target)
        (directory/"latest.json").write_text(payload+"\n",encoding="utf-8")
        return target

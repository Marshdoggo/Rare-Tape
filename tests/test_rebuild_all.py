from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_all.py"
    spec = importlib.util.spec_from_file_location("rebuild_all_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rebuild_all_uses_dependency_order(monkeypatch, tmp_path):
    module = _module()
    calls: list[str] = []
    processed = {"rally_quarterly_indices": pd.DataFrame([{"index_id": "art"}])}
    coverage = pd.DataFrame([{"asset_id": "art-1"}])
    leaderboard = pd.DataFrame([{"subject_id": "asset:art-1"}])

    monkeypatch.setattr(module, "build_dataset", lambda as_of=None: calls.append("processed") or processed)
    monkeypatch.setattr(module, "build_research_coverage", lambda: calls.append("coverage") or coverage)
    monkeypatch.setattr(module, "build_default_archive", lambda: calls.append("leaderboards") or leaderboard)
    monkeypatch.setattr(module, "write_archive_atomic", lambda frame: calls.append("persist_leaderboards") or tmp_path / "archive.parquet")

    result = module.rebuild_all()

    assert calls == ["processed", "coverage", "leaderboards", "persist_leaderboards"]
    assert result.processed is processed
    assert result.research_coverage is coverage
    assert result.leaderboard_archive is leaderboard

#!/usr/bin/env python
"""Run the deterministic rebuild graph for all Rally-derived artifacts."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from alt_asset_explorer.leaderboards import build_default_archive, write_archive_atomic  # noqa: E402
from alt_asset_explorer.pipeline import build_dataset  # noqa: E402
from build_research_coverage import build_research_coverage  # noqa: E402


@dataclass(frozen=True)
class RebuildResult:
    """Outputs from the ordered, canonical downstream rebuild."""

    processed: dict[str, pd.DataFrame]
    research_coverage: pd.DataFrame
    leaderboard_archive: pd.DataFrame
    leaderboard_path: Path


def rebuild_all(*, as_of: date | None = None) -> RebuildResult:
    """Rebuild every committed artifact that depends on canonical Rally data.

    Dependency order is intentional: processed datasets (including quarterly
    indexes and AI/export context) must exist before coverage and the leaderboard
    archive are refreshed. Runtime-only correlation, scatter, portfolio, custom
    index, benchmark-comparison, and contribution views consume these canonical
    inputs directly and therefore need no independent snapshot build.
    """

    processed = build_dataset(as_of=as_of)
    coverage = build_research_coverage()
    leaderboard = build_default_archive()
    leaderboard_path = write_archive_atomic(leaderboard)
    return RebuildResult(processed, coverage, leaderboard, leaderboard_path)


def main() -> None:
    result = rebuild_all()
    print("Canonical Rally rebuild complete:")
    for name, frame in result.processed.items():
        print(f"- processed/{name}: {len(frame)} rows")
    print(f"- reports/research_coverage: {len(result.research_coverage)} rows")
    print(f"- processed/quarterly_leaderboard_history: {len(result.leaderboard_archive)} rows")


if __name__ == "__main__":
    main()

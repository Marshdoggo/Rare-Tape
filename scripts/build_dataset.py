from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rebuild_all import rebuild_all


if __name__ == "__main__":
    result = rebuild_all()
    print("Built canonical downstream datasets:")
    for name, frame in result.processed.items():
        print(f"- {name}: {len(frame)} rows")
    print(f"- research_coverage: {len(result.research_coverage)} rows")
    print(f"- quarterly_leaderboard_history: {len(result.leaderboard_archive)} rows")

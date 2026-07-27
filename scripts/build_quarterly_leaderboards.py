#!/usr/bin/env python
"""Rebuild or validate the committed quarterly leaderboard state archive."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alt_asset_explorer.leaderboards import (  # noqa: E402
    ARCHIVE_PATH, build_default_archive, load_archive, validate_archive,
    write_archive_atomic,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-refresh", action="store_true", help="Explicitly request the default full rebuild (also the default behavior).")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--from", dest="from_date")
    args = parser.parse_args()
    if args.validate_only:
        archive = load_archive()
        if archive.empty:
            raise SystemExit(f"No archive found at {ARCHIVE_PATH} or its CSV fallback")
        validate_archive(archive)
        print(f"Valid archive: {len(archive):,} states, {archive.snapshot_date.nunique()} snapshots")
        return
    archive = build_default_archive(from_date=args.from_date)
    output = write_archive_atomic(archive)
    print(f"Wrote {len(archive):,} states to {output}")
    print(f"Snapshots: {archive.snapshot_date.min().date()} through {archive.snapshot_date.max().date()} ({archive.snapshot_date.nunique()} quarter ends)")
    print(f"Subjects: {archive.subject_id.nunique()}; metrics: {archive.metric_key.nunique()}")


if __name__ == "__main__":
    main()

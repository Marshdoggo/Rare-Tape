#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alt_asset_explorer.benchmark_lab import load_persisted_benchmarks
from alt_asset_explorer.content_lab import ContentLabEngine, ScoringConfig
from alt_asset_explorer.content_lab.storage import write_archive
from alt_asset_explorer.valuation_library.temporal import load_dated_valuations


def load_engine() -> ContentLabEngine:
    read = lambda p: pd.read_csv(ROOT / p) if (ROOT / p).exists() else pd.DataFrame()
    benchmark = load_persisted_benchmarks().data
    leaderboard_path=ROOT/"data/processed/quarterly_leaderboard_history.parquet"
    leaderboards=pd.read_parquet(leaderboard_path) if leaderboard_path.exists() else pd.DataFrame()
    return ContentLabEngine(read("data/normalized/assets.csv"), read("data/normalized/price_observations.csv"),
        benchmarks=benchmark, liquidity=read("data/processed/liquidity_metrics.csv"), exits=read("data/processed/rally_exits.csv"),
        valuations=load_dated_valuations(ROOT/"data/valuation_library"), leaderboards=leaderboards,
        indices=read("data/processed/rally_quarterly_indices.csv"),
        config=ScoringConfig.load(ROOT / "config/content_story_scoring.yml"))


def build_content_archive(*, limit: int = 20, output_dir: Path | None = None):
    """Rebuild the complete Content Lab archive from current canonical inputs."""
    engine = load_engine()
    results = engine.discover_all(limit_per_quarter=limit)
    paths = write_archive(results, output_dir or ROOT / "data/processed/content_lab")
    return results, paths


def main() -> int:
    parser=argparse.ArgumentParser(description="Build deterministic Rally Content Lab story archives.")
    group=parser.add_mutually_exclusive_group(); group.add_argument("--all-quarters",action="store_true"); group.add_argument("--quarter"); group.add_argument("--latest",action="store_true")
    parser.add_argument("--limit",type=int,default=20); parser.add_argument("--output-dir",type=Path,default=ROOT/"data/processed/content_lab")
    args=parser.parse_args(); engine=load_engine()
    periods=engine.quarters if args.all_quarters or (not args.quarter and not args.latest) else [args.quarter] if args.quarter else engine.quarters[-1:]
    invalid=[p for p in periods if p not in engine.quarters]
    if invalid: parser.error(f"Unavailable quarter(s): {', '.join(invalid)}")
    results=[engine.discover(p,limit=args.limit) for p in periods]; paths=write_archive(results,args.output_dir)
    print(json.dumps({"quarters":periods,"raw_candidates":sum(r.raw_candidates for r in results),"quality_candidates":sum(r.quality_candidates for r in results),"deduplicated_candidates":sum(r.deduplicated_candidates for r in results),"slate_leads":sum(len(r.slate) for r in results),"outputs":[str(x.relative_to(ROOT)) if x.is_relative_to(ROOT) else str(x) for x in paths]},indent=2))
    for result in results[-1:]:
        for rank,lead in enumerate(result.slate[:5],1): print(f"{rank}. [{lead.content_score:.1f}] {lead.thesis}")
    return 0


if __name__ == "__main__": raise SystemExit(main())

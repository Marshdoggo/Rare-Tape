#!/usr/bin/env python3
"""Bootstrap or incrementally refresh committed Benchmark Lab price history."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alt_asset_explorer.benchmark_lab import (
    BENCHMARKS,
    BENCHMARK_PARQUET_PATH,
    BenchmarkDataError,
    download_benchmark,
    earliest_rally_observation_date,
    load_persisted_benchmarks,
    merge_benchmark_history,
    validate_benchmark_history,
    write_benchmark_history_atomic,
)
from alt_asset_explorer.canonical_market import load_authored_price_observations


def _provider_rows(raw: pd.DataFrame, ticker: str, fetched_at: datetime) -> pd.DataFrame:
    definition = BENCHMARKS[ticker]
    return pd.DataFrame(
        {
            "date": raw["date"],
            "ticker": ticker,
            "display_name": definition.name,
            "asset_class": definition.asset_class,
            "adjusted_close": raw["raw_value"],
            "data_source": definition.source,
            "fetched_at": fetched_at,
        }
    )


def update(*, full_refresh: bool = False, overlap_days: int = 7, delay_seconds: float = 1.0) -> tuple[pd.DataFrame, Path, dict[str, int], dict[str, str]]:
    observations = load_authored_price_observations()
    earliest = earliest_rally_observation_date(observations)
    full_start = earliest - pd.Timedelta(days=7)
    end = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    persisted = load_persisted_benchmarks()
    existing = pd.DataFrame(columns=persisted.data.columns) if full_refresh else persisted.data
    additions: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    failures: dict[str, str] = {}
    fetched_at = datetime.now(timezone.utc)

    print(f"Earliest Rally date detected: {earliest.date()}")
    print(f"Full-history fetch start: {full_start.date()}")
    print(f"Fetch end: {end.date()}")
    print(f"Tickers requested: {', '.join(BENCHMARKS)}")
    for position, ticker in enumerate(BENCHMARKS):
        prior = existing[existing["ticker"].eq(ticker)] if not existing.empty else pd.DataFrame()
        start = full_start
        if not prior.empty:
            start = max(full_start, pd.to_datetime(prior["date"]).max() - pd.Timedelta(days=overlap_days))
        try:
            raw = download_benchmark(ticker, start, end)
            additions.append(_provider_rows(raw, ticker, fetched_at))
            counts[ticker] = len(raw)
            print(f"  {ticker}: {len(raw):,} rows ({pd.Timestamp(start).date()} onward)")
        except BenchmarkDataError as exc:
            failures[ticker] = str(exc)
            print(f"  {ticker}: FAILED — {exc}")
        if position + 1 < len(BENCHMARKS) and delay_seconds:
            time.sleep(delay_seconds)

    if not additions and existing.empty:
        raise BenchmarkDataError("No benchmark downloads succeeded; existing history was not replaced.")
    merged = merge_benchmark_history(existing, pd.concat(additions, ignore_index=True) if additions else pd.DataFrame(columns=existing.columns))
    output = write_benchmark_history_atomic(merged)
    print(f"Missing tickers: {', '.join(failures) if failures else 'none'}")
    print(f"Output: {output.relative_to(ROOT)} ({len(merged):,} total rows)")
    print(f"Last available observation: {merged['date'].max().date()}")
    print(f"Mode: {'replaced (full refresh)' if full_refresh else 'incrementally updated'}")
    return merged, output, counts, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-refresh", action="store_true", help="Ignore stored prices and fetch the complete history.")
    parser.add_argument("--validate-only", action="store_true", help="Validate the persisted dataset without downloading.")
    parser.add_argument("--delay-seconds", type=float, default=1.0, help="Pause between provider requests (default: 1).")
    args = parser.parse_args()
    try:
        if args.validate_only:
            result = load_persisted_benchmarks()
            clean = validate_benchmark_history(result.data)
            print(f"Validated {len(clean):,} rows from {result.path}; latest date {clean['date'].max().date()}.")
        else:
            update(full_refresh=args.full_refresh, delay_seconds=max(0, args.delay_seconds))
    except BenchmarkDataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from alt_asset_explorer.manual_imports import import_assets, import_price_history
from alt_asset_explorer.paths import DATA_NORMALIZED, ensure_dirs
from rebuild_all import rebuild_all


def _copy_normalized(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return
    for path in source.glob("*.csv"):
        shutil.copy2(path, target / path.name)


def _summary_line(label: str, accepted_total: int, rejected: int, warnings: int) -> str:
    return f"{label}: normalized_rows={accepted_total}, rejected_rows={rejected}, warnings={warnings}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Process manual Rally asset master and quarterly price research files.")
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--prices", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DATA_NORMALIZED)
    parser.add_argument("--materiality-tolerance", type=float, default=0.01)
    parser.add_argument("--max-quarter-lookback-days", type=int, default=14)
    args = parser.parse_args()

    ensure_dirs()
    if args.dry_run:
        with tempfile.TemporaryDirectory(prefix="rally-manual-dry-run-") as tmp:
            dry_output = Path(tmp) / "normalized"
            _copy_normalized(args.output_dir, dry_output)
            asset_outcome = import_assets(
                args.assets,
                dry_run=True,
                strict=args.strict,
                output_dir=dry_output,
                tolerance=args.materiality_tolerance,
            )
            asset_outcome.accepted.to_csv(dry_output / "assets.csv", index=False)
            price_outcome = import_price_history(
                args.prices,
                dry_run=True,
                strict=args.strict,
                output_dir=dry_output,
                tolerance=args.materiality_tolerance,
                max_quarter_lookback_days=args.max_quarter_lookback_days,
            )
            print("Manual research dry-run complete.")
            print(_summary_line("Assets", len(asset_outcome.accepted), len(asset_outcome.rejected), len(asset_outcome.warnings)))
            print(_summary_line("Quarterly prices", len(price_outcome.accepted), len(price_outcome.rejected), len(price_outcome.warnings)))
            print("No production normalized files were modified.")
            return 2 if args.strict and (len(asset_outcome.rejected) or len(price_outcome.rejected) or asset_outcome.warnings or price_outcome.warnings) else 0

    asset_outcome = import_assets(
        args.assets,
        strict=args.strict,
        output_dir=args.output_dir,
        tolerance=args.materiality_tolerance,
    )
    price_outcome = import_price_history(
        args.prices,
        strict=args.strict,
        output_dir=args.output_dir,
        tolerance=args.materiality_tolerance,
        max_quarter_lookback_days=args.max_quarter_lookback_days,
    )
    rebuild = rebuild_all()
    quarterly_indices = rebuild.processed.get("rally_quarterly_indices")

    print("Manual research processing complete.")
    print(_summary_line("Assets", len(asset_outcome.accepted), len(asset_outcome.rejected), len(asset_outcome.warnings)))
    print(_summary_line("Quarterly prices", len(price_outcome.accepted), len(price_outcome.rejected), len(price_outcome.warnings)))
    print(f"Coverage assets: {len(rebuild.research_coverage)}")
    print(f"Quarterly index rows: {len(quarterly_indices) if quarterly_indices is not None else 0}")
    print(f"Leaderboard states: {len(rebuild.leaderboard_archive)}")
    if asset_outcome.quarantine_path:
        print(f"Asset quarantine: {asset_outcome.quarantine_path}")
    if price_outcome.quarantine_path:
        print(f"Price quarantine: {price_outcome.quarantine_path}")
    return 2 if args.strict and (len(asset_outcome.rejected) or len(price_outcome.rejected) or asset_outcome.warnings or price_outcome.warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

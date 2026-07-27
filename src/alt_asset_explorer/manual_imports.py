from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from alt_asset_explorer.paths import DATA_MANUAL_IMPORTS, DATA_NORMALIZED, DATA_REPORTS, ensure_dirs


ASSET_STATUSES = {
    "announced",
    "offering",
    "funded",
    "holding_period",
    "trading",
    "accepting_orders",
    "suspended",
    "asset_sale_pending",
    "exit_announced",
    "pending_approval",
    "liquidated",
    "delisted",
    "sold",
    "buyout",
    "exited",
    "unknown",
}

EVENT_TYPES = {
    "executed_trade",
    "daily_close",
    "chart_observation",
    "offering_price",
    "distribution",
    "asset_sale",
    "buyout",
    "pending_buyout",
    "unknown",
}

PRICE_EVENT_TYPES = {"executed_trade", "daily_close", "chart_observation"}
PRECISION_STATUSES = {"exact", "rounded", "chart_estimate", "unverified"}
SOURCE_TYPES = {"rally_app", "rally_app_chart", "rally_website", "sec_filing", "manual_research", "other"}
EXIT_TYPES = {"buyout", "asset_sale", "redemption", "liquidation", "delisting", "issuer_repurchase", "auction_sale", "private_sale", "other", "distribution", "unknown"}
EXIT_STATUSES = {"active", "exit_announced", "pending_approval", "pending_settlement", "settled", "exited", "cancelled_exit", "unknown"}

ASSET_COLUMNS = [
    "asset_id",
    "ticker",
    "asset_name",
    "category",
    "subcategory",
    "status",
    "shares_outstanding",
    "offering_date",
    "offering_price_per_share",
    "offering_market_cap",
    "first_trade_date",
    "exit_date",
    "exit_price_per_share",
    "exit_value_total",
    "exit_type",
    "source_reference",
    "verified_at",
    "notes",
]

PRICE_COLUMNS = [
    "asset_id",
    "period_end",
    "observed_at",
    "price_per_share",
    "market_cap",
    "event_type",
    "source_type",
    "source_reference",
    "collected_at",
    "researcher",
    "precision_status",
    "notes",
]

OPTIONAL_ASSET_COLUMNS = ["rally_url", "currency"]
OPTIONAL_PRICE_COLUMNS = ["volume"]

RUN_COLUMNS = [
    "run_id",
    "input_filename",
    "input_hash",
    "started_at",
    "completed_at",
    "accepted_rows",
    "rejected_rows",
    "warning_count",
    "importer_version",
    "status",
]

IMPORTER_VERSION = "manual-import-v2-quarterly"


@dataclass
class ImportOutcome:
    run_id: str
    accepted: pd.DataFrame
    rejected: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    run_record: dict[str, object] = field(default_factory=dict)
    quarantine_path: Path | None = None
    normalized_path: Path | None = None

    def summary(self) -> str:
        lines = [
            f"Run ID: {self.run_id}",
            f"Accepted rows: {len(self.accepted)}",
            f"Rejected rows: {len(self.rejected)}",
            f"Warnings: {len(self.warnings)}",
        ]
        if self.normalized_path:
            lines.append(f"Normalized output: {self.normalized_path}")
        if self.quarantine_path:
            lines.append(f"Quarantine output: {self.quarantine_path}")
        for warning in self.warnings[:20]:
            lines.append(f"WARNING: {warning}")
        return "\n".join(lines)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_id(path: Path, input_hash: str, started_at: str) -> str:
    seed = f"{path.name}:{input_hash}:{started_at}".encode()
    return hashlib.sha256(seed).hexdigest()[:16]


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value or "").strip().split())


def _blank(value: object) -> bool:
    return _normalize_text(value) == ""


def _date(value: object) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce", utc=False)
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _timestamp_date(value: object) -> pd.Timestamp | None:
    text = _normalize_text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_convert(None).normalize()


def _datetime(value: object) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _number(value: object) -> float | None:
    text = _normalize_text(value).replace(",", "").replace("$", "")
    if not text:
        return None
    parsed = pd.to_numeric(text, errors="coerce")
    return float(parsed) if pd.notna(parsed) else None


def _format_number(value: float | None) -> float | None:
    return None if value is None else float(value)


def _material_difference(left: float, right: float, tolerance: float) -> bool:
    baseline = max(abs(left), abs(right), 1.0)
    return abs(left - right) / baseline > tolerance


def is_quarter_end(value: object) -> bool:
    parsed = _timestamp_date(value)
    if parsed is None:
        return False
    return parsed.month in {3, 6, 9, 12} and parsed.day == parsed.days_in_month


def quarter_ends_between(start: object, end: object) -> list[str]:
    start_ts = _timestamp_date(start)
    end_ts = _timestamp_date(end)
    if start_ts is None or end_ts is None or start_ts > end_ts:
        return []
    quarter_ends = pd.date_range(start=start_ts, end=end_ts, freq="QE")
    return [item.date().isoformat() for item in quarter_ends]


def _empty_frame(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _load_existing(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return _empty_frame(columns)
    frame = _read_csv(path)
    for column in columns:
        if column not in frame:
            frame[column] = ""
    return frame[columns]


def _write_run_record(output_dir: Path, record: dict[str, object]) -> None:
    path = output_dir / "import_runs.csv"
    existing = _load_existing(path, RUN_COLUMNS)
    pd.concat([existing, pd.DataFrame([record])], ignore_index=True).to_csv(path, index=False)


def _write_json_run_record(record: dict[str, object]) -> None:
    DATA_REPORTS.mkdir(parents=True, exist_ok=True)
    path = DATA_REPORTS / "manual_import_runs.json"
    records = []
    if path.exists():
        records = json.loads(path.read_text())
    records.append(record)
    path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")


def _archive_input(input_path: Path, run_id: str) -> None:
    archive = DATA_MANUAL_IMPORTS / "archive" / f"{run_id}_{input_path.name}"
    if not archive.exists():
        shutil.copy2(input_path, archive)


def _reject(row: dict[str, object], reasons: list[str], warnings: list[str] | None = None) -> dict[str, object]:
    out = dict(row)
    out["rejection_reason"] = "; ".join(reasons)
    out["warning_reason"] = "; ".join(warnings or [])
    return out


def validate_asset_rows(frame: pd.DataFrame, *, tolerance: float = 0.01) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    missing = [column for column in ASSET_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for idx, raw in frame.iterrows():
        row = {column: _normalize_text(raw.get(column, "")) for column in ASSET_COLUMNS}
        for column in OPTIONAL_ASSET_COLUMNS:
            row[column] = _normalize_text(raw.get(column, ""))
        reasons: list[str] = []
        row_warnings: list[str] = []
        asset_id = row["asset_id"]
        if not asset_id:
            reasons.append("missing_asset_id")
        elif asset_id in seen:
            reasons.append("duplicate_asset_id")
        seen.add(asset_id)
        if not row["asset_name"]:
            reasons.append("missing_asset_name")
        if not row["category"]:
            reasons.append("missing_category")
        if not row["verified_at"]:
            reasons.append("missing_verified_at")
        if not row["source_reference"]:
            reasons.append("missing_source_reference")

        status = row["status"].lower() or "unknown"
        row["status"] = status
        if status not in ASSET_STATUSES:
            reasons.append("invalid_status")

        currency = row.get("currency", "").upper()
        row["currency"] = currency
        if currency and (len(currency) != 3 or not currency.isalpha()):
            reasons.append("invalid_currency")

        shares = _number(row["shares_outstanding"])
        offering_price = _number(row["offering_price_per_share"])
        offering_cap = _number(row["offering_market_cap"])
        exit_price = _number(row["exit_price_per_share"])
        exit_value = _number(row["exit_value_total"])
        if shares is not None and shares <= 0:
            reasons.append("nonpositive_shares_outstanding")
        if offering_price is not None and offering_price < 0:
            reasons.append("negative_offering_price_per_share")
        if offering_cap is not None and offering_cap < 0:
            reasons.append("negative_offering_market_cap")
        if exit_price is not None and exit_price < 0:
            reasons.append("negative_exit_price_per_share")
        if exit_value is not None and exit_value < 0:
            reasons.append("negative_exit_value_total")

        offering_date = _date(row["offering_date"])
        first_trade_date = _date(row["first_trade_date"])
        exit_date = _date(row["exit_date"])
        verified_at = _datetime(row["verified_at"]) or _date(row["verified_at"])
        if row["offering_date"] and not offering_date:
            reasons.append("invalid_offering_date")
        if row["first_trade_date"] and not first_trade_date:
            reasons.append("invalid_first_trade_date")
        if row["exit_date"] and not exit_date:
            reasons.append("invalid_exit_date")
        if row["verified_at"] and not verified_at:
            reasons.append("invalid_verified_at")
        exit_type = row["exit_type"].lower() or ""
        row["exit_type"] = exit_type
        if exit_type and exit_type not in EXIT_TYPES:
            reasons.append("invalid_exit_type")
        if exit_value is not None:
            row_warnings.append("exit_value_total_is_not_shareholder_proceeds")

        implied_cap = None
        if shares is not None and offering_price is not None and offering_cap is not None:
            implied_cap = shares * offering_price
            if _material_difference(implied_cap, offering_cap, tolerance):
                row_warnings.append("offering_market_cap_reconciliation_difference")

        row.update(
            {
                "ticker": row["ticker"].upper(),
                "shares_outstanding": _format_number(shares),
                "offering_date": offering_date,
                "offering_price_per_share": _format_number(offering_price),
                "offering_market_cap": _format_number(offering_cap),
                "implied_offering_market_cap": _format_number(implied_cap),
                "first_trade_date": first_trade_date,
                "exit_date": exit_date,
                "exit_price_per_share": _format_number(exit_price),
                "exit_value_total": _format_number(exit_value),
                "verified_at": verified_at,
                "warning_reason": "; ".join(row_warnings),
            }
        )
        if reasons:
            rejected.append(_reject(row, reasons, row_warnings))
        else:
            accepted.append(row)
            warnings.extend(f"row {idx + 2} {warning}" for warning in row_warnings)

    columns = [*ASSET_COLUMNS, *OPTIONAL_ASSET_COLUMNS, "implied_offering_market_cap", "warning_reason"]
    return pd.DataFrame(accepted, columns=columns), pd.DataFrame(rejected), warnings


def validate_price_rows(
    frame: pd.DataFrame,
    asset_master: pd.DataFrame,
    *,
    tolerance: float = 0.01,
    max_quarter_lookback_days: int = 14,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    assets = asset_master.copy()
    if "asset_id" not in assets:
        assets["asset_id"] = ""
    share_lookup = {}
    if "shares_outstanding" in assets:
        share_lookup = dict(zip(assets["asset_id"].astype(str), pd.to_numeric(assets["shares_outstanding"], errors="coerce")))
    exit_lookup = {}
    if "exit_date" in assets:
        exit_lookup = dict(zip(assets["asset_id"].astype(str), assets["exit_date"].astype(str)))
    known_ids = set(assets["asset_id"].astype(str))
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    warnings: list[str] = []
    seen_payload: dict[tuple[str, str, str], dict[str, object]] = {}
    seen_exact: set[tuple[str, str, str, str, str]] = set()

    for idx, raw in frame.iterrows():
        row = {column: _normalize_text(raw.get(column, "")) for column in PRICE_COLUMNS}
        for column in OPTIONAL_PRICE_COLUMNS:
            row[column] = _normalize_text(raw.get(column, ""))
        reasons: list[str] = []
        row_warnings: list[str] = []
        asset_id = row["asset_id"]
        if not asset_id:
            reasons.append("missing_asset_id")
        elif asset_id not in known_ids:
            reasons.append("unknown_asset_id")
        period_end = _date(row["period_end"])
        observed_at = _datetime(row["observed_at"]) or _date(row["observed_at"])
        collected_at = _datetime(row["collected_at"]) or _date(row["collected_at"])
        period_ts = _timestamp_date(period_end)
        observed_ts = _timestamp_date(observed_at)
        if not period_end:
            reasons.append("invalid_period_end")
        elif not is_quarter_end(period_end):
            reasons.append("period_end_not_calendar_quarter_end")
        if not observed_at:
            reasons.append("invalid_observed_at")
        if period_ts is not None and observed_ts is not None:
            if observed_ts > period_ts:
                row_warnings.append("observed_at_after_period_end")
            lookback_days = (period_ts - observed_ts).days
            if lookback_days >= 0 and lookback_days > max_quarter_lookback_days:
                row_warnings.append(f"observed_at_exceeds_quarter_lookback:{lookback_days}d")
            exit_date = _timestamp_date(exit_lookup.get(asset_id))
            if exit_date is not None and observed_ts > exit_date:
                reasons.append("observed_at_after_verified_exit_date")
        if not collected_at:
            reasons.append("missing_or_invalid_collected_at")
        if not row["source_reference"]:
            reasons.append("missing_source_reference")

        price = _number(row["price_per_share"])
        market_cap = _number(row["market_cap"])
        volume = _number(row.get("volume"))
        if price is not None and price <= 0:
            reasons.append("nonpositive_price_per_share")
        if market_cap is not None and market_cap <= 0:
            reasons.append("nonpositive_market_cap")
        if volume is not None and volume < 0:
            reasons.append("negative_volume")

        event_type = row["event_type"].lower() or "unknown"
        source_type = row["source_type"].lower() or "other"
        precision_status = row["precision_status"].lower() or "unverified"
        row["event_type"] = event_type
        row["source_type"] = source_type
        row["precision_status"] = precision_status
        if event_type not in EVENT_TYPES:
            reasons.append("invalid_event_type")
        if source_type not in SOURCE_TYPES:
            reasons.append("invalid_source_type")
        if precision_status not in PRECISION_STATUSES:
            reasons.append("invalid_precision_status")
        if event_type == "chart_observation" and precision_status == "exact":
            row_warnings.append("chart_observation_marked_exact")
        if event_type == "offering_price":
            row_warnings.append("offering_price_excluded_from_secondary_returns")
        if event_type in {"distribution", "asset_sale"} and price is not None:
            row_warnings.append("non_price_event_has_price")

        implied_cap = None
        shares = share_lookup.get(asset_id)
        if pd.notna(shares) and price is not None and market_cap is not None:
            implied_cap = float(shares) * price
            if _material_difference(implied_cap, market_cap, tolerance):
                row_warnings.append("observed_market_cap_reconciliation_difference")

        duplicate_key = (asset_id, str(period_end), event_type, str(price), str(market_cap))
        conflict_key = (asset_id, str(period_end), event_type)
        if duplicate_key in seen_exact:
            reasons.append("duplicate_price_observation")
        seen_exact.add(duplicate_key)
        previous = seen_payload.get(conflict_key)
        if previous and (previous.get("price_per_share") != price or previous.get("market_cap") != market_cap):
            reasons.append("conflicting_price_observation")
        else:
            seen_payload[conflict_key] = {"price_per_share": price, "market_cap": market_cap}

        row.update(
            {
                "observed_at": observed_at,
                "period_end": period_end,
                "price_per_share": _format_number(price),
                "market_cap": _format_number(market_cap),
                "volume": _format_number(volume),
                "implied_market_cap": _format_number(implied_cap),
                "collected_at": collected_at,
                "frequency": "quarterly",
                "warning_reason": "; ".join(row_warnings),
            }
        )
        if reasons:
            rejected.append(_reject(row, reasons, row_warnings))
        else:
            accepted.append(row)
            warnings.extend(f"row {idx + 2} {warning}" for warning in row_warnings)

    columns = [*PRICE_COLUMNS, *OPTIONAL_PRICE_COLUMNS, "frequency", "implied_market_cap", "warning_reason"]
    return pd.DataFrame(accepted, columns=columns), pd.DataFrame(rejected), warnings


def _merge_assets(existing: pd.DataFrame, incoming: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
    rejected: list[dict[str, object]] = []
    warnings: list[str] = []
    if existing.empty:
        return incoming.copy(), rejected, warnings
    existing_by_id = existing.set_index("asset_id", drop=False)
    additions: list[pd.Series] = []
    updates: dict[str, pd.Series] = {}
    for _, row in incoming.iterrows():
        asset_id = row["asset_id"]
        if asset_id in existing_by_id.index:
            current = existing_by_id.loc[asset_id]
            comparable_cols = [column for column in incoming.columns if column in existing.columns and column != "warning_reason"]
            changed = [
                column
                for column in comparable_cols
                if _normalize_text(current.get(column, "")) != _normalize_text(row.get(column, ""))
            ]
            if changed:
                updates[asset_id] = row
                warnings.append(f"asset_master_updated:{asset_id}:{','.join(changed)}")
        else:
            additions.append(row)
    merged = existing.copy()
    if updates:
        for asset_id, row in updates.items():
            mask = merged["asset_id"].astype(str).eq(str(asset_id))
            for column in row.index:
                if column in merged.columns:
                    merged.loc[mask, column] = row[column]
    if additions:
        merged = pd.concat([merged, pd.DataFrame(additions)], ignore_index=True)
    return merged, rejected, warnings


def _merge_prices(existing: pd.DataFrame, incoming: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    rejected: list[dict[str, object]] = []
    if existing.empty:
        return incoming.copy(), rejected
    exact_keys = set(
        zip(
            existing["asset_id"].astype(str),
            existing.get("period_end", pd.Series([""] * len(existing))).astype(str),
            existing["observed_at"].astype(str),
            existing["event_type"].astype(str),
            existing["price_per_share"].astype(str),
            existing["market_cap"].astype(str),
        )
    )
    conflict = {
        (row["asset_id"], row.get("period_end", ""), row["event_type"]): row
        for _, row in existing.iterrows()
    }
    additions: list[pd.Series] = []
    for _, row in incoming.iterrows():
        exact_key = (
            str(row["asset_id"]),
            str(row.get("period_end", "")),
            str(row["observed_at"]),
            str(row["event_type"]),
            str(row["price_per_share"]),
            str(row["market_cap"]),
        )
        conflict_key = (str(row["asset_id"]), str(row.get("period_end", "")), str(row["event_type"]))
        if exact_key in exact_keys:
            continue
        previous = conflict.get(conflict_key)
        if previous is not None:
            rejected.append(_reject(row.to_dict(), ["existing_price_observation_conflict"]))
        else:
            additions.append(row)
    merged = pd.concat([existing, pd.DataFrame(additions)], ignore_index=True) if additions else existing.copy()
    return merged, rejected


def _finish_import(
    *,
    input_path: Path,
    output_dir: Path,
    normalized_name: str,
    accepted: pd.DataFrame,
    rejected: pd.DataFrame,
    warnings: list[str],
    started_at: str,
    dry_run: bool,
) -> ImportOutcome:
    completed_at = _now()
    input_hash = _file_hash(input_path)
    run_id = _run_id(input_path, input_hash, started_at)
    quarantine_path = DATA_MANUAL_IMPORTS / "quarantine" / f"{run_id}_{normalized_name}_rejected.csv"
    normalized_path = output_dir / f"{normalized_name}.csv"
    status = "dry_run" if dry_run else ("completed_with_rejections" if len(rejected) else "completed")

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        accepted.to_csv(normalized_path, index=False)
        if not rejected.empty:
            rejected.to_csv(quarantine_path, index=False)
        _archive_input(input_path, run_id)
        record = {
            "run_id": run_id,
            "input_filename": input_path.name,
            "input_hash": input_hash,
            "started_at": started_at,
            "completed_at": completed_at,
            "accepted_rows": len(accepted),
            "rejected_rows": len(rejected),
            "warning_count": len(warnings),
            "importer_version": IMPORTER_VERSION,
            "status": status,
        }
        _write_run_record(output_dir, record)
        _write_json_run_record(record)
    else:
        record = {
            "run_id": run_id,
            "input_filename": input_path.name,
            "input_hash": input_hash,
            "started_at": started_at,
            "completed_at": completed_at,
            "accepted_rows": len(accepted),
            "rejected_rows": len(rejected),
            "warning_count": len(warnings),
            "importer_version": IMPORTER_VERSION,
            "status": status,
        }

    return ImportOutcome(
        run_id=run_id,
        accepted=accepted,
        rejected=rejected,
        warnings=warnings,
        run_record=record,
        quarantine_path=quarantine_path if not dry_run and not rejected.empty else None,
        normalized_path=normalized_path if not dry_run else None,
    )


def import_assets(input_path: Path, *, dry_run: bool = False, strict: bool = False, output_dir: Path = DATA_NORMALIZED, tolerance: float = 0.01) -> ImportOutcome:
    ensure_dirs()
    started_at = _now()
    frame = _read_csv(input_path)
    accepted, rejected, warnings = validate_asset_rows(frame, tolerance=tolerance)
    existing = _load_existing(output_dir / "assets.csv", [*ASSET_COLUMNS, *OPTIONAL_ASSET_COLUMNS, "implied_offering_market_cap", "warning_reason"])
    merged, merge_rejected, merge_warnings = _merge_assets(existing, accepted)
    if merge_rejected:
        rejected = pd.concat([rejected, pd.DataFrame(merge_rejected)], ignore_index=True)
    warnings.extend(merge_warnings)
    if strict and (not rejected.empty or warnings):
        merged = existing.copy()
    merged = merged.sort_values(["asset_id"]).reset_index(drop=True)
    return _finish_import(
        input_path=input_path,
        output_dir=output_dir,
        normalized_name="assets",
        accepted=merged,
        rejected=rejected,
        warnings=warnings,
        started_at=started_at,
        dry_run=dry_run,
    )


def import_price_history(
    input_path: Path,
    *,
    dry_run: bool = False,
    strict: bool = False,
    output_dir: Path = DATA_NORMALIZED,
    tolerance: float = 0.01,
    max_quarter_lookback_days: int = 14,
) -> ImportOutcome:
    ensure_dirs()
    started_at = _now()
    frame = _read_csv(input_path)
    asset_master = _load_existing(output_dir / "assets.csv", [*ASSET_COLUMNS, *OPTIONAL_ASSET_COLUMNS, "implied_offering_market_cap", "warning_reason"])
    accepted, rejected, warnings = validate_price_rows(frame, asset_master, tolerance=tolerance, max_quarter_lookback_days=max_quarter_lookback_days)
    existing = _load_existing(output_dir / "price_observations.csv", [*PRICE_COLUMNS, *OPTIONAL_PRICE_COLUMNS, "frequency", "implied_market_cap", "warning_reason"])
    merged, merge_rejected = _merge_prices(existing, accepted)
    if merge_rejected:
        rejected = pd.concat([rejected, pd.DataFrame(merge_rejected)], ignore_index=True)
    if strict and (not rejected.empty or warnings):
        merged = existing.copy()
    merged = merged.sort_values(["asset_id", "period_end", "event_type", "source_reference"]).reset_index(drop=True)
    return _finish_import(
        input_path=input_path,
        output_dir=output_dir,
        normalized_name="price_observations",
        accepted=merged,
        rejected=rejected,
        warnings=warnings,
        started_at=started_at,
        dry_run=dry_run,
    )


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DATA_NORMALIZED)
    parser.add_argument("--materiality-tolerance", type=float, default=0.01)
    parser.add_argument("--max-quarter-lookback-days", type=int, default=14)

from __future__ import annotations

from datetime import date

import pandas as pd


CANONICAL_ASSET_COLUMNS = [
    "asset_id",
    "ticker",
    "name",
    "category",
    "subcategory",
    "brand",
    "model",
    "year",
    "size",
    "material",
    "color",
    "hardware",
    "status",
    "share_count",
    "offering_date",
    "offering_price_usd",
    "offering_valuation_usd",
    "exit_date",
    "exit_price_per_share",
    "exit_value_usd",
    "total_return_at_exit",
    "acquisition_cost_usd",
    "rally_url",
    "sec_filing_url",
    "source_type",
    "source_url",
    "source_notes",
    "last_quote_observed_at",
    "data_quality_status",
    "data_quality_warnings",
]


def _blank_to_none(value: object):
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return float(parsed) if pd.notna(parsed) else None


def _date_iso(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.date().isoformat() if pd.notna(parsed) else None


def _latest_quote_dates(price_history: pd.DataFrame) -> pd.DataFrame:
    if price_history.empty or not {"asset_id", "date"}.issubset(price_history.columns):
        return pd.DataFrame(columns=["asset_id", "last_quote_observed_at"])
    quotes = price_history[["asset_id", "date"]].copy()
    quotes["date"] = pd.to_datetime(quotes["date"], errors="coerce")
    quotes = quotes.dropna(subset=["asset_id", "date"])
    if quotes.empty:
        return pd.DataFrame(columns=["asset_id", "last_quote_observed_at"])
    latest = quotes.groupby("asset_id", as_index=False)["date"].max()
    latest["last_quote_observed_at"] = latest["date"].dt.date.astype(str)
    return latest[["asset_id", "last_quote_observed_at"]]


def _source_type(row: pd.Series) -> str:
    asset_id = str(row.get("asset_id") or "")
    notes = str(row.get("source_notes") or "")
    if asset_id.startswith("sec-rally-"):
        return "sec_synthesized"
    if "portfolio capture" in notes.lower():
        return "rally_portfolio_capture"
    return "manual_seed"


def _quality(row: pd.Series, *, as_of: date | None = None) -> tuple[str, str]:
    warnings: list[str] = []
    if not _blank_to_none(row.get("ticker")):
        warnings.append("missing_ticker")
    if not _blank_to_none(row.get("category")):
        warnings.append("missing_category")
    if _num(row.get("share_count")) is None:
        warnings.append("missing_share_count")
    if _num(row.get("offering_price_usd")) is None:
        warnings.append("missing_offering_price")
    if _blank_to_none(row.get("last_quote_observed_at")) is None:
        warnings.append("missing_quote_snapshot")
    elif as_of is not None:
        observed = pd.to_datetime(row.get("last_quote_observed_at"), errors="coerce")
        if pd.notna(observed) and (pd.Timestamp(as_of) - observed).days > 30:
            warnings.append("stale_quote_snapshot")
    if row.get("source_type") == "sec_synthesized":
        warnings.append("sec_synthesized_not_live_rally_quote")

    if not warnings:
        return "usable", ""
    severe = {"missing_ticker", "missing_category", "missing_share_count", "missing_offering_price"}
    if any(warning in severe for warning in warnings):
        return "incomplete", "; ".join(warnings)
    return "limited", "; ".join(warnings)


def build_canonical_asset_master(
    rally_asset_universe: pd.DataFrame,
    price_history: pd.DataFrame | None = None,
    *,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Build the normalized asset master used by market-table and detail views.

    The input is the already-normalized Rally asset universe, not raw scraped or
    manually imported files. This keeps raw collection concerns outside the
    presentation-facing asset master.
    """
    if rally_asset_universe.empty:
        return pd.DataFrame(columns=CANONICAL_ASSET_COLUMNS)

    quote_dates = _latest_quote_dates(price_history if price_history is not None else pd.DataFrame())
    source = rally_asset_universe.copy()
    if "last_quote_observed_at" not in source.columns:
        source = source.merge(quote_dates, on="asset_id", how="left")

    rows: list[dict] = []
    for _, item in source.iterrows():
        sec_url = _blank_to_none(item.get("sec_filing_url"))
        notes = _blank_to_none(item.get("source_notes"))
        source_url = sec_url or (notes if notes and notes.startswith("http") else None)
        row = {
            "asset_id": _blank_to_none(item.get("asset_id")),
            "ticker": (_blank_to_none(item.get("ticker")) or "").upper() or None,
            "name": _blank_to_none(item.get("name")),
            "category": _blank_to_none(item.get("category")),
            "subcategory": _blank_to_none(item.get("subcategory")),
            "brand": _blank_to_none(item.get("brand")),
            "model": _blank_to_none(item.get("model")),
            "year": _num(item.get("year")),
            "size": _blank_to_none(item.get("size")),
            "material": _blank_to_none(item.get("material")),
            "color": _blank_to_none(item.get("color")),
            "hardware": _blank_to_none(item.get("hardware")),
            "status": _blank_to_none(item.get("status")),
            "share_count": _num(item.get("share_count")),
            "offering_date": _date_iso(item.get("offering_date")),
            "offering_price_usd": None,
            "offering_valuation_usd": _num(item.get("offering_market_cap_usd")),
            "exit_date": _date_iso(item.get("exit_date")),
            "exit_price_per_share": _num(item.get("exit_price_per_share")),
            "exit_value_usd": _num(item.get("exit_market_cap_usd")) or _num(item.get("exit_value_total")),
            "total_return_at_exit": _num(item.get("total_return_at_exit")),
            "acquisition_cost_usd": _num(item.get("acquisition_cost_usd")),
            "rally_url": source_url if source_url and "rally" in source_url.lower() else None,
            "sec_filing_url": sec_url if sec_url and "sec.gov" in sec_url.lower() else sec_url,
            "source_type": None,
            "source_url": source_url,
            "source_notes": notes,
            "last_quote_observed_at": _date_iso(item.get("last_quote_observed_at")),
            "data_quality_status": None,
            "data_quality_warnings": None,
        }
        shares = row["share_count"]
        valuation = row["offering_valuation_usd"]
        row["offering_price_usd"] = valuation / shares if shares and valuation else None
        if row["total_return_at_exit"] is None and shares and row["offering_price_usd"] and row["exit_value_usd"]:
            row["total_return_at_exit"] = row["exit_value_usd"] / shares / row["offering_price_usd"] - 1
        row["source_type"] = _source_type(pd.Series(row))
        row["data_quality_status"], row["data_quality_warnings"] = _quality(pd.Series(row), as_of=as_of)
        rows.append(row)

    out = pd.DataFrame(rows, columns=CANONICAL_ASSET_COLUMNS)
    out = out.dropna(subset=["asset_id"]).drop_duplicates(subset=["asset_id"], keep="last")
    return out.sort_values(["category", "ticker"], na_position="last").reset_index(drop=True)

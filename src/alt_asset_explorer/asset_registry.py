"""Validation and lifecycle-aware queries for the canonical Asset Registry."""

from __future__ import annotations

import math

import pandas as pd


STATUSES = {"trading", "buyout_pending", "exit_pending", "exited"}
TRADING_STATES = {"active", "halted", "inactive"}
EVENT_TYPES = {"none", "buyout_offer", "buyout", "sale", "liquidation", "other_exit"}
EVENT_STATUSES = {"none", "pending", "approved", "rejected", "completed", "withdrawn", "expired"}


def active_registry(registry: pd.DataFrame) -> pd.DataFrame:
    """Return assets that are currently active, not merely historical listings."""
    return registry[
        registry["status"].astype(str).str.lower().eq("trading")
        & registry["trading_state"].astype(str).str.lower().eq("active")
    ].copy()


def historical_registry(registry: pd.DataFrame) -> pd.DataFrame:
    """Return the full supported historical universe, including halted offers."""
    return registry[registry["status"].astype(str).str.lower().isin(STATUSES)].copy()


def pending_buyouts(registry: pd.DataFrame) -> pd.DataFrame:
    """Return pending offers without interpreting offer prices as trades."""
    return registry[
        registry["status"].astype(str).str.lower().eq("buyout_pending")
        & registry["lifecycle_event_status"].astype(str).str.lower().eq("pending")
    ].copy()


def validate_asset_registry(registry: pd.DataFrame, observations: pd.DataFrame) -> list[str]:
    """Return deterministic registry errors; an empty list means valid."""
    errors: list[str] = []
    for key in ("asset_id", "ticker"):
        duplicates = registry.loc[registry[key].duplicated(keep=False), key].astype(str).unique()
        if len(duplicates):
            errors.append(f"duplicate_{key}: {', '.join(sorted(duplicates))}")

    enum_fields = {
        "status": STATUSES,
        "trading_state": TRADING_STATES,
        "lifecycle_event_type": EVENT_TYPES,
        "lifecycle_event_status": EVENT_STATUSES,
    }
    for field, allowed in enum_fields.items():
        invalid = set(registry[field].dropna().astype(str).str.lower()) - allowed
        if invalid:
            errors.append(f"invalid_{field}: {', '.join(sorted(invalid))}")

    prices = observations.copy()
    prices["observed_at"] = pd.to_datetime(prices["observed_at"], errors="coerce")
    for _, row in registry.iterrows():
        ticker = str(row["ticker"])
        offer = pd.to_numeric(row.get("buyout_offer_price_per_share"), errors="coerce")
        if pd.isna(offer):
            continue
        shares = pd.to_numeric(row.get("shares_outstanding"), errors="coerce")
        total = pd.to_numeric(row.get("buyout_offer_total_value"), errors="coerce")
        reference = pd.to_numeric(row.get("buyout_reference_price"), errors="coerce")
        premium = pd.to_numeric(row.get("buyout_premium_pct"), errors="coerce")
        if offer <= 0:
            errors.append(f"{ticker}: nonpositive offer")
        if pd.isna(shares) or pd.isna(total) or not math.isclose(total, offer * shares, abs_tol=0.01):
            errors.append(f"{ticker}: offer total does not reconcile")
        history = prices[prices["asset_id"].astype(str).eq(str(row["asset_id"]))].sort_values("observed_at")
        latest = history.iloc[-1] if not history.empty else None
        ref_date = pd.to_datetime(row.get("buyout_reference_price_date"), errors="coerce")
        if latest is None or not math.isclose(float(latest["price_per_share"]), reference, abs_tol=1e-9) or latest["observed_at"].date() != ref_date.date():
            errors.append(f"{ticker}: reference does not match latest canonical observation")
        if pd.isna(reference) or pd.isna(premium) or not math.isclose(premium, offer / reference - 1, abs_tol=1e-9):
            errors.append(f"{ticker}: premium does not reconcile")
        if str(row["status"]).lower() == "buyout_pending" and str(row["trading_state"]).lower() != "halted":
            errors.append(f"{ticker}: pending buyout is not halted")
        if str(row["lifecycle_event_status"]).lower() == "pending" and any(pd.notna(row.get(c)) for c in ("exit_date", "exit_price_per_share", "exit_value_total")):
            errors.append(f"{ticker}: pending offer has completed exit fields")
        votes = [pd.to_numeric(row.get(c), errors="coerce") for c in ("buyout_vote_yes_pct", "buyout_vote_no_pct", "buyout_vote_advisory_pct")]
        present = [v for v in votes if pd.notna(v)]
        if present and sum(present) > 100.5:
            errors.append(f"{ticker}: vote percentages exceed rounding tolerance")
        if present and pd.isna(pd.to_datetime(row.get("buyout_vote_as_of"), errors="coerce")) and not bool(row.get("buyout_vote_provisional")):
            errors.append(f"{ticker}: approximate votes lack as-of/provisional metadata")
    return errors

from __future__ import annotations

from datetime import date

from .schemas import CandidateReading


def validate_reading(reading: CandidateReading, shares_outstanding: float | None = None, today: date | None = None) -> CandidateReading:
    notes: list[str] = []
    today = today or date.today()
    if reading.observation_date is None: notes.append("missing_or_ambiguous_date")
    elif reading.observation_date > today: notes.append("future_date")
    if reading.price_per_share is None: notes.append("missing_price")
    elif reading.price_per_share <= 0: notes.append("nonpositive_price")
    if reading.market_cap is not None and reading.market_cap <= 0: notes.append("nonpositive_market_cap")
    if reading.price_per_share and reading.market_cap:
        implied = reading.market_cap / reading.price_per_share
        if shares_outstanding and abs(implied - shares_outstanding) / shares_outstanding > 0.05:
            notes.append(f"implied_share_count_mismatch:{implied:.2f}")
    reading.validation_notes = notes
    reading.validation_status = "fail" if notes else "pass"
    return reading

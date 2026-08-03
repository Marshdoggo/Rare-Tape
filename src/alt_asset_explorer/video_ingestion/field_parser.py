from __future__ import annotations

import re
from datetime import date, datetime

from .schemas import CandidateReading

MONEY = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.\d+)?)(?:\s*([KMB])\b)?", re.I)
DATE_PATTERNS = ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d")


def parse_currency(value: str) -> float | None:
    match = MONEY.fullmatch(value.strip())
    if not match:
        return None
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get((match.group(2) or "").upper(), 1)
    return float(match.group(1).replace(",", "")) * multiplier


def parse_date(value: str, *, day_first: bool | None = None) -> date | None:
    cleaned = " ".join(value.strip().replace("Sept ", "Sep ").split())
    for pattern in DATE_PATTERNS:
        try: return datetime.strptime(cleaned, pattern).date()
        except ValueError: pass
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", cleaned)
    if not match: return None
    first, second, year = map(int, match.groups())
    if first <= 12 and second <= 12 and first != second and day_first is None:
        return None
    month, day = (second, first) if day_first or first > 12 else (first, second)
    try: return date(year, month, day)
    except ValueError: return None


def parse_ocr_text(text: str, frame: int = 0, timestamp: float = 0, ocr_confidence: float | None = None, day_first: bool | None = None) -> CandidateReading:
    date_value = None
    date_regexes = [r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}", r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", r"\d{4}-\d{2}-\d{2}"]
    for pattern in date_regexes:
        found = re.search(pattern, text, re.I)
        if found:
            date_value = parse_date(found.group(0).replace(",", ", "), day_first=day_first)
            break
    monies = [(match.group(0), parse_currency(match.group(0))) for match in MONEY.finditer(text) if "$" in match.group(0) or match.group(2)]
    values = [value for _, value in monies if value is not None]
    price = next((v for raw, v in monies if not raw.strip().upper().endswith(("K", "M", "B"))), values[0] if values else None)
    cap = next((v for raw, v in monies if raw.strip().upper().endswith(("K", "M", "B"))), values[1] if len(values) > 1 else None)
    fields = sum(value is not None for value in (date_value, price, cap))
    return CandidateReading(date_value, price, cap, text, frame, timestamp, ocr_confidence, fields / 3)

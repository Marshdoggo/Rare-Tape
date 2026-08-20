from __future__ import annotations

import random

import pandas as pd
import pytest

from alt_asset_explorer.tape import (
    build_tape_candidate_pool,
    build_tape_sequence,
    load_saved_tape_headlines,
    select_tape_panel,
)


def _market() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"asset_id": "a", "ticker": "AAA", "name": "Alpha", "last_price": 12, "return_1q": .2, "return_1y": .5, "last_quote_observed_at": "2026-06-28", "is_current_listed": True},
            {"asset_id": "b", "ticker": "BBB", "name": "Beta", "last_price": None, "return_1q": None, "return_1y": None, "last_quote_observed_at": "2026-06-29", "is_current_listed": True},
            {"asset_id": "x", "ticker": "OLD", "name": "Exited", "last_price": 50, "return_1q": .1, "return_1y": .2, "last_quote_observed_at": "2026-06-30", "is_current_listed": False},
        ]
    )


def _indices() -> pd.DataFrame:
    rows = []
    for index_id, category, method, levels in (
        ("cars-ew", "cars", "equal", [("2025-06-30", 80), ("2026-03-31", 100), ("2026-06-30", 110)]),
        ("all-mcw", "all", "market_cap", [("2026-03-31", 100), ("2026-06-30", 95)]),
        ("books-ew", "books", "equal", [("2025-06-30", 90), ("2026-06-30", 100)]),
    ):
        for date, level in levels:
            rows.append({"index_id": index_id, "date": date, "index_level": level, "weighting_method": method, "category": category, "data_quality_notes": "test artifact"})
    return pd.DataFrame(rows)


def test_candidate_pool_excludes_invalid_and_unlisted_asset_metrics():
    pool = build_tape_candidate_pool(_market(), _indices(), allowed_asset_ids={"a", "b"})
    by_id = {item["candidate_id"] for item in pool}
    assert "a:latest_price" in by_id
    assert "a:qoq_return" in by_id
    assert "a:yoy_return" in by_id
    assert not any(candidate_id.startswith("b:") for candidate_id in by_id)
    assert not any(candidate_id.startswith("x:") for candidate_id in by_id)
    assert next(item for item in pool if item["candidate_id"] == "a:latest_price")["as_of"] == "Through 2026-06-28"


def test_index_returns_require_exact_comparison_quarters():
    pool = build_tape_candidate_pool(pd.DataFrame(), _indices())
    by_id = {item["candidate_id"]: item for item in pool}
    assert by_id["cars-ew:qoq_return"]["value"] == pytest.approx(0.1)
    assert by_id["cars-ew:yoy_return"]["value"] == pytest.approx(0.375)
    assert "all-mcw:qoq_return" in by_id
    assert "all-mcw:yoy_return" not in by_id
    assert "books-ew:qoq_return" not in by_id
    assert "books-ew:yoy_return" in by_id
    assert by_id["cars-ew:index_level"]["as_of"] == "As of 2026-Q2"


def test_panel_selection_avoids_duplicate_objects_and_survives_small_pool():
    pool = build_tape_candidate_pool(_market(), _indices(), allowed_asset_ids={"a"})
    panel = select_tape_panel(pool, rng=random.Random(7))
    assert len(panel) == 3
    assert len({item["object_id"] for item in panel}) == 3
    assert len({item["label"] for item in panel}) == 3
    small = select_tape_panel(pool[:2], rng=random.Random(7))
    assert 1 <= len(small) <= 2


def test_randomization_changes_order_not_candidate_values():
    pool = build_tape_candidate_pool(_market(), _indices(), allowed_asset_ids={"a"})
    first = build_tape_sequence(pool, seed=11, panel_count=8)
    second = build_tape_sequence(pool, seed=29, panel_count=8)
    assert first != second
    canonical = {item["candidate_id"]: item["value"] for item in pool}
    for panel in first + second:
        for item in panel:
            assert item["value"] == canonical[item["candidate_id"]]


def test_saved_headlines_are_read_directly_and_missing_data_is_safe(tmp_path):
    path = tmp_path / "story_leads.csv"
    pd.DataFrame(
        [
            {"headline": "Saved older", "period_end": "2026-03-31", "content_score": 99},
            {"headline": "Saved latest", "period_end": "2026-06-30", "content_score": 50},
            {"headline": "Saved latest", "period_end": "2026-06-30", "content_score": 40},
            {"headline": "", "period_end": "2026-06-30", "content_score": 30},
        ]
    ).to_csv(path, index=False)
    assert load_saved_tape_headlines(path) == ["Saved latest", "Saved older"]
    assert load_saved_tape_headlines(tmp_path / "missing.csv") == []

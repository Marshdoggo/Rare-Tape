from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from alt_asset_explorer.saved_strategies import SavedStrategyDefinition
from alt_asset_explorer.saved_strategy_storage import JsonDirectorySavedStrategyStorage


def _definition(**updates):
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    values = {
        "id": "strategy_books_123456",
        "name": "Books strategy",
        "created_at": now,
        "updated_at": now,
        "saved_type": "strategy",
        "component_rules": [{"component_id": "books", "component_type": "category_strategy", "reference": "Books", "target_weight": 1}],
        "exclusions": {"asset_ids": ["rally-a"]},
        "weighting": {"method": "equal"},
        "alignment": {"calendar": "intersection"},
        "eligibility": {"universe_scope": "include_exited", "admission": "point_in_time_launch"},
        "exit": {"treatment": "terminal_proceeds"},
        "rebalance": {"frequency": "quarterly"},
        "as_of_cutoff": now,
        "dataset_version": "normalized-2026-07-26",
        "methodology_version": "category-strategy-v1",
    }
    values.update(updates)
    return SavedStrategyDefinition.model_validate(values)


def test_saved_strategy_round_trip_uses_its_own_store(tmp_path):
    store = JsonDirectorySavedStrategyStorage(tmp_path / "saved_strategies")
    expected = _definition()
    store.save(expected)
    assert store.get(expected.id) == expected
    assert store.list() == [expected]
    assert (tmp_path / "saved_strategies" / f"{expected.id}.json").exists()


def test_schema_forbids_unlabeled_or_generic_optimization_results():
    with pytest.raises(ValidationError):
        _definition(optimization_results=[{"result_type": "optimized", "objective": "sharpe"}])

    result = _definition(optimization_results=[{
        "result_type": "in_sample", "objective": "sharpe",
        "sample_start": "2024-01-01T00:00:00Z", "sample_end": "2025-01-01T00:00:00Z",
        "optimized_weights": {"books": 1.0},
    }])
    assert result.optimization_results[0].label.startswith("In-sample optimization")


def test_store_rejects_custom_index_tree(tmp_path):
    with pytest.raises(ValueError, match="custom-index"):
        JsonDirectorySavedStrategyStorage(tmp_path / "custom_indices" / "local")

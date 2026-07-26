import pytest

from alt_asset_explorer.builder_state import (
    BUILDER_STATE_VERSION, add_components, bulk_edit_weights, empty_builder_state,
    grouped_components, migrate_builder_state, normalize_weights, remove_components,
)


def component(key, weight, **extra):
    return {"component_id": key, "label": key, "type": "individual_asset", "reference": key, "method": "direct", "weight": weight, **extra}


def test_legacy_state_is_migrated_without_mutating_it():
    legacy = {"asset:a": component("asset:a", .4)}
    state, migrated = migrate_builder_state(legacy)
    state["components"]["asset:a"]["weight"] = 1
    assert migrated and state["version"] == BUILDER_STATE_VERSION
    assert legacy["asset:a"]["weight"] == .4


def test_add_bulk_edit_and_normalize_are_pure():
    original = add_components(empty_builder_state(), [component("a", 2), component("b", 1)])
    edited = bulk_edit_weights(original, {"a": 3})
    normalized = normalize_weights(edited)
    assert original["components"]["a"]["weight"] == 2
    assert normalized["components"]["a"]["weight"] == pytest.approx(.75)
    assert normalized["components"]["b"]["weight"] == pytest.approx(.25)


def test_remove_redistributes_and_groups_category_constituents():
    state = add_components(empty_builder_state(), [
        component("sleeve", .5),
        component("asset:a", .3, method="expanded", origin="books"),
        component("asset:b", .2, method="expanded", origin="books"),
    ])
    assert grouped_components(state) == {"top_level": ["sleeve"], "category:books": ["asset:a", "asset:b"]}
    result = remove_components(state, ["sleeve"], policy="pro_rata")
    assert result["components"]["asset:a"]["weight"] == pytest.approx(.6)
    assert result["components"]["asset:b"]["weight"] == pytest.approx(.4)


def test_invalid_future_state_has_clear_reset_path():
    state, reset = migrate_builder_state({"version": 999, "components": {"x": component("x", 1)}})
    assert reset and state == empty_builder_state()

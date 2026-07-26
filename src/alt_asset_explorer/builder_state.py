"""Versioned, Streamlit-independent state for the portfolio builder.

The reducers in this module never mutate their input.  That makes UI reruns and
state migrations deterministic and lets callers test editing behavior without a
Streamlit runtime.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping


BUILDER_STATE_VERSION = 1


def empty_builder_state() -> dict[str, Any]:
    return {"version": BUILDER_STATE_VERSION, "components": {}}


def migrate_builder_state(value: object) -> tuple[dict[str, Any], bool]:
    """Return current state and whether a legacy/invalid value was migrated.

    The former session value was the component mapping itself.  It is upgraded
    once in place; unknown future versions are deliberately reset rather than
    being interpreted with stale semantics.
    """
    if isinstance(value, Mapping) and value.get("version") == BUILDER_STATE_VERSION:
        components = value.get("components")
        if isinstance(components, Mapping):
            return {"version": BUILDER_STATE_VERSION, "components": deepcopy(dict(components))}, False
    if isinstance(value, Mapping) and "version" not in value:
        candidates = {str(key): deepcopy(dict(item)) for key, item in value.items() if isinstance(item, Mapping)}
        if all(item.get("component_id") == key for key, item in candidates.items()):
            return {"version": BUILDER_STATE_VERSION, "components": candidates}, True
    return empty_builder_state(), value is not None


def add_components(state: Mapping[str, Any], components: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Add missing components, retaining existing edits for duplicate IDs."""
    result = _copy_current(state)
    for component in components:
        item = deepcopy(dict(component))
        component_id = str(item["component_id"])
        item["component_id"] = component_id
        item["weight"] = max(0.0, float(item.get("weight", 0.0)))
        result["components"].setdefault(component_id, item)
    return result


def remove_components(state: Mapping[str, Any], component_ids: Iterable[str], policy: str = "unallocated") -> dict[str, Any]:
    """Remove IDs and optionally redistribute their allocation."""
    result = _copy_current(state)
    ids = set(component_ids)
    removed = sum(float(item.get("weight", 0.0)) for key, item in result["components"].items() if key in ids)
    result["components"] = {key: item for key, item in result["components"].items() if key not in ids}
    remaining = result["components"]
    if removed > 0 and remaining and policy != "unallocated":
        if policy == "equal":
            additions = {key: removed / len(remaining) for key in remaining}
        elif policy == "pro_rata":
            total = sum(float(item.get("weight", 0.0)) for item in remaining.values())
            additions = ({key: removed * float(item.get("weight", 0.0)) / total for key, item in remaining.items()}
                         if total > 0 else {key: removed / len(remaining) for key in remaining})
        else:
            raise ValueError(f"Unknown removal policy: {policy}")
        for key, addition in additions.items():
            remaining[key]["weight"] = float(remaining[key].get("weight", 0.0)) + addition
    return result


def bulk_edit_weights(state: Mapping[str, Any], edits: Mapping[str, float]) -> dict[str, Any]:
    """Apply a set of weight edits atomically."""
    result = _copy_current(state)
    unknown = set(edits) - set(result["components"])
    if unknown:
        raise KeyError(f"Unknown component IDs: {sorted(unknown)}")
    for key, weight in edits.items():
        value = float(weight)
        if value < 0:
            raise ValueError("Component weights cannot be negative")
        result["components"][key]["weight"] = value
    return result


def normalize_weights(state: Mapping[str, Any], component_ids: Iterable[str] | None = None, *, equal: bool = False) -> dict[str, Any]:
    """Normalize all or a selected group to a total weight of one."""
    result = _copy_current(state)
    ids = list(result["components"] if component_ids is None else component_ids)
    if not ids:
        return result
    unknown = set(ids) - set(result["components"])
    if unknown:
        raise KeyError(f"Unknown component IDs: {sorted(unknown)}")
    total = sum(float(result["components"][key].get("weight", 0.0)) for key in ids)
    if equal:
        edits = {key: 1.0 / len(ids) for key in ids}
    elif total > 0:
        edits = {key: float(result["components"][key].get("weight", 0.0)) / total for key in ids}
    else:
        return result
    return bulk_edit_weights(result, edits)


def grouped_components(state: Mapping[str, Any]) -> dict[str, list[str]]:
    """Group top-level entries separately from each expanded category strategy."""
    groups: dict[str, list[str]] = {"top_level": []}
    for key, item in _copy_current(state)["components"].items():
        origin = item.get("origin") if item.get("method") == "expanded" else None
        groups.setdefault(f"category:{origin}", []).append(key) if origin else groups["top_level"].append(key)
    return {key: value for key, value in groups.items() if value}


def _copy_current(state: Mapping[str, Any]) -> dict[str, Any]:
    migrated, _ = migrate_builder_state(state)
    return migrated

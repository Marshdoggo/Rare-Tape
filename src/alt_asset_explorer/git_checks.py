"""Small Git-policy checks used by repository maintenance scripts."""

from __future__ import annotations


def binary_paths(numstat: str) -> list[str]:
    """Extract paths Git reports as binary (``-``/``-`` in numstat)."""
    paths: list[str] = []
    for line in numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0] == parts[1] == "-":
            paths.append(parts[2])
    return paths

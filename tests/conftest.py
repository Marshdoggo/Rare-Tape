"""Repository-wide, self-contained test fixtures."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def synthetic_valuation_library():
    """Materialize legacy valuation inputs for tests, never as production data."""
    source = Path("tests/fixtures/valuation_library/SYNTHETIC-ASSET")
    target = Path("data/valuation_library/SYNTHETIC-ASSET")
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        shutil.copy2(path, target / path.name)
    yield
    shutil.rmtree(target, ignore_errors=True)

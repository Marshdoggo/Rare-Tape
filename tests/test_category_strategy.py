from pathlib import Path

import pandas as pd
import pytest

from alt_asset_explorer.category_strategy import CategoryStrategyDefinition, simulate_category_strategy


@pytest.fixture(scope="module")
def production_books_inputs():
    root = Path(__file__).parents[1]
    assets = pd.read_csv(root / "data/normalized/assets.csv")
    observations = pd.read_csv(root / "data/normalized/price_observations.csv")
    book_ids = tuple(assets.loc[assets["category"].str.casefold().eq("books"), "asset_id"])
    return assets, observations, book_ids


@pytest.fixture(scope="module")
def production_books_minus_two(production_books_inputs):
    assets, observations, book_ids = production_books_inputs
    return assets, observations, book_ids, frozenset(book_ids[-2:])


def test_full_production_books_admits_all_launches(production_books_inputs):
    assets, observations, book_ids = production_books_inputs
    result = simulate_category_strategy(CategoryStrategyDefinition("Books"), assets, observations)
    assert len(book_ids) == 45
    assert result.eligible_asset_ids == book_ids
    assert result.series.iloc[-1]["active_constituent_count"] == 40
    assert result.series["portfolio_value"].gt(0).all()


def test_production_books_minus_two(production_books_minus_two):
    assets, observations, book_ids, removed = production_books_minus_two
    result = simulate_category_strategy(CategoryStrategyDefinition("Books", exclude_asset_ids=removed), assets, observations)
    assert set(result.eligible_asset_ids) == set(book_ids) - removed
    assert result.series.iloc[-1]["active_constituent_count"] == 38


def test_custom_absolute_weights_preserve_cash_and_dynamic_admission():
    assets = pd.DataFrame([
        {"asset_id": "a", "category": "Books", "shares_outstanding": 10, "offering_date": "2024-01-01", "offering_price_per_share": 10},
        {"asset_id": "b", "category": "Books", "shares_outstanding": 20, "offering_date": "2024-04-01", "offering_price_per_share": 10},
    ])
    observations = pd.DataFrame([
        {"asset_id": "a", "period_end": "2024-03-31", "observed_at": "2024-03-30", "frequency": "quarterly", "price_per_share": 10, "event_type": "chart_observation"},
        {"asset_id": "a", "period_end": "2024-06-30", "observed_at": "2024-06-29", "frequency": "quarterly", "price_per_share": 10, "event_type": "chart_observation"},
        {"asset_id": "b", "period_end": "2024-06-30", "observed_at": "2024-06-29", "frequency": "quarterly", "price_per_share": 10, "event_type": "chart_observation"},
    ])
    result = simulate_category_strategy(CategoryStrategyDefinition("Books", "custom_weight", custom_weights={"a": .4, "b": .4}), assets, observations)
    assert list(result.series["active_constituent_count"]) == [1, 2]
    assert result.series.iloc[0]["cash_value"] == pytest.approx(60)
    assert result.series.iloc[-1]["cash_value"] == pytest.approx(20)

from pathlib import Path

import pandas as pd
import pytest

from alt_asset_explorer.asset_registry import active_registry, historical_registry, validate_asset_registry
from alt_asset_explorer.canonical_market import load_asset_master
from alt_asset_explorer.schemas import Category

ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "data/normalized/assets.csv"
OBSERVATIONS = ROOT / "data/normalized/price_observations.csv"
ACTIVE = {"GYMBOX", "POKEMON2", "FOSSILBOX", "BLASTOISE", "05JAYZ", "ROCKETBOX", "JUNGLEBOX", "99TMB2", "85GPK2", "BEATLES2", "HOMER", "BART", "95TOPSUN", "85GPK", "STARWARS3"}
EXITED = {"95CHARZRD", "POKELUGIA", "POKEMON3", "99CHARZRD", "98KNGA", "POKEMON1", "NEOBOX"}
EXIT_TOTALS = {"95CHARZRD": 75_000, "POKELUGIA": 115_000, "POKEMON3": 911_630, "99CHARZRD": 300_000, "98KNGA": 216_000, "POKEMON1": 260_000, "NEOBOX": 33_300}


def _cards():
    return pd.read_csv(ASSETS).query("category == 'trading cards'")


def test_trading_cards_registry_category_counts_and_uniqueness():
    assert Category.trading_cards.value == "trading cards"
    cards = _cards()
    assert len(cards) == cards["ticker"].nunique() == cards["asset_id"].nunique() == 22
    assert set(cards["ticker"]) == ACTIVE | EXITED
    assert set(active_registry(cards)["ticker"]) == ACTIVE
    assert set(historical_registry(cards)["ticker"]) == ACTIVE | EXITED
    completed = cards.query("status == 'exited' and trading_state == 'inactive' and lifecycle_event_type == 'buyout' and lifecycle_event_status == 'completed'")
    assert set(completed["ticker"]) == EXITED
    assert len(load_asset_master().query("category == 'trading cards'")) == 22


def test_trading_cards_offering_and_exit_arithmetic_and_unknown_exit_dates():
    cards = _cards().set_index("ticker")
    actual_offering_totals = cards["shares_outstanding"] * cards["offering_price_per_share"]
    assert actual_offering_totals.to_numpy() == pytest.approx(cards["offering_market_cap"].to_numpy())
    assert cards.loc["BLASTOISE", "offering_market_cap"] == 250_000
    for ticker, total in EXIT_TOTALS.items():
        row = cards.loc[ticker]
        assert row["exit_value_total"] == total
        assert row["exit_price_per_share"] == pytest.approx(total / row["shares_outstanding"])
        assert pd.isna(row["exit_date"])
        assert pd.isna(row["lifecycle_event_date"])
    assert cards.loc["99CHARZRD", "exit_price_per_share"] < cards.loc["99CHARZRD", "offering_price_per_share"]
    assert cards.loc["NEOBOX", "exit_price_per_share"] < cards.loc["NEOBOX", "offering_price_per_share"]


def test_distinct_complete_set_securities_and_dynamic_pokemon_metadata():
    cards = _cards().set_index("ticker")
    assert cards.loc["POKEMON1", "asset_id"] != cards.loc["POKEMON3", "asset_id"]
    assert cards.loc["POKEMON1", "underlying_collectible"] == cards.loc["POKEMON3", "underlying_collectible"]
    assert set(cards[cards["significance"].str.startswith("Pokémon", na=False)].index) == {"GYMBOX", "POKEMON2", "FOSSILBOX", "BLASTOISE", "ROCKETBOX", "JUNGLEBOX", "99TMB2", "95TOPSUN", "95CHARZRD", "POKELUGIA", "POKEMON3", "99CHARZRD", "98KNGA", "POKEMON1", "NEOBOX"}


def test_trading_cards_price_history_preserves_authored_coverage_and_registry_validates():
    cards = _cards()
    observations = pd.read_csv(OBSERVATIONS)
    covered = {
        "GYMBOX": 21,
        "POKEMON2": 21,
        "FOSSILBOX": 23,
        "BLASTOISE": 16,
        "05JAYZ": 18,
        "ROCKETBOX": 21,
        "JUNGLEBOX": 23,
        "99TMB2": 22,
        "85GPK2": 17,
        "BEATLES2": 17,
        "HOMER": 17,
        "BART": 19,
        "95TOPSUN": 21,
        "85GPK": 21,
        "STARWARS3": 17,
    }
    asset_ids = cards.set_index("ticker")["asset_id"]
    history = observations[observations["asset_id"].isin(asset_ids.loc[list(covered)])]

    actual = history.groupby("asset_id").size()
    assert {ticker: int(actual[asset_ids[ticker]]) for ticker in covered} == covered
    assert len(history) == 294
    assert history["frequency"].value_counts().to_dict() == {"quarterly": 277, "weekly": 17}
    assert not history.duplicated(["asset_id", "observed_at"]).any()
    assert set(cards.loc[cards["asset_id"].isin(observations["asset_id"]), "ticker"]) == set(covered)

    shares = cards.set_index("asset_id")["shares_outstanding"]
    expected_caps = history["price_per_share"] * history["asset_id"].map(shares)
    assert history["market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())
    assert history["implied_market_cap"].to_numpy() == pytest.approx(expected_caps.to_numpy())

    fossilbox = history.query("asset_id == 'rally-fossilbox'").set_index("observed_at")
    assert fossilbox.loc["2026-06-25T00:00:00Z", "frequency"] == "weekly"
    assert fossilbox.loc["2026-07-02T00:00:00Z", "frequency"] == "quarterly"
    assert fossilbox.loc["2026-07-02T00:00:00Z", "period_end"] == "2026-06-30"

    junglebox = history.query("asset_id == 'rally-junglebox'").set_index("observed_at")
    assert junglebox.loc["2022-02-14T00:00:00Z", "frequency"] == "weekly"
    assert junglebox.loc["2022-02-18T00:00:00Z", "frequency"] == "weekly"
    assert junglebox.loc["2022-03-29T00:00:00Z", "frequency"] == "quarterly"
    assert set(junglebox.loc[["2022-02-14T00:00:00Z", "2022-02-18T00:00:00Z", "2022-03-29T00:00:00Z"], "period_end"]) == {"2022-03-31"}

    bart = history.query("asset_id == 'rally-bart'").set_index("observed_at")
    assert bart.loc["2026-07-10T00:00:00Z", "frequency"] == "weekly"
    assert bart.loc["2026-08-18T00:00:00Z", "frequency"] == "weekly"
    assert set(bart.loc[["2026-07-10T00:00:00Z", "2026-08-18T00:00:00Z"], "period_end"]) == {"2026-09-30"}

    starwars3 = history.query("asset_id == 'rally-starwars3'").set_index("observed_at")
    assert starwars3.loc["2026-08-13T00:00:00Z", "frequency"] == "weekly"
    assert starwars3.loc["2026-08-13T00:00:00Z", "period_end"] == "2026-09-30"

    active_ids = cards.loc[cards["ticker"].isin(ACTIVE), "asset_id"]
    active_history_ids = set(observations.loc[observations["asset_id"].isin(active_ids), "asset_id"])
    assert active_history_ids == set(active_ids)
    assert validate_asset_registry(cards, observations) == []

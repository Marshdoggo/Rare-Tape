from __future__ import annotations

from datetime import date

import pandas as pd

from alt_asset_explorer.connectors.category_imports import load_all_category_imports, load_chrono24_market_data
from alt_asset_explorer.connectors.rally_manual import load_assets, load_comps, load_price_history, load_quarterly_index_observations
from alt_asset_explorer.assets import build_canonical_asset_master
from alt_asset_explorer.birkin import birkin_market_summary, build_birkin_comparison
from alt_asset_explorer.connectors.sec_edgar import EdgarClient, build_sec_outputs
from alt_asset_explorer.context import build_ai_context, write_ai_context
from alt_asset_explorer.export import build_mme_universe_export, build_newsletter_exports, build_universe_export
from alt_asset_explorer.investable import (
    build_ai_report_context,
    build_comparable_sales_universe,
    build_data_diagnostics,
    build_rally_asset_universe,
    estimate_secondary_navs,
    match_assets_to_comps,
    write_ai_report_context,
)
from alt_asset_explorer.indices import build_quarterly_rally_indices, build_rally_indices, prepare_quarterly_observations
from alt_asset_explorer.universe import build_asset_universe_diagnostics
from alt_asset_explorer.exchange_history import rebuild_exchange_history
from alt_asset_explorer.current_universe import build_current_asset_universe, calculate_current_universe_summary
from alt_asset_explorer.canonical_market import manual_exits_from_assets
from alt_asset_explorer.liquidity import compute_liquidity_metrics
from alt_asset_explorer.normalization import normalize_comps
from alt_asset_explorer.paths import DATA_NORMALIZED, DATA_PROCESSED, ensure_dirs
from alt_asset_explorer.scoring import compute_scores, load_scoring_config
from alt_asset_explorer.valuation import estimate_navs


def build_dataset(*, as_of: date | None = None) -> dict[str, pd.DataFrame]:
    as_of = as_of or date.today()
    ensure_dirs()
    assets = load_assets()
    comp_frames = [load_comps(), load_all_category_imports()]
    comps = normalize_comps(pd.concat([frame for frame in comp_frames if not frame.empty], ignore_index=True))
    price_history = load_price_history()
    quarterly_index_observations = load_quarterly_index_observations()
    rally_indices = build_rally_indices(price_history)
    rally_quarterly_indices = build_quarterly_rally_indices(quarterly_index_observations, assets)
    market_context = load_chrono24_market_data()
    config = load_scoring_config()
    navs = estimate_navs(assets, comps, as_of=as_of, category_modifiers=config.get("category_modifiers", {}))
    liquidity = compute_liquidity_metrics(assets, price_history, as_of=as_of)
    scores = compute_scores(assets, navs, liquidity)
    sec_series, exits = build_sec_outputs(EdgarClient(user_agent="cache-only", cache_only=True))
    manual_exits = manual_exits_from_assets(pd.read_csv(DATA_NORMALIZED / "assets.csv"))
    if not manual_exits.empty:
        exits = pd.concat([exits, manual_exits], ignore_index=True)
        exits = exits.drop_duplicates(subset=["asset_id"], keep="last")
    if exits.empty:
        exits = pd.DataFrame(columns=["exit_id", "asset_id", "series_name", "sale_price", "sale_date", "realized_return", "source_url", "source_confidence"])
    if sec_series.empty:
        sec_series = pd.DataFrame(columns=["series_id", "cik", "accession_number", "filing_type", "filing_date", "filing_url", "series_name", "asset_name", "offering_price", "shares", "acquisition_cost", "offering_expenses", "status", "source_confidence"])
    birkin_comparison = build_birkin_comparison(assets, comps, sec_series)
    birkin_summary = birkin_market_summary(birkin_comparison, as_of=as_of)
    rally_asset_universe = build_rally_asset_universe(assets, price_history, sec_series, exits)
    canonical_asset_master = build_canonical_asset_master(rally_asset_universe, price_history, as_of=as_of)
    comparable_sales_universe = build_comparable_sales_universe(comps)
    asset_comp_matches = match_assets_to_comps(rally_asset_universe, comparable_sales_universe)
    rally_asset_decision_universe = estimate_secondary_navs(rally_asset_universe, comparable_sales_universe, asset_comp_matches, as_of=as_of)
    data_diagnostics = build_data_diagnostics(
        rally_asset_universe,
        comparable_sales_universe,
        rally_asset_decision_universe,
        DATA_PROCESSED.parent / "diagnostics" / "import_errors.csv",
    )
    universe_export = build_universe_export(assets, price_history, liquidity, as_of=as_of)
    mme_universe_export = build_mme_universe_export(rally_asset_decision_universe, as_of=as_of)
    newsletter_exports = build_newsletter_exports(rally_asset_decision_universe, as_of=as_of)
    ai_context = build_ai_context(assets, navs, liquidity, scores, exits, as_of=as_of)
    ai_report_context = build_ai_report_context(rally_asset_decision_universe, asset_comp_matches, data_diagnostics, as_of=as_of)
    exchange_history = rebuild_exchange_history(canonical_asset_master, price_history, exits, frequency="native", persist=False)
    current_universe = build_current_asset_universe(canonical_asset_master, exchange_history.asset_history, as_of_date=as_of)
    current_universe_summary = pd.DataFrame([calculate_current_universe_summary(current_universe)])
    asset_universe_diagnostics = build_asset_universe_diagnostics(canonical_asset_master, prepare_quarterly_observations(quarterly_index_observations, canonical_asset_master), exits, include_exited=True)

    outputs = {
        "assets": assets,
        "comps_normalized": comps,
        "price_history": price_history,
        "rally_indices": rally_indices,
        "rally_quarterly_indices": rally_quarterly_indices,
        "nav_estimates": navs,
        "liquidity_metrics": liquidity,
        "scores": scores,
        "rally_sec_series": sec_series,
        "rally_exits": exits,
        "market_context": market_context,
        "birkin_comparison": birkin_comparison,
        "birkin_summary": birkin_summary,
        "rally_asset_universe": rally_asset_universe,
        "canonical_asset_master": canonical_asset_master,
        "comparable_sales_universe": comparable_sales_universe,
        "asset_comp_matches": asset_comp_matches,
        "rally_asset_decision_universe": rally_asset_decision_universe,
        "data_diagnostics": data_diagnostics,
        "exchange_data_quality_report": exchange_history.data_quality_report,
        "exchange_reconciliation_report": exchange_history.reconciliation_report,
        "exchange_validation_warnings": exchange_history.validation_warnings,
        "asset_universe_diagnostics": asset_universe_diagnostics,
        "universe_export": universe_export,
        "mme_universe_export": mme_universe_export,
        **newsletter_exports,
    }
    for name, frame in outputs.items():
        frame.to_csv(DATA_PROCESSED / f"{name}.csv", index=False)
    write_ai_context(ai_context, DATA_PROCESSED / "ai_context.json")
    write_ai_report_context(ai_report_context, DATA_PROCESSED / "ai_report_context.json")
    return outputs

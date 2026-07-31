# Rally Terminal Data Architecture Inventory

Last audited: 2026-07-27

## Canonical Rebuild Graph

`python scripts/build_dataset.py` is the standard, system-wide rebuild command.
It delegates to `scripts/rebuild_all.py`; successful manual ingestion invokes the
same function. The ordered graph is:

```text
data/normalized/assets.csv + data/normalized/price_observations.csv
  + comparable sources + cached SEC context + persisted benchmark history
        ↓
processed master/history, quarterly and daily indexes, valuation/liquidity,
decision universe, diagnostics, exports, and AI/report contexts
        ↓
research coverage reports
        ↓
quarterly leaderboard archive (reads the newly built quarterly indexes)
        ↓
Streamlit semantic loaders and runtime analytics
```

Correlation, scatter, Portfolio Construction Laboratory, custom indexes,
Benchmark Lab comparisons, contribution analysis, the market table, and sector
performance do not own separate Rally-history snapshots. They calculate from the
normalized inputs, the canonical market object, and/or the regenerated quarterly
index output. Benchmark price history is intentionally an independently refreshed
external input; the Rally side of Benchmark Lab is canonical and needs no second
snapshot.

## Module Dependency Matrix

| Consumer | Rally dependencies | Rebuild behavior |
| --- | --- | --- |
| Home market table, asset history, sector performance | normalized assets and observations via `get_canonical_market()`; regenerated decision universe, liquidity, and coverage | canonical runtime calculation plus standard rebuild |
| Rally Assets and category pages | regenerated `assets.csv`, NAV, scores, comps, and SEC-context outputs | standard rebuild |
| Index Explorer and equal-/market-cap-weight indexes | regenerated `rally_quarterly_indices.csv`; canonical total-return series in memory | standard rebuild / semantic loader |
| Portfolio Construction Laboratory and custom indexes | canonical market observations and canonical index resolvers | runtime calculation; no private snapshot |
| Exchange Market Cap | canonical market object from normalized inputs | runtime deterministic calculation |
| Rally Leaderboards Lab | normalized assets/observations, regenerated quarterly indexes, persisted external benchmarks | archive rebuilt last by standard rebuild |
| Correlation Structure Lab | normalized assets/observations, regenerated quarterly indexes, canonical total-return series, persisted external benchmarks | runtime calculation; quality cap 300 |
| Modular Scatter Plot Explorer | canonical asset master and authored observations | runtime calculation; no private snapshot |
| AI Report Context | regenerated `ai_context.json` and `ai_report_context.json` | standard rebuild |
| MME/newsletter/universe exports | regenerated decision universe, canonical history, liquidity | standard rebuild |
| Contribution Analysis | current built-in/custom index or portfolio result over canonical observations | runtime calculation; no private snapshot |
| Research Coverage | normalized assets and observations | rebuilt after processed outputs |
| Benchmark Lab | canonical Rally subjects plus independently refreshed `benchmark_history.parquet` | Rally side automatic; external prices intentionally refreshed separately |

The only cached intermediate inputs are the optional ignored `data/cache/` SEC
cache and external benchmark history. SEC content remains contextual rather than
canonical Rally listing data. Curated custom-index definitions are durable user
definitions, not derived market datasets.

## Before Architecture

```text
data/normalized/assets.csv + data/normalized/price_observations.csv
        ↓
scripts/build_dataset.py / scripts/rebuild_exchange_history.py
        ↓
data/processed/canonical_asset_master.csv
        ↓
multiple committed derived CSV snapshots:
  current_asset_universe.csv
  current_universe_summary.csv
  exchange_*_history.csv
  index_*_history.csv
  rally_exit_events.csv
  exit_analytics.csv
        ↓
Streamlit pages loaded page-specific processed CSVs directly
```

This made large generated CSVs look like durable market inputs and caused routine analytics changes to rewrite thousands of rows.

## After Architecture

```text
AUTHORITATIVE RALLY MARKET INPUTS
  data/normalized/assets.csv
  data/normalized/price_observations.csv
        ↓
alt_asset_explorer.canonical_market
  load_asset_master()
  load_quarterly_prices()
  build_canonical_market_data()
        ↓
in-memory deterministic calculations
  current tradable universe
  exchange market-cap history
  category decomposition
  exit-aware total-return indexes
  exit analytics
        ↓
app/app_data.py semantic loaders
        ↓
Home.py + Exchange Market Cap page
```

The two principal Rally market CSV sources of truth are:

1. `data/normalized/assets.csv` — normalized manual Rally asset master imported from the manual asset-master workflow.
2. `data/normalized/price_observations.csv` — normalized manual Rally quarterly price-history observations imported from the manual price-history workflow.

Templates for the authored incoming files live at `data/manual_imports/templates/rally_asset_master_template.csv` and `data/manual_imports/templates/rally_price_history_template.csv`. `data/manual_imports/incoming/`, archives, and quarantines remain local/untracked.

## Source-of-Truth Table

| Path | Classification | Purpose | Authoritative? | Manually authored? |
| --- | --- | --- | --- | --- |
| `data/normalized/assets.csv` | SOURCE | Canonical authored Rally asset master: IDs, tickers, categories, statuses, offerings, shares, and durable exit fields when known. | Yes | Yes, via manual import |
| `data/normalized/price_observations.csv` | SOURCE | Canonical authored Rally quarterly/observed price history with event, precision, source, and market-cap metadata. | Yes | Yes, via manual import |
| `data/normalized/import_runs.csv` | REPORT | Manual import audit log. | No | Generated audit metadata |
| `data/manual_imports/templates/*.csv` | TEMPLATE | Empty templates for authored imports. | No | Maintained schema examples |
| `data/raw/rally_assets_seed.csv` | LEGACY SOURCE | Small seed/demo bootstrap used by legacy research pipeline, not production canonical market source. | No for canonical market | Yes/seeded |
| `data/raw/price_history_seed.csv` | LEGACY SOURCE | Small seed/demo bootstrap used by legacy research pipeline, not production canonical market source. | No for canonical market | Yes/seeded |
| `data/raw/comps_seed.csv` and `data/raw/imports/*_template.csv` | SOURCE/TEMPLATE | Comparable-sales seeds and import templates. | Yes for comps research only | Yes/curated |
| `data/processed/canonical_asset_master.csv` | DERIVED SNAPSHOT | Legacy processed universe containing SEC-synthesized rows; retained for non-migrated research pages. | No | No |
| `data/processed/price_history.csv` | DERIVED SNAPSHOT | Legacy processed price history; retained for non-migrated pages. | No | No |
| `data/processed/rally_exits.csv` | DERIVED SEC CONTEXT | SEC-derived exit context, not canonical Rally market truth. | No | No |
| Other retained `data/processed/*.csv`/`.json` | DERIVED/REPORT | Research, comps, liquidity, exports, diagnostics, and report contexts for pages not migrated in this cleanup. | No unless explicitly a curated export/report | Mostly generated |
| `data/reports/research_coverage.*` | REPORT | Research coverage diagnostics over authored manual assets and observations. | No | Generated report |
| `data/reports/manual_import_runs.json` | REPORT | Detailed manual import history/audit. | No | Generated audit metadata |
| `data/custom_indices/curated/*.json` | USER-CREATED DURABLE DATA | Reviewed index definitions safe for Git. | Yes for curated custom definitions | Yes |
| `data/custom_indices/local/*.json` | USER-CREATED LOCAL DATA | Local user-created index definitions. | No shared authority | User-created; ignored |
| `data/cache/` | CACHE | Optional rebuildable local cache. | No | No |

## Dataset Audit Summary

| Dataset group | Creator / feeder | Runtime consumers before | Decision |
| --- | --- | --- | --- |
| `data/normalized/assets.csv` | `scripts/process_manual_research.py` / manual asset import workflow | Indirectly through processed snapshots | Principal Rally asset source. |
| `data/normalized/price_observations.csv` | `scripts/process_manual_research.py` / manual quarterly price workflow | Home offering context and legacy processed snapshots | Principal Rally price source. |
| `current_asset_universe.csv`, `current_universe_summary.csv`, current reconciliation/contributor CSVs | `pipeline.py`, `scripts/reconcile_current_universe.py` from canonical/processed exchange history | Home and Exchange Market Cap | Removed from Git tracking; calculated through `build_canonical_market_data()`. |
| `exchange_asset_history.csv`, `exchange_category_history.csv`, `exchange_market_cap_history.csv` | `rebuild_exchange_history()` from master/prices/exits | Exchange page and Home KPIs | Removed from Git tracking; calculated in memory. |
| `index_portfolio_history.csv`, `index_constituent_history.csv` | `rebuild_total_return_indexes()` from master/prices/exits | Home and Exchange total-return views | Removed from Git tracking; calculated in memory. |
| `rally_exit_events.csv`, `exit_analytics.csv` | `rebuild_total_return_indexes()` from exit inputs | Home and Exchange exit analytics | Removed from Git tracking; durable authored exit inputs are asset-master exit columns; SEC `rally_exits.csv` remains context only. |
| `index_engine_reconciliation.csv` | `scripts/reconcile_index_engines.py` | Diagnostic only | Removed from Git tracking; can be regenerated as a local report if needed. |
| Exchange quality/reconciliation/warnings reports | `rebuild_exchange_history()` | Exchange audit expander | Retained for now as small diagnostics for non-migrated workflows; not authoritative. |

## Directory Policy

- `data/manual_imports/`: manual workflow templates plus ignored incoming/archive/quarantine working files.
- `data/normalized/`: versioned canonical authored Rally market inputs and import audit outputs.
- `data/processed/`: legacy derived snapshots and reports for pages not yet migrated; not source of truth for canonical Rally market analytics.
- `data/cache/`: ignored, rebuildable local artifacts only.
- `data/reports/`: diagnostics/reports; authoritative only when explicitly curated as report output.
- `data/custom_indices/curated/`: durable reviewed custom index definitions. `local/` remains ignored.

## Removed Redundancies

The following deterministic generated CSVs are now ignored and removed from Git tracking: `current_asset_universe.csv`, `current_universe_summary.csv`, `current_universe_reconciliation.csv`, `current_market_cap_difference_contributors.csv`, `exchange_asset_history.csv`, `exchange_category_history.csv`, `exchange_market_cap_history.csv`, `index_constituent_history.csv`, `index_portfolio_history.csv`, `index_engine_reconciliation.csv`, `exit_analytics.csv`, and `rally_exit_events.csv`.

They can be recalculated from canonical inputs and should not be committed after routine changes.

## App Dependency Changes

- `app/Home.py` uses `app_data.get_canonical_market()` for the current universe, current tradable market cap, represented exchange value, total-return indexes, and exit analytics.
- `app/pages/1_Exchange_Market_Cap.py` uses the same canonical market object and no longer reads committed exchange/index/current-universe snapshots.
- Shared Streamlit caching is provided by `app/app_data.py`, so cache invalidation follows source CSV changes instead of committed generated artifact changes.

## Exit Data Decision

The canonical authored asset master already contains exit columns (`exit_date`, `exit_price_per_share`, `exit_value_total`, and `exit_type`). This cleanup treats those fields as the durable authored exit input for canonical market analytics. SEC-derived `data/processed/rally_exits.csv` remains a contextual derived dataset and is not used as canonical Rally exit truth by the migrated Home and Exchange Market Cap calculations.

## Fake / Demo / Fixture Safety

Production current-universe logic remains centralized in `alt_asset_explorer.current_universe`. It excludes fixture/demo/test/sample/mock/placeholder/synthetic/example rows through production classification rather than page-specific ticker blacklists.

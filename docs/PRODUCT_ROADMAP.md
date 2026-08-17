# Product Roadmap

This roadmap assumes the product is evolving toward Rare Tape: a professional market intelligence and valuation layer for Rally and eventually the broader fractional alternative-asset market.

## Phase 0 - Repository Audit And Stabilization

Status: mostly complete for the local prototype.

- Document current application architecture and data flow.
- Confirm current raw and processed Rally datasets.
- Add canonical asset master with provenance and data-quality status.
- Add homepage market-table MVP and prototype index surface.
- Keep existing Streamlit pages working.
- Add focused tests around newly introduced canonical logic.
- Avoid deleting existing functional code until replacement surfaces are proven.
- Add structured configuration and logging in a later stabilization pass.

Exit criteria:

- A developer can run the dataset build, tests, and Streamlit app locally.
- Current data limitations are documented.
- There is one normalized asset master that downstream product work can join against.

## Phase 1 - Canonical Asset Master

Goal: create the authoritative asset table for Rare Tape.

Status: started. `data/processed/canonical_asset_master.csv` now exists and separates current Rally capture rows from SEC-synthesized research rows.

Deliverables:

- Stable `asset_id` policy.
- `asset_identifiers` mapping for Rally tickers, SEC series names, accession references, and future official Rally IDs.
- Asset master validation report for duplicates, missing identifiers, missing share counts, stale quotes, and SEC-only rows.
- Clear distinction between live/imported Rally rows and SEC-synthesized rows.
- Source provenance retained on every important field.

Suggested storage:

- CSV initially.
- SQLite or DuckDB once quote snapshots and valuation runs become append-only.

## Phase 2 - Market Table MVP

Goal: build the flagship sortable Rally market table.

Status: active. The homepage now uses the canonical asset master plus decision-universe estimates, quote history, and liquidity metrics. The default view is current imported Rally assets only.

Required columns for first version:

- Asset name
- Ticker
- Asset ID
- Category and subcategory
- Last price when available
- Bid and ask when available
- Spread when available
- Shares outstanding
- Market capitalization
- Offering price and offering valuation
- Estimated fair value fields only where existing deterministic estimates are available
- Confidence/data-quality status
- Last market-data update

Required behavior:

- Sort ascending/descending.
- Filter by category and subcategory.
- Search by name and ticker.
- Filter above/below fair value only when fair-value fields are present.
- Show unavailable fields plainly.
- Use provenance and freshness indicators.

## Phase 3 - Asset Detail Page Foundation

Goal: make each row click through to a research page.

Initial sections:

- Market overview.
- Offering and SEC filing context.
- Existing price history.
- Comparable-sales table.
- Experimental valuation summary.
- Data-quality warnings.
- Research-source placeholders.

The page should answer what is known, what is estimated, what is missing, and where the evidence came from.

## Phase 4 - Comparable-Sales Research System

Goal: make manual research productive before automation.

Deliverables:

- Comparable-sale schema extension with inclusion/exclusion fields.
- Source registry.
- Manual CSV import workflow with validation report.
- Similarity scoring by category.
- Notes and reason-for-inclusion fields.
- Currency conversion interface.
- Provenance requirement for every valuation input.

## Phase 5 - Fair-Value Engine MVP

Goal: replace ad hoc NAV calculations with explicit model contracts.

Deliverables:

- `ValuationModel` protocol.
- `ValuationResult` dataclass or pydantic model.
- `FactorContribution` structure.
- Baseline comparable-sales model.
- Confidence score and range calculation.
- Model versioning.
- Serialization tests.
- Category-specific placeholder interfaces.

The first deeper models should be selected based on available data. Current data suggests Hermès handbags are the best initial candidate.

## Phase 6 - Historical Quote Pipeline

Goal: support returns, volume, volatility, spread, liquidity, and market-cap analytics.

Deliverables:

- Append-only quote snapshots.
- Snapshot validation and duplicate handling.
- End-of-day aggregation.
- Return calculations over daily, weekly, monthly, year-to-date, and since-offering windows.
- Missing-price and stale-price handling.
- Tests for new listings, delistings, suspended trading, and missing quotes.

## Phase 7 - Rally Market Indices

Goal: build transparent Rally market indices.

Status: prototype started early for MVP demonstration. `data/processed/rally_indices.csv` includes equal-weighted and market-cap-weighted total-market index series from local quote history.

Initial indices:

- Equal-weighted Rally Market Index.
- Market-cap-weighted Rally Market Index.
- Equal-weighted category indices.
- Market-cap-weighted category indices.

Methodology must document:

- Constituent membership.
- Rebalancing.
- Missing and stale prices.
- Delistings and exited assets.
- Outlier treatment.
- Prevention of survivorship bias.

## Phase 8 - Automated Reporting

Goal: produce deterministic market facts and optional narrative.

Flow:

1. Raw data.
2. Validated metrics.
3. Deterministic facts JSON.
4. Optional LLM narrative.
5. Validation and citation checks.
6. Published report.

The LLM should never inspect raw unbounded data and invent conclusions. It should narrate a bounded facts package that marks confirmed facts, model estimates, inferences, and limitations.

## Phase 9 - Partnership-Ready Product

Goal: demonstrate why Rare Tape and an official Rally data integration would matter.

Deliverables:

- Public demo.
- Product screenshots.
- Architecture diagram.
- Data methodology.
- Fair-value methodology.
- API partnership proposal.
- Data-provider integration proposal.
- Rally growth and analytics case study.

## Proposed Schedule

- Intraday quote collection: manual/local first, hourly only after provider boundaries and caching are reliable.
- End-of-day aggregation: daily after quote snapshots exist.
- Comparable-sales updates: manual imports daily or weekly.
- Search-interest and cultural relevance updates: weekly after providers are selected.
- SEC filing checks: daily or weekly, respecting SEC policies and user-agent requirements.
- Fair-value recalculation: after new comps, quote snapshots, or model changes.
- Index calculation: after end-of-day aggregation.
- Reporting: after deterministic facts package exists.

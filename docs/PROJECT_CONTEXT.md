# Rally Terminal Project Context

Last audited: 2026-07-25
Verification baseline: Python 3.11, Streamlit 1.51.0, pandas 2.3.3, lxml 6.1.1

## Purpose And Product State

Rally Terminal is a Python and Streamlit research application for fractionalized collectible assets. It combines manually researched Rally asset and quarterly-price observations, SEC offering and exit context, secondary-market comparable sales, prototype indices, liquidity and valuation research, and deterministic report/export outputs. It is research software, not a trading system or appraisal service.

The homepage is the primary product surface. It includes research coverage, sector performance, built-in and saved index exploration, constituent attribution, single-asset price history, a custom-index workshop, and a filterable Rally market table. Additional pages cover Rally assets, category research, comparable sales, exits, liquidity, report context, exports, and broader asset-universe diagnostics.

## Architecture And Entry Points

- `app/Home.py` is the Streamlit entrypoint; `app/pages/` contains the multipage views.
- `src/alt_asset_explorer/` contains schemas, connectors, normalization, research, index, valuation, scoring, export, and storage logic.
- `scripts/build_dataset.py` builds processed application artifacts from repository data.
- `scripts/process_manual_research.py` validates and imports manual asset and price research before rebuilding the dataset.
- `scripts/build_research_coverage.py` creates asset-level coverage reports.
- `scripts/fetch_sec_data.py` refreshes the local SEC cache when an appropriate SEC user agent is configured.
- `scripts/write_report.py --date today` writes a deterministic Markdown market report.
- `scripts/rebuild_exchange_history.py` rebuilds exchange market-cap, category, return, decomposition, coverage, and reconciliation artifacts.

The application has no API server or database. Runtime storage is CSV/JSON on the local filesystem. Streamlit pages read committed artifacts from `data/processed/`, `data/normalized/`, `data/reports/`, and reviewed definitions in `data/custom_indices/curated/`.

## Data Flow And Provenance

1. Manual Rally research is validated into normalized asset and price-observation tables. Invalid rows are quarantined and import runs are recorded.
2. Verified normalized/manual imports provide production Rally assets and observations; legacy seed CSVs are fixture/demo bootstrap files and are excluded from production-facing dataset builds by default.
3. Cached SEC filings are parsed into offering-series and exit-event context. SEC-synthesized identifiers are research identifiers, not official Rally IDs.
4. The pipeline builds a canonical asset master and broader decision universe with provenance and quality warnings.
5. Comparable matching, experimental NAV/fair-value estimates, liquidity metrics, scoring, indices, diagnostics, and exports are derived from those normalized inputs.
6. The deployed app reads committed derived snapshots. It does not fetch SEC data or rebuild datasets during startup.

Current generated snapshot after removing legacy demo/SEC-synthesized rows from production-facing app artifacts:

| Artifact | Rows |
| --- | ---: |
| Canonical asset master | 103 |
| Rally asset decision universe | 103 |
| Normalized manual assets | 103 |
| Normalized manual price observations | 1846 |
| Processed price history | 1750 |
| General Rally index rows | 544 |
| Quarterly Rally index rows | 308 |
| SEC series context | 0 |
| Rally exits | 0 |
| Comparable sales universe | 6 |
| Asset-to-comp matches | 0 |
| Research coverage rows | 103 |
| Asset universe diagnostics rows | 103 |

Counts describe the committed research snapshot and are not live market coverage.

## Cars Category Expansion (2026-07-25)

The normalized Rally asset master now includes 20 user-provided, currently trading Cars category records. These authoritative static records include normalized offering-month dates, share counts, offering prices, and validated offering market caps. The canonical master and research-coverage artifacts were rebuilt to include the Cars records without adding synthetic price observations; future price-history imports can link to them by ticker. Current-tradable calculations continue to require a valid recent secondary quote, so this metadata ingestion does not by itself represent the records as live quoted listings.

## Manual Cars Price Coverage Update (Five Assets, 2026-07-25)

The normalized Rally observations now include 150 manually transcribed dated price observations for five existing Cars assets: `rally-93xj1` (`#93XJ1`, 31 rows; 30 quarterly), `rally-83fb1` (`#83FB1`, 31; 31 quarterly), `rally-63cc1` (`#63CC1`, 28; 28 quarterly), `rally-65fm1` (`#65FM1`, 28; 27 quarterly), and `rally-55ps1` (`#55PS1`, 32; 30 quarterly). All implied market caps reconcile to the authoritative master share counts, all five offering observations reconcile to the master offering prices and initial market caps, no asset-master rows were added or changed, and no observations were rejected or quarantined. Actual observation dates and sparse histories are preserved without interpolation or forward-filling. Where multiple raw observations occupy a quarter, the closest observation to quarter-end is the quarterly representative and earlier observations remain non-quarterly evidence; this preserves both September 2020 `55PS1` observations. The Cars equal-weight and market-cap-weighted quarterly index prototypes, full-market indexes, research coverage, contribution inputs, return histories, and dependent processed analytics were rebuilt from the canonical inputs. Five of the 20 Cars master constituents now have authored price history.

## Implemented Capabilities

- Canonical asset and decision-universe construction with provenance and data-quality flags.
- Validated manual research imports with dry runs, archives, quarantine outputs, conflict handling, and run records.
- SEC filing cache/parser for offering-series and exit context.
- Secondary comparable normalization, similarity matching, and experimental NAV estimates.
- Equal-weighted, market-cap-weighted, quarterly descriptive price-index prototypes, exit-aware total-return portfolios, and user-defined index calculations with contribution analysis, cash/pending-settlement accounting, and risk metrics.
- Exchange Market Cap & Performance reconstruction with asset-level carry-forward audit fields, assets-added hover diagnostics for issuance-driven jumps, tradable market-cap exit removals, category decomposition, exit-aware total-return indexes, reconciliation reports, and CSV exports.
- Local and curated custom-index registries. Local JSON persistence is development-only; cloud saving is disabled through `RALLY_CUSTOM_INDEX_READ_ONLY=true`.
- Market-table filters with asset-level trailing/full-history returns, coverage diagnostics, category performance, liquidity metrics, deterministic AI/report context, and MME/newsletter exports.
- Unified Portfolio Construction Laboratory combining full-market and category-index sleeves with expanded category constituents and direct assets. The typed component engine preserves top-level versus internal weighting, common-inception/no-fill alignment, deterministic expansion/removal policies, overlap-aware look-through exposure, exact period-by-period arithmetic contribution, frequency-aware risk metrics, correlation research, and long-only inverse-volatility comparisons. The optimizer comparison is explicitly in-sample and is not presented as a forecast.
- Portfolio construction now separates immutable component definitions, methodology-owning resolvers, and resolved-component evidence. Canonical full-market/category sleeves, direct canonical asset history, and category strategies enter one top-level accounting pass through this boundary; accounting consumes sleeve levels rather than recreating internal returns. Dated constituent snapshots support point-in-time look-through and overlap histories, with explicit internal-cash/unresolved exposure and weight reconciliation on every portfolio date. The former combined component object remains only as a compatibility adapter.
- Portfolio builder session state now has an explicit version boundary and pure add, remove, normalize, and bulk-weight reducers. The Streamlit editor groups top-level sleeves/direct positions separately from the constituents of each expanded category strategy; legacy unversioned component maps are migrated once, while unknown versions are safely reset.

## Important Semantics And Constraints

- A current listed asset requires Rally portfolio-capture provenance and a latest secondary quote. SEC-only rows are not presented as live listings by default.
- Offering price, distributions, and asset-sale events are not ordinary secondary-price returns.
- Missing observations are not imputed in interactive indices. Effective dates and constituent coverage therefore matter.
- Bid, ask, and spread fields remain mostly unavailable.
- Fair-value fields are experimental comparable-sales estimates and must retain that label.
- Category inference and SEC identity matching remain heuristic. Asset linkage must be reviewed before being treated as canonical.
- The deployed filesystem is not durable shared storage. Curated definitions belong in Git; user persistence requires a future database-backed adapter.

## Known Risks And Technical Debt

- Sparse and category-skewed comparable-sales coverage limits valuation confidence.
- Manual/captured trading observations can become stale and are not an official Rally market feed.
- Regex and table-based SEC parsing can over-extract or duplicate series-like rows.
- Historical exchange state is reconstructed from current committed asset, price, and exit artifacts rather than an append-only database, creating revision-history limitations; first-class exit-aware total-return artifacts now reduce survivorship bias when exit records are linked.
- Processed CSV schemas are coupled to Streamlit views and lack a versioned migration boundary.
- Pandas emits five forward-compatibility warnings in the current test suite around concatenation with empty/all-null values.
- There is no production health endpoint, telemetry, durable user storage, or automated data-refresh service.
- Portfolio construction currently uses a fixed common-inception universe for expanded assets. It does not yet model custom baskets, dynamic constituent admission, explicit cash for intentionally unallocated weights, transaction costs, or out-of-sample/walk-forward optimization.

## Portfolio Frequency-Layer Correction (2026-07-26)

The Portfolio Construction Laboratory now treats canonical category-index construction and top-level portfolio rebalancing as separate methodology layers. Category sleeves and category-constituent expansion use the canonical quarterly total-return series and its quarterly constituent history, selected by category, internal weighting method, and universe scope. The portfolio control independently applies buy-and-hold, monthly, quarterly, or annual rebalancing to the selected top-level components; it is no longer used as a constituent-table filter. Runtime constituent data is validated against its actual schema with a controlled diagnostic, and the canonical builder retains one quarterly constituent history rather than concatenating indistinguishable constituent rows from weekly, monthly, and quarterly source-series builds.

## Portfolio Phase 0 Production Diagnostic (2026-07-26)

The Portfolio Laboratory now has a deterministic Phase 0 diagnostic over the committed normalized schemas, before any backtest or derived-index transformation. The verified Books snapshot contains exactly 40 normalized asset IDs and 850 authored observation rows. All 40 IDs resolve; a deliberately unknown test ID remains explicitly missing. There are no common actual `observed_at` dates across all 40 assets. After selecting quarterly rows and resolving four asset/period collisions by retaining the latest actual observation in each canonical period, 837 canonical rows remain from 841 quarterly rows and the all-asset canonical-period intersection contains 12 periods: 2023 Q1 through 2024 Q4, 2025 Q1, 2025 Q4, 2026 Q1, and 2026 Q2. There are no duplicate asset/actual-observation-date rows in this snapshot. Canonical launch periods range from 2019 Q4 through 2022 Q3, while every Books series currently ends at the 2026 Q2 canonical period.

These diagnostics do not imply that the 40 assets traded on common real dates, that missing quarters may be filled, or that canonical period labels are quote timestamps. The canonical-period intersection is a research alignment over authored quarterly assignments; it notably excludes 2025 Q2 and Q3 because at least one selected asset lacks each period. Post-quarter weekly observations remain dated evidence and are excluded from canonical quarterly collision counts. Offering rows may share a canonical quarter with later chart observations; both remain in the normalized source, while the diagnostic's canonical view deterministically keeps the later actual observation.

## Canonical History And Eligibility Contract (2026-07-26)

The Portfolio Laboratory now has a canonical history resolver that returns unchanged source evidence separately from its canonical research view. Canonical rows expose `source_observed_at`, `canonical_period`, and `available_at`; as-of cutoffs are enforced against actual information availability rather than the period label, and same-asset/period collisions deterministically retain the latest observation available by that cutoff. Typed alignment rules make intersection versus union explicit and enforce the production no-fill/no-carry policy. An asset/period eligibility timeline records whether each canonical period has sourced evidence and explains missing observations instead of manufacturing values. A narrow compatibility adapter still emits the legacy `date`/`index_level` component-series shape while retaining both date meanings for callers that have not migrated.

## Near-Term Priorities

## Category-Constituent Strategy Simulator (2026-07-26)

The research engine now composes the canonical quarterly-history resolver and canonical exit normalization to simulate category constituent strategies. It supports equal, observed-market-cap, and absolute custom selected-asset weights; quarterly, annual, or initial-only internal rebalancing; point-in-time launch admission; explicit inclusion and exclusion sets; terminal proceeds; and intentional residual cash. Canonical missing quarters are not manufactured: existing positions retain their last sourced valuation solely for portfolio accounting, while the constituent audit identifies whether each period contains a source observation. Integration coverage exercises the complete committed 40-asset Books universe and a deterministic Books-minus-two universe directly from normalized production inputs.

1. Validate the private GitHub and Streamlit deployment without exposing excluded research inputs.
2. Reconcile manual Rally identities and offering facts against SEC context.
3. Add an asset-detail foundation keyed by canonical `asset_id`.
4. Introduce provider boundaries and append-only quote storage before claiming live-market behavior.
5. Formalize valuation-result and factor-contribution interfaces before expanding category models.
6. Add durable custom-index persistence only when multi-user sharing becomes a product requirement.

## Books Category Expansion (2026-07-19)

The normalized Rally asset master now includes 40 user-provided, currently trading Books category records for rare and signed first-edition books. These rows are committed as Rally App manual asset records with offering dates, share counts, offering prices, and offering market caps. Current-tradable universe calculations continue to require valid current or recent secondary quotes before treating these assets as current tradable market capitalization.

## Production Asset Cleanup (2026-07-19)

Production-facing dataset builds now exclude the legacy raw Rally asset and price seed CSVs by default. Those seed files remain available only as explicit fixtures/legacy diagnostics because their rows were illustrative bootstrap/demo records, not verified Rally Rd listings. The investable universe builder also no longer appends SEC-synthesized series rows unless a caller explicitly opts into SEC context. As a result, committed processed app artifacts now contain 83 verified normalized production asset rows, including the 40 currently trading Books category records and authored exit coverage rows, with corresponding Rally App/manual price observations; SEC-derived series remain filing research context rather than app-listed assets.


## Manual Exit Coverage Update (2026-07-20)

The normalized Rally inputs now include the exited `rally-faubourg` Hermès Faubourg handbag record with a confirmed May 30, 2023 buyout at $87.50 per share / $175,000 total value. Its authored quarterly observations run from the September 2020 offering through the May 2023 terminal buyout observation so exchange-history reconstruction and exit-aware total-return simulations can account for the asset instead of treating the dataset as survivor-only for this handbag. The buyout is an exit event and terminal payout observation, not a current Rally listing or definitive appraisal.

## Manual Exit Price Coverage Update (2026-07-20)

The normalized Rally price observations now include authored quarterly chart observations and terminal buyout observations for exited handbag assets `rally-faubourg2` and `rally-birkinblu`. `rally-faubourg2` runs from its January 2021 offering context through the January 6, 2025 buyout at $16.50 per share / $181,500 total value. `rally-birkinblu` runs from its November 2019 offering context through the April 10, 2025 buyout at $68.00 per share / $68,000 total value. These terminal rows are exit payout observations for reconstruction and total-return research, not current Rally listings or definitive appraisals.

## Manual Watch Exit Coverage Update (2026-07-20)

The normalized Rally inputs now include authored watch exit coverage for `rally-7orlex` (`#70RLEX`) and `rally-aproak` (`#APROAK`). `rally-7orlex` runs from its November 2019 offering context through the December 12, 2023 buyout at $30.00 per share / $30,000 total value. `rally-aproak` runs from its December 2019 offering context through the June 30, 2021 buyout at $110.00 per share / $110,000 total value. APROAK intentionally retains both the May 10, 2021 intra-quarter secondary chart observation and the June 30, 2021 terminal buyout in Q2 2021; canonical quarter-end research should use the realized buyout while preserving the May observation as historical evidence. These terminal rows are exit payout observations for reconstruction and total-return research, not current Rally listings or definitive appraisals.


## Manual Wine Exit Coverage Update (2026-07-20)

The normalized Rally inputs now include authored wine-and-whiskey exit coverage for `rally-17dujac` (`#17DUJAC`), modeled as the 2017 Domaine Dujac Wine Collection. The observation history runs from the March 2021 offering context through the May 13, 2025 realized buyout at approximately $10.923077 per share / $35,500 total value. This terminal row is an exit payout observation for reconstruction and total-return research, not a current Rally listing or definitive appraisal.

## Pending Buyout Offer Coverage Update (2026-07-20)

The normalized Rally inputs now include authored quarterly price observations for `rally-deaton`, the Deaton Triceratops Skull fossil asset, from its January 2021 offering context through the June 22, 2026 last close before a pending buyout vote. The asset is marked `exit_announced`, with pending offer metadata for a proposed $600,000 / $52.631579 per-share buyout and 54% yes vote snapshot. Because the offer has not been approved and completed, Deaton is not modeled as a realized exit, settled buyout, or terminal payout observation.

## Manual Books Price Coverage Update (2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-alice` (`#ALICE`), Lewis Carroll — Alice's Adventures in Wonderland, First Edition. The history preserves the actual observed Rally dates from the September 2020 offering context through the June 25, 2026 Q2 observation at $2.00 per share; a later conversational approximately $1.50 note is intentionally excluded from the current historical build. The verbally supplied first 2021 observation (`2-02-21`) is stored in ISO form as February 2, 2021 and marked unverified/ambiguous in the row notes rather than silently treated as a higher-precision source. ALICE now has sufficient quarterly price history to participate in the Books quarterly index where the prototype methodology permits.


## Manual Books Price Coverage Update (SHKSPR4, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-shkspr4` (`#SHKSPR4`), Shakespeare's Comedies, Histories, and Tragedies. The history preserves the actual observed Rally dates from the July 2020 offering context through the June 24, 2026 Q2 observation at $75.00 per share / $75,000 total value. Market caps are validated against the existing 1,000-share master record. The February 7, 2022 observation is normalized to the December 31, 2021 period as the nearest available after-quarter observation so the March 28, 2022 quote remains the Q1 2022 observation. SHKSPR4 now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (CHURCHILL, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-churchill` (`#CHURCHILL`), Winston Churchill - The Second World War (Signed First Edition). The history preserves the actual observed Rally dates from the July 2020 offering context through the June 24, 2026 Q2 observation at $3.15 per share / $23,625 total value. Market caps are validated against the existing 7,500-share master record. A more recent conversational $3.90 trade note after the Q2 2026 cutoff is intentionally excluded from this quarterly historical build and reserved for future weekly-history coverage. CHURCHILL now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (HGWELLS, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-hgwells` (`#HGWELLS`), H.G. Wells's The Time Machine, Inscribed First Edition. The history preserves the actual observed Rally dates from the June 2021 offering reference value through the June 29, 2026 Q2 observation at $2.30 per share / $17,250 total value. Market caps are validated against the existing 7,500-share master record. The November 1, 2021 observation is normalized to the September 30, 2021 period as the nearest available after-quarter observation. HGWELLS now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.



## Manual Books Price Coverage Update (LOTR, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-lotr` (`#LOTR`), J.R.R. Tolkien's The Lord of the Rings Trilogy, First Edition. The history preserves actual observed Rally dates from the June 5, 2020 offering observation through the July 1, 2026 observation at $75.00 per share / $75,000 total value. Market caps are validated against the existing 1,000-share master record. The July 1, 2026 observation preserves its actual date while being assigned to the June 30, 2026 period by the current nearest-quarter research convention, producing an explicit after-period warning rather than rewriting the source date. LOTR now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (HUCKFINN, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-huckfinn` (`#HUCKFINN`), Mark Twain's Adventures of Huckleberry Finn, First Edition. The history preserves the actual observed Rally dates from the April 2021 offering reference value through the June 29, 2026 Q2 observation at $5.40 per share / $10,800 total value. Market caps are validated against the existing 2,000-share master record. The October 28, 2021 and January 24, 2022 observations are normalized to the September 30, 2021 and December 31, 2021 periods, respectively, as nearest available after-quarter observations. No Q2 2025 observation is imputed because none was supplied. HUCKFINN now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (62BOND, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-62bond` (`#62BOND`), Ian Fleming's The Spy Who Loved Me, Inscribed to RFK. The history preserves the actual observed Rally dates from the December 2020 offering reference value through the June 26, 2026 Q2 observation at $2.65 per share / $41,075 total value. Market caps are validated against the existing 15,500-share master record. 62BOND now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (NEWTON, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-newton` (`#NEWTON`), Sir Isaac Newton's The Principia, First Edition. The history preserves the actual observed Rally dates from the May 2021 offering reference value through the June 29, 2026 Q2 observation at $6.85 per share / $205,500 total value. Market caps are validated against the existing 30,000-share master record. The October 22, 2021 and January 10, 2022 observations are normalized to the September 30, 2021 and December 31, 2021 periods, respectively, as nearest available after-quarter observations. NEWTON now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (NEWWORLD, 2026-07-22)

The normalized Rally price observations now include manually transcribed chart coverage for existing Books asset `rally-newworld` (`#NEWWORLD`), Aldous Huxley - Brave New World (First Edition). The history preserves the actual observed Rally dates from the January 2022 offering reference value through the June 26, 2026 Q2 observation at $2.95 per share / $5,900 total value, with market caps validated against the existing 2,000-share master record. A known July 22, 2026 post-Q2 observation at $5.80 per share / $11,600 total value is retained as a weekly/current-price observation for future higher-frequency history; it is intentionally not used as the Q2 2026 quarterly observation because it falls 22 days after June 30 under the strict quarterly cutoff note. NEWWORLD now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (ROOSEVELT, 2026-07-22)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-roosevelt` (`#ROOSEVELT`), Theodore Roosevelt - African Game Trails (Signed First Edition). The history preserves the actual observed Rally dates from the March 2020 offering reference value through the June 30, 2026 Q2 observation at $19.80 per share / $19,800 total value. Market caps are validated against the existing 1,000-share master record. The April 13, 2021 and January 31, 2022 observations are normalized to the March 31, 2021 and December 31, 2021 periods, respectively, as nearest available after-quarter observations. ROOSEVELT now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (WZRDOFOZ, 2026-07-23)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-wzrdofoz` (`#WZRDOFOZ`), The Wonderful Wizard of Oz, First Edition. The history preserves the actual observed Rally dates from the April 2021 offering reference value through the June 29, 2026 Q2 observation at $6.15 per share / $36,900 total value. Market caps are validated against the existing 6,000-share master record. No Q4 2022 observation is imputed because none was supplied. WZRDOFOZ now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (GWTW, 2026-07-23)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-gwtw` (`#GWTW`), Gone with the Wind (Inscribed First Printing). The history preserves the actual observed Rally dates from the February 2022 offering reference value through the June 26, 2026 Q2 observation at $3.40 per share / $17,000 total value. Market caps are validated against the existing 5,000-share master record. No observations are imputed for missing quarters. GWTW now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.



## Manual Books Price Coverage Update (BROSGRIMM, 2026-07-23)

The normalized Rally price observations now include manually transcribed Rally chart coverage for existing Books asset `rally-brosgrimm` (`#BROSGRIMM`), Grimms' Fairy Tales (Inscribed). The history preserves actual observed Rally dates from the May 2021 offering reference value through the June 29, 2026 Q2 observation at $12.50 per share / $62,500 total value. Market caps are validated against the existing 5,000-share master record. A July 23, 2026 post-Q2 observation at $20.00 per share / $100,000 total value is retained as a weekly observation for future higher-frequency history; it is intentionally not used as the Q2 2026 quarterly observation because it falls 23 days after June 30 under the strict quarter-end cutoff note. BROSGRIMM now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (JEKYLL, 2026-07-23)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-jekyll` (`#JEKYLL`), Robert Louis Stevenson's Dr. Jekyll and Mr. Hyde, First Edition. The history preserves the actual observed Rally dates from the August 2022 offering reference value through the June 30, 2026 Q2 observation at $2.80 per share / $14,000 total value. Market caps are validated against the existing 5,000-share master record. No observations are imputed for missing quarters. JEKYLL now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (GATSBY, 2026-07-23)

The normalized Rally price observations now include manually transcribed Rally chart coverage for existing Books asset `rally-gatsby` (`#GATSBY`), The Great Gatsby (Signed First Edition). The history preserves actual observed Rally dates from the September 2020 offering reference value through the June 26, 2026 Q2 observation at $24.00 per share / $96,000 total value. Market caps are validated against the existing 4,000-share master record. The January 3, 2022 observation is normalized to the December 31, 2021 period as the nearest available after-quarter observation so the March 29, 2022 quote remains the Q1 2022 observation. No observations are imputed for missing quarters. GATSBY now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (TREASURE, 2026-07-23)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-treasure` (`#TREASURE`), Robert Louis Stevenson's Treasure Island, First Edition. The history preserves the actual observed Rally dates from the May 2022 offering reference value through the June 29, 2026 Q2 observation at $3.10 per share / $13,950 total value. Market caps are validated against the existing 4,500-share master record. No observations are imputed for missing quarters, including Q3 2022. TREASURE now has sufficient secondary quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.

## Manual Books Price Coverage Update (MARX, 2026-07-23)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-marx` (`#MARX`), Karl Marx's Das Kapital, First Edition. The history preserves the actual observed Rally dates from the October 2021 offering reference value through the June 25, 2026 Q2 observation at $4.60 per share / $36,800 total value. Market caps are validated against the existing 8,000-share master record. The February 22, 2022 observation is normalized to the December 31, 2021 period as the nearest available after-quarter observation so the March 29, 2022 quote remains the Q1 2022 observation. No observations are imputed for missing quarters. MARX now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.

## Manual Books Price Coverage Update (WILDTHING, 2026-07-23)

The normalized Rally price observations now include manually transcribed quarterly chart coverage for existing Books asset `rally-wildthing` (`#WILDTHING`), Maurice Sendak's Where the Wild Things Are, Inscribed First Edition. The history preserves the actual observed Rally dates from the October 2021 offering reference value through the June 25, 2026 Q2 observation at $6.95 per share / $13,900 total value. Market caps are validated against the existing 2,000-share master record. No observations are imputed for missing quarters. WILDTHING now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (RABBIT, 2026-07-23)

The normalized Rally price observations now include manually transcribed Rally chart coverage for existing Books asset `rally-rabbit` (`#RABBIT`), Beatrix Potter's The Tale of Peter Rabbit, First Edition. The history preserves the actual supplied observation dates from the August 2022 offering reference value through the June 30, 2026 Q2 observation at $2.45 per share / $24,500 total value, with market caps validated against the existing 10,000-share master record. A dated July 9, 2026 post-quarter observation at $4.75 per share / $47,500 total value is retained as a weekly/non-quarterly research row and is intentionally not used as the Q2 2026 quarterly observation. The supplied latest-trade note at $4.70 per share / $47,000 total value is omitted because no precise observed_at date was supplied. RABBIT now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.


## Manual Books Price Coverage Update (ANMLFARM, 2026-07-23)

The normalized Rally price observations now include manually transcribed Rally chart coverage for existing Books asset `rally-anmlfarm` (`#ANMLFARM`), George Orwell's Animal Farm, First Edition. The history preserves actual observed Rally dates from the November 2020 offering reference value through the June 26, 2026 Q2 observation at $20.70 per share / $20,700 total value. Market caps are validated against the existing 1,000-share master record. A July 23, 2026 post-Q2 observation at $23.45 per share / $23,450 total value is retained as a weekly/non-quarterly research row for future higher-frequency history; it is intentionally not used as the Q2 2026 quarterly observation. ANMLFARM now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits. With this ingestion, the working Books manual-history coverage count is 21 of 40 currently trading Books assets cataloged (52.5%).

## Manual Books Price Coverage Update (Nine Assets, 2026-07-25)

The normalized Rally observations now include 187 manually transcribed price-history rows for nine existing Books assets: `rally-lotf` (`#LOTF`, 17 rows), `rally-59bond` (`#59BOND`, 21), `rally-holmes` (`#HOLMES`, 19), `rally-bradbury` (`#BRADBURY`, 17), `rally-irobot` (`#IROBOT`, 19), `rally-mobydick` (`#MOBYDICK`, 19), `rally-59jfk` (`#59JFK`, 23), `rally-aghowl` (`#AGHOWL`, 27), and `rally-bond1` (`#BOND1`, 25). All market caps reconcile to the existing master-record share counts, and no new assets were created. The spoken `AGHOL` ticker was resolved to canonical `AGHOWL`. AGHOWL retains both the February 14, 2022 and March 28, 2022 observations, and both the June 26 and July 2, 2026 observations, as dated research evidence; the earlier/later same-quarter observations remain non-quarterly rows so canonical quarterly analytics select the applicable in-quarter close without inventing or forward-filling a quote. The Books quarterly-history working coverage is now 30 of 40 currently trading Books assets (75%).


## Manual Books Price Coverage Update (GRAPES, KEROUAC, WALDEN, DUNE, FROST; 2026-07-25)

The normalized Rally observations now include 115 manually transcribed price-history rows for five existing Books assets: `rally-grapes` (`#GRAPES`, 21 rows), `rally-kerouac` (`#KEROUAC`, 22), `rally-walden` (`#WALDEN`, 21), `rally-dune` (`#DUNE`, 23), and `rally-frost` (`#FROST`, 28). All market caps reconcile to the existing master-record share counts, no new assets were created, and the erroneous GRAPES March 31, 2022 transcription is excluded. GRAPES has no imputed Q3 2025 row. FROST preserves both the March 25 and April 1, 2022 observations and retains July 9, 2026 as dated non-quarterly research evidence; canonical quarterly analytics select the applicable representative without forward-filling. The Books quarterly-history working coverage is now 35 of the 40 currently trading Books assets cataloged for this coverage program (87.5%).

## Manual Books Price Coverage Completion (TKAM, ULYSSES, TWOCITIES, CONGRESS, YOKO; 2026-07-25)

The normalized Rally observations now include 120 manually transcribed price-history rows for five existing Books assets: `rally-tkam` (`#TKAM`, 22 rows), `rally-ulysses` (`#ULYSSES`, 25), `rally-twocities` (`#TWOCITIES`, 27), `rally-congress` (`#CONGRESS`, 21), and `rally-yoko` (`#YOKO`, 25). All supplied market caps reconcile to the existing master-record share counts, no new assets were created, and no observations were quarantined. Actual observation dates are preserved; the July 2, 2026 TWOCITIES observation is assigned to the June 30, 2026 research period under the established nearest-quarter convention, and sparse quarters remain missing rather than forward-filled. YOKO's April 13, 2021 observation is assigned to the June 30, 2021 period so both supplied 2021 observations remain distinct quarterly evidence. CONGRESS retains its offering context and November 8, 2021 secondary observation in the same period under distinct event types.

This ingestion completes the stated Books quarterly-history coverage program at 40 of 40 currently trading assets (100%). The normalized master contains those same 40 Books records; the previously included `rally-catcher` row was removed because it is not part of Rally's 40-asset trading Books catalog. Both Books equal-weight and market-cap-weighted quarterly index prototypes and their dependent coverage and analytics artifacts were rebuilt from the canonical inputs.

## Market Table Return Screening Update (2026-07-22)

The homepage Rally Market Table now includes asset-level 1Q, 1Y, and full-history return columns calculated from the same canonical historical price-cleaning path used by the exit-aware total-return engine. Sparse trailing windows use the latest valid observable price on or before the lookback anchor date, avoiding interpolation and avoiding forward-looking prices. Full-history return uses each asset's first valid observable price and latest valid or terminal price. Insufficient trailing history remains blank rather than imputed. The market table also supports single-row selection to seed the Asset Price History selector, beginning the Asset Explorer workflow without introducing custom JavaScript.

## Development And Verification

```bash
python3 scripts/build_dataset.py
python3 scripts/build_research_coverage.py
pytest -q
streamlit run app/Home.py
```

Run Streamlit from the repository root so local and Community Cloud path behavior match. Deployment uses Python 3.11, `requirements.txt`, branch `main`, and entrypoint `app/Home.py`.

## Current-Universe And Index Reconciliation Update (2026-07-18)

The current-tradable universe is now defined centrally in `alt_asset_explorer.current_universe` and is the shared source for same-name homepage and Exchange Market Cap KPI cards. A current tradable asset is a production Rally asset with canonical `active_tradable` status, positive shares, a valid current price, no offering-only valuation, and an observation age no greater than the canonical 120-day staleness threshold. Stale carried-forward observations remain in exchange-history diagnostics and represented-value analysis, but they are not labeled tradable market capitalization.

Canonical asset-state normalization maps legacy labels such as `trading`, `active`, and `accepting_orders` to `active_tradable`; terminal labels such as `sold`, `redeemed`, `liquidated`, `exited`, `delisted`, and `buyout` to `exited`; and other offering, paused, pending-settlement, cancelled, withdrawn, or unknown states to explicit canonical states. Production-facing Rally assets should use `platform = Rally` and `record_environment = production` when those fields exist. Fixture, demo, sample, mock, placeholder, synthetic, and test rows are excluded from production current-universe calculations.

Current-price methodology is intentionally conservative for tradable market cap:

1. Use the latest valid Rally/current secondary quote when available.
2. Use latest valid historical secondary-market observation on or before the as-of date when it is within the staleness threshold.
3. Carry forward a prior observation only while it remains within the staleness threshold and flag it as carried forward.
4. Treat offering price as production context, not current tradable value, unless a methodology explicitly opts in.
5. Prefer missing current valuation over silently substituting stale, future-dated, or offering-only values.

The latest reconciliation artifact explains the previous homepage-vs-exchange discrepancy row by row. The legacy homepage counted 37 imported/manual listed rows with a summed decision-universe market cap near $1.57M. The Exchange Market Cap page displayed the latest reconstructed represented exchange-history value for 43 rows, approximately $28.8M, because it included stale carried-forward values and terminal/stale large fossil and handbag records. In the committed snapshot, the canonical current-tradable universe contains 28 assets and approximately $1.571M of tradable market cap as of 2026-07-01. The largest excluded represented-value rows are `rally-steg` and `rally-baro`, whose stale carried-forward fossil values account for most of the historical represented-value gap.

Reconciliation artifacts:

- `data/processed/current_universe_reconciliation.csv` — row-level inclusion, status, price, share, and reason-code audit for each asset in either legacy current source.
- `data/processed/current_market_cap_difference_contributors.csv` — ranked market-cap gap contributors.
- `data/processed/current_universe_summary.csv` — canonical current-tradable summary consumed by Streamlit.
- `data/processed/index_engine_reconciliation.csv` — side-by-side legacy quarterly Index Explorer prototype versus monthly exit-aware total-return engine on common dates.

Index methodology remains intentionally split between descriptive quarterly observed-row price-index prototypes and the newer exit-aware total-return portfolio engine. The reconciliation artifact documents that the legacy Index Explorer prototype is based on quarterly observation rows without imputation and dynamically changing observed constituents, whereas the total-return engine uses point-in-time eligibility, offering-price entry, scheduled rebalancing, carry-forward portfolio prices, explicit cash/pending-settlement handling, and exit awareness. The canonical app build now generates quarterly, monthly, and weekly total-return variants, with quarterly presented first as the default benchmark because authored Rally observations are quarterly-oriented. Production pages should avoid presenting legacy quarterly prototypes as the same economic quantity as the exit-aware “What $100 Became” total-return indexes unless the chart is explicitly labeled as a diagnostic/prototype comparison.

Data flow:

```text
Raw Rally Sources
    +
Manual Verified Records
    +
Historical Prices
    +
Exit Events
        ↓
Canonical Asset Identity
        ↓
Production / Fixture Classification
        ↓
Canonical Status as of Date
        ↓
Canonical Current Price
        ↓
Current Tradable Universe
        ↓
Shared Summary Metrics
        ↓
Homepage + Exchange Market Cap Page
```

## Canonical Market Data Cleanup (2026-07-19)

Rally market analytics now have an explicit canonical path for the migrated Home and Exchange Market Cap surfaces: `data/normalized/assets.csv` and `data/normalized/price_observations.csv` are the two principal authored CSV inputs, loaded through `alt_asset_explorer.canonical_market`. Current tradable universe, exchange market-cap history, category decomposition, exit-aware total-return indexes, and exit analytics are calculated deterministically in memory and cached by Streamlit through semantic loaders in `app/app_data.py`.

Large redundant generated CSVs including current-universe snapshots, exchange history snapshots, total-return portfolio/constituent histories, exit analytics, and index-engine reconciliation are no longer tracked as source-of-truth artifacts. They are ignored if generated locally. Legacy processed snapshots remain for pages that have not been migrated, but they are classified as derived/report artifacts rather than authoritative Rally market inputs.

The architecture inventory and directory policy are documented in `docs/DATA_ARCHITECTURE_INVENTORY.md`.


## Methodology Transparency Update (2026-07-19)

The app now labels the survivor-biased Index Explorer universe as **Current Survivors Only** rather than **Currently Trading Only**. This label is meant to communicate that current trading status is applied retroactively and should be read as a descriptive survivor diagnostic, not a point-in-time investable benchmark.

Total-return portfolio variants are generated for quarterly, monthly, and weekly scheduled rebalancing. Quarterly is the preferred default benchmark for the current dataset because normalized Rally price observations are quarterly-oriented. Offering prices remain investable entry prices for total-return methodology; exits still convert held units into cash or pending settlement and reinvest on the next scheduled rebalance.

## Universe Eligibility Architecture Update (2026-07-20)

Rally analytics now share `alt_asset_explorer.universe` for reusable source-data-driven eligibility and propagation diagnostics. The builder distinguishes canonical source presence, production eligibility, normalized status, active-tradable versus exit-aware scopes, price-history availability, market-cap-history availability, and dated entry eligibility. Index Explorer uses this layer for its Current Survivors Only and Include Exited Assets scopes, while its plotted `constituent_count` remains the actual number of assets with usable observations at each point in the calculation; the UI also surfaces the selected historical universe size so exited assets are visible without creating look-ahead-biased date counts.

Exit-aware total-return portfolios are now generated for both `include_exited` and `active_only` universe scopes, allowing the Home and Exchange Market Cap pages to compare survivor-only portfolios against lifecycle-aware simulations where exits realize proceeds and reinvest according to the selected rebalance methodology. The dataset build also emits `data/processed/asset_universe_diagnostics.csv` as a lightweight developer audit table showing each asset's category, normalized status, history rows, equal-weight eligibility, market-cap-weight eligibility, exit recognition, and named exclusion reason. This diagnostic is derived from canonical normalized assets and observations and is intended to prevent silent orphaning when new Rally assets or exited assets are entered.

## Custom Portfolio Engine And Simulator Update (2026-07-22)

Rally Terminal now includes a reusable custom-portfolio layer in `alt_asset_explorer.custom_portfolios`. `PortfolioDefinition` and `PortfolioMethodology` represent selected assets, equal/custom weighting, buy-and-hold/monthly/quarterly/annual rebalancing, survivor/exited universe policy, and centrally named entry, missing-price, exit, cash, and reinvestment assumptions. The homepage Portfolio Simulator uses this engine for custom portfolios and continues to use canonical exit-aware total-return artifacts for built-in full-market and category simulations.

The Custom Index Workshop remains a descriptive index-construction surface using common observed quarter-end dates without forward-filling. Custom Portfolio simulation is intentionally separate because it models investor capital, entry as assets become available, carry-forward prices between observations, cash after exits, and scheduled reinvestment/rebalancing. Both surfaces share basket-selection concepts and normalized growth/metric utilities where appropriate, but they are not presented as the same methodology.

The homepage Rally Market Table now places Last Price, 1Q Return, 1Y Return, and Full Return immediately after Ticker and Asset Name. Market-table row selection updates the canonical `asset_explorer_selected_asset_id` session-state value before Asset Price History renders, with a guarded rerun only when the selected asset changes, so the selector and chart reflect the clicked asset without a manual refresh or stale “on rerun” message.

## Modular Portfolio Components Update (2026-07-25)

The Portfolio Simulator now supports a multi-index Exposure Builder. Users can select any number of category index sleeves, assign explicit component weights, equal-weight all selected sleeves, or normalize positive allocations to 100%. The reusable `alt_asset_explorer.component_portfolios` engine consumes typed component series rather than underlying asset pools, so a 50% Books / 50% Watches portfolio preserves equal capital at the category-sleeve layer and is not misrepresented as an equal-weight pool of every underlying book and watch.

Component simulation uses common inception: the portfolio begins on the first valid observation date shared by all selected sleeves. It uses only subsequent dates shared by every sleeve and does not forward-fill missing component-level observations or treat a not-yet-available sleeve as cash. Existing canonical total-return indexes remain responsible for their internal point-in-time eligibility, equal- versus market-cap-weighting, exited-asset handling, and underlying price carry policy. The simulator's rebalance control separately returns top-level sleeves to their target allocations. Full-market and single custom-asset portfolio quick paths remain available; full-market, individual-asset, and custom-basket component adapters are a future extension of the typed component interface.

## Contribution Explorer Build 3 (2026-07-22)

The homepage now includes a first-class Contribution Explorer that reuses existing index, custom-index, and custom-portfolio simulation outputs rather than introducing a separate portfolio/index calculation path. The reusable attribution layer lives in `alt_asset_explorer.contribution` and wraps period-level index contributions from `indices.build_index_from_selection`, full-period compatible custom-index basket contributions from `custom_indices.build_custom_index`, and holdings-through-time output from `custom_portfolios.simulate_portfolio`.

Displayed contribution units are normalized index points for built-in and custom-index targets and normalized growth-of-$100 dollars for custom portfolios. The reconciliation convention is: starting value plus constituent contributions plus explicit cash/rebalance/entry-exit effects plus residual equals ending value within a documented numerical tolerance. Portfolio attribution uses actual simulated position-value changes and cash deltas from the Portfolio Engine; built-in observed-price index attribution retains the legacy descriptive quarterly methodology with no price imputation. The explorer also exposes concentration, breadth, deterministic summaries, a reconciling waterfall, cumulative contribution-over-time lines for additive series, full ranked tables, and drill-down into the shared Asset Price History selected-asset session state.

Known limitation: built-in Contribution Explorer targets currently analyze the descriptive quarterly observed-price index path, while the Portfolio Simulator's built-in comparisons read prebuilt exit-aware total-return artifacts. Build 4 Methodology Lab should make this distinction user-toggleable alongside weighting, rebalance schedule, survivor/exited universe, entry policy, exit treatment, cash/reinvestment, and missing-price treatment.

## Manual Books Price Coverage Update (KELLER, 2026-07-23)

The normalized Rally price observations now include manually transcribed chart coverage for existing Books asset `rally-keller` (`#KELLER`), Helen Keller's 1892 Book, Inscribed to Frances Cleveland. The history preserves actual observed Rally dates from the March 2022 offering reference value through the June 29, 2026 Q2 observation at $2.50 per share / $7,500 total value. Market caps are validated against the existing 3,000-share master record. The supplied July 8, 2026 post-quarter-end observation at $3.55 per share / $10,650 total value is retained in the normalized observation layer as a weekly/future-current research row and is intentionally not forced into Q2 2026. Under the current quarter-end convention, the June 29, 2026 observation is selected for the June 30, 2026 quarterly period because it is the nearest supplied observation to quarter-end. KELLER now has sufficient quarterly price and market-cap history to participate in the Books equal-weight and market-cap-weighted historical index prototypes where the methodology permits.

## Typed Portfolio Backtest Boundary (2026-07-26)

The Portfolio Construction Laboratory now passes a complete typed request into the component backtest engine, including the calendar, top-level rebalance schedule, inception/alignment, missing-observation, eligibility, exit/cash, risk-free-rate, as-of, and component settings. The engine returns a UI-ready, fingerprinted result containing portfolio and drawdown series, component composition, eligibility, rebalance and cash ledgers, diagnostics, methodology, and summary metrics. The Streamlit view renders this result contract rather than recomputing risk or methodology.

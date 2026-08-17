# Rally Leaderboards Lab Methodology

Rally Leaderboards Lab is a reproducible research archive, not a live Rally listing feed or appraisal. The persisted long-format archive is built with:

```bash
python scripts/build_quarterly_leaderboards.py --full-refresh
```

## Source and frequency

The canonical asset inputs are `data/normalized/assets.csv` and `data/normalized/price_observations.csv`. The current observation table is mixed but overwhelmingly authored quarterly evidence; actual `observed_at` timestamps are preserved. Weekly and unclassified rows are not overwritten. Existing committed equal-weight, market-cap-weighted, and full-market quarterly index prototypes are reused from `data/processed/rally_quarterly_indices.csv`; public benchmarks are read from Benchmark Lab's committed local history. Runtime page requests never fetch benchmark data. The standard rebuild writes the large leaderboard archive only to ignored `data/cache/`; when that local cache is absent, the Streamlit process reconstructs the same archive from committed canonical inputs. The page's in-memory cache key fingerprints all four inputs, and a persisted local archive is accepted only when its stored source fingerprint matches. Changing assets, observations, quarterly indices, or benchmark history therefore invalidates both cache layers automatically.

The Individual Rally Asset subject universe is discovered by joining every asset
with authored observations in those two canonical tables. There is no category
allowlist or separately curated subject registry: category labels are carried
through exactly as normalized at ingestion, so a newly ingested category flows
into the next standard rebuild automatically.

## Point-in-time snapshots

Snapshots occur at March 31, June 30, September 30, and December 31. At snapshot `T`, source series are truncated at actual source date `<= T`. A quarterly as-of series selects the latest known value on or before each quarter-end. Values more than 186 days old are unavailable by default. No later observation is moved backward into a prior snapshot. Metrics use only the truncated quarterly series.

For an individual asset, since-inception total return is the simple price return
from its first eligible authored value through the latest eligible as-of value.
An authored offering-price observation can therefore establish inception. This
matches the Rally Market Table's full-return price ratio when both surfaces have
the same first and latest canonical values; neither calculation includes cash
distributions or claims to be an investor total-return portfolio simulation.

Historical Rally tradability/status history is not available. Individual eligibility is therefore inferred from price inception, metric history, metric validity, and staleness; current known status is stored separately and must not be interpreted as historical status. Existing index prototypes use their committed artifact dates and retain their research-prototype label. Historical market capitalization is estimated as the latest as-of price times available canonical share count; the repository does not contain a point-in-time share-count history.

## Eligibility and metrics

Every subject/quarter/metric combination is retained, including exclusions. Reasons include not yet launched, insufficient observations, insufficient trailing history, stale observations, and invalid metric values. Returns are quarterly as-of returns. Arithmetic mean and sample volatility use `4` and `sqrt(4)` annualization respectively; CAGR uses elapsed calendar time. Sharpe, Sortino, drawdown, and Calmar reuse the shared frequency-aware portfolio analytics implementation after constructing the point-in-time quarterly series.

## Ranking

Higher-is-better metrics sort descending and lower-is-better metrics sort ascending. Ties use ascending stable `subject_id` as an explicit secondary key, producing deterministic ordinal ranks. File order never breaks ties. The best subject's percentile is 100% and the worst subject's is 0%, using `(N - rank) / (N - 1)`. A one-subject universe is assigned 100%.

Rank movement exists only when a subject is eligible at both endpoints. Newly eligible and newly ineligible subjects are categorical entries/dropouts, not artificially ranked below the universe. Rank-history data contains null ranks in ineligible intervals so charts render gaps rather than interpolation.

## Revision and coverage warning

Historical rankings reflect the assets currently cataloged in Rare Tape, not necessarily the complete contemporaneous Rally catalog. Adding newly researched historical assets can revise old rankings. `generated_at`, methodology version, and a source-file fingerprint distinguish rebuilds. The archive is reproducible for that source version, but its historical values may change as manual catalog coverage expands.

## Refresh contract and prevention

The earlier refresh gap was cache invalidation rather than subject discovery: the leaderboard page cached a zero-argument loader for the life of the Streamlit process, and the loader trusted any existing ignored archive without comparing it to current canonical inputs. Other modules read their regenerated artifacts directly, which is why they reflected new Comics observations while Leaderboards could retain its older subject set. The source fingerprint is now an explicit loader validation and Streamlit cache argument. A canonical input change forces an in-memory rebuild even if an old local archive remains.

To prevent regression, the standard dataset/manual-ingestion orchestrator remains the supported refresh path; it builds processed inputs before coverage and leaderboards. Integration tests assert that newly added canonical categories require no registry edit and that the five authored Comics histories appear in the latest individual-asset leaderboard. Cache tests also assert that an archive with an older source fingerprint is rejected and rebuilt.

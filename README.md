# Rare Tape

Rare Tape is a standalone research dashboard for fractionalized collectible assets. The current milestone focuses on Rally seed assets, manual comparable sales, NAV estimates, liquidity metrics, deterministic AI context, and an MME-compatible export.

This software is for research only. Rally shares are securities backed by collectible entities, not direct ownership of physical items. Liquidity may be thin or periodic, comparable sales may be imperfect, and stale marks can materially distort returns.

## Quickstart

```bash
python scripts/build_dataset.py
streamlit run app/Home.py
python scripts/write_report.py --date today
```

Outputs are written to `data/processed/`, `reports/`, and `data/processed/universe_export.csv`.

## Custom Index Workshop

The Home dashboard now includes a **Custom Index Workshop** mode inside Asset
Price History. Build an equal- or custom-weight basket, inspect its normalized
history, metrics, and contribution analysis, then save it locally and reopen it
in Index Explorer beside built-in indexes. Custom definitions can also be
exported as JSON.

See [`docs/CUSTOM_INDEX_WORKSHOP.md`](docs/CUSTOM_INDEX_WORKSHOP.md) for the
calculation policy, schema, local/curated storage layout, Streamlit Cloud
limitations, and the path to a durable shared backend.

Run the complete deterministic test suite with:

```bash
pytest -q
```

## Current Data Status

The app currently uses manual Rally seed files plus normalized comparable-sale seeds. The valuation scatter compares Rally market cap with weighted secondary-market NAV estimates, but live Rally trading data and most category connectors still need to be added.

See `docs/source_strategy.md` for the recommended build order for reliable Rally data, SEC ingestion, category-specific secondary-market connectors, and dashboard coverage checks.

## Real Data Imports

Fetch public SEC/Rally filing data:

```bash
SEC_USER_AGENT="RareTape/0.1 your-email@example.com" python3 scripts/fetch_sec_data.py --max-filings 40
python3 scripts/build_dataset.py
```

For Rally trading snapshots and secondary comps, copy permitted CSV exports into `data/raw/imports/` using the template files there, then rebuild the dataset.

Secondary import files are source-specific. Auction houses normalize into comparable sales; Chrono24 market/index rows normalize into `data/processed/market_context.csv`.

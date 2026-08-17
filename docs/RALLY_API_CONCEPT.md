# Rally API Concept

This document describes the data Rare Tape would benefit from if Rally ever offered an official API or partner data feed. It is not an attempt to build an API on Rally's behalf.

## Why An Official API Matters

The current project can use SEC filings, manual seeds, user-provided CSVs, visible portfolio captures, and manually reviewed auction comps. That is enough for a research prototype, but it is not enough for a professional market terminal.

An official Rally API would improve:

- Asset identity stability.
- Current quotes and trading status.
- Historical trades and order-book depth.
- Intraday market data.
- Corporate actions, exits, halts, and offering updates.
- Data freshness and auditability.
- Institutional confidence in analytics derived from Rally data.

## Current Data The Terminal Needs

- Asset IDs and tickers.
- Asset names and descriptions.
- Categories and subcategories.
- Share counts.
- Offering price and offering valuation.
- Offering circular and SEC filing links.
- Last traded price.
- Best bid and best ask.
- Spread.
- Volume.
- Market capitalization.
- Trading status.
- Trade history.
- Order book or indicative market depth.
- Corporate actions and exits.
- Data timestamps.
- Source or revision metadata.

## Data That Is Currently Difficult To Collect Reliably

- Complete official Rally asset universe.
- Stable official Rally asset IDs.
- Live bid and ask.
- Intraday quotes.
- Trade-level history.
- Order-book depth.
- Suspensions and trading-window state.
- Official delisting/exit status.
- Updated share counts after corporate actions.
- Full historical constituent membership for index calculations.

## Suggested Endpoints

- `GET /assets`
- `GET /assets/{asset_id}`
- `GET /assets/{asset_id}/quotes`
- `GET /assets/{asset_id}/trades`
- `GET /assets/{asset_id}/order-book`
- `GET /assets/{asset_id}/filings`
- `GET /assets/{asset_id}/offering`
- `GET /categories`
- `GET /indices`
- `GET /market-summary`

## Suggested Schemas

### Asset

- `asset_id`
- `ticker`
- `name`
- `description`
- `category`
- `subcategory`
- `status`
- `share_count`
- `offering_price`
- `offering_valuation`
- `offering_date`
- `rally_url`
- `sec_filing_urls`
- `created_at`
- `updated_at`

### Quote Snapshot

- `asset_id`
- `observed_at`
- `last_price`
- `best_bid`
- `best_ask`
- `volume`
- `market_cap`
- `trading_status`
- `source`
- `collection_status`

### Trade

- `trade_id`
- `asset_id`
- `executed_at`
- `price`
- `quantity`
- `notional_value`
- `market_session_id`
- `correction_status`

### Order Book

- `asset_id`
- `observed_at`
- `bids`
- `asks`
- `depth_level`
- `trading_status`

### Offering

- `asset_id`
- `series_name`
- `offering_price`
- `shares_offered`
- `gross_offering_value`
- `acquisition_cost`
- `offering_expenses`
- `offering_circular_url`
- `sec_accession_number`
- `effective_date`

### Filing

- `asset_id`
- `cik`
- `accession_number`
- `form_type`
- `filing_date`
- `filing_url`
- `series_name`
- `parsed_fields`

## Authentication

Possible tiers:

- Public API key for delayed asset metadata and end-of-day data.
- Partner API key for current quotes, richer history, and higher limits.
- Institutional tier for order-book depth, trade history, bulk snapshots, and webhooks.

All requests should be over HTTPS and include usage attribution through API keys or OAuth client credentials.

## Rate Limits

Suggested starting point:

- Public metadata: 60 requests per minute.
- Public end-of-day data: 30 requests per minute.
- Partner quote data: 300 requests per minute.
- Bulk export endpoints: asynchronous jobs with daily quotas.
- Webhooks for quote/status changes where polling would be inefficient.

Rate-limit headers should expose remaining quota and reset time.

## Premium Data Tiers

- Real-time quotes.
- Historical trade tape.
- Order-book depth.
- Bulk historical quote snapshots.
- Corporate-action feed.
- Research-grade asset metadata.
- Webhooks for listings, trading windows, halts, and exits.

## Developer And Institutional Use Cases

- Third-party research terminals.
- Personal portfolio analytics.
- Index products.
- Valuation and comparable-sales research.
- Liquidity monitoring.
- Automated market reports.
- Academic research on fractional alternative assets.
- Institutional due diligence tools.

## Partnership Pitch

Rare Tape can demonstrate demand for a reliable Rally data layer by showing:

- How many fields are currently unavailable or stale without official data.
- Which analytics become possible with reliable quotes and trade history.
- How official identity and timestamping reduce misinformation risk.
- How better data can deepen liquidity, research coverage, and issuer trust.

The goal is to create an analytics product that expands the Rally ecosystem without bypassing access controls or creating brittle scraping dependencies.

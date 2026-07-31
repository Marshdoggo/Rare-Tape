# Data Dictionary

## Canonical Asset Registry

`data/normalized/assets.csv` contains exactly one authoritative row per `asset_id` and ticker. `status` is the broad lifecycle (`trading`, `buyout_pending`, `exit_pending`, or `exited`); `trading_state` is `active`, `halted`, or `inactive`; and `lifecycle_event_type` / `lifecycle_event_status` describe the current normalized event. `lifecycle_event_date` and `status_updated_at` retain event timing without manufacturing dates that are not known.

Pending-offer fields are `buyout_offer_date`, `buyout_offer_price_per_share`, `buyout_offer_total_value`, `buyout_reference_price`, `buyout_reference_price_date`, `buyout_premium_pct`, provisional vote percentages and their `buyout_vote_as_of`, `buyout_vote_provisional`, and `buyout_notes`. These are lifecycle metadata, never executed price observations. Existing `exit_date`, `exit_price_per_share`, `exit_value_total`, and `exit_type` remain the compatibility contract for completed legacy exits and must be null for pending offers.

## Normalized Comparable Sales

`comp_id, category, subcategory, asset_id, source, source_url, date, price_usd, currency, condition, exactness_score, source_confidence, notes`

- `exactness_score`: 0-1 estimate of match quality by model, year, condition, provenance, size, grade, rarity, and other category factors.
- `source_confidence`: 0-1 confidence in source reliability and reproducibility.
- `price_usd`: normalized USD price. Currency conversion hooks are intentionally deferred.

## MME Export

`date,ticker,name,universe,category,price,return_1d,return_7d,return_30d,volatility,sharpe,sortino,max_drawdown,source_quality`

`universe` is always `collectibles` for this standalone export boundary.

## Caveats

Scores are research features only. Rally interests are securities backed by collectible entities, not direct ownership of the physical item. Thin liquidity, stale marks, offering expenses, sourcing spreads, and imperfect comps can materially affect observed returns.

# Exit-Aware Total-Return Methodology

Rare Tape separates two questions:

1. **Tradable Exchange Market Cap** asks how much represented asset value remains active and tradable on Rally. Exited assets leave this series on the effective removal date.
2. **Total-Return Investment Indexes** ask what an investor's money became under a rules-based index. Realized exit proceeds do not disappear; they become pending settlement or cash and are reinvested at scheduled rebalances.

## Exit event model

Normalized exit events are written to `data/processed/rally_exit_events.csv`. The schema supports asset and ticker linkage, event type, event status, announcement date, last trading date, valuation date, effective date, settlement date, per-share payout, total payout, shares at exit, source references, confirmation status, and data-quality flags.

Statuses are centralized in code and include `active`, `exit_announced`, `pending_approval`, `pending_settlement`, `settled`, `exited`, `cancelled_exit`, and `unknown`. Exit types include buyouts, asset sales, redemptions, liquidations, delistings, issuer repurchases, auction/private sales, and other events.

## Terminal value hierarchy

Terminal price is selected in this order:

1. Confirmed actual per-share investor payout.
2. Confirmed total investor payout divided by valid shares outstanding.
3. Confirmed shareholder-attributable sale/acquisition value when represented in the normalized total payout field.
4. Official terminal valuation when represented in the normalized payout fields.
5. Last valid secondary-market price.
6. Manual terminal estimate, if supplied by future manual workflows and flagged.

Cancelled exits never create realized proceeds. Fallback to last trade is explicitly flagged as `terminal_price_fallback_last_trade`.

## Event-date treatment

Before announcement, assets are treated normally. Announced exits remain tradable if trading is still open and use observed trading prices. On the effective exit/removal date, an asset leaves tradable market cap. In total-return portfolios, the position converts to pending settlement value when the record is pending settlement, then to cash on settlement. Settled/exited records convert directly to cash at the terminal price.

When only one historical exit date is known, the normalizer uses that date for announcement, last-trading, valuation, effective, and settlement dates and surfaces data-quality limitations through the normalized exit fields.

## Index methodology

Both total-return indexes start at 100. The default reinvestment policy is `scheduled_rebalance`; exit proceeds sit in non-interest-bearing cash until the next scheduled rebalance. The implemented and documented default frequency is monthly, with weekly and quarterly supported by the calculation engine.

- **Equal-weighted total return:** at each rebalance, all active eligible constituents receive equal target allocations. Between rebalances, weights drift with asset returns.
- **Market-cap-weighted total return:** at each rebalance, target weights are based on eligible constituent market capitalization at the rebalance date. This is portfolio accounting, not aggregate exchange market-cap growth.
- **New listings:** assets become eligible on their offering/listing date and enter the index at the next scheduled rebalance. Future prices are never used.
- **Zero constituents:** the portfolio remains in cash, preserving index continuity, and resumes investment at the next rebalance with eligible assets.
- **Categories:** each canonical category is calculated independently. Category cash never migrates to other categories.

## Illustrative example

Two assets begin at $50 each. Asset A rises to $100 and exits. Asset B remains worth $50. The investor portfolio is worth $150, so the total-return index rises from 100 to 150. After Asset A leaves, tradable exchange market cap falls from $150 to $50 because only Asset B remains listed. The investor gained 50%, while tradable exchange size fell 66.7%. Both figures are correct because they answer different questions.

## Derived artifacts

- `rally_exit_events.csv`: normalized exit-event table with terminal-value fields.
- `index_portfolio_history.csv`: portfolio-level index, cash, pending settlement, constituent counts, returns, and drawdowns.
- `index_constituent_history.csv`: asset-level units, values, prices, weights, and status audit trail.
- `exit_analytics.csv`: realized exit proceeds, returns versus offering, holding periods, annualized returns, and premiums/discounts versus last trade.

## Data-quality limitations

SEC-derived exit rows are often not canonically linked to Rally asset IDs. The normalizer attempts ticker/series matching but does not pretend unmatched SEC series are live Rally listings. Incomplete exit records remain visible; they are not hidden.

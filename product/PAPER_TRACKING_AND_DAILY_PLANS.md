# Paper Results and Daily Trade Plans

October 17, 2026: David authorized paper tracking repairs and daily suggestions with
stops. Morning paper automation remains permitted; daily plans never submit orders.

## Accounting Contract

- Persist intent before submission with a stable client order ID and paper account
  binding. Repeated approvals do not resubmit. Unknown outcomes stay unresolved
  until broker lookup confirms them; no blind retry.
- Capture original setup, direction, score, full signal and `morning-v1` strategy
  version. Keep intended prices separate from actual average fills.
- Reconcile cumulative entry, nested stop/target and app-close fills, deduplicated
  by order ID. Partial quantities remain open. Unfilled canceled/rejected/expired
  orders are not wins, losses or completed trades.
- Manual close cancels owned orders, awaits confirmation, then submits remaining
  attributed quantity. Submission is not realized P&L. A lock plus stable close ID
  prevents duplicate concurrent closes in the single supported application process.
- Verified closed results require matched fill quantities, terminal owned orders
  and exit timestamps. P&L is gross of fees, not net account returns. R divides
  gross P&L by original planned risk/share times filled quantity.
- Group results by setup, direction and version; show sample sizes. Under 30 closed
  trades gets a small-sample label. Thirty is not a statistical significance claim.
- Startup restores journal and Eastern-date risk counters. Open partially realized
  losses conservatively count toward the loss limit until closure; this is not
  per-fill daily tax/accounting attribution.
- External position changes, replaced orders, unknown orders or account changes
  remain unresolved and block new entries. Never infer exits from a quote or from
  a position disappearing.

## Persistence

Supabase uses the existing `settings(key,value,updated_at)` JSONB table for full
`paper.trade.<id>` and `paper.signal.<id>` records. Startup reads are paginated and
journal write failures block new submissions. Legacy rows are retained but their
estimated P&L is excluded. Legacy open records without order IDs are quarantined
as UNATTRIBUTED, not marked closed or profitable. They remain visible and cannot
authorize closes. Broker positions outside the journal are shown separately for
management in Alpaca. Every new entry checks actual broker positions/open orders
before taking ownership of a symbol.

Without Supabase, SQLite uses `STATE_DB_PATH` (default `data/paper.sqlite3`). Local
restarts retain it. On Railway the path MUST be under `RAILWAY_VOLUME_MOUNT_PATH`,
otherwise new entries are blocked with a visible warning. Never silently treat
ephemeral storage as durable. Run one worker/replica. No paid volume or service is
provisioned automatically; cross-process coordination is not implemented.

Reconciliation runs about every 60 seconds. Partially filled regular brackets and
extended-hours positions may lack active stops; protection warnings disclose this.
Terminal extended entries get OCO exits for remaining filled shares during regular
hours. Failed/canceled manual closes are not automatically replaced. Inspect Alpaca
paper orders when warnings persist.

## Daily Plan v1

The full history, not the selected 1Y-5Y display range, determines the plan. It uses
the score's trigger/anchor, not a user-selected display-only AVWAP anchor.

- Requires eligible held signal, score >=50 and valid ATR(14).
- Long entry beyond latest daily high/trigger plus 0.1 ATR; short is mirrored.
- Stop beyond the five-session low/high by 0.25 ATR, at least one ATR from entry.
- 2R target is a planning objective, not a forecast. Prices round outward to ticks.
- Wait for earnings within two calendar days, nearby prior 60-session structure
  leaving under 1.5R, stop distance over 8%, or price over 3 ATR from SMA 20.
- No plan for invalid inputs or history older than three calendar days. This
  conservative check is not a full exchange-calendar freshness fix.
- Recalculate after the next completed bar. Skip gaps over 0.25 ATR beyond entry.
  Unknown earnings, borrow, live liquidity and gap risk remain explicit. Daily
  plans add no sizing or automatic execution.

These versioned constants are unvalidated hypotheses, not optimized claims. ATR
supports volatility-aware stops but does not establish a universally best stop.
Sources: [Fidelity ATR](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr),
[Fidelity execution risk](https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Transcript_Entry-and-exit-points_v2.pdf),
[Alpaca order lifecycle](https://docs.alpaca.markets/us/docs/orders-at-alpaca),
[Alpaca Python order API](https://alpaca.markets/sdks/python/api_reference/trading/orders.html).

## Validation and Limits

189 Python tests, seven JavaScript tests and both fixture-backed browser suites
passed. Coverage includes fill arithmetic, partial fills, cancellation races,
duplicate closes, restart recovery, broker outages, chart pixels, plan levels and
desktop/mobile daily layouts. No broker test order was submitted.

Still open: market-session evidence, fees/activity ledger, cross-process locking,
full partial-fill/extended-hours protection, external-action remediation, private
access/authentication and out-of-sample strategy evaluation. Old estimates cannot
prove which setups work.

## Deployment Evidence

Railway deployment e1d1d44 succeeded. Production verified paper transport and
Supabase journal recovery with no storage error. It recovered three June records
(SPCE, AVXX, ASTX) with no order IDs. Those cannot supply attributable historical
P&L; they prompted the explicit UNATTRIBUTED migration above. No open broker orders
were reported. No synthetic trades were written into production statistics.

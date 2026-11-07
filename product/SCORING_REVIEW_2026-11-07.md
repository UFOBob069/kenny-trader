# Which charts deserve five minutes?

Product review, 2026-11-07. Scope: production Daily Technicals and its v5 scoring, plus the morning scanner's readiness score. Recommendations only. Daily is research-only; morning paper experiments are a separate strategy.

## What the current top ten actually mean

Read-only production check on Saturday using Friday, November 6 bars: resolved the Nasdaq-100 membership endpoint, scanned all members in batches of 25, applied the default held-signal and minimum-50 filters, sorted by setup score, and opened the ten leading chart plans. This measures the review experience on one session, not trading performance.

| Membership | Chart scores available | Held setups scoring at least 50 | Top ten with conditional plans | Top ten marked Wait |
| ---: | ---: | ---: | ---: | ---: |
| 101 | 99 | 24 | 0 | 10 |

KDP ranked first at 71; its plan found less than 1.5 times initial risk in room before a prior high/low. Across the ten, seven cited limited room and six cited a stop over 8% away (reasons overlap). In a separate ten-symbol spot check, MSFT's chart leaned bullish at 27.7 while its held AVWAP-loss setup scored 27.4 bearish. It would not clear the default 50 filter. The two numbers answer different questions; neither is a probability.

## Decisions recommended, in order

1. **Make review priority reflect the research decision.** Separate *Conditional plan*, *Wait*, and *Data incomplete*. Default to new or materially changed conditional plans, strongest setup first within that group. Keep Wait setups available with the blocker and the condition worth revisiting. Never fill ten slots by silently promoting blocked ideas. Reuse the chart's plan evaluator for list, chart and alerts at the same timestamp; a technical-cross alert should still be possible, but clearly distinct from a plan becoming conditional. Do not loosen plan gates just to populate the screen. Specifically test whether treating every prior high/low as an obstacle is too sensitive before changing that rule.
2. **Freeze the weights and measure whether ranking helps.** Log point-in-time daily candidates, including lower-ranked controls, feed, bar status, direction, model, trigger, component points, plan and blocker. Deduplicate repeated days of the same held event. Compare the top group to the eligible pool and a trigger-plus-volume baseline on the same dates/directions. Primary measure: signed, benchmark-relative five-session return after signal availability; secondary: 20 sessions and adverse excursion. Evaluate plans separately using next executable entry, unfilled entries, costs and gaps. Keep morning paper P&L separate. Report sample size, missing outcomes and uncertainty; use later dates as holdout. No rank improvement claims on a single day or on immature outcomes.
3. **Give each chart one headline.** Lead with setup direction and status; label the broader chart *bullish*, *bearish* or *mixed* instead of competing for attention with another decimal score. Show the held trigger and its age, strongest positive driver, biggest blocker, and the level that changes the conclusion. Keep the full bullish/bearish breakdown one action away, including in guided review. Use daily candles, 20/50/200 SMAs, anchored VWAP and earnings by default. Reveal bands, squeeze, ATR and Elliott details on demand or when they explain the setup. Keep the user's preferred study settings.
4. **Separate incomplete evidence from weak evidence.** An unknown earnings date gets no deduction while a known event within seven days costs ten points. Show verified date, unknown, and not applicable (funds) distinctly; do not imply unknown means safe. Today's partial volume is compared with prior full days: label volume pending or compare against historical same-time volume. Use the last expected trading session for freshness: Saturday's Friday close is current, not a missing Saturday bar. Label closed and forming bars separately. Keep stock-specific missing inputs visible without turning them into a statistical confidence percentage.
5. **Answer the liquidity question explicitly.** Daily turnover is a historical screen, not evidence of fillability at a given size. Label it as feed-specific; the production sample used IEX (a single exchange, per [Alpaca](https://docs.alpaca.markets/us/docs/market-data-faq)). For an active session, show observed spread, quote age and size where available; otherwise say "execution liquidity unverified." No new minimum share price or paid feed is required for honest labeling. On the morning scanner, gap and relative-volume progress both cap at the qualification threshold. A qualified earnings/mover earns 100 regardless of how far it exceeds the checks. Rename that number *checks passed*, or show the checks; compare setup quality separately in paper outcomes rather than changing the minimums.

## The proposed five-minute workflow

Open the last completed universe scan immediately, with its session, timestamp and coverage. Refresh in the background and show partial coverage explicitly; don't reshuffle a review already in progress. For example: "Nasdaq-100: 99/101 scored; 24 held setups above threshold." Give verified zero results, missing data and a refresh in progress different states.

One chart, one decision: **Save, Pass, Next**. A useful headline for the observed AMZN example would be: **Bullish AVWAP reclaim | Wait: stop 9.4% away; nearby resistance leaves only 0.01R.** Show stop/invalidation and the next earnings status on the chart. Define R once as the distance from entry to stop. Distinguish new triggers, previously reviewed holds, and meaningful status changes. Preserve access to any ticker and the 1-5 year chart alongside the queue.

## Next 30 days and release checks

| Order | Deliverable | Acceptance |
| --- | --- | --- |
| Week 1 | Shared status definitions and daily outcome snapshots before scoring changes | Same symbol, session and model give the same setup and plan status across list and chart; unknown/stale inputs cannot appear verified. Capture controls and missing rows. |
| Week 2 | Separate conditional and wait queues; concise decision view; cached scan coverage | No Wait item represented as conditional. In five observed sessions, review up to ten charts in ten minutes or less and identify the trigger and blocker without opening the full breakdown. Measure time to first useful chart. |
| Week 3 | Session-aware volume/freshness, earnings coverage and morning readiness labels | Opening-hour partial bars do not earn a misleading full-day volume comparison; weekend/holiday, ETF, missing-date and stale-quote examples each have an explicit state. |
| Week 4 | First outcome report and component comparison | Publish counts by direction, trigger and score band. Compare with the simple baseline and with Elliott removed while holding other weights fixed. Mark immature horizons as pending; retain v5 unless later evidence supports a change. |

Not recommended now: more indicators, more frequent Elliott labels, a new weight table based on intuition, or a percentage "chance of winning." Keep selectable studies, existing research-only daily plans and paper-only morning boundaries.

Evidence locations: `app/engine/technicals.py` (inputs and two score selections), `app/engine/trade_plan.py` (plan blockers), `app/web/technicals.js` (filter, queue, review and summary), `app/engine/scoring.py` (morning readiness), and [the measurement plan](METRICS.md). No live market-hours timing study, user-timed usability test or return backtest was performed in this review.

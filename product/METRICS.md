# Metrics and Discovery Plan

Date: 2026-10-17. Personal-use research/alerts pilot. No analytics code was added
in this audit. Proposed targets must not be confused with observed baselines.

## What We Actually Know

| Evidence | Baseline | Interpretation |
| --- | --- | --- |
| David's feedback | Slow, weak setups, low motivation to open the app | Strong problem signal, not a quantified failure rate |
| Live morning scanner | Paused on Russell-membership data, zero active detectors | Availability failure; closed-market sample cannot measure detection latency |
| Live daily scan | 62 symbols, 6.494s, 24 eligible rows at >=50 | One observation, not p95 or all-market coverage |
| Warm AAPL 5Y response | 286ms and 250ms after scanning | Warm API latency, not browser paint or cold-provider latency |
| Live browser first chart | 4.617s | One run with warmed server; full browser path |
| Daily review | Live pass-to-next worked | Functionality, not proven completion time or usefulness |
| AAPL 5Y earnings | 1 scheduled, 0 historical, available status | Coverage problem despite HTTP success |
| Trade/signal counters | Zero after deployment | Process-local, not reliable lifetime adoption or performance |
| Usage analytics | None found | Active days, retention and review completion unknown, not zero |

## Morning Research Scorecard

1. **Availability:** healthy sampling intervals / expected sampling intervals within
   the agreed morning window. Record provider, entitlement and app failures separately;
   market holidays are excluded using the exchange calendar. Healthy with no setup
   is different from empty because data failed. Target: no unexplained outage in
   five observed morning sessions; set an uptime target after a reliable baseline.
2. **Fresh-signal latency:** provider arrival, detector, API and browser times,
   measured against the trigger candle's close. Report p50/p95 and missing samples.
   Proposed initial target: p95 <=30 seconds from data receipt to visible research
   alert; never show an actionable alert beyond the configured 90-second freshness
   limit. Provider lag is reported separately, not hidden by that internal target.
3. **Setup precision:** labeled valid emitted setups / all labeled emitted setups.
   **Recall:** emitted valid setups / all valid setups identified in the replay set.
   Report both, with counts and uncertainty; a filter that emits nothing cannot
   win on precision alone. Use a blind frozen sample and explicit pattern criteria.
4. **Useful session:** David can identify why a setup is interesting or why nothing
   qualifies, without troubleshooting. Record a binary rating and one short reason.
   Target: 4 of 5 observed sessions useful. No trade is required.

## Daily Review Scorecard

| Metric | Definition | Proposed gate |
| --- | --- | --- |
| Review completion | Every symbol in frozen review queue receives reviewed/saved/passed in that session | 4/5 observed top-10 sessions complete |
| Review time | Monotonic elapsed time from start to final decision, including waits; report pauses separately | 4/5 top-10 reviews <=10 minutes |
| Usefulness | Explicit post-review useful/not useful rating, even if all charts passed | 4/5 useful |
| Fresh coverage | Symbols with required history through expected session / declared requested symbols | >=95%; every exception visible |
| Earnings coverage | Historical and upcoming coverage evaluated separately; unknown dates/times counted | No false complete-coverage claim; audited reference sample reported |
| Chart flip | Navigation action to usable candles plus essential context | Warm p95 <=1 second over >=30 requests |
| First useful chart | Page navigation to chart and current risk/freshness context | Warm p95 <=5 seconds over >=30 requests |
| Scan time | Request to complete ranked response, with universe/feed/cache-state tags | 62-symbol healthy-provider p95 <=15 seconds |
| Ranking usefulness | Blind labels on top-10 versus predefined baselines | Baseline first; improvement target after labels, no invented percentage |

Empty qualified queues are recorded separately, not silently removed from failure
analysis and not padded. When fewer than 10 qualify, report queue size and avoid
comparing that session directly with a full top-10 review. A saved pick is interest,
not a recommendation, trade, fill, win or source of revenue.

## Minimal Instrumentation Specification

Proposed events: scan_started, scan_completed, scan_failed, chart_requested,
chart_ready, chart_failed, review_started, chart_decision, review_completed,
review_feedback, signal_detected, signal_visible, signal_expired, provider_degraded.

Common fields: UTC timestamp, opaque session/request ID, event-schema version,
environment (production/test/audit), model version, feed, expected session, data
as-of, universe identifier/count, duration, cache state, outcome/error category.
Review fields: queue ID/count, ordinal, decision, direction and score version.
Signal timing must preserve bar-close and provider-receipt time independently.

Do not log API keys, token-bearing URLs, broker account IDs, balances, order payloads
or personal notes by default. If ticker-level snapshots are needed for evaluation,
keep them in the owner's private data store, not this public repository. Exclude
our audit and fixture traffic from adoption metrics. Persist events only after
agreeing collection scope; for this personal pilot propose 30-day diagnostics
retention with deletion capability. localStorage alone cannot measure cross-device
continuity or survive browser-data clearing.

## Discovery Experiments

### E1: Why are morning setups weak?

Hypotheses: missing universe coverage, delayed inputs, incorrect pattern semantics,
insufficient liquidity, or ranking misalignment. Capture at least 30 candidate
windows from five or more sessions, including no-setup controls. Ask David to label
a small initial sample (10-15 minutes), then use the agreed rubric on the rest.
Hide model scores during labeling. Separate technical correctness from subjective
interest and subsequent price movement. Compare to the current engine before tuning.

Pass condition: identify the dominant failure class with traceable examples and a
testable fix. A negative result or insufficient sample is an acceptable finding.

### E2: Does the daily queue save attention?

Observe five top-10 reviews using current daily-v2. Record load delays, confusion,
save/pass reasons, completion and usefulness. Compare a fixed subset presented
with sparse versus existing annotations without changing the scoring model.
Do not infer ranking quality from which visual style users prefer.

### E3: Do ranking and AVWAP add value?

Create immutable point-in-time snapshots with universe/feed/model and anchor
confirmation dates. Compare daily-v2 with price/200-only and unranked qualified
baselines. Analyze bullish and bearish sets separately and account for market
regime. Do not let current snapshot anchor selection rewrite historical decisions.

For later outcome evaluation, predefine 1/5/20-session horizons, executable entry
assumptions, adverse/favorable excursion, spread/slippage/fees and benchmark excess
return. Include delisted/renamed securities where available and disclose survivorship
bias otherwise. Record missing prices and uncertain earnings rather than dropping
losers. Freeze weights and holdout first; collect longer if outcome samples are
immature. This is research design, not an implementation or a profitability claim.

## Evidence Review

During authorized work, update this scorecard weekly with numerator/denominator,
date window, data quality and examples. Compare against the same definition and
model version. Publish a concise decision: keep, change, stop or collect more.
No experiment should require David to invent the next feature; Codex proposes the
next bounded action from the evidence and escalates only material trade-offs.

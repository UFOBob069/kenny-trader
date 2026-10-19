# Product Strategy

Version: 2026-10-17. Status: personal audience and paper-only experiments authorized;
sequencing and numerical success targets remain subject to evidence.

**Implementation update:** David authorized starting the roadmap and automated
paper trading for tests (D015). The research-only authority statements in this
original strategy now apply to daily research and optional research mode; the
morning tool may run paper experiments behind a verified paper-only transport.
Live execution is prohibited. Paper fill reconciliation moves ahead of any use
of simulated P&L as evidence; no broader automation platform is planned.

## Problem and audience

David reports that the morning product feels slow, chooses weak setups, and has
not earned habitual use. He values actual tradable liquidity rather than a $5
stock-price floor. His newer workflow is daily candlestick review over 1-5 years,
20/50/200 SMAs, breakouts/breakdowns, anchored VWAP, earnings context, and a ranked
queue that takes 5-10 minutes to inspect. These are direct user statements,
not inferred analytics or proof of trading performance.

Confirmed audience: David, for personal trading research. Optimize for
desktop chart inspection, with a usable phone review flow. Do not build a social
network, subscription business, or generalized broker platform before this job
works reliably for the owner.

## Product promise

"Give me a short, explainable list of charts worth my attention, with clear data
freshness, event risk, and liquidity context, so I can decide quickly what to
watch or reject."

Success is informed selection, including deciding that no setup deserves a trade.
Do not promise profitable signals, a minimum number of opportunities every day,
or that a high score is a probability of success.

## Core jobs

1. During the morning session, distinguish a fresh, qualified VWAP setup from
   missing data, a stale signal, or an unavailable scanner. This is the primary
   improvement track for the next 30 days.
2. Before the next session, review a top-10 queue, understand why each chart ranks,
   save a few candidates or pass all of them, and finish within ten minutes.
3. Inspect a candidate's daily trend, SMA crosses, AVWAP reclaim/loss, breakout
   level, overextension, and earnings timing without reconstructing its context.
4. Only in a separately approved execution phase, reconcile every order and fill
   with the broker and preserve safety limits across retries and restarts.

## Strategic choices

| Choice | Rationale | Trade-off |
| --- | --- | --- |
| Research/alerts only; isolate execution authority | David explicitly excludes automation; existing trading paths remain risky | Execution-engine repair is deferred behind isolation, not silently ignored |
| Morning setup quality first | David's clarified priority and original dissatisfaction | Daily workflow improvements follow morning availability and evidence collection |
| Quality and completeness before more indicators | Existing SMA/AVWAP/range toolkit already covers the stated job | Fewer visible feature additions |
| A bounded, explicit universe | Current starter list is 62 symbols, not market-wide discovery | Can miss opportunities; evaluate expansion after coverage and cost tests |
| Liquidity evidence, not price floors | Matches David's preference; price alone does not establish executable size | Daily turnover is only a research proxy; entry-time checks remain necessary |
| Evidence-linked rankings | daily-v2 weights are transparent but unvalidated | No confidence-percentage or return claims |
| Fast repeated review | A short queue with prefetch and clear context supports the ten-minute job | Long-range chart annotation must be less crowded |
| Keep morning and daily workflows distinct | Intraday execution and end-of-day research have different freshness and risk contracts | Some shared infrastructure needs explicit boundaries |

## Anchored VWAP policy

Retain the confirmed six-month swing-high default as an interpretable hypothesis
for recovery from a prior peak. Keep the anchor date, five-session confirmation,
and calculation method visible. Earnings-reaction, swing-low, YTD and custom
anchors remain useful alternatives. The ranking continues to use one specified
default anchor so changing chart presentation does not silently change the model.

AVWAP measures the volume-weighted traded price since an anchor. It cannot prove
that current holders have broken even: turnover, exits, shorts and ownership are
not observed. "New price discovery" remains explicitly bounded to a prior
52-week or fetched-history high, not an unsupported all-time-high claim.

These are interpretation and design choices, not validated return forecasts.
The existing [methodology](../docs/DAILY_TECHNICALS.md) records the research basis.

## Success and guardrails

Primary outcome: morning research sessions that are available, timely, and useful
without manual troubleshooting. Measure qualified-setup precision, missed labeled
setups and delivery latency; a healthy no-setup session can be successful.

Secondary outcome: completed, useful daily reviews within ten minutes. A useful
review may save zero charts. Measure time, completion and usefulness separately;
saving a stock is neither a trade nor proof of signal quality.

Proposed end-of-month gates:

- Five observed morning sessions without an unexplained scanner outage; known
  provider failures are explicit and never represented as "no opportunities."
- Evaluate signal precision and recall against a blind, labeled replay set before
  changing thresholds; establish a baseline first, then set an improvement target.
- At least 4 of the last 5 observed top-10 review sessions finish within 10 minutes.
- At least 4 of those 5 are rated useful by David, with skip reasons captured.
- Ranked data includes today's provisional session when available, with explicit
  as-of/coverage labels (D018). Missing current-day bars during regular/post-market
  hours are excluded. Calendar coverage is disclosed independently of HTTP success.
- At least 95% of the declared daily universe has the required completed history
  during the evaluation window; no missing or stale rows silently rank.
- No unauthenticated trading control, no implicit expansion of trading authority,
  and no return or win-rate claims based on unreconciled app P&L.

Targets are provisional, not measured outcomes. Definitions and denominators are
in [Metrics](METRICS.md). Small personal-use samples establish usability direction,
not statistical evidence of investment performance.

## Not now

Defer additional indicator families, AI-generated buy/sell recommendations,
options/crypto, social feeds, subscriptions, multi-broker expansion, an all-market
scan, and automatic trading from daily-v2 scores. Defer score-weight optimization
until a point-in-time evaluation and untouched holdout exist. Do not expand the
universe or reduce liquidity/freshness checks simply to fill a queue.

## What would change this strategy

- Daily review first: move daily completion and visual clarity ahead of additional
  morning latency optimizations; retain the same security and data-trust gates.
- Execution first: dedicate the month to authenticated paper-mode reconciliation,
  restart recovery and order lifecycle; defer daily UX and broad discovery.
- A private group: add identity, per-user state, isolation and data-use permissions
  before invitations. Browser-local saved picks are not shared user accounts.
- A paid product: validate demand and data redistribution rights before pricing,
  onboarding or acquisition work. No product-market fit is established today.

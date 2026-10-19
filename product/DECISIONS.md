# Product Decision Log

## D018: Broker Fills Define Paper Outcomes; Daily Plans Stay Research

Date: 2026-10-17. David requested tracking to identify working setups and daily
trade suggestions with stops. Use durable intent plus confirmed broker fills;
exclude old estimates and unfilled orders from results. Group by setup, direction
and version, with sample sizes and gross-of-fees P&L. Daily plans are versioned
ATR/structure hypotheses with entry, stop, 2R objective and wait/unavailable states,
not daily order automation. [Implementation contract](PAPER_TRACKING_AND_DAILY_PLANS.md).

Append decisions; supersede explicitly rather than deleting prior rationale.
"Confirmed" means directly requested/answered by David. "Proposed" means a product
recommendation awaiting development authorization, not a production setting.

| ID / Date | Status | Decision and rationale | Revisit trigger |
| --- | --- | --- | --- |
| D001 / 2026-10-17 | Confirmed | Audit and plan only; push previously completed chart work, but implement no new features in this phase | Explicit authorization to develop |
| D002 / 2026-10-17 | Confirmed | Personal product for David, not a group or paid service | Audience expansion request |
| D003 / 2026-10-17 | Confirmed | Research and alerts only; do not prioritize automation this month | Explicit trading-authority change, with separate safety review |
| D004 / 2026-10-17 | Proposed interpretation | Prioritize better morning VWAP setups; keep daily chart review alongside it. David answered "2 and 3" but explicitly excluded automation; D003 governs over the ambiguous numbering | David corrects emphasis or observed usage changes the allocation |
| D005 / 2026-10-17 | Proposed | Isolate current execution capability before treating deployment as research-only; do not repair the full execution stack inside this roadmap | Verification of KT-001 or a new execution mandate |
| D006 / 2026-10-17 | Proposed | Provider availability, freshness and liquidity evidence precede score tuning | Baselines establish that these are healthy and ranking is the dominant problem |
| D007 / 2026-10-17 | Existing, retained | daily-v2 remains a transparent review heuristic, never a win probability; keep score and investment performance distinct | Reproducible out-of-sample evaluation justifies a documented model revision |
| D008 / 2026-10-17 | Existing, retained | Default AVWAP is a confirmed six-month swing high; alternatives are chart views, not silent ranking changes; do not equate traded average with current-holder cost basis | Labeled review evidence favors another predefined anchor policy |
| D009 / 2026-10-17 | Proposed | Verify existing delayed historical SIP rights before considering paid real-time data; no purchase or feed change in this audit | Entitlement/coverage comparison and owner budget approval |
| D010 / 2026-10-17 | Proposed | Preserve fail-closed universe filters; distinguish provider failure from no setups; do not widen silently to make the UI look populated | Owner explicitly selects a different universe contract |
| D011 / 2026-10-17 | Proposed | Minimize telemetry for a personal pilot and exclude broker/account secrets; use observed sessions before tuning metrics | Group usage or a specific need for a different retention/scope |
| D012 / 2026-10-17 | Confirmed constraint | No additional indicators, notification automation or broker experiments were implemented during the audit | A later approved roadmap item |
| D013 / 2026-10-17 | Proposed | Move historical earnings coverage and long-range chart readability ahead of more chart overlays | Coverage/readability acceptance criteria pass |
| D014 / 2026-10-17 | Completed | Pushed existing chart work as 3998465 to UFOBob069/kenny-trader main; Railway status succeeded and live daily-v2 endpoints/browser flow were verified | A later deployment or rollback |

## Decision context

The first draft recommended daily review as the primary workflow. David's strategy
answers arrived during the audit, so the roadmap was revised to morning setup
quality first, with personal-use research/alerts as the authority boundary. The
strongest safety findings remain recorded even though execution development is
deferred. This is a deliberate scope decision, not a statement that the existing
trading engine is safe.

Production reported AUTO ON during the audit. No toggle, order, credential,
subscription, database or infrastructure setting was changed. A strategy decision
does not itself change a running service. The operational mismatch is an open
KT-001 gate, and paper versus live account mode remains unverified.

## Deferred decisions

### D015 / 2026-10-17 / Confirmed: Paper Automation Authorized

David authorized starting implementation and then clarified that automated paper
trades are acceptable for testing. This supersedes D001's planning-only limit and
D003's research-only authority only for paper experiments. It does not authorize
live trading. The initial production automation was disabled before this change;
the new release hard-binds all Alpaca mutations to a verified paper transport and
blocks IBKR execution. Research mode remains available. Default paper automation
is enabled, subject to existing risk/freshness/liquidity checks.

### D016 / 2026-10-17 / Implemented: Same Proxy, Issuer Source

Use the public iShares IWB holdings CSV for the existing Russell proxy rather than
the failing Finnhub ETF lookup. Preserve exchange/common-stock/cap filters. Require
a publication date no more than five calendar days old, 900-1200 equity rows,
97-101% aggregate equity weight and at least 850 eligible tickers. Cache success
for the day, back off failures five minutes, and fail closed instead of silently
widening or reusing an unverified snapshot. These are defensive heuristics, not a
claim of official index-membership completeness. No provider subscription bought.

### D017 / 2026-10-17 / Implemented: Broader Initialization, Unchanged Setups

Raise bounded automatic chart initialization from 12 to 100 filtered symbols;
publish unmonitored-symbol coverage and perform independent lookups with at most
four concurrent operations. This addresses missing RVOL qualification outside the
initial twelve. Do not loosen gap, RVOL, liquidity or technical pattern thresholds
until labeled morning observations support a change.

### D018 / 2026-10-19 / Implemented: Current-Day Daily Technicals

David requires current-day data, superseding the completed-session-only daily
input policy. Keep cached split-adjusted history and merge the same feed's valid
current New York-date snapshot daily bar. Refresh the visible page every minute;
recompute overlays, rankings and research plans with provisional labels. Preserve
review decisions and zoom. No source bar means no invented candle; missing
current-day coverage during regular/post-market hours excludes ranked signals.
Snapshot errors must not silently masquerade as today's opportunities. Scoring
weights are unchanged; version `daily-v3-intraday` distinguishes the input policy.
Partial volume is not time-normalized. Exchange-calendar/early-close semantics
remain open under KT-006. Daily plans stay research-only; no execution changes.

Validation: 200 Python tests, 7 Node tests and the browser Daily Technicals suite
passed, including snapshot cache/date rollover, current SMA/AVWAP/plan inputs,
missing/malformed bars, denied feed, preserved review/zoom, refresh failure and
recovery, desktop and 320/390px mobile screenshots.

### D019 / 2026-10-19 / Implemented: Score Any Supported Chart

David wants a score for any ticker he opens. Retain unrestricted single-ticker
lookup independent of the scan universe, and expose `chart-v1` assessments on
chart summaries. Show both bullish/bearish evidence totals and the stronger
side's breakdown using existing weights, without the setup-only no-trigger zero
override. Do not loosen ranked-signal eligibility or research trade-plan gates.
Insufficient history returns an unavailable assessment with a bar count, not a
fabricated zero. No auto-add to the scan universe and no execution changes.

Validation: 205 Python tests, 7 Node tests and desktop/mobile browser checks passed.
Coverage includes unlisted ticker lookup, bullish/bearish assessments without a
fresh trigger, unavailable-versus-zero scoring, and unchanged trade-plan gates.

### Remaining Deferred Decisions

- Exact split of implementation time between morning reliability and daily polish:
  decide from week-one evidence; default allocation favors morning research.
- Paid data or alternate provider: decide only after entitlement diagnosis, coverage
  comparison, licensing review and a concrete cost proposal.
- Alert delivery outside the app: no channel or schedule was requested; first
  establish that alerts are timely and worth receiving.
- Live execution: no discovery or implementation commitment this month. Paper
  experiments are now explicitly permitted under D015.

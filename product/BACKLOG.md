# Prioritized Backlog

Updated: 2026-10-17. Initial audit completed; implementation subsequently authorized.
David confirmed personal use, then permitted automated paper tests (D015). Live
execution remains out of scope. Original acceptance criteria below remain recorded.

## Delivery Status Override

Second tranche: KT-002/003 now have fill accounting, restored journal state and
single-process submission/close idempotency. Daily plans added at David's request.
Remaining limits: [tracking and plan contract](PAPER_TRACKING_AND_DAILY_PLANS.md).

| Item | Current state | Still required |
| --- | --- | --- |
| KT-001 | Partial: hard paper transport, research-mode API/engine/adapter guards, IBKR orders blocked | Authentication, privacy and deployment-level credential isolation |
| KT-005 | Partial: issuer IWB proxy, dated validation/cache, source errors, bounded concurrency, active coverage | Five morning sessions and failure-recovery observation |
| KT-004 | Partial: accepted pending orders reserve daily slots without double-counting fills | Partial-fill exits, durable reservations and supported-session protection |
| KT-002/003 | Next paper reliability work, no longer wholly deferred | Broker fill truth, restart reconciliation and idempotency |
| KT-016 | Next discovery work | Observed/labeled sessions and timing baseline |

See [first delivery](DELIVERY_2026-10-17.md). This table supersedes the original
"planned/deferred" states for these items, without marking acceptance criteria
complete when only a safety subset shipped.
Owner of product/specification: Codex. Engineering owner: Codex after development
authorization. David supplies only material decisions and bounded review feedback.

P0 findings gate execution. Because execution is not the chosen product goal,
isolate it through KT-001 and defer deeper execution work rather than trying to
repair a broker platform inside a research month. A research-only label is not
isolation. Estimates are engineering days, ranges rather than commitments.

## Now: Release and Morning Research

### KT-001 / P0 / Research-only access and authority boundary

- Evidence: F01-F04; production AUTO ON conflicts with the chosen product authority.
- Outcome: only David can use protected data; the research deployment cannot submit,
  approve, close or automatically generate broker orders.
- Acceptance: explicit server-enforced research mode; no order credentials/worker
  authority in the research runtime; authenticated sensitive reads; unauthorized
  writes rejected; direct API calls cannot bypass UI controls; negative-path tests.
  Existing broker positions/orders must be inspected by the authorized owner before
  removing any supervising process; disabling new entries must not imply liquidation.
- State: proposed; not operationally applied. Dependencies: owner verifies actual
  paper/live mode and existing broker exposure. Estimate: 1-3 days; confidence high.

### KT-005 / P1 / Restore and explain morning-universe availability

- Evidence: F05, live scanner pause. This is availability, not proof of weak signals.
- Outcome: enabled filters have verifiable inputs or an explicit actionable failure.
- Acceptance: diagnose IWB holdings entitlement/response; distinguish missing key,
  entitlement, empty response, timeout and rate limit without leaking credentials;
  choose a dated, licensed membership source or explicitly approved alternative;
  preserve fail-closed semantics; last-good snapshot only within an agreed age limit;
  provider outage/recovery tests and five observed morning sessions.
- State: next after safety gate. Dependencies: KT-001, provider access. Estimate:
  1-2 days excluding vendor wait; confidence high on symptom, unknown root cause.

### KT-016 / P1 / Morning setup-quality and delivery investigation

- Evidence: David's bad-setup/slowness reports; README acknowledges inferred strategy
  thresholds; existing tests do not establish discretionary signal quality.
- Outcome: distinguish incorrect detection, slow data, stale UI, weak ranking and
  mismatched strategy expectations before choosing a fix.
- Deployment evidence: October 17's 26 source symbols produced no filtered symbols
  despite healthy membership. Compare earnings/top-mover intersection coverage
  against within-universe movers before treating empty scans as no opportunities.
- Acceptance: assemble a versioned replay set of at least 30 candidate windows over
  at least five sessions, including long/short, rejected and no-setup examples;
  David labels a bounded initial sample; record bar-close/provider-receipt/detection/
  API/render times; classify misses and false positives; freeze one holdout before
  threshold tuning; produce a short ranked root-cause report. Use synthetic cases
  for correctness but do not substitute them for observed session evidence.
- State: first discovery track. Dependencies: KT-005 for live sampling; historical
  replay can start earlier. Estimate: 2-3 engineering days plus 5+ sessions; confidence medium.

### KT-008 / P1 / Feed-aware liquidity and explicit research universe

- Evidence: F08; actual liquidity matters more than nominal stock price.
- Outcome: each shortlisted symbol has interpretable turnover, spread/activity
  context where available, and a clear distinction between research and execution.
- Acceptance: compare IEX and entitled delayed SIP daily data on a fixed sample;
  evaluate morning spread/activity and desired size with explicit timestamps;
  document feed-specific thresholds and unknown states; avoid labeling a chart
  "tradable" from daily turnover alone; no price-floor regression; disclose the
  62-symbol starter scope and exclusions; no paid service enabled without approval.
- State: discovery then bounded change proposal. Dependencies: KT-016 sample, KT-005;
  KT-006 for daily freshness. Estimate: 1-2 days; confidence medium.

### KT-006 / P1 / Exchange-session freshness contract

- Evidence: F07, four-day-old synthetic chart still eligible; current-day exclusion.
- Outcome: users know which completed session they are reviewing; absent recent
  data cannot masquerade as today's opportunity set.
- Acceptance: use an exchange-calendar implementation with holiday/early-close
  tests; specify publication time after close; rank only the expected completed
  session; explicit partial/stale exclusions; session-aware review keys; test
  holidays, DST, early closes, missing symbols, after-close and pre-open behavior.
- State: planned. Dependencies: KT-001; supports both workflows. Estimate: 1-2 days;
  confidence high. Do not use five calendar days as a substitute for session age.

### KT-011 / P1 / Minimal evidence and reliability instrumentation

- Evidence: F12; no durable usage baseline or trustworthy historical app P&L.
- Outcome: measure the research job and failure causes without collecting account
  credentials, balances or order data.
- Acceptance: versioned scan/request timing and rejection counts; review started,
  chart ready, reviewed/saved/passed/completed events; model/feed/as-of metadata;
  consistent session IDs; separate production, audit and synthetic traffic; dedupe
  retries; agreed 30-day retention for pilot diagnostics; user-readable deletion
  policy; manual timing/notes remain an acceptable initial baseline.
- State: minimal scope only. Dependencies: KT-001. Estimate: 1 day for first slice;
  confidence high. Not a third-party analytics procurement project.

### KT-014 / P1 / Reproducible release verification

- Evidence: F12; local tests pass, no tracked CI workflow, broad dependency bounds.
- Outcome: every authorized application release has an auditable test gate.
- Acceptance: reproducible dependency setup; run Python + Node tests and browser
  smoke in a credential-free environment; auth/research-mode regression tests;
  verify deployed commit/version and provider health after deploy; document rollback
  and a fail-closed startup path. Never use live broker credentials in CI.
- State: planned enabling work. Dependencies: KT-001. Estimate: 1 day; confidence high.

## Next: Daily Trust and Review

### KT-007 / P1 / Earnings coverage, not just request success

- Evidence: F06, live five-year requests returning only one upcoming date.
- Outcome: distinguish upcoming-only, historical-complete, partial and unknown data.
- Acceptance: validate coverage for at least 10 varied symbols over 1Y and 5Y
  against permitted provider/issuer sources; separate coverage status from HTTP
  success; unknown announcement times are not guessed; anchor uses a verifiable
  reaction session; never silently substitute an older event as the latest one;
  expose missing history and scheduled-date uncertainty. Define licensing/cost
  gate before changing provider.
- State: planned. Dependencies: KT-005 provider diagnosis, KT-006. Estimate: 1-2 days;
  confidence high on gap, medium on available remedy.

### KT-009 / P2 / Bound cold/degraded-provider latency

- Evidence: F09; shared calendar lock blocks unrelated chart/scan requests.
- Outcome: fast chart flips and bounded, explicit degraded states.
- Acceptance: measure 30 cold/warm chart requests with labels, plus timeout/rate-limit
  tests; set total-operation deadlines; let candles render independently of slow
  historical earnings where semantically safe; bounded concurrency and deduplication
  respect provider limits; chart flip p95 <=1s warm, first useful chart p95 <=5s
  warm, full 62-symbol scan <=15s p95 under the agreed healthy-provider profile.
- State: planned only after measured bottlenecks. Dependencies: KT-011 and data
  contracts. Estimate: 1-2 days; confidence medium. Targets are not current SLAs.

### KT-010 / P2 / Ten-minute daily review clarity

- Evidence: F10; live five-year labels overlap; existing queue actions work.
- Outcome: price, averages, anchor, recent trigger and risk are immediately readable.
- Acceptance: sparse/zoom-aware event annotation with complete details still
  accessible; 1D candles retained for 1-5Y; no label collisions at 1440/390/320px;
  keyboard and button review parity; progress resumes locally; stale saved picks
  remain dated; no forced saves or minimum opportunity count; 4/5 observed top-10
  reviews finish within 10 minutes and 4/5 are rated useful.
- State: planned. Dependencies: KT-006, KT-007, KT-011. Estimate: 1-2 days; confidence high.

### KT-012 / P1 / Daily ranking evaluation, not more heuristic weights

- Evidence: F08; no measured ranking quality, current AVWAP anchor is snapshot-selected.
- Outcome: determine whether top-ranked charts improve review selection over simple
  baselines and identify failure modes before changing scores.
- Acceptance: point-in-time snapshots with model/universe/feed/anchor versions;
  blind useful/not-useful labels and reasons; compare top-10 to price/200-only and
  unranked qualified baselines; stratify long/short/regime; no future anchor or
  earnings information; reserve holdout; publish uncertainty and negative results.
  Outcome work must include costs, splits, survivorship and missing data; it is not
  a promise of profitable backtest results within this month.
- State: capture now, initial assessment late month. Dependencies: KT-006, KT-008,
  KT-011; prospective sample collection may exceed 30 days. Estimate: 1-2 days for
  protocol/capture and initial report, not a full backtesting platform; confidence medium.

### KT-015 / P2 / Single operational source of truth

- Evidence: F12; historical README still contains superseded broker/filter/scoring claims.
- Acceptance: current setup, read-only mode, provider entitlements, filters, clocks,
  health states and rollback instructions are unambiguous; old architecture moved
  to clearly labeled history; documentation matches tested defaults.
- State: planned with related changes. Dependencies: KT-001/005/006. Estimate: 0.5 day.

## Later: Explicitly Deferred

### KT-002 / P0 execution blocker / Broker-authoritative lifecycle

- Evidence: F03. No implementation while research-only is the mandate.
- Future acceptance: accepted/partial/filled/canceled/rejected/closed state machine;
  broker-confirmed fill quantity and price; reconcile regular bracket exits;
  idempotent close and submission, durable client order keys, uncertain-result
  recovery; quote marks never become realized P&L. Mock and paper broker scenarios.
- Dependencies: KT-001 and KT-003. Estimate: 3-5 days; confidence high on defect.

### KT-003 / P0 execution blocker / Durable state and restart reconciliation

- Evidence: F02. Deferred only behind KT-001's verified execution isolation.
- Future acceptance: hydrate order IDs, exit obligations, settings and trading-day
  risk; reconcile broker positions/open orders/fills before enabling entries;
  fail closed on DB/reconciliation error; restart and multiple-worker safety tests;
  one authoritative execution owner. Dependencies: KT-001. Estimate: 3-5 days.

### KT-004 / P0 execution blocker / Pending-risk reservation and exit protection

- Evidence: F04. No expanded extended-hours support is planned.
- Future acceptance: pending orders reserve trade slots and risk; release correctly
  on rejection/cancel; account for partial fills; retries cannot duplicate exits;
  supported session-specific protection clearly tested and disclosed. Keep execution
  disabled where protection cannot be established. Dependencies: KT-002/003.
  Estimate: 2-4 days, plus broker validation; confidence high on defect.

### KT-013 / P2 / Morning phone layout

- Evidence: F11. Desktop morning research is the first target; mobile daily review
  already works. Move forward only if observed personal usage justifies it.
- Acceptance: reachable chart/status/opportunity context at 390/320px; no clipped
  controls or fixed-grid overflow; keyboard/touch parity. Dependencies: KT-010
  discovery. Estimate: 1-2 days; confidence high on layout defect.

## Prioritization rule

Safety isolation precedes availability; availability precedes signal tuning;
coverage and freshness precede ranking claims; measured usability precedes feature
breadth. Reorder with new evidence in DECISIONS.md, not by silently appending work.
Do not equate a P0 execution defect with authorization to build automation.

# 30-Day Roadmap

Window: October 18-November 16, 2026, inclusive (30 calendar days).
Status: implementation authorized after the initial audit; first tranche in validation.
Audience: David only. Updated authority: research plus automated paper experiments;
live execution is excluded. D015 supersedes the original automation exclusion.
Priority: better morning VWAP setups; retain and improve daily chart review.

## Progress

- KT-001 partial: verified paper-only transport and research-mode guards implemented;
  authentication and deployment credential isolation remain open.
- KT-005 partial: dated issuer IWB source, integrity checks, source diagnostics and
  bounded lookup concurrency implemented; market-open validation remains pending.
- KT-004 partial: pending submissions reserve daily slots; full lifecycle/protection
  work remains open. Paper P&L is explicitly unverified.
- Next: KT-016 observed setup evidence, then KT-002/003 paper-state reconciliation.

The original weekly sequencing below remains a baseline, with paper-only testing
now permitted. Statements excluding all automation are superseded only for this
bounded paper experiment, not for live trading or new notification automation.

## Outcome

By day 30, David can trust whether the morning scanner is working, understand why
a fresh setup qualifies, and review daily SMA/AVWAP charts quickly with honest
freshness and earnings context. The release must not require trading authority
or imply that its signals are profitable.

## Capacity and sequencing

Assume one engineering owner, roughly 21 weekdays in this window, with 15-17 days
of planned work and the remainder reserved for validation/provider delays. These
are capacity assumptions, not a promise of unattended work. Proposed estimates
must be revised after provider diagnosis. Keep at most one implementation item
and one discovery track active; no parallel execution-engine rewrite.

Date windows are planning windows, not scheduled tasks. If development starts late,
retain dependencies and move dates rather than compressing verification.

## Days 1-7: Establish Safety, Availability and Evidence

Dates: Oct 18-24. Theme: make research usable before optimizing signals.

- KT-001: specify and implement the approved research-only deployment boundary,
  authenticate sensitive surfaces and verify no reachable order authority.
- KT-005: diagnose the live Russell-membership failure and choose an explicit,
  permitted source or owner-approved alternative. Preserve fail-closed behavior.
- KT-014: establish credential-free release tests and deployed-version verification.
- Start KT-016/011 discovery: observe one morning workflow, record the user's
  definition of a bad setup, time the current flow, and assemble replay examples.

Gate: the authorized owner verifies broker mode/exposure before any deployment
change that could interrupt supervision. Research deployment cannot submit orders;
scanner data availability is distinguishable from no qualifying setups. If the
provider problem is unresolved, investigate or use a clearly dated replay dataset;
do not call it a live scan or silently disable the requested filter.

Planned effort: 4-5 days. The deep KT-002/003/004 repairs are not in this week's scope.

## Days 8-14: Explain and Improve Morning Setup Quality

Dates: Oct 25-31. Theme: correct data and strategy interpretation before tuning.

- KT-016: label/replay candidate windows; separate stale feed, detection, ranking,
  liquidity and usability failures. Select the smallest evidence-supported fix.
- KT-006: establish expected completed-session semantics and calendar-aware
  freshness for both morning timing and daily rankings.
- KT-008: verify feed-aware liquidity inputs and evaluate entitled historical SIP
  for daily research independently of real-time morning-data requirements.
- KT-007 discovery: measure historical versus upcoming earnings coverage; choose
  a bounded remedy or explicit incomplete state.

Gate: at least 30 replay windows across five sessions, including counterexamples,
with baseline precision/recall and latency reported. No threshold change is accepted
solely because it yields more alerts. Freshness, unknown liquidity and missing
calendar coverage remain visible; no new price floor is introduced.

Planned effort: 4-5 days. If historical data cannot be obtained, preserve the
protocol and continue prospective collection rather than fabricate evidence.

## Days 15-21: Make Daily Review Fast and Readable

Dates: Nov 1-7. Theme: bounded improvements to the existing workflow.

- KT-007: implement the selected coverage disclosure or provider-supported remedy.
- KT-010: reduce long-range marker crowding while retaining 1D candles, SMA/AVWAP,
  trigger details, earnings risk and saved-review progress.
- KT-009: profile cold/warm/degraded paths; address the measured blocking work with
  deadlines and bounded concurrency, not an unmeasured architecture migration.
- KT-011: finish minimal event capture or structured manual observation needed for
  review-completion and chart-latency baselines.

Gate: desktop plus 390/320px checks, slow-provider and missing-calendar tests,
correct 1Y/5Y range and AVWAP anchoring, and no regression to morning availability.
First human top-10 review is timed; no automatic trades or push notifications are
added under the vague label "alerts."

Planned effort: 4-5 days. If morning reliability remains unresolved, trade daily
polish scope for that blocker rather than claiming both are complete.

## Days 22-30: Validate, Consolidate and Decide

Dates: Nov 8-16. Theme: demonstrate useful research and set the next priorities.

- Complete at least five observed morning sessions; report outages and alert age
  separately from signal-quality judgments. In-app alerts remain research only.
- KT-012: evaluate collected daily rankings against simple baselines using fixed
  model versions; report uncertainty. Twenty-session return outcomes may still
  be immature and must remain pending.
- Run five timed top-10 daily reviews where enough qualified charts exist. Never
  pad a queue to satisfy a target; record healthy no-opportunity sessions separately.
- KT-015: consolidate operational docs, test results, known limitations and a
  prioritized next-month proposal. Revisit decisions using evidence, not feature count.

Gate: no unresolved research-access/authority blocker; full automated suite and
deployed smoke checks pass; fresh-data/exclusion rules hold; review usefulness and
timing results are reported honestly. Missing targets lead to focused follow-up,
not wider automation or inflated claims of completion.

Planned effort: 3-4 days plus scheduled human observations during active work.
No actual observation appointments or automation were created by this plan.

## Contingencies and Scope Trade-offs

| Trigger | Response |
| --- | --- |
| Execution remains enabled/reachable | Stop research release expansion until KT-001 isolates it; do not substitute a disclaimer |
| Provider entitlement blocks morning universe | Verify current plan, evaluate permitted alternatives, request spend approval only with evidence and cost; no silent widening |
| Data-source wait exceeds two working days | Continue offline replay/UX measurement; preserve live-blocked status |
| Morning latency/quality fails the gate | Spend the daily-polish allocation on the measured failure; defer KT-009/010 breadth |
| No time for all work | Keep safety, morning availability, freshness and coverage; defer UI refinements and ranking calibration |
| David later requests trading | Create a new execution phase for KT-002/003/004 with paper validation; this roadmap does not authorize it |

## Explicit Non-Deliverables

No auto-trading, broker migration, live-order experiments, full historical
backtesting platform, all-market scanner, paid tier, multi-user platform, or
guaranteed strategy improvement. No notification-channel purchase or recurring
automation without a separate request. Existing order defects remain recorded
release blockers for any future execution product.

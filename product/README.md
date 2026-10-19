# Kenny Product System

Last updated: 2026-10-17. Product owner: Codex, acting as Head of Product.
Accountable owner and trading-authority approver: David.

## Current recommendation

Make Kenny a trustworthy personal research-and-alerts tool, prioritizing better
morning VWAP setups and retaining the 5-10 minute daily SMA/AVWAP review workflow.
David subsequently authorized automated paper trading for tests. Live execution
is excluded. The first implementation adds a hard paper-only transport boundary
and restores the morning membership source. [Delivery details](DELIVERY_2026-10-17.md).

**Current release posture:** Daily Technicals remains research-only; morning
execution is an experimental paper-only capability. Authentication, fill
reconciliation and restart recovery remain open. P&L is unverified; paper results
are not evidence of profitability. The initial audit's unknown-mode AUTO ON state
was disabled before implementing the paper boundary.

## Documents

| Document | Purpose |
| --- | --- |
| [Strategy](STRATEGY.md) | Audience, jobs, positioning, choices, non-goals, assumptions |
| [Audit](AUDIT_2026-10-17.md) | Architecture, history, findings, live observations, test evidence |
| [30-day roadmap](ROADMAP.md) | Sequenced outcomes, dependencies, capacity, release gates |
| [Backlog](BACKLOG.md) | Stable IDs, priorities, acceptance criteria, ownership |
| [Metrics and discovery](METRICS.md) | Baselines, experiments, event definitions, evaluation protocol |
| [Decision log](DECISIONS.md) | Decisions, rationale, status, triggers for reconsideration |
| [Scoring methodology](../docs/DAILY_TECHNICALS.md) | daily-v3-intraday inputs, unchanged heuristic weights and limitations |

## Ownership and operating rules

- Codex owns discovery synthesis, evidence gathering, prioritization, specifications,
  and maintaining this backlog during authorized work. David should approve
  outcomes and material trade-offs, not supply a feature list for every iteration.
- David authorized roadmap implementation after the initial audit. Chart work
  was pushed as `3998465` and initial product docs as `b4c2c04`.
- Take the highest-priority unblocked item
  from the agreed roadmap, define acceptance tests, deliver a small increment,
  verify it, and update the backlog and decision log. Do not start lower-priority
  feature work while its release gates are unresolved.
- Escalate changes to trading authority, paid services, audience, data licensing,
  risk limits, or product direction. Never enable live trading or buy data as an
  inferred consequence of a research feature request.
- Keep a weekly evidence review and milestone brief during active product work:
  what changed, what was observed, whether a hypothesis held, and the next action.
  This is a proposed working cadence, not a scheduled job. No background
  monitoring, reminders, or autonomous future development was created.
- Append dated decisions; preserve prior rationale when revising it. Every new
  backlog item needs a user problem, evidence, acceptance criteria, and a priority
  relative to existing work. Keep implementation details in the owning code/docs.

## Confirmed direction

David answered the material strategy questions on 2026-10-17:

1. "2 and 3, do not to worry about automation for now."
2. "Just me, for my own trading."
3. "Research and alerts only."

Interpretation: better morning VWAP setups first; existing daily technical review
remains in scope; no automated-execution development. Although "2 and 3" referred
to choices that included execution, the explicit automation exclusion and
research-only authority govern. This interpretation was stated back to David.
Exact allocation between morning and daily work remains an adjustable planning
choice, not a reason to block the audit.

The research-only answer above was superseded by the subsequent explicit paper
automation authorization in D015. Live trading remains prohibited. Provider spend is a later
approval gate after measuring existing entitlements; no paid upgrade is assumed.

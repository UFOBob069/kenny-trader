# Product Decision Log

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

- Exact split of implementation time between morning reliability and daily polish:
  decide from week-one evidence; default allocation favors morning research.
- Paid data or alternate provider: decide only after entitlement diagnosis, coverage
  comparison, licensing review and a concrete cost proposal.
- Alert delivery outside the app: no channel or schedule was requested; first
  establish that alerts are timely and worth receiving.
- Automated execution: no discovery or implementation commitment this month.

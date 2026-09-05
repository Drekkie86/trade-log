# Christiania V1 — Persisted Shadow Risk Lifecycle

Package 13 turns shadow risk controls into prospective evidence.

## Invariants

- One immutable frozen risk plan per shadow candidate.
- A plan cannot be frozen retrospectively after a candidate already has an outcome mark.
- The active speculative bankroll ceiling remains €500.
- Defined maximum loss remains the primary protection.
- Percentage price stops are monitoring thresholds only; they are never presented as guaranteed fills.
- Time, thesis-invalidation, and event-risk rules may be predeclared.
- Assessments are append-only.
- A persisted shadow mark can only be assessed against the same candidate.
- When an assessment cites a persisted shadow mark, that mark's timestamp and P&L are authoritative.
- Missing thesis/event evidence produces REVIEW_REQUIRED, never a fabricated CLEAR.
- EXIT_TRIGGERED is a shadow monitoring state, not an order instruction.
- No broker-order path exists.

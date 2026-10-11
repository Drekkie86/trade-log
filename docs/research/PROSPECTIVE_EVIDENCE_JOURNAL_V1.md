# Prospective evidence journal — V1 staging contract

**Issue:** Gate C #98; prerequisites Gate A #96, frozen strategy #97, strategy matrix #100.
**Status:** research-only, no production schema change, no provider or broker calls.

Files:
- src/research/prospective_evidence_journal_v1.py
- docs/research/PROSPECTIVE_EVIDENCE_JOURNAL_REFERENCE_V1.sql
- tests/test_prospective_evidence_journal_v1.py

## Purpose

Build an explicit prospective denominator. The journal retains observations
that would otherwise be invisible: opportunities, price requests, valid
market references, rejected and unavailable quotes, and NO TRADE decisions.

Each opportunity has exactly one opening event and must precede its
subsequent price or decision records. Every event has one unique opaque
event key, structured reason codes, explicit timezone-aware event time,
source family and optional digest of an externally retained source record.

Rows are append-only (SQL update/delete guards), with an atomic single-
writer SHA-256 predecessor hash. Duplicates and backdated orphan events
are rejected. A bounded verifier inspects at most 1,000 rows per call.

The stored chain proves neither authentic broker provenance nor a complete
accounting of *all* market opportunities: anyone with privileged DB/file
access can replace or recalculate a chain, and a caller can fail to emit an
opportunity. Operational acceptance will require independent external hash
anchoring, source receipt fetching, candidate/session accounting, and
reconciliation to all scan/research/rejection denominators.

Only source-evidence SHA256 and safe reason codes are stored. No raw account
keys, bearer tokens, passwords, full provider responses or arbitrary text
appear in the persisted payload. Producers must use nonsecret event keys.

## Hard outcome firewall

This table has no price P&L field, outcome-eligible field, broker-trade flag
or ability to mark SCORED. A MARKET_REFERENCE means observed source evidence
ONLY, not broker execution. Native multi-leg broker price responses remain
quotes, not order fills. Every incomplete observation remains visible.

PR #106 independently freezes the existing marker-only scorer; simply
adding this audit trail cannot and will not restore scoring.

## Staging and performance

This SQL is intentionally kept under docs/research and **NOT**
migrations/035_*. The current production DB is v34; blindly adding a
migration would require changing runtime schema constants, full migration
history tests, rollback/preflight dependencies and audit/backup behavior.
The current API requires an explicitly provisioned SQLite connection with
the reference schema installed. It does NOT create a DB, attach tables or
run migrations automatically.

Tests create isolated throwaway DBs; no production database is touched.
All writers run one BEGIN IMMEDIATE transaction per small bounded event.
Current implementation is a correctness prototype, not a production-scale
concurrency/performance or journal retention certification.

## Before promotion to a controlled release

1. Define authoritative opportunity IDs at the candidate-selection boundary
   to avoid survivorship bias, not only after a proposed trade is admitted.
2. Integrate PR #104 per-leg Saxo source and PR #105 native package-pricing
   adapters behind opt-in/auth checks, source proof and request-rate budgets.
   Persist attempted, failed, unfilled, blocked and NO TRADE cases.
3. Add signed/verifiable source storage and external anchoring with replay,
   duplicate, tampering, clock and migration/restore tests. Protect secrets.
4. Design migration 035 only after DB lifecycle, backup, WAL, archive,
   FK/index/performance, exact-main quality gate and rollback plans are proven.
5. Implement broker or authorized-paper independently verified complete
   package ENTRY and EXIT receipts, true economics and a checked
   scoring writer before a SCORED transition is ever accepted.
6. Establish prospective matched controls and out-of-time distributions.
   The current 28,415 old stress marks never become validated outcomes.

This is not an assertion that Christiania currently has a positive edge.
No order, real money or unapproved provider call was made.

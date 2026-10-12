# Bounded nightly audit export — 12 October 2026

**Status:** research-controlled draft only. No server change or skipped restore protection.

## Observed incident

Production christiania-audit.service timed out after exactly 30 minutes
on 11–12 October 2026 and on preceding nights. Systemd killed its process.
Existing build_audit_snapshot calls inventory_backups(), which iterates
every backup file and deeply verifies each large SQLite database using
PRAGMA quick_check/foreign_key_check or compressed payload verification.
This is strong code-level evidence for unnecessary I/O in a daily
reporting task, though the precise timed-out stage has not yet been
directly measured on production.

The current restore-drill service independently fails capacity preflight,
so audit-report completion alone cannot establish recovery readiness.

## Scoped fix

The daily audit now calls inventory_backups_fast(), an existing
metadata-only function. Its output explicitly marks every backup entry
NOT_REVERIFIED, with valid_files=0; neither export nor readiness may
silently treat these backups as verified. Dedicated backup and restore
jobs retain responsibility for deep checksum/SQLite/foreign-key checks.

Three fixed audit stages emit flushed stderr markers:
AUDIT_STAGE_START/FINISH command_deck, backup_metadata, readiness.
They contain only stage identifiers and elapsed milliseconds, no
provider keys, account values, filesystem names or raw observations.
If another step blocks, journalctl can reveal the last started stage.
The JSON export still redacts configured secrets.

## Tests and limits

Tests use a small verified fixture and enforce that daily export never
calls deep inventory, entries are NOT_REVERIFIED, secret redaction is
preserved, and stage markers exist. Full application/systemd runtime
performance and exact SHA quality gate remain required. Do not
silently lift TimeoutStartSec to hide slow operations.

This is not a production deployment and does not certify backups, archive
or restore. Before release require no migration, rollback safety, disk
headroom, exact Windows/Ubuntu CI, production-scale read latency and
safe next scheduled audit. Do NOT start deep verification during market
collection to validate this change.

# P0 backup retention / recovery capacity — 12 October 2026

Status: draft policy safeguard, not merged or deployed; no backup was moved,
pruned, opened for deep verification, or restored during this investigation.

## Independent production evidence (metadata only)

- Filesystem capacity 160,921,083,904 bytes (150 GiB).
- Free capacity approximately 38,548,725,760 bytes (35.9 GiB).
- Live SQLite file 28,627,828,736 bytes (26.7 GiB).
- Ordinary full backups: October 8 (27,875,274,752 bytes) and October 1
  (27,143,593,984 bytes). Neither was independently re-verified.
- A distinct September 25 schema-v33 release rollback database
  (21,304,389,632 bytes, ~19.8 GiB) occupies backup-directory space
  but is NOT counted as an ordinary retained backup by backup_data_files.
  Never delete/move it without verifying the active release rollback pointer,
  independent archive copy and restoration contract.
- Latest weekly restore-drill error required 43,967,383,142 bytes;
  available at Oct11 preflight was 39,414,947,840 bytes. At Oct12
  recorded free space, the shortfall is about 5.42 billion bytes, varying
  with WAL, files and reserve. This safe preflight block remains OPEN.

## Critical policy vulnerability

Existing plan_backup_capacity could lower preprune_keep from 2 to 1 if
new backup disk headroom required it. create_verified_backup executes
_prune_backups BEFORE it starts and verifies a replacement copy. Production
therefore risked reducing the only two ordinary full recovery points to one
before knowing whether a new copy would pass integrity, FK and schema checks.

## Fail-closed fix

Where configured retention >= 2 and at least two copies exist, never
pre-prune below TWO recovery points. If enough capacity cannot be
reserved for the new backup on top of those two, return infeasible and
fail before deleting or creating any file. For configured retention=1,
the established explicit one-copy behavior remains (and needs separate
operator risk signoff on production, where retention is 3).

This does NOT create capacity. It deliberately converts a risky
pre-deletion into a safe, visible failure until storage is provisioned.
Do NOT lower disk reserve, delete the old rollback, or prune current backups
in response to that failure.

## Tests

27 focused tests passed locally, covering retention plans, capacity
budgeting, preserving both existing copies on failure, default backup
creation/recovery path and backward-compatible explicitly configured
retention=1. Requires green Windows/Ubuntu CI on exact SHA and independent
risk/performance review before main or production.

## Operational recommendation

First validate the independent Hetzner archive/backup copy and rollback
pointer, then expand production filesystem capacity (prefer comfortably
more than the few GiB restore shortfall, given repeated backup growth and
third-copy retention). Before moving legacy rollback files, verify archive
hash/size, restoration path and committed rollback recovery pointer.

After capacity is proven, schedule a supervised restore drill off-market
and require complete hash/schema/integrity/FK report. Stop on uncertainty.
The local retrospective EOD research archive does NOT replace recovery
points. Backup timers remain unchanged in this draft.

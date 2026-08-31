# Hostile Review Round-One Fixes

This slice addresses the concrete findings from the independent hostile review
without rewriting already-applied migration 013.

## Fixed

### Hard-crash recovery

Stale `RUNNING` daemon iterations are reconciled to terminal `ORPHANED` state
on daemon startup, after the singleton lease has been acquired.

### SQLite connection timeout

Repository connections now explicitly use a 30-second busy timeout.

### FX direction

A hand-calculated regression test confirms Christiania's ECB convention:

`1 EUR = 1.20 USD` means `120 USD = 100 EUR`.

## Migration discipline

Migration 013 is intentionally unchanged.

Migration 014 rebuilds `research_daemon_iterations` to permit `ORPHANED`, so a
real database that was already migrated to v13 receives the same schema as a
fresh database.

The dedicated migration-014 test is frozen to migration 014.

## Review scope caveat

The hostile reviewer explicitly described this as round one and did not deeply
audit every scanner/admission/structure-bridge path.

Passing this fix slice therefore means the confirmed round-one operational
issues are addressed. It does not mean Christiania has been exhaustively
validated for economic edge.

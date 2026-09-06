# Christiania V1 — Interactive Startup Performance

Package 13.6 separates interactive status from deep integrity verification.

## Why

The production research database is already multi-gigabyte. Running SQLite
`quick_check`, `foreign_key_check`, and opening every backup database before
the Streamlit page can render creates tens of seconds of avoidable startup
latency and grows worse as backup retention fills.

## Interactive path

Normal Streamlit refresh uses:

- database existence/schema/journal/basic connection state;
- the normal read-model queries;
- the bounded Theta readiness probe;
- backup file metadata only.

Metadata-only backup rows are explicitly labelled `NOT_REVERIFIED`. The UI
does not call them valid backups.

## Deep path

The following continue to perform full integrity work:

- `christiania_health.py`;
- backup creation and verification;
- restore drills;
- release acceptance;
- Ops -> Readiness.

The Ops readiness result is cached for five minutes after the expensive deep
verification completes, but the verification itself is unchanged.

This package changes no schema, scientific governance, candidate admission,
risk policy, provider contract, or broker-execution boundary.

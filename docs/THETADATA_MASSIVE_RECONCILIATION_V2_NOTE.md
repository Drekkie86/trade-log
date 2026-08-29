# ThetaData / Massive Reconciliation v2

The first reconciliation run failed for a local representation reason, not a
provider-identity reason.

Christiania's existing `normalize_massive_option_chain()` stores:

- underlying on the snapshot, not on each quote;
- option right as `C` / `P`, not `CALL` / `PUT`.

The first reconciliation helper incorrectly expected per-row underlying and
`CALL` / `PUT`, causing every Massive identity-key construction to fail.

v2 fixes that.

It also makes the historical/current timing asymmetry explicit:

- ThetaData is queried for historical EOD 2026-08-28.
- Massive's snapshot endpoint is current.
- `as_of_date=2026-08-28` defines the requested expiration window, but Massive
  cannot be expected to return contracts that have already expired and been
  removed from the current chain.

Therefore the report separates ThetaData-only identities that are already
expired from ThetaData-only identities that are still live. The latter are the
more important reconciliation failures to investigate.

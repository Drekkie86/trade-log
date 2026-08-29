# Christiania — ThetaData / Massive Reconciliation Plan

Status: read-only provider reconciliation

## Purpose

Before historical ingestion, prove that Christiania can map the same option
contract across Massive and ThetaData using a canonical identity:

- underlying
- expiration
- strike
- right

## First run

Use AAPL and the same historical date already validated through ThetaData.

Command:

`python reconcile_massive_thetadata_aapl.py AAPL 2026-08-28 --min-dte 0 --max-dte 45 --sample 10`

## What to review

- Massive normalized row count
- ThetaData flattened row count
- exact-match count
- Massive-only identities
- ThetaData-only identities
- duplicate identities
- key-construction failures
- coverage ratios

Unmatched rows are not automatically errors.

Possible legitimate causes include:

- different chain inclusion timing
- expired same-day contracts
- provider universe policy differences
- contract listing changes
- DTE boundary semantics
- corporate-action / symbology edge cases

Do not build the historical importer until unmatched rows are understood.

## Provenance rule

ThetaData's `created` field is preserved as a provider field.

Do not relabel it as market quote timestamp until its semantics are verified.
Likewise, `last_trade` is trade timestamp evidence, not quote timestamp evidence.

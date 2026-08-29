# Christiania — ThetaData historical staging importer v1

Purpose: begin collecting historical ThetaData evidence without touching
`trade_log.db`.

## Safety

The importer writes only to:

`thetadata_history_staging.db`

The project's `.gitignore` already ignores `*.db`.

No Saxo calls are made.

No historical data is yet promoted into Christiania's canonical evidence schema.

## Why staging first

The AAPL/XOM/JPM reconciliation showed 100% identity coverage for every
non-expired contract visible in Massive.

That is enough to begin historical collection, but not enough to silently
declare ThetaData rows canonical.

Staging preserves the raw provider evidence while the schema/provenance mapping
is designed.

## First test

Start small:

`python import_thetadata_history_stage.py AAPL 2026-08-27 2026-08-28 --max-dte 45`

Then inspect:

`python inspect_thetadata_history_stage.py`

If both days are clean, extend gradually.

## Rate limit

The importer sleeps 3.2 seconds between requests by default.

That keeps the script below 20 requests/minute.

Do not remove throttling merely because local calls to Theta Terminal are fast;
Theta Terminal still retrieves entitlement-controlled provider data.

## Resume behavior

A `(symbol, trading_date, max_dte)` run is unique.

Existing runs are skipped rather than silently overwritten.

Failed runs remain visible and must be diagnosed explicitly.

## Timestamp semantics

`created` is stored as `provider_created`.

`last_trade` is stored as `provider_last_trade`.

Neither is relabelled as Christiania's canonical quote timestamp yet.

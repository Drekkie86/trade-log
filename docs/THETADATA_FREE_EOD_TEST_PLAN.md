# Christiania — ThetaData Free EOD Test Plan

Status: read-only provider evaluation
No Cohort 001 dependency.

## What we are testing

The provider documentation says the EOD response contains the last NBBO reported
by OPRA at ThetaData's report-generation time.

Christiania must verify the actual payload rather than infer schema from docs.

First success criterion:
- non-empty full-chain response;
- actual `bid` field;
- actual `ask` field;
- at least one row with numeric bid and ask.

This is only a shape/connectivity test.

It does NOT yet certify:
- canonical contract identity;
- point-in-time tradability;
- live entitlement;
- historical completeness across dates;
- correctness of provider joins;
- actual Saxo executability.

## First date

Use a recent completed US trading day inside the free historical window.

Suggested first test:
AAPL, 2026-08-28, max DTE 45.

## Commands

1. Install/start Theta Terminal and log in.
2. Run:
`python check_thetadata_free_eod.py AAPL 2026-08-28 --max-dte 45 --sample-rows 3`
3. Paste the full output into ChatGPT.

## What happens next if it passes

Do not bulk-import history yet.

Next build:
1. canonical ThetaData option identity parser;
2. Massive <-> ThetaData join diagnostics;
3. one-day AAPL reconciliation report;
4. only then a historical batch importer;
5. empirical spread/noise parameter extraction;
6. temporal discovery/confirmation split.

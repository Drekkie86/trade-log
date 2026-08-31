# Reference-first ingestion head start v0.1

Status: IMPLEMENTATION SCAFFOLD — NOT COHORT 002 FROZEN

This increment turns the 2026-08-31 provider finding into code.

## What it adds

1. Massive reference-contract enumeration through
   `/v3/reference/options/contracts`.
2. Independent pagination/truncation protection for the listing frame.
3. A deterministic reconciliation layer:
   `reference = snapshot_present + snapshot_absent`.
4. Explicit `SNAPSHOT_ROW_ABSENT` evidence without inferring a cause.
5. Detection of snapshot-only identities and duplicate/invalid identities.

## What it deliberately does not do yet

- no live provider call during tests
- no database writes
- no Cohort 002 freeze
- no ThetaData join
- no scanner ranking
- no trade or shadow admission

Tomorrow's next increment should persist the reference frame and its
PRESENT/ABSENT observation states into the schema-v8 tables, then add the
ThetaData quote/Greek evidence join.

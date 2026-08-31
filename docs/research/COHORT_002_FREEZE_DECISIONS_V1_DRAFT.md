# Cohort 002 — Freeze Decisions v1 DRAFT

Status: DRAFT — NOT LAUNCH AUTHORITATIVE  
Purpose: empirical dependence / cost / measurement characterization, not edge discovery.

## Underlyings

- AAPL
- XOM
- JPM

## Primary design

- session-day is the primary independence unit
- 7–45 DTE
- same 30 strata per underlying:
  - DTE: 7–14, 15–30, 31–45
  - |delta|: frozen five bands
  - CALL / PUT
- one primary nonempty contract per stratum
- no edge/profitability claim
- no candidate-edge promotion
- hypothesis-discovery count: k = 0

## Mandatory provider hierarchy

ThetaData is the reference measurement-universe authority for expiration-set completeness.

Massive remains an independent reference/reconciliation provider.

Saxo remains the broker-identity provider. Saxo API market prices must not be treated as contemporaneous/executable unless a current entitlement probe explicitly returns:
- delayed_by_minutes = 0
- current quote-quality state
- is_executable = true

## Mandatory universe-completeness gate

For every underlying and run:

1. obtain ThetaData expiration set for the exact frozen DTE window
2. obtain Massive expiration set for the same window
3. diff the sets before selection
4. persist:
   - common expirations
   - ThetaData-only expirations
   - Massive-only expirations
   - contract counts per expiration
5. if a provider difference exists:
   - do not silently continue as "complete"
   - either FAIL the run under strict mode, or
   - continue only under an explicitly frozen DEGRADED_UNIVERSE mode that records every difference

Do not encode any provider-specific pattern such as "Massive misses Mondays." Completeness is per run, per underlying.

## Collection time

The previously drafted 13:30 America/New_York collection time remains the candidate freeze point.

Cohort 001 was captured near the open and is not a time-of-day baseline for Cohort 002.

## Measurement

For each selected candidate/control pair, preserve:

- canonical identity
- provider lineage
- per-row timestamps
- ThetaData NBBO
- ThetaData first-order Greeks
- ThetaData IV and iv_error
- Massive model/reference fields where present
- Saxo instrument resolution
- broker quote quality if observed, but separately labelled from market evidence
- next eligible session observation
- gross mid-to-mid return
- paper ask-to-bid return
- quoted/assumed/actual cost provenance

## Interim / target sample

Draft staging:
- interim: 20 independent session-days
- interim: 40 independent session-days
- promotion review: 60 independent session-days

These numbers remain draft until the cohort is consciously frozen.

## Result vocabulary

Permitted Cohort 002 outcomes include:
- DATA QUALITY FAILURE
- INSUFFICIENT EVIDENCE
- MODEL DEPENDENT / NOT ROBUST
- NOT HARVESTABLE AT CURRENT SCALE

Cohort 002 is not itself a validated-edge cohort.

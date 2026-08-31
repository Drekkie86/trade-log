# Cohort 002 — Freeze Decisions v2 DRAFT

Status: DRAFT — NOT LAUNCH AUTHORITATIVE  
Purpose: empirical dependence / cost / measurement characterization, not edge discovery.

## Underlyings

- AAPL
- XOM
- JPM

## Universe construction

Cohort 002 must be reference-first before freeze.

For each underlying:

1. enumerate 7–45 DTE listed contracts from Massive reference contracts
2. normalize the reference frame
3. persist listing metadata
4. fetch Massive snapshot/model evidence
5. fetch ThetaData quote evidence
6. fetch ThetaData Greek/IV evidence when required
7. reconcile all observations onto the reference frame
8. resolve selected contracts against Saxo reference data

The Massive snapshot endpoint must not define the listing frame.

## Mandatory accounting

For each underlying/run:

REFERENCE_LISTED
=
SNAPSHOT_PRESENT
+
SNAPSHOT_ABSENT

and:

NORMALIZED_REFERENCE
=
SELECTION_ELIGIBLE
+
SELECTION_EXCLUDED

All missing observation states are explicit.

## Provider disagreement

Cross-provider disagreement is evidence, not an automatic run failure.

Run status:
- CONSISTENT
- DISAGREEMENT_RECORDED
- UNUSABLE

A disagreement becomes UNUSABLE only if the frozen sampling/measurement rule cannot be applied reproducibly.

## ThetaData Greek rule

Greek-dependent stratification requires:
- matching contract quote row
- acceptable quote freshness
- matching Greek row
- acceptable iv_error quality
- preserved raw quote and Greek timestamps

Greek snapshot recency alone is insufficient.

## Saxo

Saxo reference data defines broker resolvability / executable-universe membership.

Saxo quote data is not considered contemporaneous execution evidence unless entitlement testing explicitly shows:
- zero delay
- acceptable quote quality
- executable status

## Sampling

The previously drafted 30 strata remain candidates:
- DTE: 7–14, 15–30, 31–45
- five |delta| bands
- CALL / PUT

Exact Cohort 002 sampling logic remains unfrozen until reference-first integration is implemented and tested.

## Research boundary

Cohort 002 remains a measurement/dependence/cost cohort.

No edge-discovery family is introduced by this document.

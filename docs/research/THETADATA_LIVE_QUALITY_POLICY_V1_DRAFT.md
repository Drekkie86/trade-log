# ThetaData Live Quality Policy v1 DRAFT

Status: DRAFT

## Core finding

The 2026-08-31 market-hours probe showed that a ThetaData quote snapshot can contain rows with very different ages.

Therefore freshness is a per-contract quote property, never a response-level property.

The Greek snapshot cannot be used by itself to establish market-data freshness because Greeks may be recomputed at request time while the associated option quote is much older.

## Mandatory join rule

For every Greek-dependent candidate:

1. identify the canonical contract
2. obtain the ThetaData quote row for that contract
3. obtain the ThetaData first-order Greek row for that contract
4. join them on canonical identity
5. derive freshness from the quote timestamp, not the Greek snapshot timestamp
6. store both raw source timestamps
7. reject the candidate from automated admission if the quote row is missing

## Proposed quote freshness classes

These are engineering defaults, not frozen research constants:

- FRESH: age <= 15 seconds
- AGING: 15 < age <= 60 seconds
- STALE: age > 60 seconds
- UNKNOWN: timestamp missing or timezone semantics unresolved

The first shadow cohort should admit only FRESH quote rows by default.

AGING may be displayed for investigation but must not silently enter the first shadow cohort.

STALE and UNKNOWN are ineligible for automated surfacing.

## Greek / IV quality

ThetaData `iv_error` is a quality field, not a guarantee of correctness.

Draft states:

- GOOD: abs(iv_error) <= 0.005
- REVIEW: 0.005 < abs(iv_error) <= 0.02
- BAD: abs(iv_error) > 0.02
- UNKNOWN: missing iv_error

First shadow cohort default:
- GOOD required for Greek-dependent screening
- REVIEW may be displayed but not admitted automatically
- BAD / UNKNOWN ineligible for Greek-dependent rules

These thresholds remain DRAFT pending calibration.

## Wing caution

Wide, stale, zero-bid, or otherwise weak option markets can produce unstable IV/Greek estimates even when a provider returns values.

Therefore no provider Greek is treated as ground truth.

## Timestamp rule

The current interpretation of naive ThetaData timestamps as America/New_York remains an implementation assumption until formally verified.

Never compute cross-provider latency or make a freshness claim if timezone semantics are unresolved.

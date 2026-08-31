# Provider Universe Completeness Policy v1 DRAFT

## Principle

A provider cannot prove its own silent omissions absent an external reference.

Pagination completeness is not universe completeness.

## Required invariant

For each run and underlying:

REFERENCE_EXPIRY_SET == PRIMARY_PROVIDER_EXPIRY_SET

or every difference is explicitly persisted and the run status reflects the degraded universe.

## Current roles

Reference / primary measurement universe:
- ThetaData

Independent reconciliation:
- Massive

Broker identity:
- Saxo

## Failure modes to distinguish

- pagination truncation
- malformed payload
- missing contracts within a shared expiration
- whole expiration omitted
- duplicate canonical identities
- stale snapshot
- missing model observation
- broker instrument-resolution failure

Each receives its own reason code. Never collapse them into "provider failure."

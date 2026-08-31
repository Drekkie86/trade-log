# Reference-first persistence v0.1

Status: IMPLEMENTED SLICE — NOT COHORT 002 FROZEN

This increment persists the listing frame and the Massive snapshot
observation state into schema v8.

Flow:

Massive reference contracts
→ listing_reference_contracts
→ Massive snapshot reconciliation
→ provider_observation_availability
→ v_reference_snapshot_reconciliation

The persistence layer records snapshot absence as evidence.

It does not infer provider causes from absence.

Still deferred:
- live provider invocation
- ThetaData quote/Greek joins
- scanner ranking
- shadow admission
- Cohort 002 freeze

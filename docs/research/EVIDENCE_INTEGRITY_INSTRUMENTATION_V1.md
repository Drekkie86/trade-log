# Christiania Evidence Integrity Instrumentation V1

## Scope

This package instruments evidence quality without changing the frozen V1 signal or admission policy.

### ThetaData timing metrics

New provider-model fields are observational only:

- `greek_age_seconds`: observation clock minus Greek option timestamp.
- `quote_greek_skew_seconds`: Greek option timestamp minus quote timestamp.
- `underlying_greek_skew_seconds`: Greek option timestamp minus Greek underlying timestamp.
- `timing_diagnostic_version`: `THETADATA_TIMING_DIAGNOSTIC_V1`.

All skews are signed. No timing threshold, freshness class, or admission rule is derived from them in this version. Missing or invalid timestamps remain represented by NULL metrics plus a `timing_status` list in `model_input_notes`.

## Reference-gap diagnostics

The immutable `unmatched_provider_contract_observations` table remains the source of truth. Migration 018 adds only derived views:

- `v_unmatched_provider_gap_by_run`
- `v_unmatched_provider_identity_recurrence`

No duplicate summary evidence is persisted.

## Admission query scaling

Requested proposal IDs are loaded into a connection-local TEMP table before joining to proposals. This removes the variable-length `IN (?, ...)` parameter ceiling without changing proposal-selection semantics.

## Frozen boundaries

This package does **not**:

- change `LOCAL_IV_RESIDUAL_V1` thresholds;
- classify Greek timing as acceptable/unacceptable;
- feed effective-N into selection;
- introduce p-values or BH/FDR;
- enable V2 trading or surfacing.

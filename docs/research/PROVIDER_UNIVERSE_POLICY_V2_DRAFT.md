# Provider Universe Policy v2 DRAFT

Status: DRAFT

## Key distinction

Christiania must keep two universe concepts separate.

### Listing / measurement frame
The listed-contract frame used to decide what contracts exist for research purposes.

### Executable universe
The subset Christiania can resolve and potentially trade through Saxo.

These are related but not identical.

## Massive reference-first rule

For Massive-backed research:

1. enumerate listed contracts from `/v3/reference/options/contracts`
2. normalize canonical identities
3. treat this as the listing frame
4. fetch Massive snapshot/model observations separately
5. left-join snapshot/model observations onto the reference frame

Do not define the listing frame from `/v3/snapshot/options/{underlying}`.

## Mandatory reconciliation invariant

For each underlying/run:

REFERENCE_LISTED
=
SNAPSHOT_PRESENT
+
SNAPSHOT_ABSENT_EXPLICITLY_RECORDED

No listed contract may silently disappear because the snapshot endpoint has no row.

## Snapshot absence reasons

Initial reason vocabulary:

- SNAPSHOT_ROW_ABSENT
- SNAPSHOT_NORMALIZATION_FAILURE
- MODEL_OBSERVATION_ABSENT
- QUOTE_OBSERVATION_ABSENT
- DUPLICATE_CANONICAL_IDENTITY
- OTHER_PROVIDER_OBSERVATION_FAILURE

These are observation-state facts, not inferred causes.

Do not encode unproven causes such as:
- no trading
- recently listed
- provider lag
unless separately established.

## Cross-provider evidence

ThetaData and Massive market-data universes may disagree.

Persist the disagreement.

Do not automatically hard-fail solely because providers disagree.

Suggested run-level status:
- CONSISTENT
- DISAGREEMENT_RECORDED
- UNUSABLE

UNUSABLE is reserved for disagreement that makes the frozen design impossible to execute reproducibly.

## Saxo role

Saxo reference data defines the broker-executable boundary for the account/broker context.

Saxo may be narrower than the exchange-listed universe.

Therefore:
- Saxo reference is authoritative for broker resolvability
- it is not assumed to be the universal exchange listing authority

## Contract metadata

Reference enumeration should persist when available:
- contract ticker
- underlying
- expiration
- strike
- right
- exercise style
- shares per contract
- primary exchange
- adjusted/additional-underlying metadata

Do not assume every option has a 100-share standard deliverable.

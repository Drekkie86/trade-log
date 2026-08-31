# Shadow Schema v8 plan v0.2

Status: DESIGN ONLY — NO MIGRATION IN THIS PHASE

The next DB migration should persist these concepts separately:

1. listing_reference_contracts
2. provider_observation_availability
3. shadow_candidates
4. shadow_state_events
5. shadow_outcome_observations
6. underlying_pins

## listing_reference_contracts

Reference-first listing frame.

Store:
- run/session identity
- provider
- underlying
- canonical contract identity
- provider ticker
- expiration
- strike
- right
- exercise style
- shares per contract
- primary exchange
- adjusted/additional-underlying metadata
- listed/reference observed timestamp
- ingestion timestamp

## provider_observation_availability

One row per listed contract/provider/evidence family.

Examples:
- MASSIVE_SNAPSHOT
- MASSIVE_MODEL
- THETADATA_QUOTE
- THETADATA_GREEKS
- SAXO_REFERENCE_RESOLUTION

Required states:
- PRESENT
- ABSENT
- INVALID
- DUPLICATE
- ERROR

Absence is evidence and must be persisted.

## shadow_candidates

Immutable-at-admission fields should include:
- candidate id
- canonical identity
- scanner family id/version
- scanner rule version
- surfaced_at
- listing/reference evidence ids
- entry quote evidence id
- entry Greek evidence id when used
- quote freshness class
- Greek quality class
- universe disagreement state
- structure id/version
- hypothesis family/version
- sizing policy version
- max theoretical loss
- cost model/provenance
- label: CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING

Mutable lifecycle state should not overwrite history; use state events.

## shadow_state_events

Append-only:
- candidate id
- from state
- to state
- occurred_at
- actor
- reason_code
- note

## shadow_outcome_observations

Append-only observations keyed by candidate and horizon:
- NEXT_ELIGIBLE_SESSION
- PLUS_3_SESSIONS
- PLUS_5_SESSIONS
- TERMINAL_EXPIRY
- MFE
- MAE

Store observed bid/ask/mid, underlying, provider lineage, timestamps, and derived return metrics separately.

## underlying_pins

Append-only pin/unpin events:
- underlying
- candidate id
- action PIN / UNPIN
- occurred_at
- reason

No active shadow may be orphaned from the collection universe.

## Migration rule

Migration 008 must be created only after the exact current v7 schema and repository patterns are inspected.

No manual schema snippets should be pasted into the repo.

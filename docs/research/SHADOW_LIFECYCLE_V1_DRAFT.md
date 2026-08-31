# Christiania Shadow Lifecycle v1 DRAFT

Status: DRAFT — NOT LIVE-MONEY AUTHORITATIVE

Purpose: define the deterministic lifecycle and audit semantics for Christiania v0.9 shadow candidates.

## Lifecycle

SURFACED → INVESTIGATED → DECIDED → SHADOW_TRACKED → CLOSED_OR_EXPIRED → SCORED

A candidate may also terminate as REJECTED from DECIDED.

## Admission semantics

### SURFACED
A deterministic quantitative screen emitted the candidate.

Required evidence:
- scanner family id/version
- scanner rule version
- canonical contract identity
- listing/reference provenance
- market-data provenance
- raw quote timestamp
- normalized quote timestamp, when timezone semantics are verified
- quote freshness state
- Greek/IV quality state, when used
- universe reconciliation state

No LLM may create or suppress SURFACED status for the first shadow cohort.

### INVESTIGATED
The candidate has been formally admitted to the investigation queue.

This is the trigger for persistent shadow-candidate tracking.

### DECIDED
A human decision has been recorded.

Allowed decisions:
- REJECT
- SHADOW_TRACK

Every REJECT requires a structured reason code.

### SHADOW_TRACKED
A zero-money synthetic position is opened.

The record freezes:
- canonical contract identity
- listing-source identity
- structure
- entry timestamp
- entry NBBO
- entry reference price
- entry Greeks / IV / iv_error when used
- quote freshness classification
- modeled costs
- maximum theoretical loss
- hypothesis family/version
- sizing-policy version
- provider lineage

### CLOSED_OR_EXPIRED
The synthetic position has reached a terminal observation.

### SCORED
All required outcome horizons and quality flags have been calculated.

## Outcome horizons

Store separately:
- next eligible session
- +3 eligible sessions
- +5 eligible sessions
- terminal expiry
- MFE
- MAE

Do not collapse these into one binary success label.

## Underlying pinning

An underlying with any active SHADOW_TRACKED candidate remains pinned in the collection universe.

Pin/unpin events are explicit and auditable.

## Real-money boundary

Shadow records are never brokerage orders.

All first-cohort UI surfaces must display:

CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING

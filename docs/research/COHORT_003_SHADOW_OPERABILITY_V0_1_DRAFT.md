# Cohort 003 — Shadow Operability Pilot v0.1 DRAFT

Status: DRAFT — NOT LIVE-MONEY AUTHORITATIVE

Purpose: test Christiania's end-to-end candidate lifecycle and outcome tracking with zero real-money exposure.

## Lifecycle

SURFACED → INVESTIGATED → DECIDED → SHADOW_TRACKED → CLOSED/EXPIRED → SCORED

## Admission rule

A candidate becomes shadow-trackable only when:

1. it passes a frozen deterministic quantitative screen
2. its canonical identity exists in ThetaData
3. provider lineage and timestamps are valid
4. Massive reconciliation is recorded
5. Saxo broker instrument resolves
6. max theoretical loss is computable for the candidate structure
7. required cost assumptions are present
8. no governance hold blocks the hypothesis family

The first shadow cohort must not use LLM output to decide admission.

## Provider hierarchy

- ThetaData: measurement universe, live NBBO, Greeks, IV
- Massive: independent reference/reconciliation
- Saxo: broker identity and eventual manual-execution destination

## Labels

Every shadow candidate must display:

CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING

No shadow result can promote a family to VALIDATED EDGE without the formal confirmation path.

## Outcome horizons

Track separately:
- next eligible session
- +3 eligible sessions
- +5 eligible sessions
- terminal expiry
- MFE
- MAE

Do not pool these horizons into one success label.

## Rejections

A rejection requires a structured reason code and may include a free-text note.

## Underlying pinning

An underlying with an active shadow position remains pinned in the observation universe until every active shadow resolves.

Pin/unpin events must be recorded explicitly.

## Real-money boundary

This cohort contains no live-money order placement.

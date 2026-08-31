# Cohort 001 — Post-hoc limitations record v2 DRAFT

Status: DRAFT POST-HOC RECORD  
Run: COHORT_001_DATA_QUALITY_BASELINE  
Run ID: 1  
US session date: 2026-08-31

This document does not amend, reopen, or rerun Cohort 001.

## Listing-frame limitation

Cohort 001 defined its sampling frame from Massive's option-chain snapshot rather than Massive's reference-contract listing endpoint.

Post-run reconciliation found one real AAPL expiration at 14 DTE:

- expiration: 2026-09-14
- contracts in Massive reference: 60
- calls: 30
- puts: 30
- strikes: 245 through 390
- present in Saxo option-root reference data
- absent from the Massive option-chain snapshot frame used by Cohort 001

Therefore the Cohort 001 sampling frame omitted one listed expiration from the 7–14 DTE stratum.

The correct interpretation is mechanical:
the listing frame was defined from a market-data snapshot endpoint rather than from the provider's listing-reference endpoint.

No stronger causal claim is made about why the snapshot omitted those contracts.

## Missing provider model observations

Separately, 156 contracts present in the Massive snapshot lacked provider model observations.

Post-hoc ThetaData first-order Greeks were available for all 156 canonical identities.

Measured ThetaData |delta| showed:

- 0 / 156 inside the frozen 0.10–0.80 sampling band
- 156 / 156 outside the band

Therefore these missing model observations did not contaminate eligibility for the frozen delta band.

Earlier monotone-bound/interpolation diagnostics must not be described as proof.

## Saxo observations

All 30 selected contracts resolved successfully to Saxo instruments.

The stored Saxo option observations were delayed/non-executable under the account entitlement at collection time, so they do not establish contemporaneous spread or execution quality.

The Saxo underlying observation was also delayed and must not be used as a contemporaneous moneyness anchor.

## What Cohort 001 remains valid for

- frozen-run governance
- raw-to-normalized accounting over the snapshot frame
- eligible/excluded reconciliation over the snapshot frame
- 30-stratum selection mechanics
- provider-request accounting
- Massive-to-Saxo canonical contract resolution
- terminal-run and single-use guards

It does not establish:
- listing-complete sampling
- contemporaneous Saxo execution prices
- profitability
- edge
- fill quality

Future cohorts should be reference-first and record missing market/model observations explicitly.

# Cohort 001 — Post-hoc limitations record v1

Status: FINAL POST-HOC RECORD  
Run: COHORT_001_DATA_QUALITY_BASELINE  
Run ID: 1  
US session date: 2026-08-31

This document does not amend, reopen, or reinterpret selection. It records facts learned after the terminal run.

## 1. Universe completeness

The frozen collection used Massive as the source of the 7–45 DTE option-chain universe.

Post-run cross-provider reconciliation showed:

- Massive identities: 836
- ThetaData identities: 896
- shared identities: 836
- Massive-only identities: 0
- ThetaData-only identities: 60
- the entire 60-contract difference was one expiration: 2026-09-14
- every expiration shared by the providers matched contract-for-contract

Therefore the phrase "complete 7–45 DTE Massive chain" means complete within the expirations returned by Massive. It does not establish completeness of the exchange-listed 7–45 DTE option universe.

The omitted 2026-09-14 expiration falls in the frozen 7–14 DTE stratum.

## 2. Massive missing-model observations

Massive supplied no model observation for 156 of 836 returned contracts.

Post-hoc ThetaData first-order Greeks were available for all 156 canonical identities.

Measured ThetaData |delta| showed:

- 0 / 156 inside the frozen 0.10–0.80 sampling band
- 156 / 156 outside the band

Therefore the eligible population selected from Massive was not contaminated by these missing model observations for the frozen delta band.

Earlier monotone-bound/interpolation diagnostics must not be described as proof. Second-provider measurement was load-bearing.

Provider missingness was highly asymmetric:
- 151 PUT
- 5 CALL

and concentrated in low-activity contracts.

## 3. Saxo observations

Cohort 001's Saxo arm established broker instrument resolution.

All 30 selected contracts resolved successfully to Saxo instruments.

However, all 30 stored Saxo option observations were non-executable and 15 minutes delayed:
- 19 STALE
- 11 UNAVAILABLE

The Saxo underlying observation was also 15 minutes delayed and stale. Its observed timestamp preceded the US regular-session open.

Therefore Cohort 001 Saxo prices must not be used as contemporaneous spread, moneyness, fill-quality, or executability evidence.

## 4. What Cohort 001 does establish

Cohort 001 remains a valid data-quality / plumbing baseline for:

- frozen-run governance
- raw-to-normalized accounting
- eligible/excluded reconciliation
- 30-stratum selection mechanics
- provider-request accounting
- Massive-to-Saxo canonical contract resolution
- terminal-run and single-use guards

It does not establish:

- exchange-universe completeness
- contemporaneous Saxo market prices
- executable broker spreads
- profitability
- edge
- fill quality

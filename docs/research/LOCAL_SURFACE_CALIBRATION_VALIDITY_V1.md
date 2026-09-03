# LOCAL_SURFACE_CALIBRATION_VALIDITY_V1

Discovery-only validation layer for Christiania's observational surface-residual research.

## Questions this layer asks

1. Are ThetaData naive market timestamps being interpreted under the documented America/New_York contract, including DST?
2. Does the DTE 14–20 empirical band transfer across dates or show inflation relative to its nominal 5% descriptive tail reference?
3. Does the instability survive when the unit is a contract/session episode rather than every 15-minute row?
4. Is the quadratic LOO residual materially different from a nearest-bracket local-linear alternative?
5. Are DTE-specific residual tails concentrated in wider spreads or poorer timestamp alignment?

## Timestamp semantics

ThetaData documentation states that `time_of_day` is America/New_York and that snapshot caches reset at midnight ET. The validator freezes those documented assumptions and tests summer (-04:00), winter (-05:00), and aware-UTC conversion behavior. This is stronger than an undocumented assumption but is intentionally labelled `DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED` until an independent live reference probe is recorded.

Documentation references:
- https://docs.thetadata.us/operations/option_at_time_quote.html
- https://docs.thetadata.us/operations/stock_at_time_quote.html
- https://docs.thetadata.us/operations/option_snapshot_quote.html

## Model-form comparison

The existing V2 LOO quadratic residual remains unchanged and frozen. This package computes a separate observational comparator using the nearest lower and upper strikes and straight-line interpolation. It does not replace V2 or select trades. The comparison is descriptive by DTE bucket.

## Guardrail

No p-values, BH/FDR decisions, candidate creation, shadow admission, or live-trading path is enabled. Database CHECK constraints keep `p_values_enabled`, `fdr_enabled`, and `decision_enabled` at zero.

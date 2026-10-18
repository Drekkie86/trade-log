# Opportunity engine integration and negative controls — 18 October 2026

## Scope and actual status

Claude PR #129 commit e156daac was cherry-picked without conflicts onto current main ef2c44bd, producing integration commit 6030b0a. This branch is REVIEW-ONLY; migration 037 has not been run against production, and no live orders are enabled.

The full-suite failure in test_performance_dataset_clone_v1.py was a stale test fixture: it declared only migrations 035 and 036 while the repository now expects 037. The fixture and expected disposable-clone schema have been updated to v37; the live source fixture remains v34. This does NOT imply that v34-to-v37 has passed a production-volume migration rehearsal.

## Independent synthetic false-positive experiment

Fixture: tests/test_opportunity_quote_noise_null_20261018.py. It is NOT Claude's unavailable original prove.py: the assumptions differ. It generates 600 flat-latent-IV (25%) three-strike call butterfly quotes at 60 DTE, spot $100, 95/100/105 strikes, $0.03 *half-spread* per leg, bid/ask centered around an error-contaminated midpoint, Gaussian independent midpoint-IV errors, and near-identical fair-IV fits that re-use the same two noisy wing quotes.

Fixed seed 20261017:
- zero midpoint-IV noise: WORTH 0/600, MARGINAL+ 0/600.
- 0.006 IV noise (0.6 vol pts): WORTH 34/600, MARGINAL+ 59/600.
- 0.012 IV noise (1.2 vol pts): WORTH 212/600, MARGINAL+ 242/600.

These are *not* real-world false discovery rate estimates, do not establish realized net P&L, and must not be compared as like-for-like counts to Claude's reported 128/600: the generators and maturity assumptions differ. They show the fundamental limitation: sigma_quote inferred from bid/ask width does not measure quote midpoint error, and model dispersion of fits using shared quotes cannot repair that omission.

Implementation preserves historical OPP_V1 thresholds and every signal for prospective research; it fixes unjustified certainty language and adds immutable stored feature provenance (BID_ASK_WIDTH_UNIFORM_ONLY, latent_midpoint_noise_measured=false, model_fit_independence_assumed=false, prospective_profitability_proven=false). This is a research-label/epistemic safety change, NOT a statistical fix to the false-positive rate. An independent as-of noise estimate (ideally holdout quote repeats/same-time liquidity with timestamp integrity), cost-confirmed executable fills and a preregistered placebo outcome study remain blockers for any live-money admission.

## Test and release gates

Added full Ubuntu Python 3.13 pytest CI job without test exclusions, in addition to existing Windows full suite and Ubuntu release smoke. Do not merge until that exact PR commit is green. Current production database schema is v34; actual v34→v35→v36→v37 migration, rollback and full-volume UI performance must be validated on a disposable clone. Do not deploy or merge only because local unit tests pass.

## Profitability versus outperforming the placebo

The preregistered paired bootstrap tests whether the selected structure beats a matched random strike. This does NOT establish positive net expected return. The initial implementation could show EVIDENCE_OF_EDGE when the selected trades still lost money, but the random-strike baseline lost more. Results now separately reports the selected-trade and matched-placebo mean net paper P&L. A relative win with non-positive selected mean, or a non-losing placebo, receives RELATIVE_EDGE_NOT_PROFITABLE rather than the stronger evidence banner. This is an explicit stricter operational presentation gate, not a retrofit of the preregistered paired test or a claim that mean paper P&L is statistically significantly positive. No trading authorization follows from either state.

## V2 as-of quote-variation correction (18 October, subsequent branch)

The original V1 scored uncertainty solely from bid/ask width and correlated
model-fit dispersion. Its 34/600 and 212/600 synthetic WORTH false alarms remain
a valid diagnosis of the V1 rule, not a promise that V2 has proved profitability.

V2 now refuses WORTH unless all three option legs have at least six disjoint
prior-IV difference pairs (at least twelve quote observations per leg).
Indexed same-contract quote-symbol history is pinned to the original
session/capture time, and stale, future or repeated timestamps fail closed.
Pairs are separated in time, spot moves are bounded, and an upper 95% Gaussian
one-leg variation proxy is derived from historical IV differences. Both
bid/ask uncertainty and historical IV variation are accounted for in scoring.

This measures prior same-provider IV movement, not direct latent midpoint
measurement error, independent vendors, alpha, or a calibrated multiple-
comparison false discovery rate. Structural model bias and genuine changes
in volatility remain. American puts cannot produce WORTH while the American-
exercise implied-volatility modeling gap remains open. Missing quote history
leads to MARGINAL/watchlist with an explicit reason, never invented sigma.

Scoring version OPP_V2 is stored immutably along with the as-of sample sizes
and leg-level sigma estimates. Evidence never silently pools V1 and V2.
The UI reuses the persisted as-of calibration rather than later quotes.
Actual broker submission and position/fill reconciliation are still separate
workflows and cannot be claimed merely from a corrected score.

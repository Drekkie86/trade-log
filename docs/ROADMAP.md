# Christiania Immediate Roadmap

## Core architecture

Christiania remains provider-extensible.

Providers collect evidence; they do not produce the final trade decision directly.

Provider-specific APIs live behind adapters such as:

- `src/providers/massive.py`
- `src/providers/saxo.py`
- future `src/providers/unusual_whales.py`

Research and model code should consume normalized evidence with explicit provenance rather than calling provider APIs directly.

A future provider does not have to pretend to be Massive or Saxo. If its semantics differ, it gets an appropriate normalized evidence family.

Examples:

- option-chain / quote data -> quote evidence
- provider-derived IV / Greeks -> provider model observations
- broker quote / execution data -> broker observations
- options-flow / alternative data -> flow or event evidence
- historical underlying data -> time-series evidence

Conceptual rule:

`provider API -> provider adapter -> normalized evidence -> Christiania models -> candidate evaluation`

not:

`provider API -> trade score`

This keeps the final decision provider-independent and auditable.

---

## Immediate pre-Cohort 001 work

### Gate 1 — Selection-universe integrity

Fix Claude blocker B1.

Required reconciliations:

`raw = normalized + normalization drops`

and:

`normalized = selection eligible + selection exclusions`

No normalized contract may silently disappear before stratification.

Missing delta, missing model evidence, invalid delta, and contracts outside the preregistered delta range must be explicitly counted and retained as selection-stage evidence.

Sampling rule becomes:

`BASELINE_STRATIFIED_SAMPLE_V2`

Tie-breaking becomes a total order by appending immutable `option_quote_id`.

### Gate 2 — Saxo authentication truthfulness

Fix Claude blocker B2.

Saxo requests must obtain a current access token through a token provider rather than relying on one static token for the full run.

Authentication expiry must never be measured as broker resolution failure.

### Gate 3 — Typed failure taxonomy

Fix Claude blocker B3.

Replace exception-name substring guessing with typed provider failures and HTTP-status-aware classification.

Persistence failures must abort or invalidate a run rather than becoming broker evidence.

Retry counts must reflect truth; unknown is not the same as zero.

### Gate 4 — Independent underlying observation

Fix Claude blocker B4.

Collect one deliberately timed, independent Saxo underlying observation outside the randomized option-resolution loop.

Persist its attempt, outcome, timestamps, retry information, and failure reason.

### Gate 5 — Adversarial tests and run semantics

Add or strengthen tests for:

- missing delta
- all 30 strata empty
- all Saxo resolutions failing
- token expiry mid-run
- token refresh mid-run
- persistence failure during resolution
- duplicate provider identities
- process interruption after selection freeze
- abandoned-run invalidation
- second active run for the same cohort/session
- exact delta boundaries
- fully tied candidates
- provider retry accounting
- underlying-observation failure

Define defensible terminal states before first live collection.

### Gate A — Re-review

Run the full suite and send the revised package for another hostile review.

Only then run Cohort 001.

---

## Immediate post-plumbing roadmap: multi-model trade evaluation

### Christiania model persistence

Add a new canonical layer such as:

`christiania_model_observations`

and a package:

`src/models/`

Each model observation should carry:

- model family
- model name
- model version
- exact input-evidence references
- estimate / prediction
- uncertainty
- timestamp
- calibration version where applicable

Christiania models never overwrite provider evidence.

### Evaluation dimensions

A potential trade should be evaluated separately on:

1. Opportunity
2. Tradability
3. Robustness
4. Counter-case
5. Final decision

The system must not use naive model majority voting.

Agreement is more valuable when it comes from genuinely independent evidence families.

Shared inputs and correlated models must reduce the value of apparent consensus.

### Mandatory counter-voice

Every proposed trade must include a quantitative hostile case.

It should state:

- what must be true for the trade to be attractive;
- what evidence says those assumptions may be false;
- which models share inputs or assumptions;
- where the apparent edge disappears;
- how spread, fees, slippage, uncertainty, and applicable verified taxes can erase the edge;
- what future observation would falsify the thesis.

The counter-voice is not merely another red/green vote.

---

## Planned model families

### 1. Execution / cost model

Build first.

It establishes how much apparent edge is required before a trade becomes actionable.

Potential inputs:

- spread
- displayed size
- commission
- exchange / regulatory charges
- FX
- slippage assumptions
- applicable verified tax treatment

Tax treatment stays configurable until explicitly verified.

### 2. Independent option pricer

Use an American-option-capable model.

Output independent valuation / implied-volatility comparisons with versioned inputs.

### 3. Volatility model family

Examples may include:

- realized volatility
- EWMA
- GARCH-family forecasts
- implied-versus-realized relationships
- regime-conditioned volatility

Multiple volatility models are not automatically independent votes.

### 4. Scenario / Monte Carlo payoff model

Produce:

- payoff distribution
- P(profit)
- expected value
- tail outcomes
- sensitivity
- uncertainty bands

### 5. Bayesian evidence combination

Bayesian reasoning is primarily an evidence-combination and calibration framework, not simply another BUY/SELL model.

It should preserve which evidence moved the belief.

### 6. Surface / relative-value model

Build after quote-quality, cost, and independent-pricing foundations are reliable.

---

## Outcome tracking

Outcome tracking is built alongside the model layer.

Where applicable retain:

- terminal payoff
- realized P/L under defined execution assumptions
- MFE
- MAE
- realized volatility
- forecast error
- calibration bucket
- model version

Without outcomes, multiple models are only versioned opinions.

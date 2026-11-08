# Christiania Cohort 001 Preregistration

**Preregistration ID:** COHORT_001_DATA_QUALITY_BASELINE  
**Document version:** 1.0  
**Status:** FROZEN BEFORE DATA COLLECTION  
**Research class:** RESEARCH_ONLY  
**Intended first collection date:** after schema/runner prerequisites are complete  
**Repository path:** `research/cohort_001_preregistration.md`

---

## 1. Purpose

Cohort 001 is a **data-quality and pipeline-validation cohort**.

It is **not** an edge study, trading strategy validation, profitability study, execution study, or evidence that Christiania has found mispricing.

The cohort is intended to answer only these questions:

1. What fraction of Massive option contracts selected by the frozen sampling rule can be independently resolved to Saxo?
2. How do Saxo-observed bid/ask spreads vary across DTE, absolute-delta, and option-right strata?
3. Where is market data missing, unavailable, stale, delayed, indicative, or otherwise unusable, and is that missingness associated with observable contract characteristics?
4. Can Christiania collect and persist the same research structure repeatedly without silently changing the population or dropping failures?

No conclusion about trading edge may be drawn from Cohort 001.

---

## 2. Scope and Universe

### 2.1 Underlying universe

Cohort 001 is restricted to:

- `AAPL`

This is deliberate.

AAPL is used because the Massive -> Saxo identity bridge, Saxo option-root resolution, multiplier validation, and Saxo underlying lookup have already been exercised successfully for AAPL.

Results from Cohort 001 are **not generalizable to the wider options market**.

A later cohort must preregister a broader universe separately.

### 2.2 Option universe

For each research run, Christiania requests the complete Massive option chain for AAPL with:

- minimum DTE: 7
- maximum DTE: 45
- calls and puts included
- `require_complete=True`

If Massive reports truncation, the run is invalid and must be recorded as failed.

No partial chain may be silently treated as a valid run.

### 2.3 US session reference

Every run must record:

- US Eastern calendar date
- session state:
  - `PRE_OPEN`
  - `INTRADAY`
  - `POST_CLOSE`
  - `NON_TRADING_DAY`

The session classification must be determined from US Eastern time.

---

## 3. Normalization Rules

Every raw Massive contract encountered must result in one of two outcomes:

1. normalized successfully; or
2. recorded as a normalization drop with a reason.

Normalization drops must never be silently discarded.

Minimum drop reasons:

- unsupported contract type
- missing strike
- missing expiration
- invalid strike
- invalid expiration
- missing contract identifier
- other normalization failure

The run manifest must store the total raw-contract count, normalized-contract count, dropped-contract count, and drop-reason breakdown.

---

## 4. Temporal Semantics

The following fields must be recorded when available:

- `snapshot_captured_at`
- `us_session_date`
- `us_session_state`
- `open_interest_as_of_date`
- `volume_trading_date`

If a provider does not expose a reliable effective date, Christiania must store `NULL` rather than infer one.

### 4.1 Open interest

Open interest must not be treated as an intraday observation.

It must be associated with an explicit `open_interest_as_of_date` when known.

### 4.2 Volume

Volume must be associated with an explicit `volume_trading_date` when known.

A zero volume value must never be interpreted without the corresponding session date/state.

---

## 5. Provider-Derived Model Data

Massive implied volatility and Greeks are treated as **provider-derived model output**, not direct market observations.

Canonical model fields belong in `provider_model_observations`.

For Cohort 001, Christiania must not use legacy Greek/IV columns in `option_quotes` as an independent second source of truth.

The following model outputs may be stored:

- implied volatility
- delta
- gamma
- theta
- vega

If Massive does not expose the model's underlying price, rate, dividend assumption, or observation timestamp, those values must remain `NULL`.

No value may be fabricated for reproducibility.

---

## 6. Sampling Rule

Cohort 001 does not use an edge scanner.

It uses a deterministic stratified sampling rule.

### 6.1 DTE strata

- `7-14`
- `15-30`
- `31-45`

### 6.2 Absolute-delta strata

- `0.10 <= |delta| < 0.20`
- `0.20 <= |delta| < 0.35`
- `0.35 <= |delta| < 0.50`
- `0.50 <= |delta| < 0.65`
- `0.65 <= |delta| <= 0.80`

### 6.3 Option-right strata

- CALL
- PUT

This creates at most:

`3 DTE strata x 5 delta strata x 2 rights = 30 strata`

### 6.4 Contract selection within a stratum

For each non-empty stratum, select exactly one primary contract.

Selection order:

1. minimize absolute distance between `|delta|` and the midpoint of the delta stratum;
2. if tied, choose the earlier expiration;
3. if still tied, choose the lower strike;
4. if still tied, choose lexicographically smaller option symbol.

No open-interest, volume, Saxo resolvability, Saxo spread, Saxo quote quality, or later outcome may affect primary selection.

If a stratum is empty, record it as empty.

---

## 7. Controls

Cohort 001 does **not** make a treatment-versus-control claim.

Therefore `candidate_controls` are not used in this cohort.

The sampled contracts are a stratified baseline sample, not "flagged opportunities".

A later edge-testing cohort that introduces candidates and controls must preregister:

- candidate rule
- control pool
- matching distance
- number of controls
- tie-breaking
- control selection order
- and must select both candidates and controls before Saxo resolution.

---

## 8. Saxo Resolution Pipeline

Every selected primary contract must enter the same Saxo resolution pipeline.

The resolution order must be randomized per run.

The randomized order must be generated before any Saxo contract resolution begins.

Each selected contract must store:

- `resolution_sequence`
- Saxo option-root resolution result
- Saxo contract resolution result
- multiplier validation result
- quote-fetch result
- retry count
- final success/failure state

Resolution failures must be persisted.

A failed contract must remain part of the cohort denominator.

Failure stages must distinguish at least:

- root resolution
- contract resolution
- identity validation
- quote fetch
- authentication
- network
- unknown

---

## 9. Saxo Underlying Observation

Each successful research run must attempt one independent Saxo observation of the AAPL underlying.

The underlying observation remains separate from the Massive snapshot.

The following raw fields should be persisted when available:

- bid
- ask
- provider mid
- computed mid
- reference price
- bid size
- ask size
- delay
- market state
- price source
- price source type
- price type bid
- price type ask
- Saxo observed timestamp
- Christiania ingestion timestamp

No Saxo underlying value may be rewritten into the Massive snapshot as if Massive observed it.

---

## 10. Saxo Option Observation

Every successfully resolved selected contract must have its Saxo observation stored separately from the Massive option record.

The following should be persisted when available:

- UIC
- option-root ID
- underlying UIC
- contract size
- bid
- ask
- provider mid
- computed mid
- bid size
- ask size
- delayed-by-minutes
- market state
- price source
- price source type
- price type bid
- price type ask
- Saxo observed timestamp
- Christiania ingestion timestamp

The Massive and Saxo observations must never be flattened into one provider-neutral quote.

---

## 11. Quote Classification

Every persisted Saxo observation must store:

- `quote_quality_version`
- `is_stale`
- `is_indicative`
- `is_delayed`
- `is_executable`

A summary label may additionally be stored, but the independent dimensions are canonical.

### 11.1 Classifier version

Initial classifier:

`SAXO_QUOTE_CLASSIFIER_V1`

### 11.2 Executability

For V1, `is_executable=True` requires all of:

- bid exists
- ask exists
- bid > 0
- ask > 0
- bid <= ask
- bid size exists and is > 0
- ask size exists and is > 0
- market state is OPEN
- price source type is FIRM
- quote is not provider-labelled NoAccess
- delayed-by-minutes is 0
- quote is not stale under the V1 staleness rule

A crossed market (`bid > ask`) is invalid for execution.

A locked market (`bid == ask`) is retained and explicitly identifiable rather than automatically discarded.

### 11.3 Indicative

`is_indicative=True` if any relevant provider metadata indicates non-firm or indicative pricing, including a non-FIRM price source type.

### 11.4 Delayed

`is_delayed=True` if `delayed_by_minutes > 0`.

### 11.5 Stale

For Cohort 001, provider-labelled stale states such as `OldIndicative` may set `is_stale=True`.

No additional age threshold is required before first collection because raw timestamps are stored and threshold-based staleness can be reconstructed later.

---

## 12. Observation vs Ingestion Time

Christiania distinguishes provider observation time from local processing time.

Persist separately:

- Massive observation timestamp, when available
- Massive ingestion/capture timestamp
- Saxo observation timestamp
- Saxo ingestion timestamp

Two separate gaps may exist:

- `ingestion_gap_seconds`
- `observation_gap_seconds`

`ingestion_gap_seconds` is an operational metric.

`observation_gap_seconds` is a market-timing metric.

If Massive Starter does not expose a reliable option observation timestamp, then:

- `massive_observed_at = NULL`
- `observation_gap_seconds = NULL`

Christiania must not infer a precise observation gap that the providers do not expose.

---

## 13. Research Run Manifest

Every attempted run must create a run manifest before provider collection begins.

The manifest must record at least:

- run ID
- preregistration file hash
- code Git commit SHA
- run start time
- run end time
- underlying universe attempted
- provider requests attempted
- provider requests succeeded
- provider requests failed
- Massive raw-contract count
- Massive normalized-contract count
- normalization-drop count
- normalization-drop reason breakdown
- selected-strata count
- empty-strata count
- selected-contract count
- Saxo resolution-success count
- Saxo resolution-failure count
- underlying-observation success/failure
- run status

A provider/auth/network failure must not cause an attempted underlying or run to vanish from the record.

---

## 14. Abort Conditions

A run must be marked failed or invalid if any of the following occurs:

- Massive chain is truncated
- preregistration hash is missing
- code Git commit SHA is missing
- run manifest cannot be created
- raw/normalized/drop counts do not reconcile
- a selected contract disappears without success or logged failure
- database transaction integrity fails
- schema version does not match the runner's expected version

A failed run remains recorded.

---

## 15. Analysis Plan

No unregistered edge analysis is part of Cohort 001.

The planned descriptive analyses are:

### 15.1 Massive -> Saxo resolution rate

Report:

- selected contracts
- successfully resolved contracts
- failed resolutions
- resolution rate
- failure rate by failure stage

### 15.2 Spread distribution

For Saxo observations with bid and ask present, summarize:

- absolute spread
- spread / computed mid

Group by:

- DTE stratum
- absolute-delta stratum
- call/put
- Saxo quote state

### 15.3 Missingness

Report the fraction of selected contracts with:

- missing bid
- missing ask
- missing bid size
- missing ask size
- NoAccess
- stale label
- indicative label
- delayed quote
- resolution failure

Compare missingness descriptively across:

- DTE strata
- delta strata
- call/put

### 15.4 Pipeline completeness

For every run verify:

`raw contracts = normalized contracts + normalization drops`

and:

`selected contracts = successful Saxo resolutions + logged Saxo resolution failures`

Any violation is a pipeline-integrity failure.

### 15.5 Repeated-run reliability

Across repeated runs, report:

- run success rate
- provider failure rate
- normalization-drop rate
- resolution rate
- median run duration

No statistical significance test or profitability claim is preregistered.

---

## 16. Prohibited Analyses for Cohort 001

The following are explicitly outside the preregistered purpose:

- estimating trading edge
- estimating expected profit
- ranking "best trades"
- inferring executable fills from delayed/indicative quotes
- backfilling candidate rules after inspecting results
- selecting a favorable subset after data collection
- claiming spreads imply realizable arbitrage
- estimating strategy Sharpe ratio
- estimating win rate
- estimating option mispricing

If any of these are explored later, they must be labelled exploratory and must not be presented as preregistered findings.

---

## 17. Anchoring Rule

Cohort 001 does not produce or display Christiania `P(profit)`.

Future cohorts that do produce model probabilities must preserve the rule that the user commits their own assessment before seeing Christiania's probability.

---

## 18. Reproducibility

Before the first cohort run:

1. this file must be committed to Git;
2. its content hash must be calculated;
3. the hash must be stored in the research-run manifest and relevant cohort rows;
4. the code Git commit SHA must also be stored.

Recommended file hash command:

```powershell
git hash-object research/cohort_001_preregistration.md
```

Recommended code commit command:

```powershell
git rev-parse HEAD
```

The file hash identifies the exact preregistration content.

The Git commit SHA identifies the exact code state used for collection.

---

## 19. Cohort Identity

**Cohort:** `COHORT_001_DATA_QUALITY_BASELINE`

**Scanner:** `NONE_BASELINE_STRATIFIED_V1`

**Sampling rule:** `BASELINE_STRATIFIED_SAMPLE_V1`

**Quote classifier:** `SAXO_QUOTE_CLASSIFIER_V1`

**Outcome definition:** `DATA_QUALITY_OUTCOMES_V1`

**Analysis plan:** `DATA_QUALITY_ANALYSIS_V1`

**Candidate class:** `RESEARCH_ONLY`

---

## 20. Freeze Statement

Once this document is committed and hashed, its rules must not be modified for Cohort 001.

If a material change is required, create a new preregistration document/version and new hash.

The original document must remain in Git history.

No Cohort 001 observations may be collected before the database schema and runner can persist every field and failure mode required by this document.

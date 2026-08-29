# Christiania Detectability — Empirical Parameter Contract v0.1

Status: design contract  
Purpose: define what real data must eventually replace the current synthetic detectability inputs.

## Principle

A detectability report must always disclose the source of its parameters.

Allowed high-level provenance states:

- `SYNTHETIC`
- `EMPIRICAL_COHORT_NNN`
- `EMPIRICAL_POOLED_<description>`

No empirical MDE statement is permitted when the parameters remain synthetic.

## Parameters to replace

### Noise scale

Current simulator concepts such as `idiosyncratic_scale` and `common_scale` are stress-test inputs.

Empirical replacement should be derived from observed paired-edge data using a variance decomposition rather than copied literally from the synthetic model.

Required evidence:

- pair-level paired edge in RU;
- underlying-day identity;
- session-day identity;
- enough repeated observations to separate pair-level, underlying-day, and day-level variation.

### Within-underlying correlation

Required data:

- at least two paired observations within an underlying-day cluster;
- preferably several pairs across repeated session-days.

Report uncertainty, not only a point estimate.

### Cross-underlying paired-edge correlation

Required data:

- same-day observations for multiple underlyings;
- synchronized or timestamp-preserved market states;
- underlying-level paired-edge summaries.

Do not estimate this from raw underlying returns.

### Serial dependence

Required data:

- consecutive or near-consecutive session-day summaries;
- explicit missing-day handling.

### Tail behavior

Required data:

- full observed paired-edge distribution;
- no winsorization or outlier deletion without a preregistered rule and retained raw values.

Possible empirical summaries:

- robust scale;
- excess kurtosis where meaningful;
- empirical extreme quantiles;
- fitted tail model only if diagnostics support it.

### Cost distribution

Cost must be represented as a random empirical quantity.

For each candidate/control leg or structure preserve, where available:

- quoted bid / ask at decision time;
- reference mid;
- intended side;
- actual fill if a real/manual trade occurs;
- commission;
- fees / levy;
- slippage versus the frozen reference;
- cost in EUR;
- cost normalized to max risk.

For paper-only observations, distinguish assumed execution cost from observed real fill cost.

## Minimum reporting contract

Every serious detectability run should print or persist:

- `parameters_source`;
- source cohort / date range;
- number of session-days;
- number of underlyings;
- number of underlying-days;
- number of paired observations;
- cost source;
- dependence estimates;
- effective N;
- nominal alpha;
- empirical null FPR;
- multiple-testing setting;
- MDE/power results;
- uncertainty around the empirical input estimates where feasible.

## Bootstrap / calibration rule

Null calibration remains mandatory after empirical parameters are introduced.

Changing from synthetic to empirical parameters is not permission to assume the inferential procedure stays calibrated.

The empirical false-positive rate must remain a first-class output.

## Versioning rule

Any material change in:

- candidate/control matching;
- outcome horizon;
- cost definition;
- clustering unit;
- dependence estimator;
- null calibration;
- multiple-testing correction;

creates a new detectability-analysis version.

Do not silently reuse an old result under new semantics.

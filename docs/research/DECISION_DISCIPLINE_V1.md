# Package E — Decision Engine + Discipline Leakage V1

## Purpose

Package E separates two questions that must never be conflated:

1. **Does the model/research evidence justify further consideration?**
2. **Did the operator follow the governed process?**

The package does not create broker authority. `ELIGIBLE_FOR_MANUAL_REVIEW` means exactly that: a human may review the candidate. It is not an order instruction.

`NO_TRADE` is a first-class successful outcome.

## Decision states

The engine emits only:

- `NO_TRADE`;
- `CONTINUE_SHADOW`;
- `ELIGIBLE_FOR_MANUAL_REVIEW`.

Hard blocks force `NO_TRADE`. Current hard blocks include undefined/unbounded downside and an edge family that has not explicitly been activated for manual review.

Soft evidence gaps force `CONTINUE_SHADOW`. They include insufficient calibration, robustness, sample evidence, or inadequate/unknown compensation relative to maximum loss and CVaR.

A high probability of profit cannot override weak tail compensation.

## Ranking doctrine

The research score combines:

- evidence quality;
- calibration;
- robustness;
- risk compensation.

Win probability is retained as descriptive evidence but is deliberately not part of the composite ranking formula. This prevents high-win-rate, poor-tail structures from dominating the queue merely because they win often.

## Discipline leakage

Execution evidence is separated into:

- `MODEL_APPROVED`;
- `DISCRETIONARY_UNAPPROVED`.

For each group Christiania reports count, total P&L, average P&L, realized win rate and model-expected P&L where available.

The engine also measures discretionary behaviour immediately after a profitable model-approved observation. This is designed to expose the failure cycle:

> follow rules → profit → confidence rises → discretionary trade → leakage/loss.

The output distinguishes possible strategy/model failure from possible operator-discipline failure. These are diagnostic labels, not causal proof.

## No hindsight reconstruction

The runtime is intentionally strict. If historical trades do not contain an explicit execution classification, Christiania reports:

`EXPLICIT_EXECUTION_CLASS_NOT_CAPTURED`

It does not infer approval/discretion from status, P&L, timestamps, comments or other ambiguous fields.

This preserves the scientific boundary: missing provenance remains missing provenance.

## Read-only runtime

`src/research/decision_discipline_runtime_v1.py` reads the existing database without mutation and reports whether explicit execution provenance is scoreable.

The runtime reuses Package D's prospective/shadow state and exposes no automatic promotion or execution authority.

## Browser surface

`pages/05_Decision_Discipline.py` provides:

- current decision authority;
- calibration/shadow state;
- approved versus discretionary evidence when explicitly captured;
- discipline-leakage diagnostics;
- a research-only manual-review eligibility sandbox.

The browser page cannot submit an order.

## Scientific boundary

Package E answers:

> **Should this bounded-risk candidate be rejected, remain in shadow, or become eligible for a human review — and separately, are we following the process we claim to follow?**

It does not answer whether any trade should be executed automatically. Christiania V1 retains no broker-order path.

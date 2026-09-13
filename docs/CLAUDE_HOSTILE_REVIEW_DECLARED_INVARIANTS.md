# Christiania hostile-review declared invariants

These are **claims to falsify**, not truths to assume. The hostile reviewer should trace each invariant into code, persistence, tests, deployment and documentation and report any gap between intent and enforcement.

## Trading authority

- V1 is research/shadow software, not autonomous trading software.
- No code path should submit broker orders.
- `ELIGIBLE FOR MANUAL REVIEW` must not mean `TRADE`.
- `NO TRADE` is a valid successful result.

## Capital / loss doctrine

- The experimental options bankroll is deliberately small and capped; current operating doctrine uses a €500 speculative bankroll rather than allowing gains to justify uncontrolled scaling.
- Undefined-loss / naked option exposure is not acceptable for the current experimental account.
- Where a strategy is eligible for research, practical exposure should remain bounded and explicitly sized from maximum loss.
- A high win rate or spectacular historical return must never substitute for positive expectancy after tail risk, costs and uncertainty.

## Main Engine

- The Main Engine is the disciplined core.
- It should surface only evidence-backed, bounded-risk opportunities that survive the applicable governance gates.
- Observational anomalies and research-only challengers must not silently obtain decision authority.
- Prospective promotion is separate from historical discovery.

## Casino / 0DTE Lab

- The Casino is architecturally and statistically separate from the Main Engine.
- Its charter is **Casino in spirit, quant in discipline.**
- It may research deliberately higher-variance ideas, including 0DTE, but should use tiny/capped risk, defined loss, realistic transaction costs, explicit uncertainty and `NO TRADE`.
- Casino evidence must not contaminate Main Engine evidence populations or promotion gates.
- Dealer positioning may be used only when based on measured/sourced inputs; narrative inference is not evidence.

## Scientific evidence

- Published or internet strategies enter as hypotheses/claims, not proven edge.
- Discovery, reproduction, out-of-sample validation, prospective shadow evidence, calibration and decision eligibility are distinct states.
- Backfilled/historical data must not be allowed to masquerade as prospective evidence.
- Multiplicity matters: scanner breadth and repeated model/hypothesis experimentation must not create hidden significance.
- The correct scientific result can be `INSUFFICIENT EVIDENCE`.

## Quantitative library

- Advanced quantitative models are research/challenger tools unless governance grants a stronger role.
- A model name (BSM, Heston, SVI, SABR, GARCH, etc.) does not confer correctness.
- Pricing outputs, forecasts, scenario EV and risk metrics must be interpreted within their assumptions and must not be labelled as truth or alpha merely because they are numerically precise.

## Persistence / auditability

- SQLite is deliberately single-writer for V1.
- The daemon is intended to be the primary writer.
- Read models/UI should not mutate scientific evidence accidentally.
- Prospective/frozen evidence that is supposed to be immutable must remain immutable after outcomes become known.
- Backup and restore claims must account for SQLite/WAL semantics.

## Runtime / deployment

- Windows/GitHub is the source-of-truth workshop.
- Production is an artifact deployment target, not a development checkout.
- Releases are commit-addressed and should be identity-verifiable.
- Activation should be atomic enough that failed deployment cannot silently leave a misleading healthy state.
- Rollback should restore a coherent previous release and required services.
- Health/readiness must distinguish process liveness from research freshness/progress.

## Public security boundary

The intended public chain is:

`Internet -> Caddy HTTPS -> oauth2-proxy OIDC -> loopback-only Streamlit`

Claims to verify:

- Streamlit is not directly exposed publicly.
- oauth2-proxy is not directly exposed publicly.
- Theta/provider-local control endpoints are not exposed publicly.
- Christiania stores no end-user passwords.
- authorization is explicit rather than wildcard/open-by-default.
- secret-bearing environment files and private keys are not repository content.
- public-edge service dependencies survive normal release activation and rollback.

## Review instruction

For each invariant classify enforcement as one of:

- **ENFORCED IN CODE/CONFIG**;
- **ENFORCED ONLY BY OPERATOR PROCESS**;
- **DOCUMENTED BUT NOT ENFORCED**;
- **CONTRADICTED BY IMPLEMENTATION**;
- **INSUFFICIENT EVIDENCE**.

Any safety-critical invariant that exists only in prose should be considered a candidate defect, with severity based on plausible consequence rather than on wording alone.
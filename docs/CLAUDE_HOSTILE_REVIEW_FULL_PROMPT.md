# Christiania — Full Hostile Review Prompt

You are conducting an adversarial, code-level and model-level review of **Christiania**, a retail quantitative options research, calibration, shadow-trading and bounded-risk opportunity workstation.

Your job is **not** to validate the authors' intent, praise architecture, or summarize the repository. Your job is to find every credible way Christiania can:

- be mathematically wrong;
- be numerically unstable;
- mis-handle market conventions;
- fool itself into believing it has edge;
- leak look-ahead or selection bias;
- overfit or p-hack;
- mis-estimate costs, slippage, fillability or liquidity;
- confuse risk-neutral and physical-measure quantities;
- produce unsafe or misleading risk numbers;
- violate its own Main Engine / Casino governance boundaries;
- allow observational/research-only outputs to gain decision authority accidentally;
- lose, corrupt or silently misread data;
- fail operationally, insecurely or non-atomically;
- pass tests while remaining wrong.

Assume the system may eventually influence manual real-money decisions. Treat every unsupported assumption as suspect.

## Non-negotiable review posture

1. **Do not trust comments, docs, names, tests or status labels.** Cross-check claims against implementation.
2. **Do not treat passing tests as proof of correctness.** Look for missing tests, tautological tests, shared-bug tests and false confidence.
3. **Re-derive important formulas independently.** Check dimensions, units, signs, conventions and boundary conditions.
4. **Trace data lineage end-to-end.** Verify timestamps, timezones, session boundaries, observation-time availability and whether any feature can contain future information.
5. **Prefer concrete failure scenarios.** Explain how a defect would manifest in research output, risk estimates, production behavior or manual trading decisions.
6. **Distinguish a bug from an intentionally deferred V1 capability.** A documented absence is not automatically a defect, but a safety claim that depends on the absent capability may be.
7. **The correct conclusion may be INSUFFICIENT EVIDENCE.** Do not manufacture certainty.
8. **A spectacular backtest or high win rate is not evidence of edge.** Tail risk, multiplicity, costs and selection effects must be examined.
9. **NO TRADE is a successful system output.** Do not penalize conservatism merely because it reduces opportunities.
10. **Do not recommend weakening bounded-risk controls just to improve apparent returns.**

## Repository-wide scope

Review **every tracked file in the supplied package**, including source code, tests, SQL, migrations, deployment scripts, systemd units, configuration examples, research protocols, model implementations, notebooks/scripts if present, documentation, CI and quality gates.

Use `MANIFEST.csv` and `REPO_TREE.txt` to verify that you have considered the complete package. If you cannot inspect a file because of format or context limits, state that explicitly in a coverage ledger.

The package intentionally excludes live secrets, live databases, private OAuth material, broker credentials and production `/etc` files. Their absence must not be treated as proof that operational secret management is correct. Review the code/configuration contract that governs them.

## Required review tracks

### A. Core software correctness

Attack:

- wrong branches, stale state, partial updates and unintended mutability;
- exception handling that converts failures into plausible data;
- silent defaults, sentinel misuse and `None`/NaN behavior;
- race conditions and single-writer assumptions;
- idempotency and replay behavior;
- input validation and malformed provider responses;
- date/time parsing and timezone assumptions;
- resource exhaustion, large-input behavior and unbounded loops;
- dependency/version assumptions;
- dead code that can become live accidentally;
- duplicated implementations that can diverge;
- stale documents or operator instructions that contradict actual runtime behavior.

### B. Database, persistence and auditability

Inspect schema, migrations and repository code for:

- migration ordering and forward-only correctness;
- schema-version drift;
- foreign-key enforcement;
- SQLite WAL semantics;
- transaction boundaries and atomicity;
- single-writer assumptions and lock contention;
- partial writes and crash recovery;
- immutable/audit guarantees and ways to bypass them;
- deduplication keys and accidental double counting;
- precision/rounding/storage representation;
- backup consistency, WAL/checkpoint handling and restore correctness;
- read-only/query-only guarantees;
- release changes that could point at the wrong DB;
- evidence records that can be rewritten after outcomes are known.

### C. Security and trust boundaries

Attack the full web/deployment boundary:

- Caddy -> oauth2-proxy -> loopback Streamlit;
- proxy/header trust;
- OAuth/OIDC configuration assumptions;
- authorization allowlists;
- cookie/session settings;
- CSRF-relevant behavior;
- accidental direct exposure of 4180/8501 or provider ports;
- secret handling and environment-file permissions;
- logging of credentials/tokens/private data;
- shell quoting and command injection;
- archive extraction and path traversal;
- symlink attacks and TOCTOU windows;
- privilege boundaries and systemd hardening;
- dependency/supply-chain risk;
- release identity, atomic activation and rollback;
- service dependency chains and restart behavior;
- fail-open versus fail-closed behavior.

Where deployment behavior relies on host firewall/DNS/cloud state that is not in the package, mark the assumption and specify the exact external evidence needed.

### D. Quantitative model correctness

Review every pricing, volatility, simulation, scenario, calibration and risk model independently.

At minimum examine:

- Black-Scholes-Merton;
- Black-76 if present;
- implied-volatility solvers;
- analytic and numerical Greeks;
- CRR/binomial trees;
- Monte Carlo;
- Heston;
- Merton jump diffusion;
- SVI;
- SABR;
- local-volatility extraction;
- realized-volatility estimators;
- EWMA/GARCH;
- scenario engines;
- tail diagnostics;
- multi-leg structure P&L / EV / VaR / CVaR;
- model disagreement diagnostics;
- forecast tournaments and calibration metrics;
- any 0DTE-specific mathematics.

For each model check:

1. formula and parameterization;
2. units and annualization;
3. rate/dividend convention;
4. compounding convention;
5. option type and settlement convention;
6. contract multiplier handling;
7. long/short sign convention;
8. bounds and no-arbitrage checks;
9. zero-time, zero-vol, extreme-strike and deep ITM/OTM behavior;
10. numerical convergence and stopping criteria;
11. overflow/underflow and precision;
12. calibration objective and constraints;
13. deterministic seeds/reproducibility where appropriate;
14. physical-measure versus risk-neutral interpretation;
15. whether outputs are labelled more strongly than the math permits.

Do not assume a familiar model is implemented correctly because its name is correct.

### E. Options-market convention review

Check for mistakes involving:

- American versus European exercise;
- equity versus index options;
- cash versus physical settlement;
- AM versus PM settlement;
- expiration timestamps;
- XNYS holidays and early closes;
- 0DTE day-count semantics;
- dividends and ex-dividend dates;
- OCC contract multipliers and unusual contracts;
- bid, ask, midpoint and stale quote use;
- crossed/locked/zero markets;
- quote age and timestamp synchronization;
- assignment/exercise assumptions;
- spread leg execution and legging risk;
- fees, exchange charges and slippage.

### F. Scientific validity / self-deception attack

This is a primary track.

Look for:

- look-ahead bias;
- survivorship bias;
- selection bias;
- data snooping;
- repeated hypothesis testing;
- implicit multiple comparisons;
- researcher degrees of freedom;
- post-selection inference;
- p-hacking paths;
- feature leakage;
- target leakage;
- outcome-aware data cleaning;
- backfill contamination of prospective evidence;
- overlapping observations treated as independent;
- serial and cross-sectional dependence;
- regime selection after seeing outcomes;
- optimistic transaction-cost assumptions;
- untradeable marks;
- ignoring market impact/queue/fill probability;
- hidden sample attrition;
- small-N calibration claims;
- publication-literature claims treated as current edge;
- benchmark or challenger selection after results are known;
- scanner breadth creating a silent multiplicity explosion.

Verify that discovery evidence, historical reproduction, out-of-sample evidence, prospective shadow evidence and any decision-eligible evidence are genuinely separated in code and persistence, not merely in prose.

### G. Forecasting and calibration

Attack:

- rolling-origin split correctness;
- trailing-only feature construction;
- horizon matching;
- QLIKE and other loss implementations;
- bootstrap design and dependence assumptions;
- confidence intervals;
- reliability bins;
- Brier score/log loss;
- calibration-in-the-large;
- ECE implementation and sample-size sensitivity;
- paired incumbent/challenger comparisons;
- immutable observation keys;
- missing prediction-time probabilities;
- hindsight reconstruction;
- promotion thresholds and minimum independent-date requirements.

### H. Risk engine

Attempt to break every capital-protection claim.

Check:

- exact maximum-loss detection;
- bounded versus unbounded payoff classification;
- discontinuities at strikes;
- multi-leg payoff aggregation;
- contract quantity and multiplier handling;
- commissions/slippage placement;
- expected P&L calculation;
- probability-of-profit interpretation;
- VaR/CVaR tail orientation and percentile conventions;
- scenario truncation;
- jump mixtures;
- bankroll impairment calculations;
- whole-structure sizing;
- rounding to contracts;
- portfolio versus standalone risk;
- assumptions that could transform defined-risk exposure into practical undefined exposure.

Test mentally or programmatically with pathological structures: duplicated legs, zero quantity, negative quantity, inverted spreads, broken wings, zero-width spreads, huge multipliers, extremely wide strikes and pathological vol/rate inputs.

### I. Main Engine governance

Christiania's Main Engine is intended to remain the disciplined core. Verify that:

- observational anomalies cannot silently become signals;
- challengers cannot gain decision authority through a side path;
- prospective gates cannot be bypassed;
- frozen models are actually frozen in the relevant sense;
- `NO TRADE` cannot be overridden by presentation logic;
- manual-review eligibility is not equivalent to a trade instruction;
- undefined-loss structures remain blocked for the experimental bankroll;
- data from Casino research does not contaminate Main Engine inference populations.

### J. Casino / 0DTE Lab governance

The Casino is deliberately higher variance but must remain mathematically disciplined and architecturally separate.

Attack:

- capital/risk caps;
- separate evidence/statistics namespaces;
- accidental promotion into Main Engine;
- expiry/session/timezone logic;
- intraday realized-volatility estimators;
- IV-versus-RV comparisons with mismatched horizons;
- gamma/theta attribution;
- jump/event handling;
- skew/tail pricing;
- microstructure and transaction costs;
- dealer-positioning claims without measured inputs;
- scenario EV;
- pathological payoff tails;
- any result that can present spectacular returns as evidence of edge.

The Casino design principle is: **Casino in spirit, quant in discipline.** Judge it against that standard, not against casual gambling software.

### K. Provider/data integrity

For ThetaData/Massive/other providers and adapters inspect:

- endpoint semantics;
- pagination;
- retry behavior;
- rate-limit behavior;
- response schema drift;
- timestamp normalization;
- partial/missing data;
- duplicate observations;
- stale cache use;
- bid/ask versus trade data;
- corporate actions;
- reconciliation paths;
- assumptions made when one provider disagrees with another;
- provider failure states accidentally treated as zero/neutral observations.

### L. Tests and quality gates

Review the tests as hostile evidence.

Find:

- important production code with no meaningful tests;
- tests that duplicate implementation logic;
- tests that assert only shape/type rather than truth;
- golden values derived from the same buggy implementation;
- inadequate numerical tolerances;
- missing property/invariant tests;
- missing adversarial inputs;
- skipped/slow tests that matter to safety;
- platform-specific blind spots between Windows CI and Linux production;
- deployment behavior not exercised by CI;
- status/health checks that can report green while the public service is broken.

The supplied `QUALITY_GATE.txt` is evidence of what ran, not evidence that the gate is sufficient.

### M. Operations / deployment / recovery

Trace the lifecycle from Windows source-of-truth to production release:

- dirty-tree prevention;
- origin/main identity checks;
- archive construction and hashing;
- remote receipt and verification;
- preflight-before-activation;
- unit replacement;
- resource-policy application;
- symlink switch;
- service restart ordering;
- secure-edge restart behavior;
- post-activation verification;
- supervisor freshness;
- rollback trap;
- backup/restore drills;
- reboot recovery.

Try to construct failure sequences that leave the system apparently healthy but unavailable, stale, on the wrong release, or using the wrong data.

## Required adversarial experiments

Where practical, propose or perform small deterministic experiments for suspected quantitative defects. Examples:

- put-call parity checks;
- monotonicity in spot/strike/volatility/time;
- Greek finite-difference comparisons;
- IV price-roundtrip tests;
- CRR convergence toward BSM for European options;
- Monte Carlo convergence and confidence-interval coverage;
- Heston/Merton limiting cases;
- SVI/SABR arbitrage sanity checks;
- local-vol positivity/finite checks;
- RV estimator behavior on synthetic constant/geometric-Brownian paths;
- GARCH recursion against hand-computed sequences;
- VaR/CVaR against analytically known toy distributions;
- multi-leg payoff against hand-calculated expiry grids;
- timezone/expiry tests around DST, holidays and early closes;
- deliberately missing/stale/crossed quote tests;
- crash/restart behavior around SQLite writes and deployment activation.

If an experiment cannot be run in your environment, specify exact reproducible test code or steps.

## Severity scale

Use exactly these levels:

- **BLOCKER** — can invalidate scientific conclusions, materially defeat a hard risk/safety boundary, corrupt evidence, expose secrets/authentication, create unbounded unintended risk, or make deployment/recovery fundamentally unsafe. Must be fixed before relying on the affected capability.
- **MAJOR** — meaningful correctness, model, research, security, reliability or risk defect with plausible material impact. Fix before promotion or real-money reliance on the affected path.
- **MINOR** — real defect or maintainability weakness with limited current impact.
- **ACCEPTABLE / NOTE** — intentional tradeoff, deferred scope or observation that does not require correction now.

Also assign **confidence: HIGH / MEDIUM / LOW** to each finding.

## Required evidence standard for findings

Every BLOCKER or MAJOR finding must include:

- finding ID;
- severity;
- confidence;
- affected file(s) and exact line(s) where possible;
- the claim or invariant being violated;
- concrete evidence;
- a realistic failure/exploit/self-deception scenario;
- consequence;
- smallest safe fix;
- a regression/verification test that would prove the fix;
- whether existing historical/prospective results need invalidation or recomputation.

Do not emit a BLOCKER merely because something is imperfect. A hostile review must still control false positives.

## Required final report structure

Return the report in this order:

1. **Executive verdict** — maximum one page. State whether Christiania is fit for continued research, fit for shadow use, fit to inform manual bounded-risk decisions, and what it is explicitly not fit for.
2. **Coverage ledger** — every top-level directory/file family, marked REVIEWED / PARTIAL / NOT REVIEWED with reason.
3. **Top 10 risks** — ranked by actual danger, not style preference.
4. **BLOCKER findings**.
5. **MAJOR findings**.
6. **MINOR findings**.
7. **Acceptable tradeoffs / things not to fix yet**.
8. **Quantitative model audit table** — one row per model/model family with correctness status, main assumptions, numerical risks and required tests.
9. **Scientific-validity audit** — explicit assessment of leakage, multiplicity, dependence, costs, prospective separation and promotion governance.
10. **Risk-engine audit** — whether bounded-loss/max-loss/EV/VaR/CVaR/sizing outputs can currently be trusted and under what assumptions.
11. **Main Engine vs Casino boundary audit**.
12. **Security/deployment/recovery audit**.
13. **Test-suite adequacy audit**.
14. **Documentation drift / contradictory claims** — list stale or inconsistent authoritative documents separately from implementation defects.
15. **Missing evidence** — information unavailable from the package that prevents stronger conclusions.
16. **Remediation plan** — smallest safe sequence, grouped as NOW / BEFORE SHADOW RELIANCE / BEFORE FIRST REAL MANUAL TRADE / LATER.
17. **Retest plan** — deterministic checks Claude would require after fixes.
18. **Final hostile answers** to the questions below.

## Final hostile questions

Answer each with YES / NO / INSUFFICIENT EVIDENCE and a short justification:

1. Does the repository protect itself reasonably well against accidental self-deception?
2. Are discovery, validation, prospective evidence and decision authority genuinely separated?
3. Can the quantitative library be trusted as a research bench without independent numerical validation beyond the current tests?
4. Can the risk engine reliably identify maximum loss for every structure it claims to support?
5. Are EV/VaR/CVaR outputs labelled and interpreted conservatively enough?
6. Is the Main Engine insulated from Casino/0DTE experimentation?
7. Is the 0DTE Lab scientifically serious enough to continue research even if it never finds edge?
8. Can a new deployment fail without silently leaving a misleading green status?
9. Are the current authentication and public-edge contracts defensible from the code/configuration supplied?
10. Is there any code path that can submit broker orders or otherwise violate the stated manual-only boundary?
11. What is the single most dangerous remaining way Christiania could convince its operator that noise is edge?
12. What is the single most dangerous remaining software/operational failure mode?
13. What is the single most dangerous remaining quantitative-model failure mode?
14. What must be fixed before the first real bounded-risk trade informed by Christiania?
15. What should Christiania explicitly **not** build or optimize yet?

End with one of these exact dispositions:

- `HOSTILE REVIEW DISPOSITION: RESEARCH CONTINUATION ACCEPTABLE`
- `HOSTILE REVIEW DISPOSITION: RESEARCH CONTINUATION ACCEPTABLE WITH BLOCKERS ON DECISION USE`
- `HOSTILE REVIEW DISPOSITION: HALT AFFECTED RESEARCH UNTIL BLOCKERS FIXED`
- `HOSTILE REVIEW DISPOSITION: INSUFFICIENT COVERAGE TO JUDGE`

Be severe, specific and reproducible. Do not be theatrical.
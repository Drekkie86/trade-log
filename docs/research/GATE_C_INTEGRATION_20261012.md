# Gate C integration checkpoint — 12 October 2026

**Scope:** research-only integration branch based on main commit
0e2d1b6abe1dc58a8e123e8d65cfbd23091343e3.
**Never deploy or enable live broker data/transactions on this basis alone.**

## Contents (all separate draft PR heads preserved)

- #101 Stage 0 deterministic 11-family strategy feasibility and reject/no-edge
  classifications, with legacy comparator separated
- #102 fail-closed shadow admission using per-leg as-of quotes, frozen
  bid/ask pricing and real provider clock validation
- #103 conservative, net two-FX-time paper leg P&L and candidate readiness,
  always ineligible for executable-edge scoring
- #104 bounded candidate-specific Saxo option leg-depth GET and shared
  root/expiration contract lookup (no order or production writer)
- #105 Saxo native multi-leg strategy price-only POST, documented Saxo
  TradableQuote quality controls; no broker order
- #106 freeze marker-only SCORED lifecycle transition until actual
  independently authenticated package entry/exit receipts exist
- #107 staged hash-chained, append-only prospective opportunity and quote
  request/result/failure/rejection/NO TRADE journal (reference schema only)

## Integration defects found and fixed

1. The legacy readiness-test helper admitted September synthetic quotes using
   today's live clock. New entry freshness correctly blocked its candidate.
   The test now freezes the historical *synthetic-only* test clock, in line
   with the established admission tests. Its expectations now recognize
   actual new entry-quality evidence, while separately requiring a genuine
   broker-package receipt before outcome scoring.
2. The admission validator previously rounded quote/bid/ask/snapshot ages to
   milliseconds BEFORE comparing to 15-second limits. A 15.0004s stale
   or -0.0004s future quote could pass after rounding. All time thresholds
   now use full precision. Only displayed diagnostic values are rounded
   (six decimal places). Added boundary regression tests.

**Verified locally, combined:** 215 passed + 27 subtests under Python
3.13 on Windows, covering strategy feasibility, entry/exit freshness,
historical replay, candidate readiness, Saxo read-only and price-only adapters,
shadow risk/lifecycle, source journal and provider/cohort regressions.

This is not the complete repository quality gate; the exact combined SHA
must pass GitHub Windows/Ubuntu, production-scale performance, migration
preflight, release/rollback check, and independent reviewer approval.

## Falsifiability, not claimed profitability

- Current production evidence (11 Oct read-only audit) had 237 shadow
  candidates, 28,415 ineligible independent-leg stress marks, ZERO validated
  package outcomes, zero score-ready candidates, zero completed shadow
  risk plans, and provider live timestamp semantics NOT_RUN.
- Retrospective Oct 6–9 historical EOD option archive (5,724 rows) is NOT
  a recreation of contemporaneous decisions/fills or forward outcomes.
- The existing daemon research-run population ends Oct 5. Restart and
  continuity plus full recovery/alerting remain separately open P0 tasks.
- The broker Saxo option table had 30 stale/unavailable rows, zero
  independently executable package quotes and no current autonomous Saxo feed.
- No synthetic label, hash chain, quote, backtest or price-only POST can
  independently prove executable complex-order fill.
- The journal lives ONLY as docs/research reference schema. No schema 035,
  release migrations, production DB alteration, broker credential use, user
  bankroll change, real order or live API call occurred in this integration.

## New staged orchestration (12 Oct integration increment)

The integration adds src/research/prospective_package_quote_attempt_v1.py:
a single bounded PRICE-ONLY Saxo package-observation attempt, performed
against a caller-provisioned *staging* journal SQLite connection.

- Append OPPORTUNITY before any request; if provider observation is disabled
  (the default), record NO_TRADE with an explicit authorization reason.
- When explicitly enabled, append PRICE_REQUEST before calling an injected
  price-only observer. Preserve observed-only market reference, provider
  failure, invalid response and final NO_TRADE; no blank/success-only samples.
- Retain exception type/contents nowhere, avoiding accidental credential
  leakage. A malformed or falsely execution-verified provider result becomes
  SOURCE_FAILURE/UNAVAILABLE rather than being silently discarded.
- Failures of the journal itself propagate instead of masquerading as Saxo
  source failures. A hash-chain consistency check verifies append order.
- Even synthetic best-case package prices generate NO_TRADE and never set
  outcome_eligible, trading_enabled or SCORED. No Saxo runtime is created.
- Tests use fake source results and a throwaway SQLite staging DB. This
  must not be wired into the production daemon before controlled v35
  migration, rate limits, identity/replay and external source validation.

## Next checks before any release

1. Exact combined CI green and source/security review.
2. Independently verify Saxo API entitlements and native package-price
   response quality in a controlled market-hours read-only evaluation,
   logging all failed/unpriced opportunities.
3. Design actual durable prospective journal migration with complete
   migration/rollback/schema/foreign-key/performance/backup QA.
4. Independently verifiable broker simulation/firm package entry and exit
   receipt chain linked to frozen strategy, size, costs, FX, tax, liquidity,
   assignment, risk plan, holdout, rejection denominator and NO TRADE.
5. Restore score eligibility only with a production-verified receipt
   verifier. Keep the default as NOT READY / NO TRADE.
6. Independently maintain the operational and UI backlog #95 including
   Oct 6–9 data coverage, daemon unattended restarts, archive/restore,
   performance, and Antwerp-local date/visual polish.

**No deployment and no live trading authority.**

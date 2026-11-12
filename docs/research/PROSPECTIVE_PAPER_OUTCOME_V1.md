# Christiania — prospective paper outcome quality contract V1

**Implementation:** src/research/prospective_paper_outcome_v1.py
**Gate:** #98 (depends on #96 / #97); feeds #100 but **not** live trading.
**State:** draft, offline pure evaluator, no migration, no DB or broker writes.
**Do not merge/deploy** before current branch's complete quality gate and
independent review. No positive expectancy claim.

## What the code now does

For a **predeclared** multi-leg option position, calculate deterministic
as-of paper *leg-liquidation stress*, recording:

- The same canonical contract identities, multipliers, sides and quantities at
  entry and exit; independent timestamped ThetaData quote evidence at both
  times; one source snapshot for each phase.
- BUY at ask, SELL at bid, with the inverse trades at exit. Enforce visible
  volume at the correct quote side for each contract quantity. The result is
  conservative standalone leg crossing, not proof of a complex-order fill.
- As-of entry and exit decisions separated in time, quote/bid/ask timestamps
  within 15 seconds, cross-leg time skew within 15 seconds, no source or
  capture in the future, and explicit timezone offsets. For each phase,
  require provider record identifiers and an explicit live timestamp
  verification *reference*; nonempty reference is an assertion by the
  importer, not independent verification by this library.
- Explicit fee/slippage/tax inputs, provenance and same-day FX observations;
  missing or nonsensical values produce NOT_EVALUABLE, never implicit zero.
  Convert entry and exit cashflows at **their own FX rates**.
- Stable SHA-256 hash of complete input evidence to support review and later
  immutable journaling; independently sourced rejection and NO TRADE
  populations must be tracked by the planned storage adapter.
- Emit individual reason codes, so a missing price, stale quote, unavailable
  depth or missing fee does not quietly disappear from performance statistics.

All quote and cost fields in tests are *synthetic*. The 15-second and
24-hour FX limits are explicitly authored quality-screen values, **not**
proven sufficient for execution, price improvement or statistical edge.

## What it deliberately cannot claim

Even where all numerical checks pass, the strongest possible output is:

- status: PAPER_LEG_QUOTE_STRESS_ONLY
- validated_package_outcome = false
- outcome_eligible = false
- usable_for_strategy_edge = false
- reason: NO_INDEPENDENT_EXECUTABLE_PACKAGE_FILL_VERIFICATION

This is the correct contract. Independent leg bid/ask quotes from one snapshot
do not prove firm complex-order execution. The active collector currently
writes 28,415 such unverified stress marks and *zero* validated package
outcomes in the 11 Oct production census; **never simply relabel them**.

The current live admissions also have unvalidated provider clock semantics
(live probe NOT_RUN), so historical FRESH labels and the October 6–9
retrospective archive are unsuitable sources for automatic eligibility.

## Test command

python -m pytest -q tests/test_prospective_paper_outcome_v1.py

The tests prove correct bid/ask sign, contract multiplier, separate EUR/USD
entry and exit conversion, full costs, stable evidence hashing, denial of
stale/future/asynchronous/missing/undersized quote evidence, malformed
contracts, missing time verification, wrong chronological order, absent
preregistration, and **never an eligible outcome** based on synthetic data.

## Existing shadow-candidate readiness bridge

src/research/shadow_outcome_readiness_v1.py reads the **canonical**
shadow candidate, admission, frozen proposal, provider clock-validation,
risk plan, state events, outcome observations and outcome marks. All reads
use SQLite mode=ro plus query_only, an indexed candidate key and bounded
limits (at most 32 candidates per batch). There is no write or promotion
path.

Even a marker labelled VALIDATED_PACKAGE_OUTCOME and outcome_eligible=1
is **not** sufficient evidence: a separate independent package-receipt
verification must exist and be reconciled before the operator or engine
may claim a validated trading outcome. The existing lifecycle's
marker-only score predicate therefore also needs a coordinated release
hardening change; do not use a synthetic database marker to bypass Gate C.

On 11 Oct 2026 a read-only probe of the **12 most recent live production
candidates** found zero ready, with all 12 independently requiring:
entry quality verification at admission, live provider timestamp
validation, a predeclared risk/exit plan, and an independently verified
executable package receipt. This is a small *recent sample*, not an
exhaustive independent census of all 237.

No audit result is a trading recommendation.

## What is still necessary to finish Gate C (#98)

1. **Gate A provenance:** deploy and independently verify corrected entry
   admission only after all release/performance safety gates; capture actual
   live provider clock validation and contemporaneous per-leg records.
2. **Frozen opportunity ledger:** record *every* opportunity, rejection,
   NO TRADE, intended structure and decision time, plus source run and
   preregistered hypothesis. Do not derive denominators by selecting
   winners from existing shadow candidates.
3. **Live source adapter:** read immutable real entry and exit source quotes
   and size/depth from the canonical DB; compare frozen entry prices,
   decision chronology, cost schedule and FX. No retrospective re-label.
4. **Independent complex-order execution validation:** implement documented,
   independently authenticated broker-paper execution receipts or a vetted
   firm multi-leg package quote pathway, with matched instruments, size,
   timestamp, fees and settlement. A manually supplied string is NOT such
   a validation. Preserve failures and censored positions as failures.
5. **Durable append-only outcome journal and lifecycle:** only an outcome
   genuinely meeting this independent verification may be entered as
   VALIDATED_PACKAGE_OUTCOME with outcome_eligible=1; a code-only simulated
   package or stress mark must remain 0. Test immutable journal guards,
   authorized scorer, timing, and no double counting.
6. **Prospective statistical comparison:** adequate independent sessions and
   out-of-time matched controls, adverse fills, full net economics,
   uncertainty/tails, discipline leakage and accountable NO TRADE rates.

No current code or local fixture can legitimately create a production
validated outcome. That requires future real market/broker evidence, and
is precisely why Gate C remains open instead of being falsely closed.

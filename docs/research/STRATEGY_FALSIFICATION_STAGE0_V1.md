# Christiania — Stage 0 strategy falsification (11-family contract)

**Status:** offline research-only implementation on \`research/strategy-stage0-20261011\`.
**Issues:** #96 (Gate A first), #100 (Stage 0), then #97/#98.
**No production writes, no provider/broker request, no strategy promotion, no live orders.**

## Why this change exists

The existing \`hypothesis_scanner\` → \`shadow_structure_bridge\` →
\`shadow_intrinsic_admission_v1\` → \`shadow_outcome_collector_v2\`
pipeline is canonical. Do not create a competing shadow store.

\`src/research/strategy_falsification_v1.py\` is only a **pure,
deterministic payoff/entry-quote/feasibility calculator**. It accepts an
already specified strategy and quotes and returns a structured decision.
It cannot place a trade, fetch a quote, persist a shadow record, or
manufacture a forward prediction.

The adapter \`from_shadow_proposal()\` accepts migration 011's frozen
\`structure_json\` and optional \`entry_pricing_json\`, independently supplied
\`option_quotes\` rows keyed by \`option_quote_id\`, and an immutable admission
decision timestamp. It enforces side prices equal to frozen ones when supplied
and all option legs belong to **one persisted market snapshot**.
It intentionally does **not** relabel retrospective marks as outcomes.

## Coverage

| ID | Structure | Lane | Evaluation scope |
|---|---|---|---|
| S01 | Covered call | C | 100-share ownership/hedge reference |
| S02 | Married/protective put | C | 100-share ownership/hedge reference |
| S03 | Bull call debit spread | A | Simple directional baseline |
| S04 | Bear put debit spread | A | Simple directional baseline |
| S05 | Protective collar | C | 100-share hedge reference |
| S06 | Long straddle | B | Volatility/event feasibility |
| S07 | Long strangle | B | Volatility/event feasibility |
| S08 | Long equal-wing call/put butterfly | A | Existing long butterfly comparator |
| S09 | Iron condor | B | Credit/range structure; assignment risk |
| S10 | Iron butterfly | B | Credit/range structure; assignment risk |
| X11 | Momentum + skew + IV/RV vertical | A | **Payoff only**, not a working signal-filter comparison |

Historical reverse butterflies are recognized under
\`S08R_REFERENCE\` for a **legacy evidence adapter only**. They are not an
extra approved strategy, and the 11-family catalogue has not been
optimized or scored on the explored 17-day residual history.

## Stage-0 math and conservative assumptions

- Option BUY at as-of ask and SELL at as-of bid. Never mark a midpoint
  as an executable trade. Size availability checked on the corresponding
  quote side, with missing size reported rather than assumed.
- Explicit option shares-per-contract, quantities (a 1/-2/1 butterfly
  has **four contract units**), common expiry, correct spreads/wings,
  and stock ownership required for stock-backed structures.
- Theoretical expiry P&L is evaluated at spot $0 and all strike
  breakpoints, with analytic right-tail slope to distinguish unlimited
  upside from unlimited downside. All negative-tail/unlimited-loss
  structures fail closed. \`gross_max_loss_usd\` excludes execution costs.
- Explicit per-contract-side round-trip cost, stock charges, additional
  slippage/FX cost budget and tax-cost budget; absent cost values are
  **UNKNOWN**, never zero. These are **scenario assumptions**, not verified
  Saxo tariffs or evidence of actual fill. Outputs also include estimated
  \`net_max_loss_usd\`, \`net_max_profit_usd\`, and adjusted break-evens if
  all cost inputs are supplied.
- Source quote timestamps must include a timezone and precede the
  decision. Maximum quote age and cross-leg quote skew thresholds must
  be **explicitly configured**; the library has no invented default.
  Future FX observations and expired contracts are rejected. Size/fee/FX
  provenance absence is visible in reason codes.
- \`conservative_capital_eur\` is the larger of estimated expiry worst-case
  loss and up-front cash debit, plus full assumed costs, converted using
  an explicitly supplied EUR→USD rate, rounded *up* in EUR cents.
  Affordability respects the €500 cap. Broker buying-power and margin
  approval may be stricter than this estimate.
- Stock holdings, assignment, exercise, dividend, corporate-action,
  physical settlement, pin, complex-order liquidity and broker fill
  mechanics require separate validation. Even the strongest positive
  Stage-0 status is **INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE**.
- All C-lane hedge structures remain \`REFERENCE_HEDGE_ONLY\` even if
  a synthetic scenario passes the arithmetic. Never infer 100-share
  ownership from a quote.

## Fail-closed statuses

\`FAILED_STRUCTURE\`: forbidden/unlimited-risk form or wrong legs.
\`UNSCORABLE\`: invalid/future/missing quote or irrecoverable data.
\`INSUFFICIENT_EVIDENCE\`: missing/old/asynchronous quote evidence,
unknown costs/FX/tax, missing ownership proof.
\`OVER_CAP\`: exceeds €500 under supplied assumptions.
\`REFERENCE_HEDGE_ONLY\`: stock-backed benchmark lane.
\`ECONOMICALLY_DOMINATED_AFTER_ASSUMED_COSTS\`: non-positive best-case net
expiry payoff after explicitly supplied costs, even before predictive modelling.
\`LEGACY_REFERENCE_ONLY\`: reverse butterfly evidence comparator; never
an additional approved strategy or a trading instruction.
\`INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE\`: arithmetic and explicitly
supplied inputs pass; STILL not an order or expected-return signal.

## Verified tests

\`python -m unittest discover -s tests -p test_strategy_falsification_v1.py -q\`

The suite uses **synthetic, hand-priced fixtures** for all eleven families,
two- and four-leg cost arithmetic, expiry payoff/break-evens, frozen
quote adapter parity, reverse butterfly preservation, bid/ask (not mid),
look-ahead, stale/asynchronous quotes, mixed snapshots, stock covers,
missing costs, future FX, and pathological inputs.

The fixture's $3/contract/side assumption reflects the historical
**assumed research stress ceiling**, not a verified current Saxo charge.
Synthetic 0 slippage/tax test fixtures do not establish those costs
are zero in reality. Tests do not establish a strategy's expected return.

## Real local snapshot integration limitation (11 October)

One bounded, read-only integration probe against the **2026-09-05** local
SQLite copy (schema 27) resolved the first proposal's three persisted
legs and its frozen entry prices, but the quote time lacked an explicit
timezone and was therefore classified **UNSCORABLE** by the new strict
timestamp rule. The probe belongs to **historical legacy evidence**
and is NOT a current production population or a trade backtest.

Do not guess a timezone and rewrite decision history. Resolve raw
timestamp semantics and actual same-session as-of evidence on the
production server first. This finding must be tracked under #96.

## Required next work

1. Finish #96 with a bounded, indexed, **current production** census of
   actual full candidate and NO TRADE cohorts, market-quote timing,
   provider source, schema triggers, outcome eligibility, costs, and
   service/schedule status. Remote key authentication currently requires
   an interactive unlock on the workstation; do not bypass it.
2. Add a strictly read-only integration adapter over **validated** same
   snapshot quote records, with explicit clock semantics, observed sizes,
   broker instrument mapping, actual fees/tax/FX/slippage, assignment and
   settlement policies. No blind 11-strategy production sweep.
3. Preregister S03/S04 momentum-only controls versus X11's **same** vertical
   with skew/IV-RV filters, and separately compare S08. Reserve new
   forward sessions; distinguish exploratory from confirmatory.
4. Only after credible independent forward trade outcomes and net
   quote-side profitability, consider Gate C and an explicitly
   human-approved small live trade. Default NO TRADE.

**No current strategy has a demonstrated statistically credible edge.**

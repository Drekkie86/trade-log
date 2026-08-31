# Shadow Admission v1

This layer turns a persisted **defined-risk structure proposal** into either:

- a blocked research admission decision, or
- a shadow candidate that immediately enters `SHADOW_TRACKED`.

It never creates a broker order.

## FX evidence

The command fetches the ECB daily EUR/USD reference rate from the ECB daily
reference-rate XML.

ECB expresses the pair as:

`1 EUR = N USD`

Christiania converts USD risk to EUR by dividing by that rate.

The source observation is persisted immutably in `fx_observations`.

## Cost model

Current frozen research cost model:

`SAXO_BE_SHADOW_COST_CEILING_V1`

Saxo Belgium publicly lists USD 2.00 per USD option contract in its highest
standard pricing category. Christiania does **not** treat this as the user's
actual fee.

For shadow research, v1 reserves:

`USD 3.00 per contract-side`

That is:

- USD 2.00 public tariff reference;
- plus USD 1.00 contingency;
- applied at entry and again at exit.

This is deliberately marked:

`ASSUMED_PUBLIC_TARIFF_PLUS_CONTINGENCY`

It is not an actual-fill cost.

## Sizing

Frozen policy:

`SIZING_POLICY_V1_FIXED_500_EUR_ONE_UNIT`

For one proposed structure unit:

`reserved risk = theoretical expiry max loss + estimated round-trip cost`

The proposal is blocked when converted reserved risk exceeds EUR 500.

There is no automatic bankroll replenishment.

## Admission semantics

If admitted, Christiania creates the exact existing candidate label:

`CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING`

It then appends explicit system lifecycle events:

`SURFACED → INVESTIGATED → DECIDED → SHADOW_TRACKED`

and pins the underlying for future outcome collection.

These transitions mean deterministic **research** admission only. They do not
mean a human approved a live trade.

## Universe evidence

The target contract must have:

- Massive listing reference;
- usable Massive snapshot reconciliation;
- present ThetaData quote evidence;
- present ThetaData Greek evidence.

A Massive snapshot disagreement is retained as
`DISAGREEMENT_RECORDED`; absence of usable reconciliation is blocked.

## Persistence

Migration 012 adds immutable:

- `fx_observations`
- `shadow_admission_decisions`

Admission is idempotent for the same proposal, sizing-policy version and
cost-model version.

## Important limitation

The candidate's historical `max_theoretical_loss_minor` column did not carry a
currency field. From this admission layer forward, admission evidence makes
the denomination explicit: admitted candidates receive the **EUR-cent**
theoretical max loss, while the full USD source risk, FX conversion, costs and
total EUR risk reserve remain recorded in `shadow_admission_decisions`.

A later schema cleanup may make candidate risk currency explicit directly on
`shadow_candidates`, but v12 does not rewrite historical candidate evidence.

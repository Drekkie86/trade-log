# Christiania: trading-first operator interface (draft)

## Single product objective

**Find options trades with defensible, positive expected net profitability
after all realistic costs, and prospectively establish that those signals
outperform doing nothing.** No feature/model/table count is a success metric.

## What the operator sees

- **Trade Desk** (first/default page): one decision; qualified candidates
  clearing the *complete* profitability/evidence gate; newest proposal session;
  actual missing stock-source coverage for the latest completed run; quantitative
  rejection reasons. NO TRADE is a valid outcome. No old all-quote table by
  default. Historical model-screened butterflies are collapsed diagnostics
  with explicit no-recommendation labels.
- **Performance**: independent priced expiry evidence counts and explicit
  lack of broker-verified realized P&L. Do not mix provider-model Greek spot
  proxies, paper expiry intrinsic, correlated candidate replays and real
  account P&L. Real money made is the *eventual* primary score, not model
  agreement or synthetic win rate.
- **System**: a concise data and backup health state; any failed recovery
  point is a release blocker and not cosmetic.
- **Advanced tools**: original Trade Ideas, Shadow Lab, Casino, legacy
  dashboard, calibration, observations and old detailed reports remain
  accessible for historical audit **but are not alternative trade authority**.
  They will be retired or converted into drill-downs once a single persisted
  canonical decision/evidence stream replaces their disparate readers.

## Why the current Trading Desk deliberately displays NO TRADE

The old pipeline is a local IV surface anomaly scanner with a butterfly-only
candidate builder. It is NOT the new multi-strategy profitability engine.
Its 'WORTH A LOOK' label and 3 correlated smile model fits cannot establish
positive net P&L. Reclassifying them as new vetted trades would be wrong.

The shared seven-family model comparison/ranker is pure and locally tested,
but a broker-eligible recommendation cannot be shown until independent
up-to-date source evidence, real forecast distributions with frozen prior
training cuts, prospective controls, cost/slippage/side-depth and exit-path
evidence, and a durable candidate ledger are connected. The dashboard
explicitly reports this missing linkage instead of presenting synthetic
trade picks or a zero win rate as an economic performance estimate.

## Current data contracts

- `src/decision/operator_profit_desk_v1.py` derives ONE operator summary
  from existing `TradeIdea`/opportunity models and (when available)
  `MarketDecision` from `unified_trade_ranker_v1.py`. Legacy results do
  not become promoted opportunities. The newest research run's independent
  stock observations are checked with the same strict 15s source clock and
  exact Massive source marker. All reads bounded by 64 source snapshots.
- `src/ui/profit_desk_page_v1.py` renders front-door and accountability
  screens using cached existing indexed idea readers; no migration or
  write-through state; no new full-database scan.
- `src/dashboard/read_model.py` declares explicit light page partitions
  `Trade Desk` and `Performance`, preserving page-specific performance.

## Non-negotiable next gate

**Not complete until** the user can see a ranked, credible trade list with
fully enumerated legs, real timestamps/side sizes, expected net return in
EUR after all brokerage costs, comparable downside, independent forecast
support and dissent, strategy-specific exit, and actual calibrated
outcome versus matched controls. The same canonical decision lineage
must feed every drilldown and the speculative budget lane.

A historical high apparent model edge **must not** substitute for any
of the above. NO TRADE is preferable to a fictional success.

## Production release

No automatic deployment from this draft. The checked 24 Oct server
had active core services, but `christiania-backup.service` failed and
`christiania-status` reported supervisor UNHEALTHY / ready=false.
Recent compressed backup files existed, yet their recovery-point validity
remained unverified by operational readiness. Resolve the backup recovery
control and require exact-main green CI, performance probe and rollback.


## Source qualification diagnostics — 24 October follow-up

Previously the independent stock reference extractor returned NULL silently
when Massive's option-chain asset payload failed the strict Theta decision
cut. The collector now writes a bounded `source_disposition=REASON` note
to each **new** Theta market snapshot when no qualified stock price is
available. Diagnostic reasons distinguish no option-chain data, no
underlying asset, wrong/missing ticker, nonpositive price, invalid
nanosecond timestamp, future value, stale value at Theta cut, and
contradictory same-timestamp prices. The extraction gate is unchanged.

The Trade Desk's bounded latest-run read-model aggregates those recorded
reasons rather than presenting a meaningless zero. Historical snapshots
without recorded reasons stay explicitly labelled
`LEGACY_NO_REJECTION_REASON`; they are not retrospectively reclassified.

**Important:** This instrumented patch does NOT establish that Massive's
current license includes a sufficiently fresh stock price, nor does it
solve the provider ordering mismatch. Current collector flow retrieves
Massive's option-chain asset early, before Theta quotes and Greeks; its
stock timestamp can age out of the 15-second source gate. The exact real
source reason should be measured on the next market-session collection
before changing provider calls, freshness rules, quota or schedule.
Failing closed is essential to the integrity of all expiry-outcome
evaluations.

No live deployments, broker orders or schema changes are included.


## One immutable cross-strategy decision book — development schema v38

Schema v38 adds only an append-only, indexed
`unified_candidate_decisions_v1` table. The single economic opportunity
identity is unique per (research run, source snapshot, trading lane, option
structure, frozen source reference). A later rerun with altered costs,
models or prices cannot overwrite, delete or create a duplicate decision.

`freeze_market_decisions()` recomputes the unified ranker itself, reads
the server UTC clock (callers cannot backdate the event), insists the
source snapshot and every referenced leg exist in the same research
run, and demands an independently sourced stock reference with the
unchanged 15-second window. It refuses a freeze more than 15 minutes
after the source capture and refuses expired candidates. It writes
both NO_TRADE and manual-requote states **atomically** with exact leg
and model distribution inputs, dependence groups, assumed costs,
risk limit, forecast training cut, proposed exit, reason codes and
tamper-evident SHA-256 input hash. No stored record is a broker order.

`load_latest_frozen_book()` verifies that frozen input digest,
identity and timestamps before presenting the one ranked decision
to Trade Desk. The ranker's current model inputs are NOT yet backed
by an independently validated forecasting process. Consequently,
current write paths tag evidence `UNPROVEN_MODEL`, and the reader
does not promote these rows to actionable manual re-quotes.

**Unfinished:** wire prospective writer into the actual collection
cycle at the time each snapshot is captured, define and validate
independent forecast distributions, establish the paper exit/mark
evaluation and matched controls, and make Performance read that
same outcome ledger. This work is not proof of positive expectancy.

**Deployment gate:** schema v38 is a migration release, not a
no-schema UI update. At the current multi-GB DB size, the release
pipeline requires a verified, schema-aware rollback/recovery copy
and exact-SHA production-scale probe. The active server remains
at schema v37, with backup supervisor readiness NOT PASS; never
apply migration until the release control is satisfied.

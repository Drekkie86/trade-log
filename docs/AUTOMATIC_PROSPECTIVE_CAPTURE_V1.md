# Christiania P0 — automatic prospective selection capture

**Goal:** rank *profitable, independently evidenced option trades*, not
collect disconnected strategies or fabricate successes.

## Integrated runtime path (schema v38)

`run_independent_research` → each `collect_underlying` →
Massive option reference & snapshot → Theta quote/Greek acquisition →
**persist Theta snapshot and option quote legs** →
`capture_frozen_snapshot(research_run_id,snapshot_id)` →
common 7-family option geometry/economic evaluation →
**one immutable cross-strategy decision set plus disposition** →
finish underlying → existing legacy scanner → mark collector.

No new provider calls, no trading permission, no broker orders.
Original legacy butterfly records remain historical diagnostics only.

### What gets frozen

When the snapshot's independently sourced stock price qualifies and
the same-snapshot chain has valid referenced option multipliers,
up to 200 candidate structures across max six expiries are evaluated.
Every eligible family receives the **same absent/available forecasting
inputs**; no family invents a probability distribution. In this first
runtime cut, model_inputs=() for all, therefore every retained candidate
is a strictly **NO TRADE / UNPROVEN_MODEL** prospective observation, not
a profitable recommendation. The signed option legs, quoted bid/ask,
retrieval source IDs, risk budget, assumed costs, forecast absence,
score, missing evidence, and exit status are preserved.

The decision writer reads the real server clock, refuses as-of cuts over
15 minutes old and an invalid source clock, and requires source quote IDs
within the **same** market snapshot. No later outcomes are used to create
or revise decisions. The 7 candidate decisions and capture disposition
are committed in the same SQLite transaction. Existing row triggers
prevent UPDATE/DELETE and a unique economic identity prevents
retroactive rescores from replacing the frozen first verdict.

### Failure is explicit

Every new captured snapshot receives exactly one append-only record
in `unified_capture_dispositions_v1`:

- FROZEN_NO_TRADE — seven or fewer families frozen with no approved
  independent predictive forecast
- NO_SOURCE — the real stock observation was unavailable/not qualified
- NO_GEOMETRY — no set of option strikes supports known retail geometry
- EVIDENCE_REJECTED — missing reference contracts, mismatched
  multipliers, stale/mixed quotes or other unsupported source data
- OUTSIDE_PROSPECTIVE_WINDOW — historical test/replay or overdue capture;
  these must never appear as prospective picks
- CAPTURE_FAILURE — database or evaluated evidence error, recorded
  without destroying the already captured independent market quotes

The Trading Desk now displays counts of **prospectively frozen
decisions**, snapshots attempted and independent source observations.
The old 'legacy butterflies screened/rejected' counters are no longer
primary dashboard metrics. The immutable decision book is always
anchored to the **latest actual research run**, never just the latest
run that happened to have candidate rows; a newer NO_SOURCE run must
not resurrect an older attractive trade.

### Strict limitations

This is not yet a money-making recommendation engine. The collector
now produces unbiased frozen rejection cohorts. Genuine ex-ante
market return/volatility/event forecast distributions with calibrated
out-of-sample performance are still required; one model fit cannot be
three independent confirmations. The result evaluator and matched
NO TRADE/alternative trade controls must be attached to these exact
frozen records with broker-realistic costs, fills, exit marks and
expiry/assignment risk.

Missing broker executable size/quotes and absent live forecasting
evidence retain a hard NO TRADE gate. Positive hypothetical payoff
is not a validated profit claim.

### Performance / release controls

No schema upgrade has been applied to the production DB. This is a
**schema-v38 migration** release and requires a verified large-DB
rollback snapshot, exact-main green GitHub quality gate, production-
scale read/capture performance, headroom, service quiesce, atomic
activation and rollback test. Production backup service is failed
and supervisor readiness is UNHEALTHY, so **do not deploy**.

Full suite and collector integration tests must pass before branch
merge. On next instrumented US market session, review actual Massive
asset entitlement/staleness disposition codes and resolve acquisition
rather than loosening the current independent-price 15s rule.


## Bounded real-world option universe (not an artificial 2,500-quote veto)

The live collector can store more than 2,500 quotes and dozens of listed
expiries for liquid symbols. Instead of discarding all of them or taking
the first arbitrary source rows, `bounded_chain_selection_v1.py`
precommits maturity targets at 7, 14, 21, 30, 40 and 45 days, choosing
at most six distinct listed expiries from a source set bounded to 64.
For each maturity it uses the actual independent stock reference to
choose at most five *common call/put* strikes around the money, covering
one center plus up to two lower and two higher strikes.

This gives the seven retail payoff expressions the same <=60 authentic
option quote receipts, with their original timestamps and contract
multiplier joins. The quotes do not become executable merely because
they are selected. Multiple provider records for the same quote identity
are rejected rather than collapsed into a synthetic quote. The
maturity/strike selection is before prospective outcomes and cannot be
optimized using future payoffs.

The ledger now independently verifies every selected option leg against
its stored quote id, original strike, right, expiration, bid, ask,
quote timestamp and the single Massive listing multiplier. A real
quote ID **cannot** be used to disguise a made-up fill price or payoff.
Any mismatch aborts the entire snapshot decision transaction.

The latest Trade Desk read is anchored to the most recent research
run, even if that run has no frozen proposals: an older recommendation
cannot be resurrected while new source evidence is failing.

**Known limits:** this deterministic near-money sampling is not an
optimizer over all strikes or expiries and does not establish edge.
Wide wings, other spread topologies, individual symbol event filters
and broker-side executable depth need independent prospective
validation and controlled expansion before selection authority.

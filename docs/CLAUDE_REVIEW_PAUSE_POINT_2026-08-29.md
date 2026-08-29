# Christiania — Claude hostile review pause point

Date: 2026-08-29

This is the intended pause point for an external hostile review before building
the next major discovery/screening layer.

## What is now established

### Provider architecture

Working direction:

Massive current chain/model snapshot
-> ThetaData historical/bulk quote evidence
-> canonical identity join
-> Christiania research models
-> Saxo final broker/account/execution verification
-> human/manual order

Saxo is no longer treated as a bulk quote bus.

### ThetaData seam

ThetaData Free via local Theta Terminal was validated.

Observed v3 EOD response shape:

`{"response": [...]}`

Historical EOD option rows expose, among other fields:

- contract symbol/expiration/strike/right;
- bid/ask;
- bid_size/ask_size;
- exchange/condition codes;
- OHLC;
- volume/count;
- provider `created`;
- `last_trade`.

### Identity reconciliation

AAPL/XOM/JPM were reconciled Massive <-> ThetaData on 2026-08-28.

For all three:

- 100% of non-expired Massive identities were found in ThetaData;
- zero Massive-only identities;
- zero ThetaData-only non-expired identities;
- zero duplicate canonical identities;
- zero key-construction failures.

Historical ThetaData-only differences were entirely already-expired contracts.

### Historical staging

A separate SQLite staging database was created:

`thetadata_history_staging.db`

It does not touch `trade_log.db`.

August 2026 data for AAPL/XOM/JPM was loaded across 20 weekday sessions.

### Empirical diagnostics v1/v2

Observed dataset:

- 59,104 quote observations;
- 53,968 identical-contract next-observed-session matches.

Quote-state:

- positive two-sided: 71.748%;
- zero bid: 28.252%.

Spread / mid, positive bid+ask only:

- median ~8.7%;
- p75 ~19.0%;
- p90 ~77.2%;
- p95 ~138.5%.

Ask-to-bid one-session return:

ALL:
- median ~-22.2%.

Positive bids both days:
- median ~-7.9%.

Positive bids both days + entry spread/mid <=25%:
- median ~-5.5%.

Very cheap options showed extremely hostile ask-to-bid economics.

Robust daily median cross-underlying option-return correlations were near zero
to mildly negative, unlike earlier naive mean-based correlations. Therefore the
mean-based dependence estimate was not promoted.

These results are descriptive EOD market-structure findings only.

No edge claim has been made.

## New research governance freeze candidate

`research/edge_discovery/EDGE_DISCOVERY_PROTOCOL_V1.md`

Key rules:

- IDEA -> SETUP -> CONTEXT -> TRADABILITY -> EMPIRICAL FINDING ->
  CANDIDATE EDGE -> VALIDATED EDGE;
- Edge Statement written before confirmation;
- discovery and confirmation datasets separate;
- multiplicity/family size explicitly recorded;
- measurement universe distinct from executable universe;
- costs are part of the hypothesis;
- comparator/control defined in advance;
- strict result vocabulary;
- process quality separate from economic edge;
- Speculation Mode separate from validated edge claims.

## What is NOT frozen yet

- exact screening/discovery feature families;
- exact statistical confirmation test for first edge family;
- empirical tradability cost model;
- historical discovery/confirmation time split;
- canonical promotion of ThetaData staging data;
- Cohort 002 final preregistration;
- paid ThetaData subscription decision;
- automatic order placement.

## Review request

Please review this as a hostile quantitative/research-methodology reviewer.

Prioritize finding ways Christiania could still fool itself.

Specifically attack:

1. survivorship / listing-history bias in historical option chains;
2. whether EOD quote snapshots are usable for the intended cost estimands;
3. stale/locked/crossed/zero-bid quote semantics;
4. whether `created` has been handled conservatively enough;
5. hidden selection introduced by Massive/ThetaData chain coverage;
6. next-observed-session matching bias;
7. premium-denominator pathologies;
8. DTE-calendar vs trading-day semantics;
9. dependence/effective-N estimation;
10. multiple testing and researcher degrees of freedom;
11. whether the proposed Edge Statement is actually sufficient to prevent
    post-hoc rationalisation;
12. whether tradability modelling risks reintroducing adverse selection;
13. whether the €500 bankroll can create a structurally bad candidate universe;
14. what should be measured before any real trade;
15. what should block a first live defined-risk trade.

Please classify findings as:

- BLOCKER
- MAJOR
- MINOR
- ACCEPTABLE

For each BLOCKER/MAJOR finding, propose the smallest concrete fix.

Do not reward complexity for its own sake. Prefer fewer tests and fewer models
when they provide stronger identification.

The desired outcome can be:

INSUFFICIENT EVIDENCE

Christiania is not required to discover an edge.


## Post-review correction notice

The v1/v2 ask-to-next-bid and dependence interpretations are retired pending
diagnostics v3. The old next-session matcher pooled held-to-expiry outcomes
with surviving contracts, and the median-based dependence statistic could be
pinned near zero by the full-chain return distribution. Dependence is currently
UNIDENTIFIED. August 2026 is registered discovery data and cannot be reused for
confirmation.

## Cohort 001 status

Cohort 001 has NOT yet run. It remains scheduled for Monday 2026-08-31 under
its frozen preregistration and launcher. Nothing in the ThetaData/edge work may
displace or weaken that run.

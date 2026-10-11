# Bounded Saxo shadow leg-depth probe — research gate V1

**Issue:** #98 (execution evidence) and #96/#100.
**Status:** isolated draft, disabled by default, no deployment.
This component is separate from PR #103's prospective paper P&L calculator.

## Verified production blocker

On October 11 live Saxo option observations had 30 rows: 19 STALE,
11 UNAVAILABLE, zero EXECUTABLE, last ingestion August 31.
The current autonomous daemon runs Massive/ThetaData research, not
the older Saxo cohort quote bridge. ThetaData option_quotes lack
bid/ask depth. This prohibits claiming broker-executable outcomes.

## Source and request constraints

The new module src/research/saxo_shadow_depth_probe_v1.py:

- Samples ONE explicitly selected candidate, maximum FOUR unique
  frozen option legs. At most four calls to the existing
  SaxoClient.get_option_contract_and_quote interface, GET-only.
  Underlying Saxo client may make several HTTP calls per leg.
- All provider requests disabled unless allow_provider_get=True.
  Never manages Saxo tokens, refreshes accounts, or places orders.
  Caller injects an already authorized read-only SaxoClient.
- Uses XNYS calendar/session window; no requests Sunday, holidays,
  market closed or outside allowed sampling hours.
- Database reads are SQLite mode=ro, query_only, exact indexed
  candidate and latest-state lookup, with 1-second query interrupt;
  never writes to production or any database.
- Requires active SHADOW_TRACKED, unique valid leg identities,
  non-expired options, small strictly bounded leg counts, matching
  Saxo underlying/right/strike/expiry/contract multiplier/UIC.
- Uses existing Saxo executable-quality classifier PLUS positive
  noncrossed bid/ask, adequate size on BOTH sides, observed source
  quote no more than 15 seconds before fetch completion, 15-second
  maximum cross-leg as-of skew and no future evidence.
- Stops on first provider/identity/timestamp failure. Provider
  exception bodies are never copied into the audit (may contain
  secrets). Produces in-memory evidence with source prices,
  sizes, timestamps, provider quality and SHA-256 digest.

Even with every check passing, each candidate sample MUST remain
observation_only=true, independent_package_execution_verified=false,
outcome_eligible=false and trading_enabled=false. There is no package
fill verification, automatic outcome scoring, DB insertion or order.

## Production and science dependencies

- Saxo credentials, entitlements and next-session quote freshness
  need independent testing. Fake provider tests never prove validity.
- Four-leg limit bounds the number of logical samples, but the
  current Saxo contract resolver repeats option root/space lookup
  for every leg. Before unattended sampling, add shared root and
  expiry-space reuse and measure worst-case end-to-end latency.
- No persistent append-only Saxo shadow research journal or
  supervised daemon integration yet. That must come next, with
  deduplicated sessions, explicit failed attempts and strict resource
  budgets. Do not silently enable quote capture.
- Current historic candidate FRESH labels are unverified; even
  successful provider quote probes on them cannot become validated
  P&L or prove source-side entry executability.
- A live Saxo leg quote with depth is NOT firm complex-order
  execution, nor does it establish actual broker fees, taxes, FX,
  assignment/exercise, settlement or fill. Independent package
  receipt source remains necessary.
- PR #102 (per-leg entry provenance) and #103 (paper outcome
  arithmetic/readiness) remain separate unmerged review branches.
  Their changes must be reconciled through main CI/performance
  and deployment safeguards before production.
- Negative, unfillable, unobservable, rejected and NO TRADE
  opportunities must remain in the prospective denominator.

## Synthetic tests

Run: python -m pytest -q tests/test_saxo_shadow_depth_probe_v1.py

Fake Saxo observations and a tiny isolated SQLite fixture exercise
the default-off path, market-session safeguards, source identity,
timestamps, size, expiration, market quality, provider errors and
non-promotion contract. Nothing calls Saxo over a real network.

Gate C remains NOT PASSED. No unattended Saxo activation,
trading, merge, deployment or outcome promotion authorized.

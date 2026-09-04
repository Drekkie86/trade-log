# Christiania Research Daemon v1 + Shadow Outcome Collector v1

This slice changes Christiania from a manually invoked research engine into a
repeated market-sampling process.

## Default cadence

The daemon samples every **15 minutes** on weekdays from:

- 09:45 America/New_York
- through 15:45 America/New_York

That is 25 samples per normal full trading day.

The first 15 minutes after the regular open are deliberately excluded in v1.

### Important calendar limitation

v1 is weekday/session-clock aware, but it is **not yet exchange-holiday
calendar aware**.

On a US market holiday it may wake up and execute a research cycle. Existing
freshness and structural gates should prevent stale evidence from becoming a
candidate, and the iteration remains useful operational evidence.

We should add an authoritative exchange calendar later rather than pretending
a hand-maintained holiday list is reliable.

## Single-daemon lease

Schema v13 adds an operational singleton lease.

A second daemon refuses to start while another daemon has a recent heartbeat.

The lease expires after 30 minutes without a heartbeat, allowing recovery after
an unclean crash.

The lock is mutable operational state. It is intentionally not treated as
immutable research evidence.

## Iteration evidence

Every scheduled iteration records:

- scheduled time;
- start/end;
- completed/failed;
- research run id;
- hypothesis scanner run id;
- proposal/admission counts;
- longitudinal mark count;
- error type/message when a cycle fails.

A provider/network exception therefore does not silently disappear and does
not kill the daemon loop.

## Longitudinal shadow marks

Schema v13 adds immutable `shadow_mark_observations`.

After each completed full research cycle, Christiania revisits every active
`SHADOW_TRACKED` candidate and attempts to mark its complete multi-leg
structure using that cycle's persisted ThetaData snapshot.

Conservative liquidation pricing:

- long leg -> bid;
- short leg -> ask.

The collector calculates:

- structure liquidation mark in USD;
- gross P&L in USD;
- estimated net P&L after the frozen admission cost reserve;
- the same P&L in EUR using the **entry FX observation**.

Using entry FX isolates option-expression performance from later FX movement.

## Freshness treatment

The collector preserves each leg's raw quote timestamp.

It deliberately labels a complete mark:

`COMPLETE_UNVERIFIED_FRESHNESS`

rather than silently claiming that the outcome collector independently
revalidated freshness.

This is conservative. A later version can reuse the canonical quote-age
classifier and promote marks to an explicitly freshness-qualified state.

## Why not reuse `shadow_outcome_observations`

The v8 table contains a small frozen set of outcome horizons and enforces one
row per candidate/horizon.

That is appropriate for milestone outcomes, but not for 15-minute longitudinal
sampling.

`shadow_mark_observations` therefore stores the high-frequency longitudinal
series while the older outcome table remains available for later derived
milestones such as MFE, MAE and terminal expiry.

## Data-volume perspective

At the current AAPL/JPM/XOM universe, one full cycle has roughly 1,900 option
rows.

At 25 samples/day this is roughly 47,500 contract observations per normal
trading day before adding model/evidence rows.

That is enough to begin building a serious longitudinal dataset without
pretending that adjacent 15-minute observations are independent samples.

The next scale lever should primarily be **more liquid underlyings and more
market regimes**, not blindly moving to per-second polling.

## Running

Keep Theta Terminal running.

Then:

```powershell
python .\run_christiania_daemon.py
```

Stop cleanly with Ctrl+C.

For a one-iteration rehearsal:

```powershell
python .\run_christiania_daemon.py --max-iterations 1
```

If started outside the sampling window, the rehearsal waits until the next
configured slot.

## Safety boundary

The daemon does not place broker orders.

Any admitted candidate retains:

`CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING`


## V1.0 bounded transient recovery

The independent research runner performs one immediate per-underlying recovery
attempt for narrowly classified transient Massive failures: network exhaustion,
rate-limit exhaustion, and exhausted HTTP 5xx server failures.

Recovery stays inside the same research run and retries only the underlying
that failed. Already-successful underlyings are not collected again.
`research_run_underlyings.retry_count` records the retry and `research_runs.notes`
records the triggering error and successful recovery.

ThetaData and arbitrary application/database failures are deliberately not
auto-retried yet because they can occur after evidence persistence. Generalized
recovery requires explicit idempotency first.

Default: one recovery attempt after a two-second delay. Massive's own internal
request retries still happen before this recovery layer. No broker orders.

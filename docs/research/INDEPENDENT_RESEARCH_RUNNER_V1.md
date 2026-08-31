# Independent Research Runner v1

## Goal

This is the first standalone Christiania research engine.

It is deliberately **not** a trading engine and does not yet create scanner
candidates.

Default command:

```powershell
python .\run_christiania_research.py
```

Default universe:

- AAPL
- JPM
- XOM
- 7–45 DTE

## What one run persists

For each underlying:

1. Massive reference listing frame.
2. Massive snapshot PRESENT/ABSENT reconciliation.
3. Massive snapshot-only anomalies.
4. ThetaData quote availability and raw quote timestamp.
5. ThetaData Greek/model availability and quality state.
6. ThetaData provider-only anomalies.
7. Actual ThetaData bid/ask market snapshot rows.
8. Actual ThetaData provider-derived IV/Greeks in
   `provider_model_observations`.
9. Structural-admission diagnostics in the returned run summary.
10. Research-run and per-underlying completion/failure state.

The runner records the current Git SHA and a SHA256 hash of the normalized
runner configuration.

## Important boundaries

The runner creates:

**research evidence**

It does not create:

- shadow candidates;
- live trades;
- Saxo orders;
- ML predictions;
- edge claims.

This is intentional. The independent evidence database must exist before
Christiania is allowed to evaluate whether a deterministic scanner or later
ML challenger adds predictive value.

## Session state

The v1 runner labels evidence as PRE_OPEN / INTRADAY / POST_CLOSE /
NON_TRADING_DAY using New York weekday and clock time.

That is adequate for evidence labelling in v1 but is **not yet an exchange
holiday calendar**. Before session-state-sensitive autonomous scheduling, a
real market calendar should replace the weekday/clock approximation.

## Failure semantics

Each underlying has an explicit ATTEMPTED → SUCCESS/FAILED row.

If an underlying fails, the run becomes FAILED and the exception is surfaced.
Evidence already committed for earlier successful underlyings remains as
immutable partial evidence attached to the failed run. The runner does not
silently retry or silently relabel a failed run as complete.

Chunked/resumable run semantics remain deferred until real data volume proves
they are necessary.

## Next step

After this runner has produced clean repeated evidence, the next layer is a
versioned deterministic scanner that reads the persisted evidence and may
produce zero or more shadow candidates.

ML remains downstream of this research database.

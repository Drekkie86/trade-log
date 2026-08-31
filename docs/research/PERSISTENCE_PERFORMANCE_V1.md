# Persistence performance hardening v1

Scope is intentionally narrow.

Implemented:
- WAL mode for file-backed repository connections.
- SQLite backup API for v8/v9 rehearsal, backup and restore paths.
- Batch `executemany` insertion for listing-reference contracts.
- Batch `executemany` insertion for provider-observation availability.
- Massive reference persistence uses the batch path.
- Massive snapshot availability persistence uses the batch path.
- Existing single-row APIs remain available.
- A checked-in 10,000-row benchmark compares single-row vs batch persistence.

## Verified benchmark — Windows development machine

Command:

```powershell
python .\benchmark_persistence_v1.py --rows 10000
```

Observed result on 2026-08-31:

- rows: 10,000
- single-row path: 104.428 s
- batch path: 0.070 s
- observed speedup: 1489.58x

Approximate per-row cost in this run:

- single-row path: ~10.4 ms/row
- batch path: ~7 microseconds/row

The durable finding is **not** that Christiania will always be 1489.58x
faster when batching. Absolute timings and multipliers depend on hardware,
operating system, filesystem, storage latency, antivirus/background I/O,
SQLite settings, cache state, and workload shape.

The durable mechanism is that the old compatibility path committed one row
at a time, repeatedly paying connection/transaction and durable-write costs.
The batch path performs many inserts inside one transaction and amortizes
those costs across the batch.

Therefore benchmark results from other environments should be treated as
environment-specific measurements rather than portable performance constants.

The checked-in benchmark remains the reproducible way to measure the effect
on the machine and environment actually running Christiania.

## Architectural implication

This result supports the current sequencing decision:

1. batch hot write paths first;
2. keep SQLite single-writer;
3. parallelize acquisition only where useful;
4. defer chunked/resumable run semantics until real collector size requires it;
5. revisit Postgres only when there is an actual concurrent-writer requirement
   or a demonstrated database bottleneck.

The benchmark shows that per-row commit overhead was a dominant avoidable cost
on the current Windows machine. Removing that bottleneck materially delays the
point at which more invasive persistence architecture changes become necessary.

Explicitly not changed:
- research-run lifecycle semantics,
- chunked/resumable runs,
- scanner behavior,
- shadow lifecycle,
- provider-universe logic,
- multiple concurrent SQLite writers,
- database engine.

The performance policy remains:
parallelize acquisition where useful, serialize persistence, and revisit
Postgres only when a real concurrent-writer requirement appears.

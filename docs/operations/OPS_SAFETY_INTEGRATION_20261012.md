# Christiania operational safety integration — October 12, 2026

**Draft integration of PRs #109, #110, #111. Do not merge or deploy on
individual PR test results alone. No schema migration or trading changes.**

## Verified production findings

- Oct12 live daemon completed 22 research cycles with fresh Theta snapshots.
  No prospective research cycles were recorded Oct6-9.
- Systemd supervisor repeatedly FAILED solely on daemon cgroup memory
  warning: current 803,332,096 B, warning 536,870,912 B. Process RSS
  ~168 MiB; inactive_file page cache 548,634,624 B; effective working set
  ~243 MiB. Historical cgroup memory.high counter=396; rate unmeasured.
- Nightly operational audit repeatedly hit its 30-minute systemd timeout.
  Its deep backup inventory was a plausible expensive step but timing
  attribution is not proven until stage logs run in production.
- Two ordinary backup data files exist: Oct1 27,143,593,984 B and Oct8
  27,875,274,752 B. Both require independent restore verification.
- Backups directory also contains a September 25 schema-v33 rollback DB
  of 21,304,389,632 B, which is NOT an ordinary backup. Do not delete or
  relocate before confirming live rollback pointer and remote copy.
- Production free disk ~38.55 GB (35.9 GiB); latest restore drill failed
  capacity preflight needing ~43.97 GB. No restore or file cleanup ran.
- Existing backup capacity planner could remove the oldest of TWO full
  recovery points prior to creating/verifying its successor.

## Integrated changes

1. Supervisor: only subtract validated cgroup-v2 inactive_file from
   MemoryCurrent for effective working-set warning; missing/malformed
   cgroup data strictly falls back to original raw threshold. Existing
   high/max memory policies retained.
2. Nightly audit: metadata-only backup listing, explicit NOT_REVERIFIED,
   distinct blocking UNVERIFIED readiness state (not falsely ABSENT or
   PASS), safe flushed stage timing. Deep backup/restore controls remain.
3. Verified backup: when retention target is at least 2 and two ordinary
   copies exist, fail before deletion if there is not enough room to
   create and verify a new full copy while retaining both. Explicit
   retention=1 remains a distinct high-risk operator choice.

## Test and deployment status

All three branch heads were merged into an independent local integration
branch; no conflicts. Cross-component local Python 3.13:
94 tests PASS, 1 skipped. Full exact-SHA GitHub Windows/Ubuntu CI plus
production-scale preflight/performance/rollback/monitoring still mandatory.

THE CODE IS NOT DEPLOYED. With insufficient disk capacity the new backup
guard correctly aborts, leaving recovery copies untouched but no new
backup. Recovery assurance is NOT restored until storage is expanded or
the old rollback is independently archived, a new full verified backup
is produced, and a complete off-market restore drill passes.

## Release blockers

- Confirm safe rollback headroom and backup retention without deleting
  unverified recovery assets.
- Check actual service unit paths and exact production revision; active
  main and production revision currently differ.
- Require an exact-main green GitHub quality gate for any release.
- Confirm Python 3.13 exact Linux dependency lock, no concurrent deploy,
  migrations/WAL and secure edge; no needlessly huge rollback copies
  for no-schema releases.
- Verify production-scale audit, supervisor, memory pressure deltas and
  research latency; no performance regression.
- Check app/daemon/Theta/services/timers/secure edge and active SHA
  after a server-side atomic activation, with automatic rollback.
- External alerts are configured but actual email delivery and dead-man
  monitoring have not been proven.
- No broker/live trades, no money-trade readiness, no validated edge.

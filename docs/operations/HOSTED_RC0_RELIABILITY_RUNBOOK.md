# Christiania Hosted RC0 — Reliability Runbook

## Release intent

RC0 is a continuously operating **research and shadow-decision workstation**.
It is not a broker and it has no order-submission path.

The deployment must be pinned to one Git commit. Do not edit files directly
under `/opt/christiania`.

## Host baseline

- Ubuntu 24.04 LTS.
- Java 21+ for Theta Terminal v3.
- Python virtual environment created by `deploy/install_one_vm.sh`.
- Persistent Christiania state under `/var/lib/christiania`.
- `/opt/christiania` is application code, not the live database.
- Streamlit, Theta HTTP and oauth2-proxy internal listeners remain loopback-only.

The database is already multi-gigabyte. Size the host for the live DB plus
retained full backups and growth. For the current ~3.7 GB DB and 14-backup
retention, do not use a tiny root disk. Prefer at least 100 GB of durable
storage until retention/remote-backup policy is formally changed.

## Health architecture

There are two health layers.

### Lightweight supervisor — every 5 minutes

`christiania-supervisor.timer` checks:

- schema/WAL/read-model readiness without SQLite full-file integrity scans;
- research-daemon heartbeat;
- Theta readiness;
- required systemd services and timers;
- effective service memory policy and current memory use;
- backup-file metadata freshness;
- absolute and percentage free-disk headroom.

It writes:

`/var/lib/christiania/audit/rc0_supervisor_status.json`

The supervisor service retains `ProtectSystem=strict`. Its sandbox exposes only
`/var/lib/christiania/data` and `/var/lib/christiania/audit` as writable paths.
The data-directory exception is required for SQLite WAL/shared-memory access
even though the supervisor opens Christiania's database through the read-only,
query-only runtime path. The supervisor itself contains no database mutation
workflow.

Optional state-transition alerts use `CHRISTIANIA_ALERT_WEBHOOK_URL`. Only
operational states and failed-check summaries are sent. Secrets are never
included.

### Service memory containment

Memory control is per systemd service. There is no scheduled VM reboot and the
supervisor does not restart processes itself.

| Service | Supervisor warning | `MemoryHigh` | `MemoryMax` |
|---|---:|---:|---:|
| Theta | 1024 MiB | 1536 MiB | 2560 MiB |
| Research daemon | 512 MiB | 768 MiB | 1280 MiB |
| Command Deck | 384 MiB | 512 MiB | 1024 MiB |

The three levels have different meanings:

1. The supervisor warning threshold is an early operational boundary. Reaching
   it makes RC0 `UNHEALTHY` and can trigger the existing state-transition alert.
2. `MemoryHigh` is a systemd/cgroup pressure boundary. It is not merely a
   warning; Linux may reclaim/throttle the cgroup above it.
3. `MemoryMax` is the hard cgroup ceiling.

All three core units use `OOMPolicy=stop`. If systemd recognizes an OOM event,
remaining processes in that unit are stopped; the unit's existing `Restart=`
policy remains responsible for process recovery.

The supervisor reads the **effective** `MemoryCurrent`, `MemoryPeak`,
`NRestarts`, `MemoryHigh` and `MemoryMax` values from systemd. A missing or
malformed current-memory value, or drift in the effective high/max limits, is a
blocking failure. `MemoryPeak` and `NRestarts` are retained as forensic
telemetry and do not by themselves make RC0 unhealthy.

Do not deliberately force an OOM on the production RC0 host as a routine
acceptance test. Verify configured/effective limits with `systemctl show` and
use ordinary service-restart/failure-injection rehearsals.

### Deep health — every 6 hours

`christiania-health.timer` retains the existing strict health path, including
SQLite `quick_check`, foreign-key verification and verified-backup inspection.

This cadence is intentionally slower because those operations read
multi-gigabyte files.

## Optional RC0 environment settings

Add to `/etc/christiania/christiania.env` only if overriding defaults:

```text
CHRISTIANIA_RC0_MIN_FREE_BYTES=16106127360
CHRISTIANIA_RC0_MIN_FREE_FRACTION=0.15
CHRISTIANIA_RC0_BACKUP_METADATA_MAX_AGE_HOURS=30
CHRISTIANIA_ALERT_WEBHOOK_URL=
CHRISTIANIA_ALERT_TIMEOUT_SECONDS=5
```

The webhook is optional. Leaving it empty never disables local supervision.

## Activation sequence

1. Bootstrap Ubuntu dependencies:
   `sudo ./deploy/bootstrap_ubuntu_2404_rc0.sh`
2. Install Christiania:
   `sudo ./deploy/install_one_vm.sh`
3. Populate `/etc/christiania/christiania.env`.
4. Put `ThetaTerminalv3.jar` in the configured vendor location.
5. Restore/copy the database using the supported backup/restore path.
6. Run deployment preflight.
7. Activate core runtime with `deploy/activate_one_vm.sh`.
8. Activate secure edge only after DNS/OIDC are correctly configured.
9. Activate RC0 reliability:
   `sudo ./deploy/activate_rc0_reliability.sh`
10. Run the safe failure-injection rehearsal:
    `sudo ./deploy/rc0_failure_injection.sh --i-understand-this-stops-services`

## Pre-departure acceptance

Do not leave RC0 unattended unless all of these are true:

- full repository quality gate passed on the deployment commit;
- deployment preflight passes;
- strict health passes;
- RC0 acceptance reports `RC0 ACCEPTED`;
- app/daemon/Theta survive service restarts;
- effective `MemoryHigh`, `MemoryMax` and `OOMPolicy` match the release policy;
- supervisor reports current memory below all warning thresholds;
- secure edge is HTTPS + authenticated;
- internal ports are not wildcard-bound;
- at least one verified backup exists;
- restore drill passes;
- free disk exceeds both supervisor thresholds;
- supervisor timer is active;
- deep health timer is active;
- live XSP data-contract proof is completed during an actual US session;
- no broker-order path exists.

## Failure philosophy

Fail closed. Missing providers, stale daemon heartbeat, stale backup metadata,
low disk headroom, memory-policy drift, high current memory or invalid runtime
state produce `UNHEALTHY`. The supervisor does not repair or mutate the live
DB. It reports; systemd restart policies own process recovery.

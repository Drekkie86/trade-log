# Christiania V1 Operational Independence

## Purpose

Christiania V1 is not operationally ready merely because its processes are
running. The platform is ready only when there is fresh evidence that its
scheduled research workload is succeeding and an external system has recently
received the dead-man heartbeat.

This gate exists specifically to prevent a repeat of the September 2026
incident in which infrastructure appeared healthy while scheduled research was
failing.

## Invariants

1. `research-progress` is mandatory evidence. A supervisor snapshot that says
   `HEALTHY` but omits the research-production check is rejected.
2. Supervisor evidence must be fresh. The default maximum age is 12 minutes,
   configurable through `CHRISTIANIA_V1_SUPERVISOR_MAX_AGE_MINUTES`.
3. External observability is fail-closed for V1. All three endpoints must be
   configured and `CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY=1` must be set.
4. The most recent supervisor external heartbeat must have state `SENT` and be
   fresh.
5. Core runtime services must be active.
6. All operational timers must be enabled, including the V1 readiness timer.
7. `/opt/christiania/DEPLOYED_COMMIT` must contain a valid full Git SHA.
8. The readiness report is written to
   `/var/lib/christiania/audit/v1_operational_readiness.json`.

## Deliberate non-goals

This package does not claim secure public web access, offsite backup, restore
acceptance, or final V1 release acceptance. Those remain separate V1 gates.
Operational independence is necessary but not sufficient for V1.

## Production activation

Before activation, configure real external endpoints in
`/etc/christiania/christiania.env`:

- `CHRISTIANIA_ALERT_WEBHOOK_URL`
- `CHRISTIANIA_HEARTBEAT_URL`
- `CHRISTIANIA_HEARTBEAT_FAILURE_URL`
- `CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY=1`

Then run:

```bash
sudo bash /opt/christiania/deploy/activate_operational_independence.sh
```

The activation script intentionally exits non-zero unless the complete
operational gate passes. It must never print a success message merely because
systemd units are alive.

## Acceptance interpretation

`OPERATIONALLY_READY` means the autonomous runtime, workload evidence and
external dead-man signal are currently healthy. It is a point-in-time
operational truth statement, not final V1 release acceptance.

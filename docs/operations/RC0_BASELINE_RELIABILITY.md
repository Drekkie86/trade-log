# Christiania RC0 — baseline unattended reliability

## Purpose

Christiania must not treat "the process is alive" as equivalent to "research is being produced."

The RC0 baseline therefore has four independent reliability layers:

1. **Workload truth** — the supervisor checks successful research iterations.
2. **Theta self-healing** — a one-minute readiness watchdog requires two consecutive failures before triggering recovery.
3. **Preventive Theta refresh** — a daily off-market recycle reduces long-lived provider-session staleness.
4. **External observability hooks** — state-transition alerts and a dead-man heartbeat URL are supported so a separate external system can notify the operator if Christiania stops reporting.

## Theta watchdog

`christiania-theta-watchdog.timer` runs every minute.

- READY resets the consecutive failure counter.
- One failed probe records DEGRADED but does not restart Theta.
- Two consecutive failed probes produce RECOVERY_REQUIRED.
- systemd `OnFailure=` starts `christiania-theta-recover.service`.

The threshold is configurable with:

`CHRISTIANIA_THETA_WATCHDOG_FAILURE_THRESHOLD=2`

## Theta recovery

Recovery is dependency-oriented:

1. stop the research daemon if active;
2. restart Theta;
3. wait for a real READY probe;
4. clear watchdog failure state;
5. restart the research daemon only if it was active before recovery started.

If Theta does not recover, the research daemon stays stopped rather than repeatedly running against a broken dependency. If the daemon was already stopped deliberately (for example, maintenance), Theta recovery preserves that state and does not start it unexpectedly. The supervisor then reports the platform unhealthy when appropriate.

Recovery events are appended to:

`/var/lib/christiania/audit/theta_recovery.jsonl`

## Preventive refresh

`christiania-theta-refresh.timer` runs daily around 08:00 UTC, well outside the XNYS research window. It uses the same controlled recovery path.

## External observability

The supervisor supports transition alerts through:

`CHRISTIANIA_ALERT_WEBHOOK_URL`

This hardening adds a dead-man heartbeat:

`CHRISTIANIA_HEARTBEAT_URL`

When the supervisor is healthy, it pings the heartbeat URL. If the server, supervisor timer, Python runtime, or network dies, the external heartbeat provider should alert because pings stop.

Optional immediate unhealthy heartbeat endpoint:

`CHRISTIANIA_HEARTBEAT_FAILURE_URL`

To make missing external observability configuration a blocking supervisor failure, set:

`CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY=1`

Do this only after real external endpoints have been configured.

## Acceptance

After deployment:

1. enable the reliability timers with `sudo bash deploy/activate_reliability_baseline.sh`;
2. verify Theta watchdog and preventive-refresh timers have future triggers;
3. run a real one-symbol production smoke iteration;
4. force the supervisor and verify `research-progress=PASS`;
5. deliberately stop Theta in a controlled maintenance window and prove automatic recovery;
6. configure external alert and heartbeat endpoints, set `CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY=1`, and prove both unhealthy and recovery notifications.

A release is not accepted merely because systemd reports services as active.

## Watchdog dependency invariant

The Theta watchdog must be able to run while `christiania-theta.service` is
inactive. It may be ordered after Theta with `After=`, but it must not use
`Requires=christiania-theta.service`.

Reason: `Requires=` causes systemd to start Theta as a side effect of starting
the watchdog. That masks a genuine Theta outage from the watchdog and bypasses
the controlled recovery path. The intended path is:

1. watchdog observes Theta unavailable;
2. consecutive-failure threshold is reached;
3. watchdog fails and triggers `christiania-theta-recover.service`;
4. controlled recovery restarts Theta, proves READY, and restores the research
   daemon only if it was running before recovery.

## Research daemon dependency invariant

The research daemon must start after Theta and should request that Theta be
started, but it must not use `Requires=christiania-theta.service`.

Use `After=` plus `Wants=` instead.

Reason: with `Requires=`, a Theta stop or failure also deactivates the research
daemon before the watchdog recovery service runs. The recovery service then
cannot distinguish "daemon intentionally stopped for maintenance" from
"daemon was running but systemd stopped it because Theta disappeared".

With `Wants=`:

1. starting the research daemon still requests Theta startup;
2. if Theta becomes unavailable, the daemon remains active long enough for the
   watchdog to observe the dependency failure;
3. thresholded recovery can see that the daemon was active, stop it cleanly,
   restart Theta, prove READY, and then restore the daemon;
4. a daemon that was genuinely stopped for maintenance remains stopped.

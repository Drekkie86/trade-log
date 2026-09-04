# Christiania V1 — One-VM Reliability Package

## Scope

This package turns the existing research workstation into a service-manager-ready
one-VM deployment without changing scientific rules or introducing PostgreSQL.

The target remains:

- one Linux VM;
- Theta Terminal;
- Christiania research daemon;
- SQLite in WAL mode on persistent storage;
- read-only Streamlit command deck;
- verified scheduled backups;
- private ingress added separately;
- systemd as process supervisor.

Christiania deliberately does not implement its own process supervisor.

## Exchange calendar

Daemon scheduling now uses the XNYS calendar from `exchange_calendars`.

This closes the weekday-only defect. For example, Monday September 7, 2026 is
US Labor Day and is not a sampling session. The next slot after Friday September
4 at 16:00 ET is Tuesday September 8 at 09:45 ET.

The existing 15-minute regular-session edge exclusion is preserved. On a normal
09:30–16:00 session the sample window is 09:45–15:45 ET. On an official 13:00
early-close session, the sample window ends at 12:45 ET.

Calendar rules are local package data. Updating `exchange_calendars` is therefore
part of normal dependency maintenance; Christiania does not call an exchange
calendar API at runtime.

## Graceful process stop

`run_christiania_daemon.py` translates SIGTERM into the same controlled shutdown
path as a keyboard interrupt. The daemon releases its singleton lease in the
existing `finally` block.

If SIGTERM interrupts a currently running daemon iteration, that iteration is
terminalized as `ORPHANED` with `INTERRUPTED_PROCESS` before the interrupt is
re-raised. This avoids leaving a daemon iteration silently RUNNING after an
ordinary service stop.

## Deployment environment

Copy `deploy/christiania.env.example` to:

`/etc/christiania/christiania.env`

Restrict it to the Christiania service account because it contains the Massive
API key in deployment.

Required deployment settings include:

- `CHRISTIANIA_DB_PATH`
- `CHRISTIANIA_BACKUP_DIR`
- `CHRISTIANIA_THETA_JAR`
- `CHRISTIANIA_SYMBOLS`
- `MASSIVE_API_KEY`

The symbol list is comma-separated. The checked-in deployment example contains
the current 26-symbol research universe. Local interactive use retains the
three-symbol fallback when no environment universe is configured.

## Theta Terminal

`run_theta_terminal.py` uses only:

`java -jar <configured jar path>`

No undocumented Theta Terminal flags are invented. The jar path is supplied by
`CHRISTIANIA_THETA_JAR`.

## Deployment preflight

Run before enabling services:

`python christiania_deploy_preflight.py`

It validates without exposing secret values:

- supported Python runtime;
- explicit absolute persistent DB path;
- schema version, WAL, integrity and foreign keys;
- explicit absolute backup path;
- separation of backup and live-DB directories;
- presence of the Massive key;
- configured Theta jar exists;
- Java is on PATH;
- XNYS calendar loads and recognizes Labor Day 2026;
- Streamlit imports;
- deployment research universe is configured.

JSON mode:

`python christiania_deploy_preflight.py --json`

## systemd units

Templates live in `deploy/systemd/`:

- `christiania-theta.service`
- `christiania-daemon.service`
- `christiania-app.service`
- `christiania-backup.service`
- `christiania-backup.timer`
- `christiania-health.service`
- `christiania-health.timer`

The application binds to `127.0.0.1:8501` in the service template. This is
intentional: private ingress/Tailscale is a separate deployment boundary rather
than making Streamlit directly public.

The backup timer runs once daily at 23:30 UTC and is persistent across VM
shutdowns. The backup implementation remains SQLite online backup + integrity
verification from Package 2.

The health timer runs every five minutes and uses:

`python christiania_health.py --strict-daemon --json`

Strict daemon health additionally requires a singleton daemon lease with a
heartbeat no older than three minutes. Default interactive health remains DB
readiness-only so historical inspection still works when the daemon is stopped.

## No scientific change

This package does not alter:

- model registry roles;
- local-surface model form;
- anomaly thresholds;
- hypotheses;
- prospective freeze boundaries;
- p-value/FDR state;
- structure builder rules;
- shadow admission rules;
- bankroll rule;
- broker execution.

There is still no live-order path in the web application or daemon.

## Remaining deployment work

After this package is merged, the next deployment package can provision the VM,
install dependencies, copy the environment file, enable services, configure
private ingress, and run the Copenhagen test with the desktop switched off.

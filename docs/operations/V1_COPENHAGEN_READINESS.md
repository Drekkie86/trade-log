# Christiania V1 — Copenhagen Readiness

This package separates **operational product readiness** from **scientific evidence maturity**. A green runtime is not evidence of a profitable edge and does not enable broker decisions or orders.

## Operator control surface

Use `python christiania_ops.py` as the V1 operator CLI.

- `status --theta` — database, market clock, daemon and Theta state.
- `readiness` — product readiness without requiring the runtime to be actively collecting.
- `readiness --runtime` — strict runtime readiness; daemon + Theta must be healthy.
- `backups` — verify every retained Christiania backup and report freshness.
- `backup` — create a verified SQLite online backup.
- `restore-drill` — restore the latest verified backup into an isolated temporary database and re-run schema/integrity/FK verification. The live DB is never overwritten.
- `export --theta` — write a secret-safe operational audit JSON.
- `copenhagen` — strict one-command runtime gate for the deployment test.

## Copenhagen gate

Before calling the one-VM deployment operationally ready:

1. deployment preflight passes with `--require-theta-live`;
2. `christiania_ops.py backup` succeeds;
3. `christiania_ops.py restore-drill` succeeds;
4. `christiania_ops.py copenhagen` returns exit code 0 while the daemon is expected to be running;
5. dashboard Readiness page is green for blocking product checks;
6. audit export is generated and contains no secret values;
7. systemd health, backup, audit and restore-drill timers are enabled;
8. remote access remains private; Streamlit stays bound to localhost;
9. reboot the VM once and repeat the strict gate without manually launching Java or Python.

## Backup recovery semantics

Backup inventory opens every candidate database read-only and checks schema v25, SQLite quick check and foreign keys. A file merely matching the backup filename pattern is not considered valid.

A restore drill uses SQLite's backup API to create an isolated temporary database from a verified backup. It then verifies the restored copy. It never writes to `CHRISTIANIA_DB_PATH`.

## Audit export

The audit JSON includes command-deck state, data-quality diagnostics, backup inventory, V1 readiness, Git metadata, safe configuration values and booleans indicating whether secrets are configured.

The export never serializes `MASSIVE_API_KEY` or `THETADATA_API_KEY` values.

## Scientific firewall

The V1 readiness gate deliberately reports scientific state separately:

- fewer than 5 independent prospective dates: `PROSPECTIVE_CALIBRATION_ACCUMULATING`;
- 5–19: `FIRST_DESCRIPTIVE_REVIEW_REACHED`;
- 20+: `PREREG_REVIEW_THRESHOLD_REACHED`.

These labels do not change a model, threshold, hypothesis, admission rule or trading decision. No live broker-order path exists in this package.

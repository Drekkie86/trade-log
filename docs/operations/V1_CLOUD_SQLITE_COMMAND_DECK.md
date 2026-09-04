# Christiania V1 — Cloud-ready SQLite + Command Deck

## Purpose

Christiania V1 remains a single-writer research workstation.

PostgreSQL is deliberately deferred. The current system does not have a
demonstrated concurrent-writer requirement. SQLite in WAL mode, with the
research daemon as the primary writer and the web application using a
read-only connection, is the V1 operational architecture.

## Runtime layout

Recommended V1 host layout:

- one persistent VM;
- Christiania repository / virtual environment;
- Theta Terminal process;
- Christiania research daemon;
- SQLite database on persistent disk;
- Streamlit command deck;
- verified SQLite backups on separate persistent storage;
- Tailscale/private-network access for the web interface.

Do not expose the Streamlit port directly to the public internet before an
authentication/reverse-proxy decision is implemented.

## Runtime database path

The normal local default remains:

`trade_log.db` in the repository root.

For a hosted VM, set:

`CHRISTIANIA_DB_PATH=/persistent/path/trade_log.db`

Explicit function-level `db_path` arguments retain highest precedence.

## Read/write discipline

- daemon/research engine: writer;
- command deck: read-only SQLite URI connection with `query_only=ON`;
- backup utility: SQLite online backup API;
- manual ad-hoc writes during daemon operation should be avoided.

## Backups

Run:

`python backup_christiania.py`

The backup is written to `CHRISTIANIA_BACKUP_DIR` when configured, otherwise
to the repository-local `backups/` directory.

Each backup is created through SQLite's backup API, verified with
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`, and only then moved
into its final filename.

Default retention is 14 verified backups. Configure with:

`CHRISTIANIA_BACKUP_RETENTION=14`

## Health check

Human-readable:

`python christiania_health.py`

Machine-readable:

`python christiania_health.py --json`

## Web command deck

Local-only default:

`python run_christiania_app.py`

Private-network bind for a VM/Tailscale host:

`python run_christiania_app.py --host 0.0.0.0 --port 8501`

Binding to `0.0.0.0` does not itself provide authentication. Firewall and
private-network controls remain mandatory.

## Scientific boundary

This package changes no scientific model, threshold, hypothesis, candidate
rule, admission rule or prospective freeze.

The command deck explicitly labels surfaced observations as observational.
It exposes recovery provenance but does not exclude, reweight or reinterpret
recovered evidence automatically.

## Live trading boundary

The V1 command deck imports no Saxo provider code and contains no broker
order action. Shadow candidates remain research objects.

## Deferred work

- production VM selection and provisioning;
- Tailscale/reverse-proxy/auth implementation;
- system service definitions and automatic restarts;
- scheduled backup execution;
- US exchange-holiday-aware daemon calendar hardening;
- end-to-end Copenhagen remote-access rehearsal.

PostgreSQL remains deferred until a real concurrent-writer or service-scale
requirement appears.

# Christiania

Personal options research, calibration and shadow-trading workstation.

Christiania is designed to test whether repeatable positive expectancy exists
net realistic costs and slippage. It is research software, not a live
autotrading system.

## V1 components

- repeated research daemon;
- provider/reference evidence;
- prospective calibration partition;
- model governance and hypothesis registry;
- bounded transient recovery with structured provenance;
- defined-risk shadow structures and longitudinal marks;
- SQLite WAL operational database;
- verified online backups;
- read-only Streamlit command deck.

## Start locally

Activate the virtual environment, start Theta Terminal, then run the research
daemon as documented in `docs/research/RESEARCH_DAEMON_V1.md`.

Launch the web command deck:

`python run_christiania_app.py`

Operational health:

`python christiania_health.py`

Verified backup:

`python backup_christiania.py`

Cloud-ready SQLite and command-deck operations are documented in:

`docs/operations/V1_CLOUD_SQLITE_COMMAND_DECK.md`

One-VM reliability and service-manager deployment preparation:

`docs/operations/V1_ONE_VM_RELIABILITY.md`

## Governance

Surfaced anomalies are observational evidence, not validated edge.
Prospective evidence remains separated from discovery evidence.
The V1 web application contains no broker-order path.

## Theta control plane

Theta Terminal remains a separate local provider process, while Christiania treats its v3 HTTP API as a first-class operational dependency. `python run_theta_probe.py` performs a read-only localhost readiness probe. Scheduled daemon sampling refuses to start unless Theta is ready, and `python christiania_health.py --strict-theta` makes the same dependency machine-checkable.

## V1 Copenhagen operator surface

Package 5 adds `christiania_ops.py` for status, product/runtime readiness, verified backup inventory, isolated restore drills, secret-safe operational audit exports and the strict Copenhagen gate. Product readiness is explicitly separate from scientific evidence maturity. See `docs/operations/V1_COPENHAGEN_READINESS.md`.

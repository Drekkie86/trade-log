# Christiania

Personal quantitative options research, calibration and shadow-trading workstation.

Christiania is designed to test whether repeatable positive expectancy exists net realistic costs and slippage. It is research software, not a live autotrading system.

## Authoritative V1 references

- `docs/V1_ARCHITECTURE.md` — current architecture and safety boundaries.
- `docs/V1_STATUS.md` — current V1 construction/science status.
- `docs/ROADMAP.md` — current path through secure web edge, advanced math and release acceptance.

## Local operation

Activate the virtual environment and start Theta Terminal, then use:

- `python run_theta_probe.py`
- `python run_christiania_app.py`
- `python run_christiania_daemon.py`
- `python christiania_health.py`
- `python christiania_ops.py status`

## V1 operational architecture

The one-VM target uses SQLite WAL, a read-only Streamlit command deck, verified online backups, isolated restore drills, audit exports, XNYS-aware scheduling, systemd supervision and a managed Theta control plane.

Package 6 adds the release web boundary: Caddy HTTPS -> oauth2-proxy OIDC -> loopback-only Streamlit. Christiania stores no end-user passwords.

## Governance

Surfaced anomalies are observational evidence, not validated edge. Prospective evidence remains separated from discovery evidence. Model decision/admission flags remain disabled under the frozen V1 protocol. The V1 application contains no broker-order path.

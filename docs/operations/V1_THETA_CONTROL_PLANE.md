# Christiania V1 — Theta Terminal control plane

## Boundary

Theta Terminal remains an external provider service. Christiania does not embed or reimplement ThetaData. Christiania owns the operational contract around it: local-only addressing, readiness probing, service ordering, daemon gating, health visibility, and a strict distinction between API readiness and research-semantic validation.

## Readiness

`python run_theta_probe.py` calls the documented ThetaData v3 localhost REST API on the read-only stock list-dates endpoint. READY means HTTP 200 plus a valid JSON response. It does not claim every subscription entitlement is present, that a particular live chain is populated, or that timestamp semantics have been independently live-validated.

Default endpoint: `http://127.0.0.1:25503/v3`.

`CHRISTIANIA_THETA_BASE_URL` is restricted to localhost. Christiania refuses a remote Theta endpoint.

## Authentication

For unattended service operation, Christiania accepts either `THETADATA_API_KEY` from the runtime environment or a `creds.txt` file beside the configured Theta JAR. The API-key value is never printed by the launcher or deployment preflight; only the selected authentication mode is reported. The Java command remains `java -jar <jar>` so authentication is inherited through the supported environment/config mechanism rather than an exposed command-line secret.

## Daemon gate

The research daemon probes Theta before acquiring its singleton database lease. If the API is not READY, sampling refuses to start. The systemd daemon unit also uses `run_theta_probe.py --wait-seconds 180` as `ExecStartPre`, so boot ordering is based on actual API readiness, not merely the Java process existing.

## Manual research runners

The independent, research-cycle, and full-cycle launchers all use the same configured local Theta endpoint and refuse to begin if the readiness probe fails. This removes the previous split where the daemon and manual runners could silently use different provider configuration.

## Health and Command Deck

Provider health is opt-in to the read model so offline analysis and unit tests remain hermetic. The Streamlit Command Deck and `christiania_health.py` request the provider probe explicitly. `--strict-theta` returns non-zero when the API is not READY. The cloud health service requires both a healthy daemon and Theta readiness.

## Timestamp semantics

Operational readiness is not timestamp validation. The existing `thetadata_timestamp_semantics_v1_runs` confidence state is exposed beside provider health. A readiness probe must never promote `DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED` to `DOCUMENTED_AND_LIVE_VALIDATED`.

## Safety

This package is read-only at the provider boundary. It adds no broker-order path, no model changes, no candidate-rule changes, no admission changes, and no schema migration.

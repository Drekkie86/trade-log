# Christiania V1.0 Architecture

This is the authoritative V1 architecture reference.

## Runtime topology

Internet -> Caddy HTTPS -> oauth2-proxy OIDC -> Streamlit on 127.0.0.1:8501

On the same Linux VM:

- Theta Terminal JAR exposes its v3 API only on localhost;
- Christiania research daemon is the primary SQLite writer;
- SQLite runs in WAL mode on persistent storage;
- dashboard/read models use read-only/query-only connections;
- verified backups, restore drills and audit exports use separate persistent paths;
- systemd supervises processes and timers.

## Security boundary

Christiania does not store end-user passwords. Generic OIDC authentication is delegated to oauth2-proxy and an external identity provider. A checked-in example email file is never an authorization wildcard; deployment requires explicit authorized identities.

Streamlit and oauth2-proxy bind loopback only. Caddy is the public HTTPS edge. Direct public exposure of ports 8501 or 4180 violates the V1 architecture.

## Provider boundary

Providers collect evidence. Theta remains a separate local process and is probed at daemon startup and before each scheduled sample. Provider failures are recorded explicitly; no sample begins when Theta is not ready.

## Persistence boundary

SQLite remains deliberately single-writer for V1. PostgreSQL is deferred until genuine concurrent-writer/service-architecture requirements exist.

## Scientific boundary

The frozen primary model and prospective hypotheses remain observational. Challenger models may be added to the model library, but admission/decision flags remain disabled unless a future governance package explicitly changes them after adequate prospective evidence.

## Quantitative-library boundary

`src/quant` is a side-effect-free research library. It does not import the database repository, broker adapters, shadow-admission logic or trade service. Advanced models produce prices, calibration diagnostics, scenarios, risk summaries and disagreement measures only. They do not mutate the frozen primary model role or prospective protocol.

## Trading boundary

V1 contains no broker-order path. Broker/provider adapters may support reference, quote, identity and research evidence, but V1 does not submit orders.

## Release-candidate boundary

Package 8 adds a side-effect-light release harness. Release manifests fingerprint Git/schema/migrations/quant-registry/runtime dependencies; burn-in snapshots live in the audit path; Linux boot IDs prove a genuine reboot. These mechanisms do not alter research models, database schema, candidate admission or broker behavior.

# Christiania V1.0 Roadmap — authoritative current plan

Status baseline: Package 6 (`c4a9a5a`) completed the secure authenticated web edge and V1 documentation/security consolidation.
This document supersedes the earlier pre-Cohort implementation roadmap. Historical documents remain useful evidence but are not current implementation instructions.

## V1 goal

Christiania V1.0 is an operationally complete quantitative options-research workstation that can run unattended on one Linux VM, expose a securely authenticated browser UI, preserve evidence/provenance/recovery, and host a serious versioned mathematical model library.

V1.0 does **not** claim a proven trading edge and contains no broker-order path.

## Completed

- Packages 1–6: recovery provenance, SQLite WAL/read-only UI, verified backup/restore, XNYS scheduling, one-VM systemd runtime, Theta control plane, per-slot Theta gating, audit exports, operational readiness, Copenhagen recovery tooling and the secure OIDC/HTTPS web edge.
- Package 7: advanced quantitative model library and Quant Bench, while keeping every new model research-only.
- Frozen prospective-science governance remains observational-only.

## Package 6 — Secure Web Edge & Documentation Consolidation — COMPLETE

- Caddy automatic HTTPS reverse proxy.
- oauth2-proxy generic OIDC authentication gateway.
- explicit per-user email allowlist; no Christiania password database.
- Streamlit remains loopback-only.
- bounded app/auth-gateway restart behavior and service sandbox hardening.
- secure-edge/deployment preflights with explicit env-file loading.
- recursive audit-export secret redaction.
- migration 021–025 governance audit converted into regression contracts.
- authoritative V1 architecture/status documentation and stale-doc cleanup.

## Package 7 — Advanced Quantitative Model Library & Research Bench — COMPLETE IN THIS PACKAGE

Build serious mathematical infrastructure without promoting unvalidated challengers into trading decisions:

- production-grade BSM/implied-vol/Greeks foundations;
- numerical cross-checks and higher-order Greeks;
- arbitrage-aware volatility-surface diagnostics;
- binomial/trinomial and finite-difference cross-validation;
- Heston/stochastic-vol challenger infrastructure;
- local-vol and jump-diffusion research models;
- Monte Carlo/scenario engine with convergence diagnostics;
- realized-volatility estimators and EWMA/GARCH-family baselines;
- model calibration quality/stability metrics;
- explicit transaction-cost/slippage EV layer;
- model-disagreement research surface.

Frozen primary/prospective hypotheses remain frozen. Challengers are research instruments, not automatic BUY/SELL authorities.

## Package 8 — Clean-VM Release Candidate / Copenhagen acceptance

- provision a clean Linux VM;
- deploy Christiania + Theta JAR + persistent SQLite;
- configure DNS, HTTPS and OIDC identity;
- demonstrate unattended reboot recovery;
- demonstrate Theta readiness and scheduled collection;
- verify browser login from a remote location;
- verify backup, restore drill, audit export and timers;
- run multi-day burn-in and fix only evidence-backed reliability defects;
- execute final migration/security/deployment review.

## V1.0 release condition

V1.0 can be declared when the clean-VM acceptance gate passes. Scientific maturity is shown separately and may still be `PROSPECTIVE_CALIBRATION_ACCUMULATING`.

Post-V1 decisions about live broker execution require a separate explicit architecture/safety project and are not implied by V1.0.


## Package 9 — V1 Product Interface

Branded browser interface using the official Christiania logo, with clear separation of core research, Shadow Lab, Casino / 0DTE Lab, readiness and release status.

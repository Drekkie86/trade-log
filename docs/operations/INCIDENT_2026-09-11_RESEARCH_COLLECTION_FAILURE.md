# Incident — RC0 research collection failure detected 2026-09-11

## Summary

Christiania's hosted RC0 infrastructure remained operational, but scheduled
research iterations failed because the installed production tree intentionally
excluded `.git` while the independent research runner attempted to derive its
code identity with `git rev-parse HEAD`.

The daemon process remained alive and maintained its heartbeat, so the RC0
supervisor incorrectly reported the platform as healthy even though the
research workload was failing.

## Detection

The incident was detected on 2026-09-11 by inspecting
`christiania-daemon.service` journal output. Repeated daemon iterations were
recorded as `FAILED` with `IndependentResearchRunnerError` and a Git
"not a repository" error.

The authoritative failure window and failed-iteration count must be taken from
`research_daemon_iterations`; journal-tail inference is not accepted as the
incident record of impact.

## Root cause

Production is installed under `/opt/christiania` by rsync with `.git`
deliberately excluded. That is correct deployment hygiene. The independent
runner nevertheless treated a live Git checkout as an ambient runtime
dependency.

A second control failure allowed the incident to remain undetected: supervisor
health covered process heartbeat, provider readiness, database state, memory,
timers, backups and disk, but did not verify successful research production.

## Corrective controls

1. `DEPLOYED_COMMIT` is the authoritative production code identity.
2. The installer writes and validates that marker automatically from the source
   checkout before the `.git` directory is excluded.
3. Development checkouts without a marker may fall back to Git.
4. A present but malformed deployment marker fails closed.
5. The supervisor reads `research_daemon_iterations` and treats workload
   failure as platform failure.
6. During an active XNYS sample window, successful research production has a
   maximum-age SLO; a fresh in-progress iteration is recognized separately.
7. The production-layout behavior is covered by automated tests.
8. The daemon scheduler is forward-looking: after each iteration it recomputes
   the next slot from current time, so missed past slots are not replayed as an
   unbounded catch-up storm.

## Remaining operational controls

- Configure an external state-transition alert endpoint.
- Add an independent external heartbeat/watchdog.
- Require successful production research iterations before unattended release
  acceptance.
- Record the authoritative incident impact from the database.
- Investigate any timer that lacks a future trigger before declaring the
  reliability layer fully accepted.

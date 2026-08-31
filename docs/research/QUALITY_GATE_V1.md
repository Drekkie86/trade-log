# Christiania Quality Gate v1

The quality gate converts repeated manual discipline into a repository-level
check that can be run locally and in GitHub Actions.

## Local command

```powershell
python .\quality_gate.py
```

Normal release/research use should not pass `--skip-tests`.

## Gate failures

The gate fails on:

- tracked secret/database file classes;
- discoverable `test_*.py` modules outside `tests/`;
- untracked files under `src/`, `tests/`, `migrations/`, or `.github/`;
- broken/non-contiguous migration numbering;
- destructive `DELETE FROM schema_version`;
- mismatch between repository expected schema version and latest migration;
- inability to construct a fresh database through the native schema plus
  numbered migrations;
- SQLite integrity or foreign-key failures;
- full pytest failure.

## Warnings, not failures

Untracked root-level diagnostics, JSON outputs, ZIPs and README debris are
reported locally but do not fail the gate.

This is deliberate. Experimental work is allowed, but production source,
tests, migrations and CI definitions may not sit untracked.

## CI

`.github/workflows/quality-gate.yml` runs the same gate on Windows with
Python 3.13 for pushes to `main`, pull requests and manual dispatches.

The 10,000-row performance benchmark is intentionally not part of normal CI.
Absolute performance is machine-dependent and the legacy single-row baseline
is deliberately slow. Functional batch-path tests remain part of pytest.

## Future extension

Do not expand this gate merely to accumulate checks. Add a new hard failure
only when it protects a demonstrated invariant or recurring process failure.

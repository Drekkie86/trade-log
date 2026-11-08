# Cohort 001 — Preregistration v2, Amendment 001

Status: preregistered addition. Additive only.

This amendment does not modify `research/cohort_001_preregistration_v2.md`.
That file's Git blob remains `d4a247aee2d25b65417905ff2f23c183608ab60d`
and must not change.

This amendment fixes two operational rules that were previously undecided.
Both are decided here, before the first official Cohort 001 collection,
specifically so that they cannot become post-hoc researcher choices.

---

## A1. Launcher code identity

### Problem

`code_git_sha` recorded on a research run is `git rev-parse HEAD`.

`require_clean_tracked_tree()` verifies only that *tracked* files are
unmodified. Untracked files are permitted, because diagnostics are
deliberately kept untracked.

The launcher itself was untracked. Its constants and guards therefore
determined whether a run was valid, while remaining outside the identity
recorded on the run.

### Rule

The following paths MUST be tracked in Git and unmodified at launch time:

- `run_cohort_001.py`
- `research/cohort_001_preregistration_v2.md`
- `research/cohort_001_preregistration_v2_amendment_001.md`
- `src/research/cohort_001.py`
- `src/research/cohort_001_persistence.py`
- `src/research/cohort_001_runner.py`
- `src/providers/massive.py`
- `src/providers/saxo.py`
- `src/providers/saxo_auth.py`
- `src/providers/bridge.py`
- `src/database/repository.py`
- `src/database/provider_evidence.py`

The launcher MUST fail closed if any of these is untracked, modified in
the working tree, or staged but uncommitted.

The launcher MUST record the Git blob SHA of `run_cohort_001.py` in the
run notes, in addition to `code_git_sha`.

---

## A2. Superseding a run that terminalises INVALID

### Problem

`previous_terminal_runs()` counts `COMPLETED`, `FAILED` and `INVALID`
and refuses to launch when the count is non-zero.

A run that aborts on an unexpected exception is preserved as `INVALID`.
That permanently blocks the launcher. The recovery rule was undecided,
which would have made the run-inclusion decision a post-hoc choice made
under time pressure after a failure.

### Rule

Let `C`, `F`, `I` be the counts of prior terminal Cohort 001 runs with
status `COMPLETED`, `FAILED` and `INVALID`.

Launch is permitted only when one of the following holds.

1. `C = 0`, `F = 0`, `I = 0` — first collection.

2. `C = 0`, `F = 0`, `I >= 1`, `I < 3`, and the operator passes
   `--allow-retry-after-invalid`.

`I` is the number of prior INVALID attempts. Therefore, after three INVALID
attempts, no fourth attempt is permitted by this launcher.

Launch is refused in every other case, including:

- any `COMPLETED` run exists;
- any `FAILED` run exists;
- `I >= 3`.

`FAILED` is deliberately non-retryable by this launcher. `FAILED` means
the Massive universe fetch failed, which is an environmental condition
that must be diagnosed by a human rather than retried automatically.

### Analysis consequences

- A run with status `INVALID` is permanently excluded from Cohort 001
  analysis. It is never repaired, edited or re-terminalised.
- The superseding run records, in its notes, the run ids it supersedes.
- The retry limit of three exists so that repeated retries cannot become
  an undisclosed selection process over collection attempts. If three
  attempts all terminalise `INVALID`, the correct response is to stop and
  diagnose, not to keep launching.
- All attempts, including superseded ones, are retained in the database
  and MUST be reported alongside any Cohort 001 result.

---

## A3. Operational preconditions

The launcher MUST verify, before creating any run row, that the SQLite
database can be locked for writing. A concurrent holder — the Streamlit
application or a database browser — would otherwise cause a
`database is locked` failure partway through collection.

---

## A4. Scope

This amendment changes launch preconditions and run-inclusion rules only.

It does not change:

- the sampling universe;
- the strata;
- the boundary conventions;
- the tie-break ordering;
- selection-before-resolution ordering;
- randomisation of resolution order;
- denominator preservation;
- exclusion reason semantics;
- prohibited conclusions.

No conclusion about edge, profitability, win rate, Sharpe ratio, fill
quality, arbitrage or P(profit) may be drawn from Cohort 001.

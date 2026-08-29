# Christiania — Cohort 001 Monday Operator Checklist

Status: operational checklist only  
Cohort definition: **unchanged**  
Purpose: prevent an avoidable launch failure without modifying the preregistered Cohort 001 path.

## Hard rule

Detectability work must not delay Cohort 001.

Do not edit any Cohort 001 collection-critical source file on launch day unless a genuine blocker is found and the run is deliberately postponed.

## Before Monday

1. Restore any accidental tracked README modification:
   `git restore README.md`

2. Cohort 001 launch-critical tracked files must be clean.
   The launcher itself enforces this.

3. Leave unrelated untracked diagnostics alone if desired.
   Untracked files do not violate `require_clean_tracked_tree()`.

4. Make a fresh backup of `trade_log.db` before the official run.

5. Close Streamlit and any SQLite browser before launch.
   The launcher performs a SQLite write-lock probe and must fail closed if another process holds the DB.

## Monday — before authentication

Run the full test suite:

`python -m pytest -q`

Do not launch if it is not fully green.

Confirm the database is schema v7:

`python check_db_schema.py`

## Monday — shortly before the intended run

Authenticate Saxo manually:

`python saxo_live_auth.py`

Because the observed Saxo refresh lifetime is short, authenticate close to the actual run.

Then verify the two important provider seams:

`python check_saxo_underlying_live.py`

`python check_massive_to_saxo_live.py`

The official run should not proceed merely because a request succeeds. During regular US market hours, the evidence should be compatible with the intended open-market path rather than only `OldIndicative` / stale evidence.

## Launch window

Cohort 001 is intentionally restricted to an intraday weekday launch.

Prefer a stable mid-session period rather than the opening or closing minutes.

Launch:

`python run_cohort_001.py`

If a previous INVALID attempt exists and the preregistered retry rule permits another attempt, use the explicit retry flag only after diagnosing the prior INVALID result.

## Stop conditions

Stop rather than improvise if any of the following occurs:

- full tests are not green;
- schema is not v7;
- the tracked tree is dirty;
- a required launch path is untracked or modified;
- the database is locked;
- Saxo authentication is stale or broken;
- provider evidence remains clearly stale / non-open-market when open-market evidence is required;
- a FAILED Cohort 001 run already exists;
- the maximum number of preregistered INVALID attempts has been reached.

## After the run

Preserve the database before doing any repair or exploratory work.

Record:

- run id;
- terminal status;
- raw / normalized Massive counts;
- eligible / excluded counts;
- selected / empty strata counts;
- Saxo success / failure counts;
- underlying observation status;
- exclusion reasons;
- provider request counts;
- any quote-quality classifications encountered.

Do not reinterpret Cohort 001 as an edge experiment. It remains a data-quality baseline.

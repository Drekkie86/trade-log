from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_required_setting
from src.providers.massive import MassiveClient
from src.providers.saxo import SaxoClient
from src.providers.saxo_auth import (
    get_saxo_live_access_token,
)
from src.research.cohort_001_runner import (
    run_cohort_001_collection,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "trade_log.db"
PREREG_PATH = (
    PROJECT_ROOT
    / "research"
    / "cohort_001_preregistration_v2.md"
)

EXPECTED_SCHEMA_VERSION = 7
EXPECTED_PREREG_GIT_BLOB = (
    "d4a247aee2d25b65417905ff2f23c183608ab60d"
)

COHORT_ID = "COHORT_001_DATA_QUALITY_BASELINE"

AMENDMENT_PATH = (
    PROJECT_ROOT
    / "research"
    / "cohort_001_preregistration_v2_amendment_001.md"
)

EXPECTED_AMENDMENT_GIT_BLOB = (
    "4c7598ba3521dab152e039744bf07d6ee779e762"
)

# Amendment 001 A1: every path here must be tracked and unmodified.
# code_git_sha alone does not identify untracked files, so the launcher
# must refuse to run if anything it depends on is outside Git.
REQUIRED_TRACKED_PATHS = (
    "run_cohort_001.py",
    "research/cohort_001_preregistration_v2.md",
    "research/cohort_001_preregistration_v2_amendment_001.md",
    "src/research/cohort_001.py",
    "src/research/cohort_001_persistence.py",
    "src/research/cohort_001_runner.py",
    "src/providers/massive.py",
    "src/providers/saxo.py",
    "src/providers/saxo_auth.py",
    "src/providers/bridge.py",
    "src/database/repository.py",
    "src/database/provider_evidence.py",
)

# Amendment 001 A2.
MAX_INVALID_ATTEMPTS = 3


def run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def determine_us_session() -> tuple[str, str]:
    """
    Cohort 001 launch helper for the current
    August-2026 US daylight-saving session.

    Regular US equity session:
      13:30-20:00 UTC
      == 09:30-16:00 America/New_York

    The first Cohort 001 run is intentionally
    restricted to an intraday weekday launch.
    """

    now = datetime.now(timezone.utc)
    session_date = now.date().isoformat()

    if now.weekday() >= 5:
        return session_date, "NON_TRADING_DAY"

    minute = (
        now.hour * 60
        + now.minute
    )

    open_minute = 13 * 60 + 30
    close_minute = 20 * 60

    if minute < open_minute:
        state = "PRE_OPEN"
    elif minute < close_minute:
        state = "INTRADAY"
    else:
        state = "POST_CLOSE"

    return session_date, state


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        "PRAGMA foreign_keys = ON;"
    )
    return connection


def schema_version(
    connection: sqlite3.Connection,
) -> int:
    row = connection.execute(
        """
        SELECT MAX(version) AS version
        FROM schema_version;
        """
    ).fetchone()

    if (
        row is None
        or row["version"] is None
    ):
        raise RuntimeError(
            "schema_version contains no version."
        )

    return int(row["version"])


def require_clean_tracked_tree() -> None:
    """
    Untracked diagnostics are allowed.

    Any tracked modification or staged-but-uncommitted
    change is forbidden because code_git_sha must
    identify the exact collection code.
    """

    unstaged = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=PROJECT_ROOT,
    ).returncode

    staged = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ],
        cwd=PROJECT_ROOT,
    ).returncode

    if unstaged != 0 or staged != 0:
        raise RuntimeError(
            "Tracked Git working tree is not clean. "
            "Commit or revert tracked changes before "
            "Cohort 001."
        )


def git_blob_at_head(
    relative_path: str,
) -> str:
    return run_git(
        "rev-parse",
        f"HEAD:{relative_path}",
    )


def require_required_paths_tracked() -> dict[str, str]:
    """
    Amendment 001 A1.

    Every path Christiania depends on for a Cohort 001 collection must be
    tracked and unmodified, otherwise the recorded code_git_sha does not
    identify the code that actually ran.

    Returns a mapping of path -> committed blob SHA.
    """

    blobs: dict[str, str] = {}
    problems: list[str] = []

    for relative_path in REQUIRED_TRACKED_PATHS:
        absolute = PROJECT_ROOT / relative_path

        if not absolute.exists():
            problems.append(
                f"{relative_path}: missing from working tree"
            )
            continue

        tracked = subprocess.run(
            [
                "git",
                "ls-files",
                "--error-unmatch",
                relative_path,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        ).returncode

        if tracked != 0:
            problems.append(
                f"{relative_path}: untracked"
            )
            continue

        unstaged = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "--",
                relative_path,
            ],
            cwd=PROJECT_ROOT,
        ).returncode

        staged = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
                "--",
                relative_path,
            ],
            cwd=PROJECT_ROOT,
        ).returncode

        if unstaged != 0 or staged != 0:
            problems.append(
                f"{relative_path}: modified but not committed"
            )
            continue

        blobs[relative_path] = git_blob_at_head(
            relative_path
        )

    if problems:
        raise RuntimeError(
            "Cohort 001 requires every collection-critical file to be "
            "tracked and committed.\n"
            + "\n".join(f"  - {line}" for line in problems)
        )

    return blobs


def require_database_writable(
    db_path: Path,
) -> None:
    """
    Amendment 001 A3.

    The whole collection runs inside one SQLite write transaction. If the
    Streamlit app or a database browser holds the file, the run fails
    partway through. Detect that before creating any run row.
    """

    probe = sqlite3.connect(db_path, timeout=2.0)

    try:
        probe.execute("BEGIN IMMEDIATE;")
        probe.execute("ROLLBACK;")

    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "The database is locked by another process. Close Streamlit "
            "and any SQLite browser before starting Cohort 001. "
            f"SQLite reported: {exc}"
        ) from exc

    finally:
        probe.close()


def terminal_run_status_counts(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT
            status,
            COUNT(*) AS n
        FROM research_runs
        WHERE cohort_id = ?
          AND status IN (
              'COMPLETED',
              'FAILED',
              'INVALID'
          )
        GROUP BY status;
        """,
        (COHORT_ID,),
    ).fetchall()

    counts = {
        "COMPLETED": 0,
        "FAILED": 0,
        "INVALID": 0,
    }

    for row in rows:
        counts[str(row["status"])] = int(row["n"])

    return counts


def evaluate_previous_run_gate(
    counts: dict[str, int],
    *,
    allow_retry_after_invalid: bool,
    max_invalid_attempts: int = MAX_INVALID_ATTEMPTS,
) -> tuple[bool, str]:
    """
    Amendment 001 A2, as a pure function so it can be tested without a
    database, a network or a Git repository.

    Returns (allowed, reason).
    """

    completed = int(counts.get("COMPLETED", 0))
    failed = int(counts.get("FAILED", 0))
    invalid = int(counts.get("INVALID", 0))

    if completed > 0:
        return (
            False,
            "A COMPLETED Cohort 001 run already exists. This launcher is "
            "single-use for the first cohort.",
        )

    if failed > 0:
        return (
            False,
            "A FAILED Cohort 001 run exists. FAILED means the Massive "
            "universe fetch failed, which must be diagnosed by a human "
            "rather than retried by this launcher.",
        )

    if invalid == 0:
        return (True, "No prior terminal Cohort 001 run.")

    if invalid >= max_invalid_attempts:
        return (
            False,
            f"{invalid} INVALID Cohort 001 runs already exist, which has "
            f"reached the preregistered maximum of {max_invalid_attempts}. "
            "Stop and diagnose rather than launching another attempt.",
        )

    if not allow_retry_after_invalid:
        return (
            False,
            f"{invalid} INVALID Cohort 001 run(s) exist. Amendment 001 A2 "
            "permits superseding them, but only with "
            "--allow-retry-after-invalid.",
        )

    return (
        True,
        f"Superseding {invalid} INVALID run(s) under amendment 001 A2.",
    )


def superseded_invalid_run_ids(
    connection: sqlite3.Connection,
) -> list[int]:
    rows = connection.execute(
        """
        SELECT id
        FROM research_runs
        WHERE cohort_id = ?
          AND status = 'INVALID'
        ORDER BY id;
        """,
        (COHORT_ID,),
    ).fetchall()

    return [int(row["id"]) for row in rows]


def build_run_notes(
    *,
    superseded_run_ids: list[int],
    launcher_blob: str,
    amendment_blob: str,
) -> str:
    parts = [
        "Cohort 001 data-quality baseline collection.",
        f"launcher_blob={launcher_blob}.",
        f"amendment_001_blob={amendment_blob}.",
    ]

    if superseded_run_ids:
        joined = ",".join(str(value) for value in superseded_run_ids)
        parts.append(
            f"supersedes_invalid_run_ids={joined}."
        )

    return " ".join(parts)


def active_run_count(
    connection: sqlite3.Connection,
    *,
    session_date: str,
) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS n
        FROM research_runs
        WHERE cohort_id = ?
          AND us_session_date = ?
          AND status IN (
              'STARTED',
              'COLLECTING'
          );
        """,
        (
            COHORT_ID,
            session_date,
        ),
    ).fetchone()

    return int(row["n"])


def previous_terminal_runs(
    connection: sqlite3.Connection,
) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS n
        FROM research_runs
        WHERE cohort_id = ?
          AND status IN (
              'COMPLETED',
              'FAILED',
              'INVALID'
          );
        """,
        (COHORT_ID,),
    ).fetchone()

    return int(row["n"])


def print_preflight(
    *,
    code_sha: str,
    prereg_hash: str,
    session_date: str,
    session_state: str,
    previous_runs: int,
) -> None:
    print()
    print(
        "Christiania - Cohort 001 launch"
    )
    print(
        "--------------------------------"
    )
    print()
    print(
        f"Schema:            v{EXPECTED_SCHEMA_VERSION}"
    )
    print(
        f"Code Git SHA:      {code_sha}"
    )
    print(
        f"Prereg Git blob:   {prereg_hash}"
    )
    print(
        f"US session date:   {session_date}"
    )
    print(
        f"US session state:  {session_state}"
    )
    print(
        f"Prior terminal runs:{previous_runs}"
    )
    print()


def report_run(
    connection: sqlite3.Connection,
    *,
    run_id: int,
) -> None:
    run = connection.execute(
        """
        SELECT *
        FROM research_runs
        WHERE id = ?;
        """,
        (run_id,),
    ).fetchone()

    print()
    print(
        "Cohort 001 reconciliation"
    )
    print(
        "-------------------------"
    )

    if run is None:
        print(
            "Run row not found."
        )
        return

    fields = [
        "id",
        "status",
        "started_at",
        "ended_at",
        "us_session_date",
        "us_session_state",
        "massive_raw_contracts",
        "massive_normalized_contracts",
        "normalization_drop_count",
        "selection_eligible_count",
        "selection_exclusion_count",
        "selected_strata_count",
        "empty_strata_count",
        "selected_contract_count",
        "saxo_resolution_success_count",
        "saxo_resolution_failure_count",
        "underlying_observation_status",
        "provider_requests_attempted",
        "provider_requests_succeeded",
        "provider_requests_failed",
    ]

    for field in fields:
        if field in run.keys():
            print(
                f"{field:34} {run[field]}"
            )

    print()
    print(
        "Selection exclusions by reason"
    )
    rows = connection.execute(
        """
        SELECT
            reason_code,
            COUNT(*) AS n
        FROM selection_exclusions
        WHERE run_id = ?
        GROUP BY reason_code
        ORDER BY reason_code;
        """,
        (run_id,),
    ).fetchall()

    if rows:
        for row in rows:
            print(
                f"  {row['reason_code']}: "
                f"{row['n']}"
            )
    else:
        print("  none")

    print()
    print(
        "Saxo failures by stage"
    )
    rows = connection.execute(
        """
        SELECT
            failure_stage,
            COUNT(*) AS n
        FROM saxo_resolution_failures
        WHERE research_snapshot_id IN (
            SELECT id
            FROM market_snapshots
            WHERE research_run_id = ?
        )
        GROUP BY failure_stage
        ORDER BY failure_stage;
        """,
        (run_id,),
    ).fetchall()

    if rows:
        for row in rows:
            print(
                f"  {row['failure_stage']}: "
                f"{row['n']}"
            )
    else:
        print("  none")

    print()
    print(
        "Provider attempts"
    )
    rows = connection.execute(
        """
        SELECT
            provider,
            operation,
            succeeded,
            COUNT(*) AS n,
            SUM(retry_count) AS retries
        FROM research_provider_attempts
        WHERE run_id = ?
        GROUP BY
            provider,
            operation,
            succeeded
        ORDER BY
            provider,
            operation,
            succeeded DESC;
        """,
        (run_id,),
    ).fetchall()

    for row in rows:
        print(
            "  "
            f"{row['provider']} / "
            f"{row['operation']} / "
            f"{'SUCCESS' if row['succeeded'] else 'FAIL'}"
            f": {row['n']} "
            f"(retries={row['retries']})"
        )

    print()
    print(
        "IMPORTANT:"
    )
    print(
        "Cohort 001 is a data-quality baseline."
    )
    print(
        "It does not establish trading edge, "
        "profitability, fill quality, or arbitrage."
    )


def mark_unexpected_run_invalid(
    connection: sqlite3.Connection,
    *,
    run_id: int | None,
    reason: str,
) -> None:
    if run_id is None:
        return

    row = connection.execute(
        """
        SELECT status
        FROM research_runs
        WHERE id = ?;
        """,
        (run_id,),
    ).fetchone()

    if row is None:
        return

    if row["status"] not in {
        "STARTED",
        "COLLECTING",
    }:
        return

    ended_at = utc_now_iso()

    invalid_reason = (
        "Launch wrapper caught unexpected "
        f"exception: {reason}"
    )[:1000]

    connection.execute(
        """
        UPDATE research_runs
        SET
            status = 'INVALID',
            ended_at = ?,
            notes = CASE
                WHEN notes IS NULL OR notes = '' THEN ?
                ELSE notes || ' ' || ?
            END
        WHERE id = ?;
        """,
        (
            ended_at,
            invalid_reason,
            invalid_reason,
            run_id,
        ),
    )


def latest_run_id(
    connection: sqlite3.Connection,
) -> int | None:
    row = connection.execute(
        """
        SELECT MAX(id) AS id
        FROM research_runs
        WHERE cohort_id = ?;
        """,
        (COHORT_ID,),
    ).fetchone()

    if (
        row is None
        or row["id"] is None
    ):
        return None

    return int(row["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Christiania Cohort 001 v2."
        )
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required explicit acknowledgement "
            "that this starts the real Cohort 001 "
            "data collection."
        ),
    )
    parser.add_argument(
        "--allow-retry-after-invalid",
        action="store_true",
        help=(
            "Permit superseding prior Cohort 001 runs that terminalised "
            "INVALID, under preregistration amendment 001 A2."
        ),
    )
    args = parser.parse_args()

    if not args.confirm:
        print(
            "Refusing to start without --confirm."
        )
        print(
            "Run: python run_cohort_001.py --confirm"
        )
        return 2

    if not DB_PATH.exists():
        raise RuntimeError(
            f"Database not found: {DB_PATH}"
        )

    if not PREREG_PATH.exists():
        raise RuntimeError(
            f"Preregistration not found: "
            f"{PREREG_PATH}"
        )

    require_clean_tracked_tree()

    # Amendment 001 A1.
    tracked_blobs = require_required_paths_tracked()

    launcher_blob = tracked_blobs["run_cohort_001.py"]

    amendment_hash = git_blob_at_head(
        "research/cohort_001_preregistration_v2_amendment_001.md"
    )

    if amendment_hash != EXPECTED_AMENDMENT_GIT_BLOB:
        raise RuntimeError(
            "Preregistration amendment 001 hash mismatch.\n"
            f"Expected: {EXPECTED_AMENDMENT_GIT_BLOB}\n"
            f"Actual:   {amendment_hash}"
        )

    code_sha = run_git(
        "rev-parse",
        "HEAD",
    )

    prereg_hash = run_git(
        "hash-object",
        str(
            PREREG_PATH.relative_to(
                PROJECT_ROOT
            )
        ),
    )

    if (
        prereg_hash
        != EXPECTED_PREREG_GIT_BLOB
    ):
        raise RuntimeError(
            "Preregistration hash mismatch.\n"
            f"Expected: "
            f"{EXPECTED_PREREG_GIT_BLOB}\n"
            f"Actual:   {prereg_hash}"
        )

    session_date, session_state = (
        determine_us_session()
    )

    # First real cohort is deliberately intraday.
    if session_state != "INTRADAY":
        raise RuntimeError(
            "Cohort 001 first collection is "
            "restricted to the regular US session. "
            f"Current derived state: {session_state}"
        )

    require_database_writable(DB_PATH)

    connection = connect()

    try:
        version = schema_version(
            connection
        )

        if version != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                "Database schema mismatch. "
                f"Expected v{EXPECTED_SCHEMA_VERSION}, "
                f"found v{version}."
            )

        if (
            active_run_count(
                connection,
                session_date=session_date,
            )
            > 0
        ):
            raise RuntimeError(
                "A non-terminal Cohort 001 run "
                "already exists for this US "
                "session date."
            )

        previous_runs = previous_terminal_runs(
            connection
        )

        # Amendment 001 A2.
        status_counts = terminal_run_status_counts(
            connection
        )

        gate_allowed, gate_reason = (
            evaluate_previous_run_gate(
                status_counts,
                allow_retry_after_invalid=(
                    args.allow_retry_after_invalid
                ),
            )
        )

        if not gate_allowed:
            raise RuntimeError(gate_reason)

        superseded = superseded_invalid_run_ids(
            connection
        )

        print_preflight(
            code_sha=code_sha,
            prereg_hash=prereg_hash,
            session_date=session_date,
            session_state=session_state,
            previous_runs=previous_runs,
        )

        print(
            f"Launcher blob:     {launcher_blob}"
        )
        print(
            f"Amendment blob:    {amendment_hash}"
        )
        print(
            f"Prior COMPLETED:   {status_counts['COMPLETED']}"
        )
        print(
            f"Prior FAILED:      {status_counts['FAILED']}"
        )
        print(
            f"Prior INVALID:     {status_counts['INVALID']}"
        )
        print(
            f"Gate:              {gate_reason}"
        )

        if superseded:
            print(
                "Superseding INVALID run ids: "
                + ", ".join(
                    str(value) for value in superseded
                )
            )

        print()

        # Validate secrets before creating the run row.
        massive_api_key = (
            get_required_setting(
                "MASSIVE_API_KEY"
            )
        )

        # This may automatically refresh a still-valid
        # Saxo refresh token. If the refresh token has
        # expired it fails before Cohort 001 begins.
        get_saxo_live_access_token()

        massive_client = MassiveClient(
            massive_api_key
        )

        saxo_client = SaxoClient(
            token_provider=(
                get_saxo_live_access_token
            )
        )

        print(
            "Starting real Cohort 001 collection..."
        )
        print()

        before_run_id = latest_run_id(
            connection
        )

        try:
            result = run_cohort_001_collection(
                conn=connection,
                massive_client=massive_client,
                saxo_client=saxo_client,
                preregistration_hash=(
                    prereg_hash
                ),
                code_git_sha=code_sha,
                us_session_date=(
                    session_date
                ),
                us_session_state=(
                    session_state
                ),
                underlying="AAPL",
                run_notes=build_run_notes(
                    superseded_run_ids=superseded,
                    launcher_blob=launcher_blob,
                    amendment_blob=amendment_hash,
                ),
            )

        except Exception as exc:
            after_run_id = latest_run_id(
                connection
            )

            created_run_id = (
                after_run_id
                if after_run_id != before_run_id
                else None
            )

            try:
                mark_unexpected_run_invalid(
                    connection,
                    run_id=created_run_id,
                    reason=(
                        f"{exc.__class__.__name__}: "
                        f"{exc}"
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()

            print()
            print(
                "COHORT 001 ABORTED BY "
                "UNEXPECTED EXCEPTION"
            )
            print(
                f"{exc.__class__.__name__}: {exc}"
            )

            if created_run_id is not None:
                print(
                    "Attempted to preserve the "
                    f"run as INVALID (run_id="
                    f"{created_run_id})."
                )

            raise

        connection.commit()

        report_run(
            connection,
            run_id=result.run_id,
        )

        print()
        print(
            "Final result"
        )
        print(
            "------------"
        )
        print(
            f"run_id:   {result.run_id}"
        )
        print(
            f"status:   {result.status}"
        )
        print(
            f"selected: "
            f"{result.selected_contract_count}"
        )
        print(
            f"Saxo OK:  "
            f"{result.saxo_resolution_success_count}"
        )
        print(
            f"Saxo fail:"
            f"{result.saxo_resolution_failure_count}"
        )

        if result.status != "COMPLETED":
            print()
            print(
                "The run was preserved but is "
                "NOT valid for normal Cohort 001 "
                "analysis."
            )
            return 1

        print()
        print(
            "COHORT 001 COMPLETED."
        )

        return 0

    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())

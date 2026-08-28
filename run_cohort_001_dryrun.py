from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_required_setting
from src.providers.massive import MassiveClient
from src.providers.saxo import SaxoClient
from src.providers.saxo_auth import get_saxo_live_access_token
from src.research.cohort_001_runner import run_cohort_001_collection


ROOT = Path(__file__).resolve().parent
SOURCE_DB = ROOT / "trade_log.db"
DRY_DB = ROOT / "trade_log_dryrun.db"
PREREG = ROOT / "research" / "cohort_001_preregistration_v2.md"

EXPECTED_SCHEMA = 7
EXPECTED_PREREG_BLOB = "d4a247aee2d25b65417905ff2f23c183608ab60d"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def session() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    session_date = now.date().isoformat()

    if now.weekday() >= 5:
        return session_date, "NON_TRADING_DAY"

    minute = now.hour * 60 + now.minute
    if minute < 13 * 60 + 30:
        state = "PRE_OPEN"
    elif minute < 20 * 60:
        state = "INTRADAY"
    else:
        state = "POST_CLOSE"

    return session_date, state


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def current_schema(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS version FROM schema_version;"
    ).fetchone()
    if row is None or row["version"] is None:
        raise RuntimeError("No schema version found.")
    return int(row["version"])


def report(conn: sqlite3.Connection, run_id: int) -> None:
    row = conn.execute(
        "SELECT * FROM research_runs WHERE id = ?;",
        (run_id,),
    ).fetchone()

    print()
    print("Dry-run result")
    print("--------------")

    if row is None:
        print("Run row not found.")
        return

    fields = [
        "id",
        "status",
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
    ]

    for field in fields:
        if field in row.keys():
            print(f"{field:34} {row[field]}")

    print()
    print("Selection exclusions")
    rows = conn.execute(
        """
        SELECT reason_code, COUNT(*) AS n
        FROM selection_exclusions
        WHERE run_id = ?
        GROUP BY reason_code
        ORDER BY reason_code;
        """,
        (run_id,),
    ).fetchall()

    if rows:
        for item in rows:
            print(f"  {item['reason_code']}: {item['n']}")
    else:
        print("  none")


def main() -> int:
    print("Christiania - Cohort 001 SHADOW DRY RUN")
    print("----------------------------------------")
    print("This does NOT write to trade_log.db.")
    print()

    if not SOURCE_DB.exists():
        raise RuntimeError("trade_log.db not found.")

    prereg_blob = git("hash-object", str(PREREG.relative_to(ROOT)))
    if prereg_blob != EXPECTED_PREREG_BLOB:
        raise RuntimeError(
            f"Prereg hash mismatch: {prereg_blob}"
        )

    code_sha = git("rev-parse", "HEAD")
    session_date, session_state = session()

    if DRY_DB.exists():
        DRY_DB.unlink()

    shutil.copy2(SOURCE_DB, DRY_DB)

    print(f"Code SHA:          {code_sha}")
    print(f"Prereg blob:       {prereg_blob}")
    print(f"Session date:      {session_date}")
    print(f"Session state:     {session_state}")
    print(f"Dry-run database:  {DRY_DB.name}")
    print()

    conn = connect(DRY_DB)

    try:
        schema = current_schema(conn)
        print(f"Schema:            v{schema}")
        if schema != EXPECTED_SCHEMA:
            raise RuntimeError(
                f"Expected schema v{EXPECTED_SCHEMA}, found v{schema}."
            )

        # Validate authentication and API configuration before the research run.
        massive_key = get_required_setting("MASSIVE_API_KEY")
        get_saxo_live_access_token()

        massive = MassiveClient(massive_key)
        saxo = SaxoClient(
            token_provider=get_saxo_live_access_token
        )

        print()
        print("Starting shadow collection...")
        print()

        result = run_cohort_001_collection(
            conn=conn,
            massive_client=massive,
            saxo_client=saxo,
            preregistration_hash=prereg_blob,
            code_git_sha=code_sha,
            us_session_date=session_date,
            us_session_state=session_state,
            underlying="AAPL",
        )

        conn.commit()
        report(conn, result.run_id)

        print()
        print(f"Runner status: {result.status}")
        print()
        print(
            "IMPORTANT: this was a SHADOW dry run on "
            "trade_log_dryrun.db only."
        )
        print(
            "It does not count as Cohort 001 and does not "
            "alter trade_log.db."
        )

        return 0 if result.status == "COMPLETED" else 1

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

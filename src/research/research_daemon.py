from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, time as clock_time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from src.database.repository import get_connection
from src.operations.market_calendar import session_sample_bounds
from src.providers.massive import MassiveClient
from src.providers.thetadata import ThetaDataClient
from src.research.full_research_cycle import (
    run_full_research_cycle,
)
from src.research.shadow_outcome_collector import (
    collect_shadow_marks,
)

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

DEFAULT_INTERVAL_MINUTES = 15
DEFAULT_SESSION_START = clock_time(9, 45)
DEFAULT_SESSION_END = clock_time(15, 45)
LOCK_STALE_AFTER = timedelta(minutes=30)
RESEARCH_RUN_STALE_AFTER = timedelta(hours=6)


class ResearchDaemonError(RuntimeError):
    pass


@dataclass(frozen=True)
class DaemonIterationSummary:
    scheduled_for: str
    status: str
    research_run_id: int | None
    hypothesis_scanner_run_id: int | None
    proposals_count: int | None
    admitted_count: int | None
    blocked_count: int | None
    outcome_mark_count: int | None
    error_type: str | None
    error_message: str | None


def load_env_file() -> None:
    path = Path(".env")

    if not path.exists():
        return

    for raw in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        name, value = line.split(
            "=",
            1,
        )

        os.environ.setdefault(
            name.strip(),
            value.strip(),
        )


def _iso_utc(
    moment: datetime | None = None,
) -> str:
    moment = (
        datetime.now(UTC)
        if moment is None
        else moment.astimezone(UTC)
    )

    return moment.isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    ).astimezone(UTC)


def _slot_on_date(
    date_value,
    *,
    hour: int,
    minute: int,
) -> datetime:
    return datetime(
        date_value.year,
        date_value.month,
        date_value.day,
        hour,
        minute,
        tzinfo=NY,
    )


def next_sampling_slot(
    now: datetime,
    *,
    interval_minutes: int =
        DEFAULT_INTERVAL_MINUTES,
    session_start: clock_time =
        DEFAULT_SESSION_START,
    session_end: clock_time =
        DEFAULT_SESSION_END,
) -> datetime:
    if interval_minutes <= 0:
        raise ValueError(
            "interval_minutes must be positive."
        )

    local = now.astimezone(NY)
    date_value = local.date()

    for day_offset in range(0, 15):
        candidate_date = (
            date_value
            + timedelta(days=day_offset)
        )

        bounds = session_sample_bounds(
            candidate_date,
            configured_start=session_start,
            configured_end=session_end,
        )

        if bounds is None:
            continue

        start, end = bounds
        slot = start

        while slot <= end:
            # For a daemon launched exactly on a slot, run that slot.
            if slot >= local:
                return slot

            slot += timedelta(
                minutes=interval_minutes
            )

    raise ResearchDaemonError(
        "Could not find a sampling slot "
        "within the next fourteen days."
    )


def acquire_daemon_lock(
    *,
    owner_token: str,
    db_path=None,
) -> None:
    now = datetime.now(UTC)

    conn = get_connection(db_path)

    try:
        conn.execute(
            "BEGIN IMMEDIATE;"
        )

        row = conn.execute(
            """
            SELECT *
            FROM research_daemon_lock
            WHERE singleton_id = 1;
            """
        ).fetchone()

        if row is not None:
            heartbeat = _parse_utc(
                str(row["heartbeat_at"])
            )

            if (
                now - heartbeat
                < LOCK_STALE_AFTER
            ):
                conn.rollback()
                raise ResearchDaemonError(
                    "Another Christiania research daemon "
                    "has an active lease."
                )

            conn.execute(
                """
                DELETE FROM research_daemon_lock
                WHERE singleton_id = 1;
                """
            )

        stamp = _iso_utc(now)

        conn.execute(
            """
            INSERT INTO research_daemon_lock (
                singleton_id,
                owner_token,
                acquired_at,
                heartbeat_at
            )
            VALUES (1, ?, ?, ?);
            """,
            (
                owner_token,
                stamp,
                stamp,
            ),
        )

        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()



def reconcile_orphaned_iterations(
    *,
    db_path=None,
) -> int:
    """
    Terminally classify stale RUNNING iterations left by a hard process stop.

    This function is called only after the singleton daemon lease has been
    acquired. A second genuinely live daemon therefore cannot race this
    startup repair.
    """
    cutoff = datetime.now(UTC) - LOCK_STALE_AFTER
    cutoff_iso = _iso_utc(cutoff)
    now_iso = _iso_utc()

    conn = get_connection(db_path)

    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE research_daemon_iterations
                SET
                    completed_at = ?,
                    status = 'ORPHANED',
                    error_type = 'INTERRUPTED_PROCESS',
                    error_message = (
                        'Recovered stale RUNNING iteration on daemon startup.'
                    )
                WHERE status = 'RUNNING'
                  AND started_at < ?;
                """,
                (
                    now_iso,
                    cutoff_iso,
                ),
            )

        return int(cursor.rowcount)
    finally:
        conn.close()



def reconcile_orphaned_research_runs(
    *,
    db_path=None,
) -> int:
    """
    Terminally fail abandoned COLLECTING research runs.

    Research runs do not currently carry the daemon owner token, so this uses
    a deliberately longer threshold than daemon-iteration recovery. This
    avoids misclassifying a slow but still-live manual/full-cycle run merely
    because it exceeded the 30-minute daemon lease threshold.

    Any ATTEMPTED underlying rows belonging to the abandoned run are also
    terminalized so the run cannot end with dangling in-progress children.
    """
    cutoff = (
        datetime.now(UTC)
        - RESEARCH_RUN_STALE_AFTER
    )
    cutoff_iso = _iso_utc(cutoff)
    now_iso = _iso_utc()
    reason = (
        "Recovered stale COLLECTING research run "
        "on daemon startup."
    )

    conn = get_connection(db_path)

    try:
        with conn:
            stale = conn.execute(
                """
                SELECT id
                FROM research_runs
                WHERE status = 'COLLECTING'
                  AND started_at < ?
                ORDER BY id;
                """,
                (cutoff_iso,),
            ).fetchall()

            for row in stale:
                run_id = int(row["id"])

                child_cursor = conn.execute(
                    """
                    UPDATE research_run_underlyings
                    SET
                        completed_at = ?,
                        status = 'FAILED',
                        failure_code = 'INTERRUPTED_PROCESS',
                        failure_reason = ?
                    WHERE run_id = ?
                      AND status = 'ATTEMPTED';
                    """,
                    (
                        now_iso,
                        reason,
                        run_id,
                    ),
                )

                interrupted_underlyings = int(
                    child_cursor.rowcount
                )

                cursor = conn.execute(
                    """
                    UPDATE research_runs
                    SET
                        ended_at = ?,
                        status = 'FAILED',
                        failed_underlyings =
                            failed_underlyings + ?,
                        underlying_observation_status =
                            CASE
                                WHEN attempted_underlyings > 0
                                    THEN 'FAILED'
                                ELSE underlying_observation_status
                            END,
                        notes =
                            COALESCE(notes, '')
                            || CASE
                                WHEN notes IS NULL OR notes = ''
                                    THEN ''
                                ELSE char(10)
                            END
                            || ?
                    WHERE id = ?
                      AND status = 'COLLECTING';
                    """,
                    (
                        now_iso,
                        interrupted_underlyings,
                        reason,
                        run_id,
                    ),
                )

                if cursor.rowcount != 1:
                    raise ResearchDaemonError(
                        "Stale research run could not be terminalized."
                    )

        return len(stale)
    finally:
        conn.close()


def heartbeat_daemon_lock(
    *,
    owner_token: str,
    db_path=None,
) -> None:
    conn = get_connection(db_path)

    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE research_daemon_lock
                SET heartbeat_at = ?
                WHERE singleton_id = 1
                  AND owner_token = ?;
                """,
                (
                    _iso_utc(),
                    owner_token,
                ),
            )

        if cursor.rowcount != 1:
            raise ResearchDaemonError(
                "Research daemon lease was lost."
            )
    finally:
        conn.close()


def release_daemon_lock(
    *,
    owner_token: str,
    db_path=None,
) -> None:
    conn = get_connection(db_path)

    try:
        with conn:
            conn.execute(
                """
                DELETE FROM research_daemon_lock
                WHERE singleton_id = 1
                  AND owner_token = ?;
                """,
                (owner_token,),
            )
    finally:
        conn.close()


def _start_iteration(
    *,
    owner_token: str,
    scheduled_for: datetime,
    db_path=None,
) -> int:
    conn = get_connection(db_path)

    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO research_daemon_iterations (
                    owner_token,
                    scheduled_for,
                    started_at,
                    status
                )
                VALUES (?, ?, ?, 'RUNNING');
                """,
                (
                    owner_token,
                    _iso_utc(
                        scheduled_for
                    ),
                    _iso_utc(),
                ),
            )

        return int(
            cursor.lastrowid
        )
    finally:
        conn.close()


def _complete_iteration(
    *,
    iteration_id: int,
    summary: DaemonIterationSummary,
    evidence_json: str,
    db_path=None,
) -> None:
    conn = get_connection(db_path)

    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE research_daemon_iterations
                SET
                    completed_at = ?,
                    status = ?,
                    research_run_id = ?,
                    hypothesis_scanner_run_id = ?,
                    proposals_count = ?,
                    admitted_count = ?,
                    blocked_count = ?,
                    outcome_mark_count = ?,
                    error_type = ?,
                    error_message = ?,
                    evidence_json = ?
                WHERE id = ?
                  AND status = 'RUNNING';
                """,
                (
                    _iso_utc(),
                    summary.status,
                    summary.research_run_id,
                    summary.hypothesis_scanner_run_id,
                    summary.proposals_count,
                    summary.admitted_count,
                    summary.blocked_count,
                    summary.outcome_mark_count,
                    summary.error_type,
                    summary.error_message,
                    evidence_json,
                    iteration_id,
                ),
            )

        if cursor.rowcount != 1:
            raise ResearchDaemonError(
                "Daemon iteration could not be finalized."
            )
    finally:
        conn.close()


def run_one_iteration(
    *,
    scheduled_for: datetime,
    owner_token: str,
    symbols: list[str],
    massive_client,
    theta_client,
    db_path=None,
    full_cycle_runner: Callable =
        run_full_research_cycle,
    mark_collector: Callable =
        collect_shadow_marks,
) -> DaemonIterationSummary:
    heartbeat_daemon_lock(
        owner_token=owner_token,
        db_path=db_path,
    )

    iteration_id = _start_iteration(
        owner_token=owner_token,
        scheduled_for=scheduled_for,
        db_path=db_path,
    )

    try:
        result = full_cycle_runner(
            symbols=symbols,
            massive_client=massive_client,
            theta_client=theta_client,
            db_path=db_path,
        )

        research_run_id = int(
            result.research_cycle
            .research
            .run_id
        )

        hypothesis_run_id = (
            result.research_cycle
            .hypothesis
            .persisted_scanner_run_id
        )

        marks = mark_collector(
            research_run_id=
                research_run_id,
            db_path=db_path,
        )

        admission = result.admission

        summary = DaemonIterationSummary(
            scheduled_for=
                _iso_utc(
                    scheduled_for
                ),
            status="COMPLETED",
            research_run_id=
                research_run_id,
            hypothesis_scanner_run_id=
                (
                    None
                    if hypothesis_run_id
                    is None
                    else int(
                        hypothesis_run_id
                    )
                ),
            proposals_count=
                result.structure_bridge
                .proposed_count,
            admitted_count=
                (
                    0
                    if admission is None
                    else admission.admitted_count
                ),
            blocked_count=
                (
                    result.structure_bridge
                    .blocked_count
                    + (
                        0
                        if admission is None
                        else admission.blocked_count
                    )
                ),
            outcome_mark_count=
                marks.marks_written,
            error_type=None,
            error_message=None,
        )

        _complete_iteration(
            iteration_id=iteration_id,
            summary=summary,
            evidence_json=json.dumps(
                {
                    "symbols":
                        symbols,
                    "shadow_marks_complete":
                        marks.complete_marks,
                    "shadow_marks_incomplete":
                        marks.incomplete_marks,
                },
                sort_keys=True,
            ),
            db_path=db_path,
        )

        heartbeat_daemon_lock(
            owner_token=owner_token,
            db_path=db_path,
        )

        return summary

    except KeyboardInterrupt:
        summary = DaemonIterationSummary(
            scheduled_for=
                _iso_utc(
                    scheduled_for
                ),
            status="ORPHANED",
            research_run_id=None,
            hypothesis_scanner_run_id=None,
            proposals_count=None,
            admitted_count=None,
            blocked_count=None,
            outcome_mark_count=None,
            error_type="INTERRUPTED_PROCESS",
            error_message=(
                "Daemon iteration interrupted by process stop."
            ),
        )

        _complete_iteration(
            iteration_id=iteration_id,
            summary=summary,
            evidence_json=json.dumps(
                {
                    "symbols": symbols,
                    "interrupted": True,
                },
                sort_keys=True,
            ),
            db_path=db_path,
        )

        raise

    except Exception as exc:
        summary = DaemonIterationSummary(
            scheduled_for=
                _iso_utc(
                    scheduled_for
                ),
            status="FAILED",
            research_run_id=None,
            hypothesis_scanner_run_id=None,
            proposals_count=None,
            admitted_count=None,
            blocked_count=None,
            outcome_mark_count=None,
            error_type=
                type(exc).__name__,
            error_message=
                str(exc),
        )

        _complete_iteration(
            iteration_id=iteration_id,
            summary=summary,
            evidence_json=json.dumps(
                {
                    "symbols":
                        symbols,
                },
                sort_keys=True,
            ),
            db_path=db_path,
        )

        heartbeat_daemon_lock(
            owner_token=owner_token,
            db_path=db_path,
        )

        return summary


def run_daemon(
    *,
    symbols: list[str],
    interval_minutes: int =
        DEFAULT_INTERVAL_MINUTES,
    max_iterations: int | None = None,
    db_path=None,
) -> int:
    load_env_file()

    massive_key = os.environ.get(
        "MASSIVE_API_KEY"
    )

    if not massive_key:
        raise ResearchDaemonError(
            "MASSIVE_API_KEY is missing."
        )

    owner_token = str(
        uuid.uuid4()
    )

    acquire_daemon_lock(
        owner_token=owner_token,
        db_path=db_path,
    )

    orphaned = reconcile_orphaned_iterations(
        db_path=db_path,
    )

    if orphaned:
        print(
            f"Recovered {orphaned} orphaned daemon iteration(s)."
        )

    orphaned_runs = reconcile_orphaned_research_runs(
        db_path=db_path,
    )

    if orphaned_runs:
        print(
            f"Recovered {orphaned_runs} abandoned research run(s)."
        )

    massive_client = MassiveClient(
        massive_key
    )
    theta_client = ThetaDataClient()

    completed = 0

    try:
        while (
            max_iterations is None
            or completed < max_iterations
        ):
            now = datetime.now(NY)

            slot = next_sampling_slot(
                now,
                interval_minutes=
                    interval_minutes,
            )

            wait_seconds = max(
                0.0,
                (
                    slot - now
                ).total_seconds(),
            )

            print(
                "Next Christiania sample: "
                f"{slot.isoformat()} "
                f"(in {wait_seconds / 60:.1f} min)"
            )

            # Heartbeat while waiting so a second daemon cannot take over.
            while wait_seconds > 0:
                sleep_for = min(
                    wait_seconds,
                    60.0,
                )

                time.sleep(
                    sleep_for
                )

                heartbeat_daemon_lock(
                    owner_token=
                        owner_token,
                    db_path=db_path,
                )

                now = datetime.now(NY)
                wait_seconds = max(
                    0.0,
                    (
                        slot - now
                    ).total_seconds(),
                )

            print()
            print(
                "Running scheduled sample "
                f"{slot.isoformat()}..."
            )

            summary = run_one_iteration(
                scheduled_for=slot,
                owner_token=owner_token,
                symbols=symbols,
                massive_client=
                    massive_client,
                theta_client=
                    theta_client,
                db_path=db_path,
            )

            print(
                f"Iteration status: "
                f"{summary.status}"
            )

            if (
                summary.research_run_id
                is not None
            ):
                print(
                    f"Research run: "
                    f"{summary.research_run_id}"
                )
                print(
                    f"Proposals: "
                    f"{summary.proposals_count or 0}; "
                    f"admitted: "
                    f"{summary.admitted_count or 0}; "
                    f"shadow marks: "
                    f"{summary.outcome_mark_count or 0}"
                )
            else:
                print(
                    f"Error: "
                    f"{summary.error_type}: "
                    f"{summary.error_message}"
                )

            print()

            completed += 1

            # Move past the slot so next_sampling_slot does not return it
            # again when an iteration completes within the same minute.
            time.sleep(1.0)

    except KeyboardInterrupt:
        print()
        print(
            "Christiania research daemon stopped by user."
        )
        return 0
    finally:
        release_daemon_lock(
            owner_token=owner_token,
            db_path=db_path,
        )

    return 0

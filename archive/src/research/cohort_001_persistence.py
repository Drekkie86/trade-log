from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.research.cohort_001 import (
    COHORT_ID,
    CohortSelection,
    EmptyStratum,
    SelectionExclusion,
)


SELECTION_RULE = "BASELINE_STRATIFIED_SAMPLE_V2"

RUN_STATUSES = {
    "STARTED",
    "COLLECTING",
    "COMPLETED",
    "FAILED",
    "INVALID",
}

SESSION_STATES = {
    "PRE_OPEN",
    "INTRADAY",
    "POST_CLOSE",
    "NON_TRADING_DAY",
}

TERMINAL_STATUSES = {
    "COMPLETED",
    "FAILED",
    "INVALID",
}


@dataclass(frozen=True)
class RunManifest:
    id: int
    cohort_id: str
    preregistration_hash: str
    code_git_sha: str
    started_at: str
    ended_at: str | None
    us_session_date: str
    us_session_state: str
    status: str
    attempted_underlyings: int
    succeeded_underlyings: int
    failed_underlyings: int
    provider_requests_attempted: int
    provider_requests_succeeded: int
    provider_requests_failed: int
    massive_raw_contracts: int | None
    massive_normalized_contracts: int | None
    normalization_drop_count: int | None
    selection_eligible_count: int | None
    selection_exclusion_count: int | None
    selected_strata_count: int | None
    empty_strata_count: int | None
    selected_contract_count: int | None
    saxo_resolution_success_count: int | None
    saxo_resolution_failure_count: int | None
    underlying_observation_status: str | None
    notes: str | None


def _require_nonblank(
    value: str,
    field_name: str,
) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} cannot be blank."
        )

    return normalized


def _require_nonnegative(
    value: int,
    field_name: str,
) -> int:
    if value < 0:
        raise ValueError(
            f"{field_name} cannot be negative."
        )

    return value


def create_research_run(
    conn,
    *,
    preregistration_hash: str,
    code_git_sha: str,
    started_at: str,
    us_session_date: str,
    us_session_state: str,
    notes: str | None = None,
) -> int:
    preregistration_hash = _require_nonblank(
        preregistration_hash,
        "preregistration_hash",
    )

    code_git_sha = _require_nonblank(
        code_git_sha,
        "code_git_sha",
    )

    started_at = _require_nonblank(
        started_at,
        "started_at",
    )

    us_session_date = _require_nonblank(
        us_session_date,
        "us_session_date",
    )

    us_session_state = (
        us_session_state
        .strip()
        .upper()
    )

    if (
        us_session_state
        not in SESSION_STATES
    ):
        raise ValueError(
            "Invalid US session state: "
            f"{us_session_state}"
        )

    cursor = conn.execute(
        """
        INSERT INTO research_runs (
            cohort_id,
            preregistration_hash,
            code_git_sha,
            started_at,
            us_session_date,
            us_session_state,
            status,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, 'STARTED', ?);
        """,
        (
            COHORT_ID,
            preregistration_hash,
            code_git_sha,
            started_at,
            us_session_date,
            us_session_state,
            notes,
        ),
    )

    return int(
        cursor.lastrowid
    )


def set_run_status(
    conn,
    *,
    run_id: int,
    status: str,
    ended_at: str | None = None,
    notes: str | None = None,
) -> None:
    normalized = (
        status
        .strip()
        .upper()
    )

    if normalized not in RUN_STATUSES:
        raise ValueError(
            f"Invalid run status: "
            f"{normalized}"
        )

    if normalized in TERMINAL_STATUSES:
        if ended_at is None:
            raise ValueError(
                "Terminal research runs "
                "require ended_at."
            )
    elif ended_at is not None:
        raise ValueError(
            "Non-terminal research runs "
            "cannot have ended_at."
        )

    cursor = conn.execute(
        """
        UPDATE research_runs
        SET
            status = ?,
            ended_at = ?,
            notes = COALESCE(?, notes)
        WHERE id = ?;
        """,
        (
            normalized,
            ended_at,
            notes,
            run_id,
        ),
    )

    if cursor.rowcount == 0:
        raise ValueError(
            f"Research run {run_id} "
            "does not exist."
        )


def set_massive_collection_counts(
    conn,
    *,
    run_id: int,
    raw_contracts: int,
    normalized_contracts: int,
    normalization_drop_count: int,
) -> None:
    raw_contracts = _require_nonnegative(
        raw_contracts,
        "raw_contracts",
    )

    normalized_contracts = _require_nonnegative(
        normalized_contracts,
        "normalized_contracts",
    )

    normalization_drop_count = (
        _require_nonnegative(
            normalization_drop_count,
            "normalization_drop_count",
        )
    )

    if (
        normalized_contracts
        + normalization_drop_count
        != raw_contracts
    ):
        raise ValueError(
            "Massive normalization counts "
            "do not reconcile."
        )

    conn.execute(
        """
        UPDATE research_runs
        SET
            massive_raw_contracts = ?,
            massive_normalized_contracts = ?,
            normalization_drop_count = ?
        WHERE id = ?;
        """,
        (
            raw_contracts,
            normalized_contracts,
            normalization_drop_count,
            run_id,
        ),
    )


def persist_normalization_drops(
    conn,
    *,
    run_id: int,
    snapshot_id: int | None,
    drops: Iterable[Any],
    dropped_at: str,
) -> int:
    dropped_at = _require_nonblank(
        dropped_at,
        "dropped_at",
    )

    count = 0

    for drop in drops:
        conn.execute(
            """
            INSERT INTO normalization_drops (
                run_id,
                snapshot_id,
                provider,
                underlying,
                provider_contract_id,
                option_symbol,
                raw_contract_type,
                raw_strike,
                raw_expiration,
                reason_code,
                reason_detail,
                dropped_at,
                raw_payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                run_id,
                snapshot_id,
                drop.provider,
                drop.underlying,
                drop.provider_contract_id,
                drop.option_symbol,
                drop.raw_contract_type,
                drop.raw_strike,
                drop.raw_expiration,
                drop.reason_code,
                drop.reason_detail,
                dropped_at,
                drop.raw_payload_json,
            ),
        )

        count += 1

    return count



def _persist_selection_exclusions(
    conn,
    *,
    run_id: int,
    snapshot_id: int,
    exclusions: Iterable[
        SelectionExclusion
    ],
    excluded_at: str,
    preregistration_hash: str,
    code_git_sha: str,
) -> int:
    count = 0

    for exclusion in exclusions:
        conn.execute(
            """
            INSERT INTO selection_exclusions (
                run_id,
                snapshot_id,
                option_quote_id,
                provider,
                underlying,
                provider_contract_id,
                option_symbol,
                option_right,
                strike,
                expiration,
                reason_code,
                reason_detail,
                excluded_at,
                preregistration_hash,
                code_git_sha
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                run_id,
                snapshot_id,
                exclusion.option_quote_id,
                exclusion.provider,
                exclusion.underlying,
                exclusion.provider_contract_id,
                exclusion.option_symbol,
                exclusion.right,
                exclusion.strike,
                exclusion.expiration,
                exclusion.reason_code,
                exclusion.reason_detail,
                excluded_at,
                preregistration_hash,
                code_git_sha,
            ),
        )

        count += 1

    return count

def freeze_selection_manifest(
    conn,
    *,
    run_id: int,
    snapshot_id: int,
    selections: Iterable[
        CohortSelection
    ],
    empty_strata: Iterable[
        EmptyStratum
    ],
    selection_eligible_count: int,
    selection_exclusions: Iterable[
        SelectionExclusion
    ],
    selected_at: str,
    preregistration_hash: str,
    code_git_sha: str,
) -> int:
    """
    Atomically persist the full selection-stage
    partition and the already-selected population
    before any Saxo option resolution is attempted.

    Mandatory reconciliation:

        normalized contracts
        = selection eligible
        + selection exclusions
    """

    selected_at = _require_nonblank(
        selected_at,
        "selected_at",
    )

    preregistration_hash = _require_nonblank(
        preregistration_hash,
        "preregistration_hash",
    )

    code_git_sha = _require_nonblank(
        code_git_sha,
        "code_git_sha",
    )

    selection_eligible_count = (
        _require_nonnegative(
            selection_eligible_count,
            "selection_eligible_count",
        )
    )

    selection_list = tuple(
        selections
    )

    empty_list = tuple(
        empty_strata
    )

    exclusion_list = tuple(
        selection_exclusions
    )

    sequences = [
        item.resolution_sequence
        for item in selection_list
    ]

    if any(
        sequence is None
        for sequence in sequences
    ):
        raise ValueError(
            "Every frozen selection requires "
            "a resolution_sequence."
        )

    if len(
        set(sequences)
    ) != len(sequences):
        raise ValueError(
            "resolution_sequence values "
            "must be unique."
        )

    expected_sequences = set(
        range(
            1,
            len(selection_list) + 1,
        )
    )

    if set(sequences) != expected_sequences:
        raise ValueError(
            "resolution_sequence values "
            "must form 1..N."
        )

    current = conn.execute(
        """
        SELECT
            preregistration_hash,
            code_git_sha,
            status,
            massive_normalized_contracts
        FROM research_runs
        WHERE id = ?;
        """,
        (run_id,),
    ).fetchone()

    if current is None:
        raise ValueError(
            f"Research run {run_id} "
            "does not exist."
        )

    if (
        current["preregistration_hash"]
        != preregistration_hash
    ):
        raise ValueError(
            "Selection preregistration hash "
            "does not match the run manifest."
        )

    if (
        current["code_git_sha"]
        != code_git_sha
    ):
        raise ValueError(
            "Selection code Git SHA "
            "does not match the run manifest."
        )

    if current["status"] in TERMINAL_STATUSES:
        raise ValueError(
            "Cannot add selections to a "
            "terminal research run."
        )

    normalized_count = (
        current[
            "massive_normalized_contracts"
        ]
    )

    if normalized_count is None:
        raise ValueError(
            "Massive normalized count must "
            "be persisted before selection."
        )

    if (
        selection_eligible_count
        + len(exclusion_list)
        != normalized_count
    ):
        raise ValueError(
            "Selection-universe counts "
            "do not reconcile: normalized "
            "must equal eligible plus "
            "exclusions."
        )

    if (
        len(selection_list)
        > selection_eligible_count
    ):
        raise ValueError(
            "Selected contracts cannot "
            "exceed selection-eligible "
            "contracts."
        )

    conn.execute(
        "SAVEPOINT cohort_selection_freeze;"
    )

    try:
        _persist_selection_exclusions(
            conn,
            run_id=run_id,
            snapshot_id=snapshot_id,
            exclusions=exclusion_list,
            excluded_at=selected_at,
            preregistration_hash=(
                preregistration_hash
            ),
            code_git_sha=code_git_sha,
        )

        for selection in selection_list:
            conn.execute(
                """
                INSERT INTO research_selections (
                    run_id,
                    option_quote_id,
                    selected_at,
                    selection_rule,
                    dte_stratum,
                    delta_stratum,
                    option_right,
                    resolution_sequence,
                    preregistration_hash,
                    code_git_sha
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    run_id,
                    selection.quote.option_quote_id,
                    selected_at,
                    SELECTION_RULE,
                    (
                        f"{selection.stratum.dte_min}-"
                        f"{selection.stratum.dte_max}"
                    ),
                    (
                        f"{selection.stratum.abs_delta_min:.2f}-"
                        f"{selection.stratum.abs_delta_max:.2f}"
                    ),
                    selection.stratum.right,
                    selection.resolution_sequence,
                    preregistration_hash,
                    code_git_sha,
                ),
            )

        conn.execute(
            """
            UPDATE research_runs
            SET
                selection_eligible_count = ?,
                selection_exclusion_count = ?,
                selected_strata_count = ?,
                empty_strata_count = ?,
                selected_contract_count = ?,
                status = 'COLLECTING'
            WHERE id = ?;
            """,
            (
                selection_eligible_count,
                len(exclusion_list),
                len(selection_list),
                len(empty_list),
                len(selection_list),
                run_id,
            ),
        )

        conn.execute(
            "RELEASE SAVEPOINT "
            "cohort_selection_freeze;"
        )

    except Exception:
        conn.execute(
            "ROLLBACK TO SAVEPOINT "
            "cohort_selection_freeze;"
        )
        conn.execute(
            "RELEASE SAVEPOINT "
            "cohort_selection_freeze;"
        )
        raise

    return len(
        selection_list
    )


def get_run_manifest(
    conn,
    *,
    run_id: int,
) -> RunManifest | None:
    row = conn.execute(
        """
        SELECT *
        FROM research_runs
        WHERE id = ?;
        """,
        (run_id,),
    ).fetchone()

    if row is None:
        return None

    return RunManifest(
        id=row["id"],
        cohort_id=row["cohort_id"],
        preregistration_hash=(
            row["preregistration_hash"]
        ),
        code_git_sha=row["code_git_sha"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        us_session_date=(
            row["us_session_date"]
        ),
        us_session_state=(
            row["us_session_state"]
        ),
        status=row["status"],
        attempted_underlyings=(
            row["attempted_underlyings"]
        ),
        succeeded_underlyings=(
            row["succeeded_underlyings"]
        ),
        failed_underlyings=(
            row["failed_underlyings"]
        ),
        provider_requests_attempted=(
            row["provider_requests_attempted"]
        ),
        provider_requests_succeeded=(
            row["provider_requests_succeeded"]
        ),
        provider_requests_failed=(
            row["provider_requests_failed"]
        ),
        massive_raw_contracts=(
            row["massive_raw_contracts"]
        ),
        massive_normalized_contracts=(
            row["massive_normalized_contracts"]
        ),
        normalization_drop_count=(
            row["normalization_drop_count"]
        ),
        selection_eligible_count=(
            row["selection_eligible_count"]
        ),
        selection_exclusion_count=(
            row["selection_exclusion_count"]
        ),
        selected_strata_count=(
            row["selected_strata_count"]
        ),
        empty_strata_count=(
            row["empty_strata_count"]
        ),
        selected_contract_count=(
            row["selected_contract_count"]
        ),
        saxo_resolution_success_count=(
            row["saxo_resolution_success_count"]
        ),
        saxo_resolution_failure_count=(
            row["saxo_resolution_failure_count"]
        ),
        underlying_observation_status=(
            row["underlying_observation_status"]
        ),
        notes=row["notes"],
    )

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from src.research.cohort_001 import (
    CohortQuote,
    SelectionExclusion,
    assign_resolution_sequence,
    make_test_rng,
    select_primary_contracts,
)
from src.research.cohort_001_persistence import (
    COHORT_ID,
    create_research_run,
    freeze_selection_manifest,
    get_run_manifest,
    persist_normalization_drops,
    set_massive_collection_counts,
    set_run_status,
)
from src.providers.massive import (
    normalize_massive_option_chain_for_research,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

SESSION_DATE = date(
    2026,
    8,
    28,
)


def build_database(
    tmp_path,
):
    db_path = (
        tmp_path
        / "cohort_persistence.db"
    )

    schema = (
        PROJECT_ROOT
        / "trade_log_schema.sql"
    ).read_text(
        encoding="utf-8"
    )

    connection = sqlite3.connect(
        db_path
    )

    connection.row_factory = (
        sqlite3.Row
    )

    connection.execute(
        "PRAGMA foreign_keys = ON;"
    )

    connection.executescript(
        schema
    )

    version = connection.execute(
        """
        SELECT version
        FROM schema_version;
        """
    ).fetchone()[0]

    if version == 6:
        migration = (
            PROJECT_ROOT
            / "migrations"
            / "007_selection_universe_integrity.sql"
        ).read_text(
            encoding="utf-8"
        )

        connection.executescript(
            migration
        )

    assert connection.execute(
        """
        SELECT version
        FROM schema_version;
        """
    ).fetchone()[0] == 7

    return connection


def create_run_and_snapshot(
    connection,
):
    run_id = create_research_run(
        connection,
        preregistration_hash="hash123",
        code_git_sha="sha123",
        started_at="2026-08-28T12:00:00Z",
        us_session_date="2026-08-28",
        us_session_state="PRE_OPEN",
    )

    snapshot_id = (
        connection.execute(
            """
            INSERT INTO market_snapshots (
                captured_at,
                underlying,
                provider,
                underlying_price,
                underlying_source,
                fx_to_eur,
                fx_source,
                research_run_id,
                us_session_date,
                us_session_state
            )
            VALUES (
                '2026-08-28T12:00:01Z',
                'AAPL',
                'MASSIVE',
                NULL,
                'UNKNOWN',
                NULL,
                'UNKNOWN',
                ?,
                '2026-08-28',
                'PRE_OPEN'
            );
            """,
            (run_id,),
        )
        .lastrowid
    )

    return (
        run_id,
        snapshot_id,
    )


def insert_quote(
    connection,
    snapshot_id: int,
    *,
    symbol: str,
    right: str,
    strike: float,
    expiration: str,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO option_quotes (
                snapshot_id,
                provider_contract_id,
                option_symbol,
                right,
                strike,
                expiration,

                bid,
                bid_source,

                ask,
                ask_source,

                last,
                last_source,

                implied_volatility,
                iv_source,

                delta,
                delta_source,

                gamma,
                gamma_source,

                theta,
                theta_source,

                vega,
                vega_source,

                volume,
                volume_source,

                open_interest,
                open_interest_source
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,

                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',

                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',

                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN'
            );
            """,
            (
                snapshot_id,
                symbol,
                symbol,
                right,
                strike,
                expiration,
            ),
        ).lastrowid
    )


def make_selection(
    quote_id: int,
    *,
    right: str = "C",
    delta: float = 0.15,
):
    result = select_primary_contracts(
        [
            CohortQuote(
                option_quote_id=quote_id,
                provider_contract_id=(
                    f"O:TEST{quote_id}"
                ),
                option_symbol=(
                    f"O:TEST{quote_id}"
                ),
                right=right,
                strike=320.0,
                expiration="2026-09-11",
                delta=delta,
            ),
        ],
        session_date=SESSION_DATE,
    )

    return assign_resolution_sequence(
        result.selected,
        rng=make_test_rng(1),
    ), result.empty


def test_create_run_manifest(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id = create_research_run(
            connection,
            preregistration_hash="hash123",
            code_git_sha="sha123",
            started_at="2026-08-28T12:00:00Z",
            us_session_date="2026-08-28",
            us_session_state="PRE_OPEN",
        )

        manifest = get_run_manifest(
            connection,
            run_id=run_id,
        )

        assert manifest is not None
        assert (
            manifest.cohort_id
            == COHORT_ID
        )
        assert manifest.status == "STARTED"
        assert manifest.ended_at is None

    finally:
        connection.close()


def test_massive_counts_must_reconcile(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, _ = (
            create_run_and_snapshot(
                connection
            )
        )

        with pytest.raises(
            ValueError,
            match="do not reconcile",
        ):
            set_massive_collection_counts(
                connection,
                run_id=run_id,
                raw_contracts=100,
                normalized_contracts=90,
                normalization_drop_count=9,
            )

    finally:
        connection.close()


def test_massive_counts_are_persisted(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, _ = (
            create_run_and_snapshot(
                connection
            )
        )

        set_massive_collection_counts(
            connection,
            run_id=run_id,
            raw_contracts=100,
            normalized_contracts=97,
            normalization_drop_count=3,
        )

        manifest = get_run_manifest(
            connection,
            run_id=run_id,
        )

        assert manifest is not None
        assert (
            manifest.massive_raw_contracts
            == 100
        )
        assert (
            manifest.massive_normalized_contracts
            == 97
        )
        assert (
            manifest.normalization_drop_count
            == 3
        )

    finally:
        connection.close()


def test_normalization_drops_persist(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    payload = {
        "request_id": "request-1",
        "reference_date": "2026-08-28",
        "results": [
            {
                "details": {
                    "ticker": "O:BAD",
                    "contract_type": "other",
                    "strike_price": 320,
                    "expiration_date":
                        "2026-09-18",
                },
            },
        ],
    }

    normalized = (
        normalize_massive_option_chain_for_research(
            "AAPL",
            payload,
        )
    )

    try:
        run_id, snapshot_id = (
            create_run_and_snapshot(
                connection
            )
        )

        written = (
            persist_normalization_drops(
                connection,
                run_id=run_id,
                snapshot_id=snapshot_id,
                drops=normalized.drops,
                dropped_at=(
                    "2026-08-28T12:00:02Z"
                ),
            )
        )

        assert written == 1

        row = connection.execute(
            """
            SELECT *
            FROM normalization_drops
            WHERE run_id = ?;
            """,
            (run_id,),
        ).fetchone()

        assert row is not None
        assert (
            row["reason_code"]
            == "UNSUPPORTED_CONTRACT_TYPE"
        )

    finally:
        connection.close()


def test_freeze_selection_writes_before_resolution(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, snapshot_id = (
            create_run_and_snapshot(
                connection
            )
        )

        quote_id = insert_quote(
            connection,
            snapshot_id,
            symbol="O:TEST1",
            right="C",
            strike=320,
            expiration="2026-09-11",
        )

        selections, empty = (
            make_selection(
                quote_id
            )
        )

        set_massive_collection_counts(
            connection,
            run_id=run_id,
            raw_contracts=1,
            normalized_contracts=1,
            normalization_drop_count=0,
        )

        written = (
            freeze_selection_manifest(
                connection,
                run_id=run_id,
                snapshot_id=snapshot_id,
                selections=selections,
                empty_strata=empty,
                selection_eligible_count=1,
                selection_exclusions=(),
                selected_at=(
                    "2026-08-28T12:00:03Z"
                ),
                preregistration_hash=(
                    "hash123"
                ),
                code_git_sha="sha123",
            )
        )

        assert written == 1

        manifest = get_run_manifest(
            connection,
            run_id=run_id,
        )

        assert manifest is not None
        assert manifest.status == "COLLECTING"
        assert (
            manifest.selected_strata_count
            == 1
        )
        assert (
            manifest.empty_strata_count
            == 29
        )
        assert (
            manifest.selected_contract_count
            == 1
        )

        selection = connection.execute(
            """
            SELECT *
            FROM research_selections
            WHERE run_id = ?;
            """,
            (run_id,),
        ).fetchone()

        assert selection is not None
        assert (
            selection["option_quote_id"]
            == quote_id
        )
        assert (
            selection["resolution_sequence"]
            == 1
        )

        # No Saxo evidence is required or written
        # by this persistence step.
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM saxo_option_observations;
            """
        ).fetchone()[0] == 0

        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM saxo_resolution_failures;
            """
        ).fetchone()[0] == 0

    finally:
        connection.close()


def test_selection_hash_must_match_run(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, snapshot_id = (
            create_run_and_snapshot(
                connection
            )
        )

        quote_id = insert_quote(
            connection,
            snapshot_id,
            symbol="O:TEST1",
            right="C",
            strike=320,
            expiration="2026-09-11",
        )

        selections, empty = (
            make_selection(
                quote_id
            )
        )

        set_massive_collection_counts(
            connection,
            run_id=run_id,
            raw_contracts=1,
            normalized_contracts=1,
            normalization_drop_count=0,
        )

        with pytest.raises(
            ValueError,
            match="preregistration hash",
        ):
            freeze_selection_manifest(
                connection,
                run_id=run_id,
                snapshot_id=snapshot_id,
                selections=selections,
                empty_strata=empty,
                selection_eligible_count=1,
                selection_exclusions=(),
                selected_at=(
                    "2026-08-28T12:00:03Z"
                ),
                preregistration_hash="wrong",
                code_git_sha="sha123",
            )

    finally:
        connection.close()


def test_selection_must_belong_to_run_snapshot(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, _ = (
            create_run_and_snapshot(
                connection
            )
        )

        other_run, other_snapshot = (
            create_run_and_snapshot(
                connection
            )
        )

        assert other_run != run_id

        quote_id = insert_quote(
            connection,
            other_snapshot,
            symbol="O:OTHER",
            right="C",
            strike=320,
            expiration="2026-09-11",
        )

        selections, empty = (
            make_selection(
                quote_id
            )
        )

        set_massive_collection_counts(
            connection,
            run_id=run_id,
            raw_contracts=1,
            normalized_contracts=1,
            normalization_drop_count=0,
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match="must belong",
        ):
            freeze_selection_manifest(
                connection,
                run_id=run_id,
                snapshot_id=other_snapshot,
                selections=selections,
                empty_strata=empty,
                selection_eligible_count=1,
                selection_exclusions=(),
                selected_at=(
                    "2026-08-28T12:00:03Z"
                ),
                preregistration_hash=(
                    "hash123"
                ),
                code_git_sha="sha123",
            )

    finally:
        connection.close()


def test_resolution_sequence_must_be_complete(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, snapshot_id = (
            create_run_and_snapshot(
                connection
            )
        )

        quote_id = insert_quote(
            connection,
            snapshot_id,
            symbol="O:TEST1",
            right="C",
            strike=320,
            expiration="2026-09-11",
        )

        selected = (
            select_primary_contracts(
                [
                    CohortQuote(
                        option_quote_id=quote_id,
                        provider_contract_id=(
                            "O:TEST1"
                        ),
                        option_symbol="O:TEST1",
                        right="C",
                        strike=320,
                        expiration=(
                            "2026-09-11"
                        ),
                        delta=0.15,
                    ),
                ],
                session_date=SESSION_DATE,
            )
        )

        set_massive_collection_counts(
            connection,
            run_id=run_id,
            raw_contracts=1,
            normalized_contracts=1,
            normalization_drop_count=0,
        )

        with pytest.raises(
            ValueError,
            match="requires.*resolution_sequence",
        ):
            freeze_selection_manifest(
                connection,
                run_id=run_id,
                snapshot_id=snapshot_id,
                selections=selected.selected,
                empty_strata=selected.empty,
                selection_eligible_count=1,
                selection_exclusions=(),
                selected_at=(
                    "2026-08-28T12:00:03Z"
                ),
                preregistration_hash=(
                    "hash123"
                ),
                code_git_sha="sha123",
            )

    finally:
        connection.close()



def test_selection_exclusion_persists_and_reconciles(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, snapshot_id = (
            create_run_and_snapshot(
                connection
            )
        )

        quote_id = insert_quote(
            connection,
            snapshot_id,
            symbol="O:TEST1",
            right="C",
            strike=320,
            expiration="2026-09-11",
        )

        set_massive_collection_counts(
            connection,
            run_id=run_id,
            raw_contracts=1,
            normalized_contracts=1,
            normalization_drop_count=0,
        )

        exclusion = SelectionExclusion(
            option_quote_id=quote_id,
            provider="MASSIVE",
            underlying="AAPL",
            provider_contract_id="O:TEST1",
            option_symbol="O:TEST1",
            right="C",
            strike=320.0,
            expiration="2026-09-11",
            reason_code="MISSING_DELTA",
            reason_detail=(
                "Matched provider model "
                "observation has no delta."
            ),
        )

        written = freeze_selection_manifest(
            connection,
            run_id=run_id,
            snapshot_id=snapshot_id,
            selections=(),
            empty_strata=(),
            selection_eligible_count=0,
            selection_exclusions=(
                exclusion,
            ),
            selected_at=(
                "2026-08-28T12:00:03Z"
            ),
            preregistration_hash="hash123",
            code_git_sha="sha123",
        )

        assert written == 0

        manifest = get_run_manifest(
            connection,
            run_id=run_id,
        )

        assert manifest is not None
        assert (
            manifest.selection_eligible_count
            == 0
        )
        assert (
            manifest.selection_exclusion_count
            == 1
        )

        row = connection.execute(
            """
            SELECT *
            FROM selection_exclusions
            WHERE run_id = ?;
            """,
            (run_id,),
        ).fetchone()

        assert row is not None
        assert (
            row["reason_code"]
            == "MISSING_DELTA"
        )

        reconciliation = (
            connection.execute(
                """
                SELECT *
                FROM v_selection_universe_reconciliation
                WHERE run_id = ?;
                """,
                (run_id,),
            ).fetchone()
        )

        assert (
            reconciliation[
                "selection_population_reconciles"
            ]
            == 1
        )

    finally:
        connection.close()


def test_selection_freeze_rejects_nonreconciling_population(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, snapshot_id = (
            create_run_and_snapshot(
                connection
            )
        )

        set_massive_collection_counts(
            connection,
            run_id=run_id,
            raw_contracts=2,
            normalized_contracts=2,
            normalization_drop_count=0,
        )

        with pytest.raises(
            ValueError,
            match="do not reconcile",
        ):
            freeze_selection_manifest(
                connection,
                run_id=run_id,
                snapshot_id=snapshot_id,
                selections=(),
                empty_strata=(),
                selection_eligible_count=1,
                selection_exclusions=(),
                selected_at=(
                    "2026-08-28T12:00:03Z"
                ),
                preregistration_hash="hash123",
                code_git_sha="sha123",
            )

        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM selection_exclusions
            WHERE run_id = ?;
            """,
            (run_id,),
        ).fetchone()[0] == 0

        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM research_selections
            WHERE run_id = ?;
            """,
            (run_id,),
        ).fetchone()[0] == 0

    finally:
        connection.close()

def test_terminal_run_locks_manifest(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    try:
        run_id, _ = (
            create_run_and_snapshot(
                connection
            )
        )

        set_run_status(
            connection,
            run_id=run_id,
            status="COMPLETED",
            ended_at="2026-08-28T12:10:00Z",
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match="Terminal research runs",
        ):
            connection.execute(
                """
                UPDATE research_runs
                SET notes = 'changed'
                WHERE id = ?;
                """,
                (run_id,),
            )

    finally:
        connection.close()

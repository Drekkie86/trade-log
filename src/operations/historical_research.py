from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from src.database.repository import (
    resolve_db_path,
)
from src.operations.research_archive import (
    ResearchArchiveManifest,
    inventory_research_archives,
    open_verified_archive_connection,
    resolve_archive_dir,
)


PROFILE_FORMAT_VERSION = 1
PARITY_STATE_PASS = (
    "HOT_ARCHIVE_ANALYTICAL_PARITY_PASS"
)
PARITY_STATE_FAIL = (
    "HOT_ARCHIVE_ANALYTICAL_PARITY_FAIL"
)


_SCOPE_FROM: dict[
    str,
    str,
] = {
    "research_runs": """
        FROM research_runs AS t
        WHERE t.id IN ({run_ids})
    """,
    "research_daemon_iterations": """
        FROM research_daemon_iterations AS t
        WHERE t.research_run_id IN ({run_ids})
    """,
    "market_snapshots": """
        FROM market_snapshots AS t
        WHERE t.research_run_id IN ({run_ids})
    """,
    "option_quotes": """
        FROM option_quotes AS t
        JOIN market_snapshots AS ms
          ON ms.id = t.snapshot_id
        WHERE ms.research_run_id IN ({run_ids})
    """,
    "provider_model_observations": """
        FROM provider_model_observations AS t
        JOIN option_quotes AS oq
          ON oq.id = t.option_quote_id
        JOIN market_snapshots AS ms
          ON ms.id = oq.snapshot_id
        WHERE ms.research_run_id IN ({run_ids})
    """,
    "listing_reference_contracts": """
        FROM listing_reference_contracts AS t
        WHERE t.research_run_id IN ({run_ids})
    """,
    "provider_observation_availability": """
        FROM provider_observation_availability AS t
        JOIN listing_reference_contracts AS lrc
          ON lrc.id = t.reference_contract_id
        WHERE lrc.research_run_id IN ({run_ids})
    """,
    "hypothesis_scanner_runs": """
        FROM hypothesis_scanner_runs AS t
        WHERE t.research_run_id IN ({run_ids})
    """,
    "hypothesis_scanner_evaluations": """
        FROM hypothesis_scanner_evaluations AS t
        JOIN hypothesis_scanner_runs AS r
          ON r.id = t.scanner_run_id
        WHERE r.research_run_id IN ({run_ids})
    """,
    "local_surface_residual_v2_runs": """
        FROM local_surface_residual_v2_runs AS t
        WHERE t.research_run_id IN ({run_ids})
    """,
    "local_surface_residual_v2_observations": """
        FROM local_surface_residual_v2_observations AS t
        JOIN local_surface_residual_v2_runs AS r
          ON r.id = t.model_run_id
        WHERE r.research_run_id IN ({run_ids})
    """,
}


_ANALYTICAL_FINGERPRINT_COLUMNS: dict[
    str,
    tuple[str, ...],
] = {
    "research_runs": (
        "id",
        "status",
        "started_at",
        "ended_at",
        "us_session_date",
        "us_session_state",
        "cohort_id",
        "preregistration_hash",
        "code_git_sha",
    ),
    "market_snapshots": (
        "id",
        "research_run_id",
        "captured_at",
        "underlying",
        "provider",
        "provider_snapshot_id",
        "underlying_price",
        "underlying_source",
        "underlying_at",
        "fx_to_eur",
        "fx_source",
        "fx_at",
    ),
    "option_quotes": (
        "id",
        "snapshot_id",
        "provider_contract_id",
        "option_symbol",
        "right",
        "strike",
        "expiration",
        "quote_at",
        "bid",
        "ask",
        "last",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
        "volume",
        "open_interest",
    ),
    "provider_model_observations": (
        "id",
        "option_quote_id",
        "provider",
        "ingested_at",
        "observed_at",
        "source",
        "model_name",
        "provider_request_id",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
    ),
    "listing_reference_contracts": (
        "id",
        "research_run_id",
        "provider",
        "underlying",
        "provider_contract_id",
        "option_symbol",
        "expiration",
        "strike",
        "right",
        "exercise_style",
        "shares_per_contract",
        "primary_exchange",
        "observed_at",
        "ingested_at",
    ),
    "provider_observation_availability": (
        "id",
        "reference_contract_id",
        "provider",
        "evidence_family",
        "state",
        "provider_observation_id",
        "reason_code",
        "observed_at",
        "raw_timestamp",
        "ingested_at",
    ),
    "hypothesis_scanner_evaluations": (
        "id",
        "scanner_run_id",
        "reference_contract_id",
        "option_quote_id",
        "underlying",
        "expiration",
        "strike",
        "right",
        "delta",
        "implied_volatility",
        "lower_strike",
        "lower_iv",
        "upper_strike",
        "upper_iv",
        "interpolated_iv",
        "iv_residual",
        "abs_iv_residual",
        "residual_threshold",
        "evaluation_state",
        "reason_code",
        "surfaced_direction",
    ),
    "local_surface_residual_v2_observations": (
        "id",
        "model_run_id",
        "reference_contract_id",
        "option_quote_id",
        "underlying",
        "expiration",
        "strike",
        "right",
        "delta",
        "implied_volatility",
        "usable_strike_count",
        "fit_point_count",
        "fit_dof",
        "fitted_iv",
        "loo_residual",
        "abs_loo_residual",
        "fit_sse",
        "fit_rmse",
        "design_condition_number",
        "observation_state",
        "reason_code",
    ),
}


@dataclass(frozen=True)
class HistoricalSessionProfile:
    format_version: int
    source_kind: str
    source_schema_version: int
    session_date: str
    run_ids: tuple[int, ...]
    table_identity: dict[
        str,
        dict[str, int | None],
    ]
    scalar_metrics: dict[
        str,
        dict[str, int | float | str | None],
    ]
    analytical_fingerprints: dict[str, str]
    dimensions: dict[
        str,
        dict[str, int],
    ]
    analytical_sha256: str

    def as_dict(
        self,
    ) -> dict[str, object]:
        data = asdict(
            self
        )
        data[
            "run_ids"
        ] = list(
            self.run_ids
        )
        return data


@dataclass(frozen=True)
class HotArchiveAnalyticalParity:
    state: str
    session_date: str
    run_ids: tuple[int, ...]
    hot_analytical_sha256: str
    archive_analytical_sha256: str
    hot_source_schema_version: int
    archive_source_schema_version: int
    differing_sections: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.state
            == PARITY_STATE_PASS
        )

    def as_dict(
        self,
    ) -> dict[str, object]:
        return {
            **asdict(self),
            "run_ids": list(
                self.run_ids
            ),
            "differing_sections": list(
                self.differing_sections
            ),
            "passed": self.passed,
        }


def _run_ids(
    values: Iterable[int],
) -> tuple[int, ...]:
    result = tuple(
        int(value)
        for value
        in values
    )

    if not result:
        raise ValueError(
            "Historical analytical profile "
            "requires at least one run ID."
        )

    if (
        len(set(result))
        != len(result)
    ):
        raise ValueError(
            "Historical analytical profile "
            "run IDs must be unique."
        )

    return result


def _placeholders(
    run_ids: tuple[int, ...],
) -> str:
    return ",".join(
        "?"
        for _value
        in run_ids
    )


def _scope_from(
    table_name: str,
    run_ids: tuple[int, ...],
) -> str:
    return _SCOPE_FROM[
        table_name
    ].format(
        run_ids=_placeholders(
            run_ids
        )
    )


def _table_identity(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    run_ids: tuple[int, ...],
) -> dict[str, int | None]:
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS row_count,
            MIN(t.id) AS min_id,
            MAX(t.id) AS max_id,
            COALESCE(SUM(t.id), 0)
                AS id_sum
        {_scope_from(
            table_name,
            run_ids,
        )};
        """,
        run_ids,
    ).fetchone()

    return {
        "row_count": int(
            row[0]
        ),
        "min_id": (
            None
            if row[1] is None
            else int(row[1])
        ),
        "max_id": (
            None
            if row[2] is None
            else int(row[2])
        ),
        "id_sum": int(
            row[3]
        ),
    }


def _single_row_metrics(
    conn: sqlite3.Connection,
    *,
    sql: str,
    params: tuple[int, ...],
) -> dict[
    str,
    int | float | str | None,
]:
    cursor = conn.execute(
        sql,
        params,
    )
    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Historical analytical metric "
            "query returned no row."
        )

    names = [
        str(item[0])
        for item
        in cursor.description
    ]

    result: dict[
        str,
        int | float | str | None,
    ] = {}

    for (
        name,
        value,
    ) in zip(
        names,
        row,
        strict=True,
    ):
        if isinstance(
            value,
            (
                int,
                float,
                str,
            ),
        ) or value is None:
            result[
                name
            ] = value
        else:
            result[
                name
            ] = str(
                value
            )

    return result


def _dimension_counts(
    conn: sqlite3.Connection,
    *,
    sql: str,
    params: tuple[int, ...],
) -> dict[str, int]:
    result: dict[
        str,
        int,
    ] = {}

    for (
        key,
        count,
    ) in conn.execute(
        sql,
        params,
    ).fetchall():
        normalized = (
            "<NULL>"
            if key is None
            else str(key)
        )

        result[
            normalized
        ] = int(
            count
        )

    return dict(
        sorted(
            result.items()
        )
    )


def _hash_value(
    digest,
    value: object,
) -> None:
    if value is None:
        encoded = b"N"
    elif isinstance(
        value,
        bool,
    ):
        encoded = (
            b"B1"
            if value
            else b"B0"
        )
    elif isinstance(
        value,
        int,
    ):
        encoded = (
            b"I"
            + str(
                value
            ).encode(
                "ascii"
            )
        )
    elif isinstance(
        value,
        float,
    ):
        encoded = (
            b"F"
            + value.hex().encode(
                "ascii"
            )
        )
    elif isinstance(
        value,
        bytes,
    ):
        encoded = (
            b"X"
            + value
        )
    else:
        encoded = (
            b"S"
            + str(
                value
            ).encode(
                "utf-8"
            )
        )

    digest.update(
        str(
            len(encoded)
        ).encode(
            "ascii"
        )
    )
    digest.update(
        b":"
    )
    digest.update(
        encoded
    )
    digest.update(
        b";"
    )


def _analytical_fingerprint(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    run_ids: tuple[int, ...],
) -> str:
    columns = (
        _ANALYTICAL_FINGERPRINT_COLUMNS[
            table_name
        ]
    )

    select_columns = ", ".join(
        f't."{column}"'
        for column
        in columns
    )

    sql = f"""
        SELECT
            {select_columns}
        {_scope_from(
            table_name,
            run_ids,
        )}
        ORDER BY t.id;
    """

    digest = hashlib.sha256()

    for column in columns:
        _hash_value(
            digest,
            column,
        )

    cursor = conn.execute(
        sql,
        run_ids,
    )

    for row in cursor:
        digest.update(
            b"R"
        )

        for value in row:
            _hash_value(
                digest,
                value,
            )

    return digest.hexdigest()


def _profile_payload(
    *,
    session_date: str,
    run_ids: tuple[int, ...],
    table_identity: dict[
        str,
        dict[str, int | None],
    ],
    scalar_metrics: dict[
        str,
        dict[str, int | float | str | None],
    ],
    analytical_fingerprints: dict[
        str,
        str,
    ],
    dimensions: dict[
        str,
        dict[str, int],
    ],
) -> dict[str, object]:
    return {
        "format_version":
            PROFILE_FORMAT_VERSION,
        "session_date":
            session_date,
        "run_ids":
            list(
                run_ids
            ),
        "table_identity":
            table_identity,
        "scalar_metrics":
            scalar_metrics,
        "analytical_fingerprints":
            analytical_fingerprints,
        "dimensions":
            dimensions,
    }


def _payload_sha256(
    payload: dict[str, object],
) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=True,
        allow_nan=False,
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


def profile_session_connection(
    conn: sqlite3.Connection,
    *,
    session_date: str,
    run_ids: Iterable[int],
    source_kind: str,
    source_schema_version: int,
) -> HistoricalSessionProfile:
    runs = _run_ids(
        run_ids
    )
    params = runs
    placeholders = (
        _placeholders(
            runs
        )
    )

    table_identity = {
        table_name:
            _table_identity(
                conn,
                table_name=table_name,
                run_ids=runs,
            )
        for table_name
        in _SCOPE_FROM
    }

    scalar_metrics = {
        "market_snapshots":
            _single_row_metrics(
                conn,
                sql=f"""
                    SELECT
                        COUNT(*) AS rows,
                        COUNT(DISTINCT underlying)
                            AS distinct_underlyings,
                        COUNT(DISTINCT provider)
                            AS distinct_providers,
                        SUM(
                            underlying_price
                            IS NOT NULL
                        ) AS priced_rows,
                        MIN(captured_at)
                            AS first_captured_at,
                        MAX(captured_at)
                            AS last_captured_at
                    FROM market_snapshots
                    WHERE research_run_id
                        IN ({placeholders});
                """,
                params=params,
            ),
        "option_quotes":
            _single_row_metrics(
                conn,
                sql=f"""
                    SELECT
                        COUNT(*) AS rows,
                        SUM(t.bid IS NOT NULL)
                            AS bid_rows,
                        SUM(t.ask IS NOT NULL)
                            AS ask_rows,
                        SUM(
                            t.implied_volatility
                            IS NOT NULL
                        ) AS iv_rows,
                        SUM(t.delta IS NOT NULL)
                            AS delta_rows,
                        MIN(t.expiration)
                            AS min_expiration,
                        MAX(t.expiration)
                            AS max_expiration
                    {_scope_from(
                        "option_quotes",
                        runs,
                    )};
                """,
                params=params,
            ),
        "provider_model_observations":
            _single_row_metrics(
                conn,
                sql=f"""
                    SELECT
                        COUNT(*) AS rows,
                        SUM(
                            t.implied_volatility
                            IS NOT NULL
                        ) AS iv_rows,
                        SUM(t.delta IS NOT NULL)
                            AS delta_rows,
                        SUM(t.gamma IS NOT NULL)
                            AS gamma_rows,
                        SUM(t.theta IS NOT NULL)
                            AS theta_rows,
                        SUM(t.vega IS NOT NULL)
                            AS vega_rows
                    {_scope_from(
                        "provider_model_observations",
                        runs,
                    )};
                """,
                params=params,
            ),
        "hypothesis_scanner_evaluations":
            _single_row_metrics(
                conn,
                sql=f"""
                    SELECT
                        COUNT(*) AS rows,
                        SUM(
                            t.iv_residual
                            IS NOT NULL
                        ) AS residual_rows
                    {_scope_from(
                        "hypothesis_scanner_evaluations",
                        runs,
                    )};
                """,
                params=params,
            ),
        "local_surface_residual_v2_observations":
            _single_row_metrics(
                conn,
                sql=f"""
                    SELECT
                        COUNT(*) AS rows,
                        SUM(
                            t.loo_residual
                            IS NOT NULL
                        ) AS residual_rows
                    {_scope_from(
                        "local_surface_residual_v2_observations",
                        runs,
                    )};
                """,
                params=params,
            ),
    }

    analytical_fingerprints = {
        table_name:
            _analytical_fingerprint(
                conn,
                table_name=
                    table_name,
                run_ids=runs,
            )
        for table_name
        in _ANALYTICAL_FINGERPRINT_COLUMNS
    }

    dimensions = {
        "research_run_status":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        status,
                        COUNT(*)
                    FROM research_runs
                    WHERE id
                        IN ({placeholders})
                    GROUP BY status
                    ORDER BY status;
                """,
                params=params,
            ),
        "option_right":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.right,
                        COUNT(*)
                    {_scope_from(
                        "option_quotes",
                        runs,
                    )}
                    GROUP BY t.right
                    ORDER BY t.right;
                """,
                params=params,
            ),
        "provider_model_provider":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.provider,
                        COUNT(*)
                    {_scope_from(
                        "provider_model_observations",
                        runs,
                    )}
                    GROUP BY t.provider
                    ORDER BY t.provider;
                """,
                params=params,
            ),
        "provider_availability_state":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.state,
                        COUNT(*)
                    {_scope_from(
                        "provider_observation_availability",
                        runs,
                    )}
                    GROUP BY t.state
                    ORDER BY t.state;
                """,
                params=params,
            ),
        "provider_availability_family":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.evidence_family,
                        COUNT(*)
                    {_scope_from(
                        "provider_observation_availability",
                        runs,
                    )}
                    GROUP BY t.evidence_family
                    ORDER BY t.evidence_family;
                """,
                params=params,
            ),
        "scanner_evaluation_state":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.evaluation_state,
                        COUNT(*)
                    {_scope_from(
                        "hypothesis_scanner_evaluations",
                        runs,
                    )}
                    GROUP BY t.evaluation_state
                    ORDER BY t.evaluation_state;
                """,
                params=params,
            ),
        "scanner_direction":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.surfaced_direction,
                        COUNT(*)
                    {_scope_from(
                        "hypothesis_scanner_evaluations",
                        runs,
                    )}
                    GROUP BY t.surfaced_direction
                    ORDER BY t.surfaced_direction;
                """,
                params=params,
            ),
        "surface_observation_state":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.observation_state,
                        COUNT(*)
                    {_scope_from(
                        "local_surface_residual_v2_observations",
                        runs,
                    )}
                    GROUP BY t.observation_state
                    ORDER BY t.observation_state;
                """,
                params=params,
            ),
        "surface_reason_code":
            _dimension_counts(
                conn,
                sql=f"""
                    SELECT
                        t.reason_code,
                        COUNT(*)
                    {_scope_from(
                        "local_surface_residual_v2_observations",
                        runs,
                    )}
                    GROUP BY t.reason_code
                    ORDER BY t.reason_code;
                """,
                params=params,
            ),
    }

    payload = _profile_payload(
        session_date=
            session_date,
        run_ids=runs,
        table_identity=
            table_identity,
        scalar_metrics=
            scalar_metrics,
        analytical_fingerprints=
            analytical_fingerprints,
        dimensions=
            dimensions,
    )

    return HistoricalSessionProfile(
        format_version=
            PROFILE_FORMAT_VERSION,
        source_kind=
            source_kind,
        source_schema_version=int(
            source_schema_version
        ),
        session_date=
            session_date,
        run_ids=runs,
        table_identity=
            table_identity,
        scalar_metrics=
            scalar_metrics,
        analytical_fingerprints=
            analytical_fingerprints,
        dimensions=
            dimensions,
        analytical_sha256=
            _payload_sha256(
                payload
            ),
    )


def _manifest_for_session(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
) -> tuple[
    Path,
    ResearchArchiveManifest,
]:
    directory = (
        resolve_archive_dir(
            archive_dir
        )
    )

    inventory = (
        inventory_research_archives(
            directory
        )
    )

    matches = [
        manifest
        for manifest
        in inventory.manifests
        if (
            manifest.session_date
            == session_date
        )
    ]

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one verified "
            "archive for historical session "
            f"{session_date}; found "
            f"{len(matches)}."
        )

    manifest = matches[0]

    return (
        directory
        / manifest.manifest_filename,
        manifest,
    )


def profile_archived_session(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
) -> HistoricalSessionProfile:
    (
        manifest_path,
        manifest,
    ) = _manifest_for_session(
        session_date,
        archive_dir=archive_dir,
    )

    with open_verified_archive_connection(
        manifest_path
    ) as (
        conn,
        verified,
    ):
        return (
            profile_session_connection(
                conn,
                session_date=
                    verified.session_date,
                run_ids=
                    verified.run_ids,
                source_kind=
                    "ARCHIVE",
                source_schema_version=
                    verified.source_schema_version,
            )
        )


def profile_hot_session(
    session_date: str,
    *,
    run_ids: Iterable[int],
    db_path: str | Path | None = None,
) -> HistoricalSessionProfile:
    database = resolve_db_path(
        db_path
    )

    uri = (
        database.resolve().as_uri()
        + "?mode=ro"
    )

    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=60.0,
    )
    conn.row_factory = (
        sqlite3.Row
    )

    try:
        conn.execute(
            "PRAGMA query_only = ON;"
        )

        version_row = (
            conn.execute(
                """
                SELECT MAX(version)
                FROM schema_version;
                """
            ).fetchone()
        )

        if (
            version_row is None
            or version_row[0] is None
        ):
            raise RuntimeError(
                "Hot database has no "
                "schema_version."
            )

        return (
            profile_session_connection(
                conn,
                session_date=
                    session_date,
                run_ids=run_ids,
                source_kind="HOT",
                source_schema_version=
                    int(version_row[0]),
            )
        )
    finally:
        conn.close()


def compare_hot_archive_session(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    hot_connection: sqlite3.Connection | None = None,
    manifest_path: str | Path | None = None,
    manifest: ResearchArchiveManifest | None = None,
) -> HotArchiveAnalyticalParity:
    if (
        manifest_path is None
        or manifest is None
    ):
        (
            resolved_path,
            resolved_manifest,
        ) = _manifest_for_session(
            session_date,
            archive_dir=archive_dir,
        )

        manifest_path = (
            resolved_path
        )
        manifest = (
            resolved_manifest
        )

    if (
        manifest.session_date
        != session_date
    ):
        raise RuntimeError(
            "Historical parity manifest "
            "session mismatch: "
            f"{manifest.session_date} != "
            f"{session_date}."
        )

    runs = _run_ids(
        manifest.run_ids
    )

    if hot_connection is None:
        hot = profile_hot_session(
            session_date,
            run_ids=runs,
            db_path=db_path,
        )
    else:
        version_row = (
            hot_connection.execute(
                """
                SELECT MAX(version)
                FROM schema_version;
                """
            ).fetchone()
        )

        if (
            version_row is None
            or version_row[0] is None
        ):
            raise RuntimeError(
                "Hot database has no "
                "schema_version."
            )

        hot = profile_session_connection(
            hot_connection,
            session_date=
                session_date,
            run_ids=runs,
            source_kind="HOT",
            source_schema_version=
                int(version_row[0]),
        )

    with open_verified_archive_connection(
        manifest_path
    ) as (
        archive_conn,
        verified_manifest,
    ):
        if (
            verified_manifest.session_date
            != session_date
            or tuple(
                verified_manifest.run_ids
            )
            != runs
        ):
            raise RuntimeError(
                "Materialized archive lineage "
                "does not match parity target."
            )

        cold = (
            profile_session_connection(
                archive_conn,
                session_date=
                    session_date,
                run_ids=runs,
                source_kind="ARCHIVE",
                source_schema_version=
                    verified_manifest.source_schema_version,
            )
        )

    differing = []

    if (
        hot.table_identity
        != cold.table_identity
    ):
        differing.append(
            "table_identity"
        )

    if (
        hot.scalar_metrics
        != cold.scalar_metrics
    ):
        differing.append(
            "scalar_metrics"
        )

    if (
        hot.analytical_fingerprints
        != cold.analytical_fingerprints
    ):
        differing.append(
            "analytical_fingerprints"
        )

    if (
        hot.dimensions
        != cold.dimensions
    ):
        differing.append(
            "dimensions"
        )

    passed = (
        hot.analytical_sha256
        == cold.analytical_sha256
        and not differing
    )

    return HotArchiveAnalyticalParity(
        state=(
            PARITY_STATE_PASS
            if passed
            else PARITY_STATE_FAIL
        ),
        session_date=
            session_date,
        run_ids=runs,
        hot_analytical_sha256=
            hot.analytical_sha256,
        archive_analytical_sha256=
            cold.analytical_sha256,
        hot_source_schema_version=
            hot.source_schema_version,
        archive_source_schema_version=
            cold.source_schema_version,
        differing_sections=tuple(
            differing
        ),
    )

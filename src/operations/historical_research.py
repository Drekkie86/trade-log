from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

from src.database.repository import (
    resolve_db_path,
)
from src.operations.research_archive import (
    ResearchArchiveManifest,
    find_archive_for_session,
    open_verified_research_archive,
    resolve_archive_dir,
)


HISTORICAL_ANALYSIS_VERSION = 1

REQUIRED_ARCHIVE_COLUMNS: dict[
    str,
    tuple[str, ...],
] = {
    "research_runs": (
        "id",
        "status",
        "us_session_date",
        "us_session_state",
        "started_at",
        "ended_at",
    ),
    "market_snapshots": (
        "id",
        "research_run_id",
    ),
    "option_quotes": (
        "id",
        "snapshot_id",
        "right",
        "bid",
        "ask",
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
        "model_name",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
    ),
    "listing_reference_contracts": (
        "id",
        "research_run_id",
    ),
    "provider_observation_availability": (
        "id",
        "reference_contract_id",
        "provider",
        "evidence_family",
        "state",
    ),
    "hypothesis_scanner_runs": (
        "id",
        "research_run_id",
    ),
    "hypothesis_scanner_evaluations": (
        "id",
        "scanner_run_id",
        "evaluation_state",
        "reason_code",
        "surfaced_direction",
        "abs_iv_residual",
    ),
    "local_surface_residual_v2_runs": (
        "id",
        "research_run_id",
    ),
    "local_surface_residual_v2_observations": (
        "id",
        "model_run_id",
        "right",
        "observation_state",
        "reason_code",
        "abs_loo_residual",
        "fit_rmse",
    ),
}


@dataclass(frozen=True)
class HistoricalMetricResult:
    name: str
    columns: tuple[str, ...]
    rows: tuple[
        tuple[object, ...],
        ...,
    ]
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "columns": list(
                self.columns
            ),
            "rows": [
                {
                    column: value
                    for (
                        column,
                        value,
                    )
                    in zip(
                        self.columns,
                        row,
                        strict=True,
                    )
                }
                for row
                in self.rows
            ],
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class HistoricalSessionAnalysis:
    analysis_version: int
    session_date: str
    run_ids: tuple[int, ...]
    source: str
    source_schema_version: int
    archive_filename: str | None
    metrics: tuple[
        HistoricalMetricResult,
        ...,
    ]
    canonical_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "analysis_version":
                self.analysis_version,
            "session_date":
                self.session_date,
            "run_ids": list(
                self.run_ids
            ),
            "source": self.source,
            "source_schema_version":
                self.source_schema_version,
            "archive_filename":
                self.archive_filename,
            "metrics": [
                metric.as_dict()
                for metric
                in self.metrics
            ],
            "canonical_sha256":
                self.canonical_sha256,
        }


@dataclass(frozen=True)
class HistoricalParityReport:
    analysis_version: int
    session_date: str
    run_ids: tuple[int, ...]
    hot_schema_version: int
    archive_source_schema_version: int
    archive_filename: str
    hot_canonical_sha256: str
    archive_canonical_sha256: str
    metric_matches: dict[str, bool]
    mismatched_metrics: tuple[str, ...]
    passed: bool

    def as_dict(self) -> dict[str, object]:
        data = asdict(
            self
        )
        data["run_ids"] = list(
            self.run_ids
        )
        data["mismatched_metrics"] = list(
            self.mismatched_metrics
        )
        return data


ANALYSIS_SQL: tuple[
    tuple[str, str],
    ...,
] = (
    (
        "run_inventory",
        """
        SELECT
            rr.id AS run_id,
            rr.status,
            rr.us_session_state,
            rr.started_at,
            rr.ended_at
        FROM research_runs AS rr
        JOIN analysis_runs AS ar
          ON ar.id = rr.id
        ORDER BY rr.id;
        """,
    ),
    (
        "quote_universe_quality",
        """
        SELECT
            ms.research_run_id AS run_id,
            oq.right,
            COUNT(*) AS quote_count,
            SUM(CASE WHEN oq.bid IS NOT NULL THEN 1 ELSE 0 END)
                AS bid_present_count,
            SUM(CASE WHEN oq.ask IS NOT NULL THEN 1 ELSE 0 END)
                AS ask_present_count,
            SUM(
                CASE
                    WHEN oq.implied_volatility IS NOT NULL
                    THEN 1 ELSE 0
                END
            ) AS iv_present_count,
            SUM(CASE WHEN oq.delta IS NOT NULL THEN 1 ELSE 0 END)
                AS delta_present_count,
            SUM(CASE WHEN oq.gamma IS NOT NULL THEN 1 ELSE 0 END)
                AS gamma_present_count,
            SUM(CASE WHEN oq.theta IS NOT NULL THEN 1 ELSE 0 END)
                AS theta_present_count,
            SUM(CASE WHEN oq.vega IS NOT NULL THEN 1 ELSE 0 END)
                AS vega_present_count,
            SUM(CASE WHEN oq.volume IS NOT NULL THEN 1 ELSE 0 END)
                AS volume_present_count,
            SUM(
                CASE
                    WHEN oq.open_interest IS NOT NULL
                    THEN 1 ELSE 0
                END
            ) AS oi_present_count,
            ROUND(
                AVG(
                    CASE
                        WHEN oq.bid IS NOT NULL
                         AND oq.ask IS NOT NULL
                        THEN oq.ask - oq.bid
                    END
                ),
                12
            ) AS avg_spread,
            ROUND(AVG(oq.implied_volatility), 12) AS avg_iv,
            ROUND(AVG(ABS(oq.delta)), 12) AS avg_abs_delta
        FROM option_quotes AS oq
        JOIN market_snapshots AS ms
          ON ms.id = oq.snapshot_id
        JOIN analysis_runs AS ar
          ON ar.id = ms.research_run_id
        GROUP BY
            ms.research_run_id,
            oq.right
        ORDER BY
            ms.research_run_id,
            oq.right;
        """,
    ),
    (
        "provider_model_coverage",
        """
        SELECT
            ms.research_run_id AS run_id,
            pmo.provider,
            COALESCE(pmo.model_name, '') AS model_name,
            COUNT(*) AS observation_count,
            SUM(
                CASE
                    WHEN pmo.implied_volatility IS NOT NULL
                    THEN 1 ELSE 0
                END
            ) AS iv_present_count,
            SUM(CASE WHEN pmo.delta IS NOT NULL THEN 1 ELSE 0 END)
                AS delta_present_count,
            SUM(CASE WHEN pmo.gamma IS NOT NULL THEN 1 ELSE 0 END)
                AS gamma_present_count,
            SUM(CASE WHEN pmo.theta IS NOT NULL THEN 1 ELSE 0 END)
                AS theta_present_count,
            SUM(CASE WHEN pmo.vega IS NOT NULL THEN 1 ELSE 0 END)
                AS vega_present_count,
            ROUND(AVG(pmo.implied_volatility), 12) AS avg_iv
        FROM provider_model_observations AS pmo
        JOIN option_quotes AS oq
          ON oq.id = pmo.option_quote_id
        JOIN market_snapshots AS ms
          ON ms.id = oq.snapshot_id
        JOIN analysis_runs AS ar
          ON ar.id = ms.research_run_id
        GROUP BY
            ms.research_run_id,
            pmo.provider,
            COALESCE(pmo.model_name, '')
        ORDER BY
            ms.research_run_id,
            pmo.provider,
            model_name;
        """,
    ),
    (
        "provider_availability",
        """
        SELECT
            lrc.research_run_id AS run_id,
            poa.provider,
            poa.evidence_family,
            poa.state,
            COUNT(*) AS observation_count
        FROM provider_observation_availability AS poa
        JOIN listing_reference_contracts AS lrc
          ON lrc.id = poa.reference_contract_id
        JOIN analysis_runs AS ar
          ON ar.id = lrc.research_run_id
        GROUP BY
            lrc.research_run_id,
            poa.provider,
            poa.evidence_family,
            poa.state
        ORDER BY
            lrc.research_run_id,
            poa.provider,
            poa.evidence_family,
            poa.state;
        """,
    ),
    (
        "scanner_outcomes",
        """
        SELECT
            hsr.research_run_id AS run_id,
            hse.evaluation_state,
            hse.reason_code,
            COALESCE(hse.surfaced_direction, '') AS surfaced_direction,
            COUNT(*) AS evaluation_count,
            SUM(
                CASE
                    WHEN hse.abs_iv_residual IS NOT NULL
                    THEN 1 ELSE 0
                END
            ) AS residual_present_count,
            ROUND(AVG(hse.abs_iv_residual), 12) AS avg_abs_iv_residual,
            ROUND(MAX(hse.abs_iv_residual), 12) AS max_abs_iv_residual
        FROM hypothesis_scanner_evaluations AS hse
        JOIN hypothesis_scanner_runs AS hsr
          ON hsr.id = hse.scanner_run_id
        JOIN analysis_runs AS ar
          ON ar.id = hsr.research_run_id
        GROUP BY
            hsr.research_run_id,
            hse.evaluation_state,
            hse.reason_code,
            COALESCE(hse.surfaced_direction, '')
        ORDER BY
            hsr.research_run_id,
            hse.evaluation_state,
            hse.reason_code,
            surfaced_direction;
        """,
    ),
    (
        "surface_v2_residual_behavior",
        """
        SELECT
            lsr.research_run_id AS run_id,
            lso.right,
            lso.observation_state,
            lso.reason_code,
            COUNT(*) AS observation_count,
            SUM(
                CASE
                    WHEN lso.abs_loo_residual IS NOT NULL
                    THEN 1 ELSE 0
                END
            ) AS residual_present_count,
            ROUND(AVG(lso.abs_loo_residual), 12) AS avg_abs_loo_residual,
            ROUND(MAX(lso.abs_loo_residual), 12) AS max_abs_loo_residual,
            ROUND(AVG(lso.fit_rmse), 12) AS avg_fit_rmse
        FROM local_surface_residual_v2_observations AS lso
        JOIN local_surface_residual_v2_runs AS lsr
          ON lsr.id = lso.model_run_id
        JOIN analysis_runs AS ar
          ON ar.id = lsr.research_run_id
        GROUP BY
            lsr.research_run_id,
            lso.right,
            lso.observation_state,
            lso.reason_code
        ORDER BY
            lsr.research_run_id,
            lso.right,
            lso.observation_state,
            lso.reason_code;
        """,
    ),
)


def _sha256_json(
    value: object,
) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(
        payload
    ).hexdigest()


def _schema_version(
    conn: sqlite3.Connection,
) -> int:
    row = conn.execute(
        """
        SELECT MAX(version)
        FROM schema_version;
        """
    ).fetchone()

    if row is None or row[0] is None:
        raise RuntimeError(
            "Hot Christiania database has no schema version."
        )

    return int(row[0])


def _table_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    quoted = (
        '"'
        + table_name.replace('"', '""')
        + '"'
    )

    rows = conn.execute(
        f"PRAGMA table_info({quoted});"
    ).fetchall()

    return {
        str(row[1])
        for row in rows
    }


def _validate_analysis_schema(
    conn: sqlite3.Connection,
) -> None:
    failures: list[str] = []

    for (
        table_name,
        required_columns,
    ) in REQUIRED_ARCHIVE_COLUMNS.items():
        actual = _table_columns(
            conn,
            table_name,
        )

        missing = [
            column
            for column in required_columns
            if column not in actual
        ]

        if missing:
            failures.append(
                f"{table_name}:"
                + ",".join(missing)
            )

    if failures:
        raise RuntimeError(
            "Historical Analysis V1 schema is incompatible: "
            + "; ".join(failures)
        )


def _analysis_runs_cte(
    run_ids: Sequence[int],
) -> tuple[
    str,
    tuple[int, ...],
]:
    normalized = tuple(
        int(run_id)
        for run_id in run_ids
    )

    if not normalized:
        raise ValueError(
            "Historical analysis requires at least one run ID."
        )

    if len(set(normalized)) != len(normalized):
        raise ValueError(
            "Historical analysis run IDs must be unique."
        )

    values = ",".join(
        "(?)"
        for _ in normalized
    )

    return (
        "WITH analysis_runs(id) "
        f"AS (VALUES {values}) ",
        normalized,
    )


def _metric_result(
    *,
    name: str,
    cursor: sqlite3.Cursor,
) -> HistoricalMetricResult:
    columns = tuple(
        str(item[0])
        for item in cursor.description
    )

    rows = tuple(
        tuple(row)
        for row in cursor.fetchall()
    )

    digest = _sha256_json(
        {
            "name": name,
            "columns": columns,
            "rows": rows,
        }
    )

    return HistoricalMetricResult(
        name=name,
        columns=columns,
        rows=rows,
        sha256=digest,
    )


def analyze_historical_connection(
    conn: sqlite3.Connection,
    *,
    session_date: str,
    run_ids: Sequence[int],
    source: str,
    source_schema_version: int,
    archive_filename: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> HistoricalSessionAnalysis:
    _validate_analysis_schema(
        conn
    )

    (
        cte,
        parameters,
    ) = _analysis_runs_cte(
        run_ids
    )

    metrics: list[
        HistoricalMetricResult
    ] = []

    for (
        name,
        sql,
    ) in ANALYSIS_SQL:
        if progress is not None:
            progress(
                f"{source.lower()} analysis "
                f"{name} started"
            )

        cursor = conn.execute(
            cte + sql,
            parameters,
        )

        metric = _metric_result(
            name=name,
            cursor=cursor,
        )

        metrics.append(
            metric
        )

        if progress is not None:
            progress(
                f"{source.lower()} analysis "
                f"{name} complete "
                f"rows={len(metric.rows)} "
                f"sha256={metric.sha256}"
            )

    canonical_payload = {
        "analysis_version":
            HISTORICAL_ANALYSIS_VERSION,
        "session_date":
            session_date,
        "run_ids": list(
            parameters
        ),
        "metrics": {
            metric.name:
                metric.sha256
            for metric in metrics
        },
    }

    return HistoricalSessionAnalysis(
        analysis_version=
            HISTORICAL_ANALYSIS_VERSION,
        session_date=session_date,
        run_ids=parameters,
        source=source,
        source_schema_version=int(
            source_schema_version
        ),
        archive_filename=
            archive_filename,
        metrics=tuple(metrics),
        canonical_sha256=
            _sha256_json(
                canonical_payload
            ),
    )


def _manifest_for_session(
    session_date: str,
    *,
    archive_dir: str | Path | None,
) -> tuple[
    Path,
    ResearchArchiveManifest,
]:
    directory = resolve_archive_dir(
        archive_dir
    )

    manifest = find_archive_for_session(
        session_date,
        archive_dir=directory,
    )

    if manifest is None:
        raise FileNotFoundError(
            "No verified Christiania research archive exists "
            f"for session {session_date}."
        )

    return (
        directory
        / manifest.manifest_filename,
        manifest,
    )


def analyze_archived_session(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
) -> HistoricalSessionAnalysis:
    (
        manifest_path,
        _,
    ) = _manifest_for_session(
        session_date,
        archive_dir=archive_dir,
    )

    with open_verified_research_archive(
        manifest_path
    ) as (
        manifest,
        conn,
    ):
        return analyze_historical_connection(
            conn,
            session_date=session_date,
            run_ids=manifest.run_ids,
            source="ARCHIVE",
            source_schema_version=
                manifest.source_schema_version,
            archive_filename=
                manifest.archive_filename,
            progress=progress,
        )


def _hot_run_ids(
    conn: sqlite3.Connection,
    session_date: str,
) -> tuple[int, ...]:
    rows = conn.execute(
        """
        SELECT id
        FROM research_runs
        WHERE us_session_date = ?
        ORDER BY id;
        """,
        (session_date,),
    ).fetchall()

    return tuple(
        int(row[0])
        for row in rows
    )


def analyze_hot_session(
    session_date: str,
    *,
    db_path: str | Path | None = None,
) -> HistoricalSessionAnalysis:
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
        timeout=30.0,
    )

    try:
        run_ids = _hot_run_ids(
            conn,
            session_date,
        )

        if not run_ids:
            raise FileNotFoundError(
                "No hot Christiania research runs exist "
                f"for session {session_date}."
            )

        return analyze_historical_connection(
            conn,
            session_date=session_date,
            run_ids=run_ids,
            source="HOT",
            source_schema_version=
                _schema_version(conn),
        )
    finally:
        conn.close()


def compare_hot_connection_to_archive(
    hot_conn: sqlite3.Connection,
    *,
    manifest_path: str | Path,
    progress: Callable[[str], None] | None = None,
) -> HistoricalParityReport:
    path = Path(
        manifest_path
    ).expanduser()

    with open_verified_research_archive(
        path,
        progress=progress,
    ) as (
        manifest,
        archive_conn,
    ):
        hot = analyze_historical_connection(
            hot_conn,
            session_date=manifest.session_date,
            run_ids=manifest.run_ids,
            source="HOT",
            source_schema_version=
                _schema_version(hot_conn),
            progress=progress,
        )

        archive = analyze_historical_connection(
            archive_conn,
            session_date=manifest.session_date,
            run_ids=manifest.run_ids,
            source="ARCHIVE",
            source_schema_version=
                manifest.source_schema_version,
            archive_filename=
                manifest.archive_filename,
        )

    hot_by_name = {
        metric.name: metric
        for metric in hot.metrics
    }
    archive_by_name = {
        metric.name: metric
        for metric in archive.metrics
    }

    all_names = sorted(
        set(hot_by_name)
        | set(archive_by_name)
    )

    metric_matches = {
        name: (
            name in hot_by_name
            and name in archive_by_name
            and hot_by_name[name].sha256
            == archive_by_name[name].sha256
        )
        for name in all_names
    }

    mismatched = tuple(
        name
        for name in all_names
        if not metric_matches[name]
    )

    passed = (
        not mismatched
        and hot.canonical_sha256
        == archive.canonical_sha256
    )

    return HistoricalParityReport(
        analysis_version=
            HISTORICAL_ANALYSIS_VERSION,
        session_date=
            manifest.session_date,
        run_ids=manifest.run_ids,
        hot_schema_version=
            hot.source_schema_version,
        archive_source_schema_version=
            manifest.source_schema_version,
        archive_filename=
            manifest.archive_filename,
        hot_canonical_sha256=
            hot.canonical_sha256,
        archive_canonical_sha256=
            archive.canonical_sha256,
        metric_matches=
            metric_matches,
        mismatched_metrics=
            mismatched,
        passed=passed,
    )


def compare_hot_archive_session(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> HistoricalParityReport:
    (
        manifest_path,
        _,
    ) = _manifest_for_session(
        session_date,
        archive_dir=archive_dir,
    )

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
        timeout=30.0,
    )

    try:
        return compare_hot_connection_to_archive(
            conn,
            manifest_path=manifest_path,
        )
    finally:
        conn.close()


@contextmanager
def open_historical_session(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
) -> Iterator[
    tuple[
        ResearchArchiveManifest,
        sqlite3.Connection,
    ]
]:
    """
    Open one historical session as a read-only hybrid research surface.

    Archived raw evidence is the main schema. The current Christiania database
    is attached read-only as schema "hot", allowing cold evidence to be joined
    to low-volume governance and outcome evidence that remains hot.
    """
    (
        manifest_path,
        _,
    ) = _manifest_for_session(
        session_date,
        archive_dir=archive_dir,
    )

    database = resolve_db_path(
        db_path
    )

    hot_uri = (
        database.resolve().as_uri()
        + "?mode=ro"
    )

    with open_verified_research_archive(
        manifest_path,
        query_only=False,
    ) as (
        manifest,
        conn,
    ):
        conn.execute(
            "ATTACH DATABASE ? AS hot;",
            (hot_uri,),
        )

        conn.execute(
            "PRAGMA query_only = ON;"
        )

        try:
            yield (
                manifest,
                conn,
            )
        finally:
            try:
                conn.execute(
                    "DETACH DATABASE hot;"
                )
            except sqlite3.Error:
                pass

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection


RUNTIME_VERSION = "1.0.0"
CASINO_NAMESPACE = "CASINO_V1"


@dataclass(frozen=True)
class CasinoZeroDteRuntime:
    version: str
    namespace: str
    state: str
    zero_dte_session_count: int
    zero_dte_snapshot_count: int
    zero_dte_quote_count: int
    zero_dte_underlying_count: int
    greek_observation_count: int
    spread_observation_count: int
    dealer_positioning_state: str
    main_engine_authority: str
    casino_authority: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (name,),
    ).fetchone() is not None


def _columns(conn, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}


def _empty(state: str, detail: str) -> CasinoZeroDteRuntime:
    return CasinoZeroDteRuntime(
        version=RUNTIME_VERSION,
        namespace=CASINO_NAMESPACE,
        state=state,
        zero_dte_session_count=0,
        zero_dte_snapshot_count=0,
        zero_dte_quote_count=0,
        zero_dte_underlying_count=0,
        greek_observation_count=0,
        spread_observation_count=0,
        dealer_positioning_state="NOT_MEASURED_DO_NOT_INFER",
        main_engine_authority="UNCHANGED_BY_CASINO",
        casino_authority="RESEARCH_SHADOW_ONLY_NO_EXECUTION",
        detail=detail,
    )


def load_casino_0dte_runtime(db_path: str | Path | None = None) -> CasinoZeroDteRuntime:
    path = resolve_db_path(db_path)
    if not path.exists():
        return _empty("DATABASE_UNAVAILABLE", "Database unavailable; no 0DTE evidence can be summarized.")

    conn = open_readonly_connection(path)
    try:
        if not (_table_exists(conn, "market_snapshots") and _table_exists(conn, "option_quotes")):
            return _empty(
                "MARKET_EVIDENCE_TABLES_UNAVAILABLE",
                "Required market snapshot / option quote evidence tables are unavailable.",
            )

        snapshot_columns = _columns(conn, "market_snapshots")
        quote_columns = _columns(conn, "option_quotes")
        if "us_session_date" not in snapshot_columns or "expiration" not in quote_columns:
            return _empty(
                "ZERO_DTE_IDENTITY_NOT_AVAILABLE",
                "0DTE identity requires immutable US session date and expiration fields.",
            )

        row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT ms.us_session_date) AS session_count,
                COUNT(DISTINCT ms.id) AS snapshot_count,
                COUNT(oq.id) AS quote_count,
                COUNT(DISTINCT ms.underlying) AS underlying_count,
                SUM(
                    CASE WHEN oq.gamma IS NOT NULL OR oq.theta IS NOT NULL
                         THEN 1 ELSE 0 END
                ) AS greek_count,
                SUM(
                    CASE WHEN oq.bid IS NOT NULL AND oq.ask IS NOT NULL
                           AND oq.ask >= oq.bid
                         THEN 1 ELSE 0 END
                ) AS spread_count
            FROM option_quotes AS oq
            JOIN market_snapshots AS ms ON ms.id = oq.snapshot_id
            WHERE ms.us_session_date IS NOT NULL
              AND oq.expiration = ms.us_session_date;
            """
        ).fetchone()
    finally:
        conn.close()

    sessions = int(row["session_count"] or 0)
    snapshots = int(row["snapshot_count"] or 0)
    quotes = int(row["quote_count"] or 0)
    underlyings = int(row["underlying_count"] or 0)
    greek_count = int(row["greek_count"] or 0)
    spread_count = int(row["spread_count"] or 0)

    if quotes == 0:
        state = "ACCUMULATING_ZERO_DTE_EVIDENCE"
        detail = (
            "No same-session-expiration option quotes are present yet. Casino research remains dormant; "
            "Main Engine authority is unchanged."
        )
    else:
        state = "ZERO_DTE_RESEARCH_EVIDENCE_AVAILABLE"
        detail = (
            "Same-session-expiration evidence is available for descriptive Casino research. "
            "This does not establish edge, activate a strategy, or create execution authority."
        )

    return CasinoZeroDteRuntime(
        version=RUNTIME_VERSION,
        namespace=CASINO_NAMESPACE,
        state=state,
        zero_dte_session_count=sessions,
        zero_dte_snapshot_count=snapshots,
        zero_dte_quote_count=quotes,
        zero_dte_underlying_count=underlyings,
        greek_observation_count=greek_count,
        spread_observation_count=spread_count,
        dealer_positioning_state="NOT_MEASURED_DO_NOT_INFER",
        main_engine_authority="UNCHANGED_BY_CASINO",
        casino_authority="RESEARCH_SHADOW_ONLY_NO_EXECUTION",
        detail=detail,
    )

"""
Tests for the migration-015 scanner join fix.

hypothesis_scanner.py's _load_reference_and_iv() used to build a literal
"oq.id IN (?, ?, ?, ...)" clause with one placeholder per structurally
eligible contract. Measured on a dataset sized like production (189k
reference rows): a 2,000-item literal IN-list took 80s; the same result
set through a temp-table join took 10s, and faster again with
idx_listing_reference_scanner_join in place.

Two things matter here, and both are tested: the rewritten query returns
the SAME rows as the old one (correctness), and it is measurably faster
at a size large enough to show it (regression guard against the fix
being quietly reverted or bypassed).
"""

from __future__ import annotations

import random
import sqlite3
import time
from pathlib import Path
from statistics import median

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]

UNDERLYINGS = ["AAPL", "MSFT", "AMD", "SPY"]


def _build_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        (BASE_DIR / "trade_log_schema.sql").read_text(encoding="utf-8")
    )
    for name in (
        "007_selection_universe_integrity",
        "008_shadow_persistence",
        "009_hostile_review_hardening",
        "010_hypothesis_scanner_evidence",
        "011_shadow_structure_proposals",
        "012_shadow_admission",
        "013_research_daemon_and_shadow_marks",
        "014_daemon_orphan_recovery",
        "015_scanner_join_performance",
    ):
        conn.executescript(
            (BASE_DIR / "migrations" / f"{name}.sql").read_text(
                encoding="utf-8"
            )
        )
    conn.execute("PRAGMA foreign_keys = ON;")


def _seed(conn: sqlite3.Connection, *, reference_rows: int, quote_rows: int):
    conn.execute(
        """
        INSERT INTO research_runs (
            cohort_id, started_at, code_git_sha, preregistration_hash,
            us_session_date, us_session_state, status
        ) VALUES ('T', '2026-09-02T12:00:00Z', 'sha', 'hash',
                  '2026-09-02', 'INTRADAY', 'STARTED');
        """
    )
    run_id = conn.execute("SELECT id FROM research_runs").fetchone()[0]

    per_underlying = max(1, reference_rows // (len(UNDERLYINGS) * 2))
    ref_rows = []
    for underlying in UNDERLYINGS:
        for strike_i in range(per_underlying):
            for right in ("C", "P"):
                ref_rows.append(
                    (
                        run_id, "MASSIVE", underlying,
                        f"O:{underlying}{strike_i}{right}",
                        f"O:{underlying}{strike_i}{right}",
                        "2026-09-18", float(100 + strike_i), right,
                        "american", 100, "OPRA",
                        "2026-09-02T12:00:00Z", "2026-09-02T12:00:00Z",
                    )
                )
    conn.executemany(
        """
        INSERT INTO listing_reference_contracts (
            research_run_id, provider, underlying, provider_contract_id,
            option_symbol, expiration, strike, right, exercise_style,
            shares_per_contract, primary_exchange, observed_at, ingested_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?);
        """,
        ref_rows,
    )

    conn.execute(
        """
        INSERT INTO market_snapshots (
            captured_at, underlying, provider, research_run_id,
            us_session_date, us_session_state, underlying_source, fx_source
        ) VALUES ('2026-09-02T12:00:00Z', 'AAPL', 'THETADATA', ?,
                  '2026-09-02', 'INTRADAY', 'UNKNOWN', 'UNKNOWN');
        """,
        (run_id,),
    )
    snapshot_id = conn.execute("SELECT id FROM market_snapshots").fetchone()[0]

    # Keep the benchmark population reproducible. Runner-to-runner timing may
    # vary, but the actual rows under test must not.
    sample = random.Random(0).sample(
        ref_rows,
        min(quote_rows, len(ref_rows)),
    )
    quote_rows_data = []
    for (_, _, underlying, _, _, expiration, strike, right, *_rest) in sample:
        quote_rows_data.append(
            (
                snapshot_id, f"C-{underlying}-{strike}-{right}", right,
                strike, expiration, "2026-09-02T10:00:00", 1.0, "FETCHED",
                "2026-09-02T10:00:00", 1.1, "FETCHED",
                "2026-09-02T10:00:00", "UNKNOWN", "UNKNOWN", "UNKNOWN",
                "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN",
            )
        )
    conn.executemany(
        """
        INSERT INTO option_quotes (
            snapshot_id, provider_contract_id, right, strike, expiration,
            quote_at, bid, bid_source, bid_at, ask, ask_source, ask_at,
            last_source, iv_source, delta_source, gamma_source,
            theta_source, vega_source, volume_source, open_interest_source
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """,
        quote_rows_data,
    )
    conn.commit()

    quote_ids = [
        row[0] for row in conn.execute("SELECT id FROM option_quotes")
    ]
    return run_id, quote_ids


def _legacy_in_list_query(conn, run_id, quote_ids):
    """The pre-fix query, reproduced verbatim, for a correctness diff."""
    placeholders = ",".join("?" for _ in quote_ids)
    rows = conn.execute(
        f"""
        SELECT oq.id AS option_quote_id, oq.expiration, oq.strike,
               oq.right, ms.underlying, pmo.implied_volatility,
               lrc.id AS reference_contract_id
        FROM option_quotes AS oq
        JOIN market_snapshots AS ms ON ms.id = oq.snapshot_id
        JOIN listing_reference_contracts AS lrc
          ON lrc.research_run_id = ms.research_run_id
         AND lrc.provider = 'MASSIVE'
         AND lrc.underlying = ms.underlying
         AND lrc.expiration = oq.expiration
         AND lrc.strike = oq.strike
         AND lrc.right = oq.right
        LEFT JOIN provider_model_observations AS pmo
          ON pmo.option_quote_id = oq.id AND pmo.provider = 'THETADATA'
        WHERE ms.research_run_id = ? AND oq.id IN ({placeholders});
        """,
        (run_id, *quote_ids),
    ).fetchall()
    return {row["option_quote_id"]: row["reference_contract_id"] for row in rows}


def test_temp_table_join_returns_identical_rows_to_legacy_in_list():
    """
    Correctness: the rewritten query must return exactly the same
    (option_quote_id -> reference_contract_id) mapping as the original
    literal-IN-list query, on the same data.
    """
    import sys

    sys.path.insert(0, str(BASE_DIR))
    from src.research.hypothesis_scanner import _load_reference_and_iv

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF;")
    run_id, quote_ids = _seed(conn, reference_rows=400, quote_rows=150)

    legacy = _legacy_in_list_query(conn, run_id, quote_ids)

    # _load_reference_and_iv opens its own connection via db_path, so
    # persist this in-memory build to a temp file it can open.
    import tempfile
    import os

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        disk_conn = sqlite3.connect(path)
        disk_conn.executescript(
            "".join(conn.iterdump())
        )
        disk_conn.commit()
        disk_conn.close()

        fixed = _load_reference_and_iv(
            research_run_id=run_id,
            option_quote_ids=quote_ids,
            db_path=path,
        )
    finally:
        os.remove(path)

    fixed_mapping = {
        quote_id: entry["reference_contract_id"]
        for quote_id, entry in fixed.items()
    }

    assert fixed_mapping == legacy
    assert len(fixed_mapping) == len(quote_ids)


def test_temp_table_is_cleaned_up_after_each_call():
    """
    The temp table must not leak across calls on connections that get
    reused, and must not collide with itself on a second call.
    """
    import sys

    sys.path.insert(0, str(BASE_DIR))
    from src.research.hypothesis_scanner import _load_reference_and_iv

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF;")
    run_id, quote_ids = _seed(conn, reference_rows=100, quote_rows=40)

    import tempfile
    import os

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        disk_conn = sqlite3.connect(path)
        disk_conn.executescript("".join(conn.iterdump()))
        disk_conn.commit()
        disk_conn.close()

        first = _load_reference_and_iv(
            research_run_id=run_id, option_quote_ids=quote_ids, db_path=path
        )
        second = _load_reference_and_iv(
            research_run_id=run_id, option_quote_ids=quote_ids, db_path=path
        )
    finally:
        os.remove(path)

    assert first.keys() == second.keys()


def test_composite_index_covers_all_six_join_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_schema(conn)

    columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA index_info(idx_listing_reference_scanner_join);"
        )
    ]
    assert columns == [
        "research_run_id",
        "provider",
        "underlying",
        "expiration",
        "strike",
        "right",
    ]


@pytest.mark.slow
def test_join_is_measurably_faster_than_the_legacy_in_list():
    """
    Regression guard: at a representative but CI-sized population, the
    rewritten query must remain materially faster than the original.

    Production-scale benchmarking belongs in the dedicated benchmark tool;
    this release guard deliberately uses a smaller deterministic population
    so every PR still proves the optimization without spending a minute on a
    single timing assertion. We compare medians from three alternating runs
    after warming both paths, retaining the coarse 2x regression floor.
    """
    import sys

    sys.path.insert(0, str(BASE_DIR))
    from src.research.hypothesis_scanner import _load_reference_and_iv

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF;")
    run_id, quote_ids = _seed(
        conn,
        reference_rows=6_000,
        quote_rows=500,
    )

    import tempfile
    import os

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    def run_legacy():
        legacy_conn = sqlite3.connect(path)
        legacy_conn.row_factory = sqlite3.Row
        started = time.perf_counter()
        try:
            result = _legacy_in_list_query(legacy_conn, run_id, quote_ids)
        finally:
            legacy_conn.close()
        return time.perf_counter() - started, result

    def run_fixed():
        started = time.perf_counter()
        result = _load_reference_and_iv(
            research_run_id=run_id,
            option_quote_ids=quote_ids,
            db_path=path,
        )
        return time.perf_counter() - started, result

    try:
        disk_conn = sqlite3.connect(path)
        disk_conn.executescript("".join(conn.iterdump()))
        disk_conn.commit()
        disk_conn.close()

        # Warm both implementations once before timing so import/disk-cache
        # startup effects do not decide the assertion.
        _, legacy = run_legacy()
        _, fixed = run_fixed()

        legacy_times = []
        fixed_times = []

        for iteration in range(3):
            if iteration % 2 == 0:
                legacy_time, legacy = run_legacy()
                fixed_time, fixed = run_fixed()
            else:
                fixed_time, fixed = run_fixed()
                legacy_time, legacy = run_legacy()

            legacy_times.append(legacy_time)
            fixed_times.append(fixed_time)
    finally:
        os.remove(path)

    assert len(fixed) == len(legacy)

    median_legacy = median(legacy_times)
    median_fixed = median(fixed_times)
    speedup = median_legacy / median_fixed

    assert speedup >= 2.0, (
        "Expected the fixed query to be at least 2x faster by median: "
        f"legacy={median_legacy:.3f}s fixed={median_fixed:.3f}s "
        f"speedup={speedup:.2f}x samples_legacy={legacy_times!r} "
        f"samples_fixed={fixed_times!r}"
    )

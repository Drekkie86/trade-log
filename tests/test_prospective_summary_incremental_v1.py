"""Behavioral tests for the incremental Dashboard prospective summary.

The oracle is the exact legacy query that aggregated the whole prospective
view on every read. Every scenario asserts the incremental path returns
identical numbers, including LEFT JOIN fan-out from duplicate THETADATA
provider rows, pre/post-freeze partitioning, recovered provenance and runs
that are still in progress.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import sqlite3

import pytest

from christiania_performance_probe import _measure_seeded_dashboard_cold
from src.dashboard import read_model
from src.operations.sqlite_runtime import open_readonly_connection

LEGACY_ORACLE = """
WITH prospective_rows AS (
    SELECT us_session_date, was_recovered, research_run_id, underlying,
           prospective_start_session_date
    FROM v_local_surface_v2_prospective_partition_v2
    WHERE evidence_phase = 'POST_FREEZE_PROSPECTIVE'
),
recovered_pairs AS (
    SELECT research_run_id, underlying
    FROM prospective_rows
    WHERE was_recovered = 1
    GROUP BY research_run_id, underlying
)
SELECT COUNT(*) AS observation_rows,
       COUNT(DISTINCT us_session_date) AS independent_dates,
       SUM(CASE WHEN was_recovered = 1 THEN 1 ELSE 0 END) AS recovered_rows,
       (SELECT COUNT(*) FROM recovered_pairs) AS recovered_samples,
       MIN(prospective_start_session_date) AS prospective_start_session_date
FROM prospective_rows;
"""

UNDERLYINGS = ("AAPL", "COIN", "SPY", "QQQ", "AMD", "MU")


def _columns(conn, table):
    return [(r[1], (r[2] or "").upper(), r[3], r[4], r[5])
            for r in conn.execute(f"PRAGMA table_info({table})")]


def _insert(conn, table, values, _depth=0):
    """Insert a row filling required columns; learn CHECK literals on failure."""
    names, params = [], []
    for name, typ, notnull, default, pk in _columns(conn, table):
        if name in values:
            names.append(name)
            params.append(values[name])
        elif notnull and default is None and not pk:
            names.append(name)
            params.append(1 if "INT" in typ else 1.0 if "REAL" in typ else "x")
    try:
        conn.execute(
            f"INSERT INTO {table} ({','.join(names)}) "
            f"VALUES ({','.join('?' for _ in names)})",
            params,
        )
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        match = (re.search(r"(\w+)\s*(?:=|IS)\s*'([^']*)'", message)
                 or re.search(r"(\w+)\s+IN\s*\(\s*'([^']*)'", message, re.S))
        if match is None or _depth > 30 or values.get(match.group(1)) == match.group(2):
            raise
        return _insert(conn, table, {**values, match.group(1): match.group(2)}, _depth + 1)
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


class Seeder:
    def __init__(self, path, *, frozen_through="2026-09-03", seed=11):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = OFF;")
        self.random = random.Random(seed)
        self.add_freeze(frozen_through)

    def add_freeze(self, frozen_through):
        _insert(self.conn, "prospective_research_freeze_v1_runs", {
            "frozen_through_session_date": frozen_through,
            "prospective_start_session_date": frozen_through,
            "config_hash": f"freeze-{frozen_through}",
        })
        self.conn.commit()

    def add_run(self, day, *, observations=9, status="COMPLETED", recovered=None, dupe_every=4):
        running = status not in ("COMPLETED", "FAILED", "INVALID")
        run_id = _insert(self.conn, "research_runs", {
            "us_session_date": day,
            "cohort_id": "INDEPENDENT_RESEARCH_RUNNER_V1",
            "started_at": f"{day}T14:00:00Z",
            "ended_at": None if running else f"{day}T14:05:00Z",
            "status": status,
            "us_session_state": "INTRADAY",
        })
        recovered = set(recovered if recovered is not None else
                        [u for u in UNDERLYINGS if self.random.random() < 0.3])
        for underlying in UNDERLYINGS:
            _insert(self.conn, "research_run_underlyings", {
                "run_id": run_id, "underlying": underlying,
                "status": "ATTEMPTED" if running else "SUCCESS",
                "retry_count": 1 if underlying in recovered else 0,
            })
        snapshot = _insert(self.conn, "market_snapshots",
                           {"research_run_id": run_id, "us_session_date": day})
        model_run = _insert(self.conn, "local_surface_residual_v2_runs",
                            {"research_run_id": run_id, "model_version": "0.1.0"})
        self.conn.commit()
        self.add_observations(run_id, snapshot, model_run, observations, dupe_every=dupe_every)
        return run_id, snapshot, model_run

    def add_observations(self, run_id, snapshot, model_run, count, *, dupe_every=4, offset=0):
        for index in range(offset, offset + count):
            quote = _insert(self.conn, "option_quotes",
                            {"snapshot_id": snapshot, "bid": 1.0, "ask": 1.1})
            copies = 2 if dupe_every and index % dupe_every == 0 else 1
            for _ in range(copies):
                _insert(self.conn, "provider_model_observations", {
                    "option_quote_id": quote, "provider": "THETADATA",
                    "implied_volatility": 0.3, "delta": 0.4,
                })
            _insert(self.conn, "local_surface_residual_v2_observations", {
                "model_run_id": model_run, "option_quote_id": quote,
                "underlying": UNDERLYINGS[index % len(UNDERLYINGS)],
                "expiration": "2026-12-18", "strike": 100.0 + index, "right": "C",
                "observation_state": "EVALUATED_OBSERVATIONAL",
                "reason_code": "LOO_QUADRATIC_RESIDUAL_MEASURED",
                "fitted_iv": 0.3, "loo_residual": 0.001, "abs_loo_residual": 0.001,
                "fit_dof": 3, "usable_strike_count": 6,
            })
        self.conn.commit()

    def close_run(self, run_id):
        self.conn.execute(
            "UPDATE research_runs SET status='COMPLETED', ended_at='2026-09-30T20:00:00Z' WHERE id=?",
            (run_id,),
        )
        self.conn.execute(
            "UPDATE research_run_underlyings SET status='SUCCESS' WHERE run_id=?", (run_id,)
        )
        self.conn.commit()


@pytest.fixture
def seeded(db_path):
    read_model._clear_prospective_summary_cache()
    seeder = Seeder(db_path)
    seeder.add_run("2026-09-02")          # pre-freeze discovery, must be excluded
    for day in ("2026-09-04", "2026-09-05", "2026-09-08"):
        seeder.add_run(day)
        seeder.add_run(day)
    yield db_path, seeder
    seeder.conn.close()
    read_model._clear_prospective_summary_cache()


def _oracle(path):
    conn = open_readonly_connection(path)
    try:
        row = conn.execute(LEGACY_ORACLE).fetchone()
        return {
            "observation_rows": int(row["observation_rows"] or 0),
            "independent_dates": int(row["independent_dates"] or 0),
            "recovered_rows": int(row["recovered_rows"] or 0),
            "recovered_samples": int(row["recovered_samples"] or 0),
            "prospective_start_session_date": row["prospective_start_session_date"],
        }
    finally:
        conn.close()


def _summary(path):
    conn = open_readonly_connection(path)
    try:
        return read_model._load_prospective_summary(conn, path)
    finally:
        conn.close()


def _deck_prospective(path):
    deck = read_model.load_command_deck(path, page="Dashboard", deep_integrity=False)
    return deck["prospective"]


def test_incremental_summary_matches_legacy_full_aggregate(seeded):
    path, _ = seeded
    expected = _oracle(path)
    assert expected["observation_rows"] > 0
    assert expected["recovered_samples"] > 0
    assert _summary(path) == expected
    assert _deck_prospective(path) == expected


def test_recovered_samples_are_distinct_run_underlying_pairs(seeded):
    path, seeder = seeded
    # One run, two recovered underlyings, many rows each: pairs, not rows.
    seeder.add_run("2026-09-09", observations=24, recovered={"AAPL", "COIN"}, dupe_every=0)
    expected = _oracle(path)
    result = _summary(path)
    assert result["recovered_samples"] == expected["recovered_samples"]
    assert result["recovered_rows"] > result["recovered_samples"]


def test_new_runs_are_added_without_recomputing_history(seeded):
    path, seeder = seeded
    assert _summary(path) == _oracle(path)
    statements = []
    original = read_model._prospective_range_part

    def spy(conn, **kwargs):
        statements.append(kwargs)
        return original(conn, **kwargs)

    read_model._prospective_range_part = spy
    try:
        seeder.add_run("2026-09-09")
        assert _summary(path) == _oracle(path)
    finally:
        read_model._prospective_range_part = original
    history_scans = [k for k in statements
                     if k.get("low_exclusive") in (0, None) and k.get("include_ids") is None]
    assert history_scans == [], "refresh must not rescan from the beginning of history"


def test_open_run_is_live_and_folded_in_when_it_closes(seeded):
    path, seeder = seeded
    open_run, snapshot, model_run = seeder.add_run("2026-09-09", status="RUNNING")
    assert _summary(path) == _oracle(path)
    seeder.add_observations(open_run, snapshot, model_run, 5, offset=100)
    assert _summary(path) == _oracle(path)
    seeder.close_run(open_run)
    assert _summary(path) == _oracle(path)
    seeder.add_run("2026-09-10")
    assert _summary(path) == _oracle(path)


def test_stuck_open_run_does_not_stop_caching_later_runs(seeded):
    path, seeder = seeded
    seeder.add_run("2026-09-09", status="RUNNING")      # never closes
    later = [seeder.add_run("2026-09-10")[0], seeder.add_run("2026-09-11")[0]]
    assert _summary(path) == _oracle(path)
    state = next(iter(read_model._prospective_cache.values()))
    assert set(later).isdisjoint(state["open_run_ids"])
    assert len(state["open_run_ids"]) == 1


def test_late_evidence_for_cached_run_forces_exact_recompute(seeded):
    path, seeder = seeded
    run_id, snapshot, model_run = seeder.add_run("2026-09-09")
    assert _summary(path) == _oracle(path)
    # Backfill into an already-cached terminal run.
    seeder.add_observations(run_id, snapshot, model_run, 7, offset=200)
    assert _summary(path) == _oracle(path)
    # Late duplicate THETADATA row (LEFT JOIN fan-out) for a cached quote.
    quote = seeder.conn.execute(
        "SELECT option_quote_id FROM local_surface_residual_v2_observations "
        "WHERE model_run_id=? LIMIT 1", (model_run,)
    ).fetchone()[0]
    _insert(seeder.conn, "provider_model_observations", {
        "option_quote_id": quote, "provider": "THETADATA",
        "implied_volatility": 0.3, "delta": 0.4,
    })
    seeder.conn.commit()
    assert _summary(path) == _oracle(path)


def test_new_freeze_resets_partition(seeded):
    path, seeder = seeded
    assert _summary(path) == _oracle(path)
    seeder.add_freeze("2026-09-05")
    assert _summary(path) == _oracle(path)


def test_empty_database_matches_legacy(db_path):
    read_model._clear_prospective_summary_cache()
    assert _summary(db_path) == {
        "observation_rows": 0, "independent_dates": 0, "recovered_rows": 0,
        "recovered_samples": 0, "prospective_start_session_date": None,
    }


def test_incremental_refresh_uses_index_seek_not_history_scan(seeded):
    path, _ = seeded
    conn = sqlite3.connect(path)
    conn.execute("ANALYZE;")
    conn.close()
    conn = open_readonly_connection(path)
    try:
        plan = [row[3] for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) "
            "FROM v_local_surface_v2_prospective_partition_v2 "
            "WHERE evidence_phase = 'POST_FREEZE_PROSPECTIVE' "
            "AND research_run_id > ? AND research_run_id <= ?",
            (3, 5),
        )]
    finally:
        conn.close()
    assert any(step.startswith("SEARCH r ") and "research_run_id>" in step for step in plan), plan
    assert not any(step.startswith("SCAN o") for step in plan), plan


def test_late_evidence_guards_scan_only_new_rows(seeded):
    """The correctness guards must stay O(new rows): driven by rowid ranges."""
    path, _ = seeded
    conn = sqlite3.connect(path)
    conn.execute("ANALYZE;")
    conn.close()
    assert _summary(path) == _oracle(path)
    state = next(iter(read_model._prospective_cache.values()))
    conn = open_readonly_connection(path)
    traced = []
    conn.set_trace_callback(traced.append)
    try:
        assert read_model._late_evidence_for_cached_runs(conn, state) is False
        guards = [s for s in traced if s.lstrip().startswith("SELECT 1")]
        assert len(guards) == 2
        # The trace callback yields SQL with bound values already expanded.
        for statement in guards:
            plan = [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + statement)]
            first = plan[0]
            assert first.startswith("SEARCH") and "rowid>?" in first, plan
    finally:
        conn.close()


def test_persisted_probe_seed_avoids_cold_history_rebuild(
    seeded,
    tmp_path,
    monkeypatch,
):
    path, _ = seeded
    expected = _summary(path)
    seed = read_model.export_prospective_summary_seed(path)
    assert seed is not None

    commit = "a" * 40
    marker = tmp_path / "DEPLOYED_COMMIT"
    marker.write_text(commit + "\n", encoding="utf-8")
    report_dir = tmp_path / "performance-probes"
    report_dir.mkdir()
    (report_dir / f"{commit}-seed.json").write_text(
        json.dumps(
            {
                "probe_version": 4,
                "release_commit": commit,
                "read_only": True,
                "deployment_lock_held": True,
                "prospective_cache_seed": seed,
            }
        ),
        encoding="utf-8",
    )

    read_model._clear_prospective_summary_cache()
    monkeypatch.setattr(read_model, "_DEPLOYED_COMMIT_PATH", marker)
    monkeypatch.setattr(read_model, "_PERFORMANCE_PROBE_DIR", report_dir)

    calls = []
    original = read_model._prospective_range_part

    def spy(conn, **kwargs):
        calls.append(kwargs)
        return original(conn, **kwargs)

    monkeypatch.setattr(read_model, "_prospective_range_part", spy)

    assert _summary(path) == expected

    history_scans = [
        kwargs
        for kwargs in calls
        if kwargs.get("include_ids") is None
        and kwargs.get("low_exclusive") in (None, 0)
    ]
    assert history_scans == []


def test_seeded_cold_probe_proves_history_rebuild_is_avoided(seeded):
    path, _ = seeded
    assert _summary(path) == _oracle(path)
    seed = read_model.export_prospective_summary_seed(path)
    assert seed is not None

    measured = _measure_seeded_dashboard_cold(
        path,
        release_commit="b" * 40,
        seed=seed,
    )

    assert measured["history_rebuild_avoided"] is True
    assert measured["wall_ms"] >= 0
    assert "prospective_ms" in measured["section_ms"]

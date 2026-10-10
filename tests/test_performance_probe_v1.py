from __future__ import annotations

from pathlib import Path

from christiania_performance_probe import (
    _measure_page,
    _measure_ops_release_manifest,
    _runtime_activity_metadata,
    _sqlite_metadata,
)


def test_performance_probe_metadata_is_readonly_and_tuning_aware(db_path):
    metadata = _sqlite_metadata(Path(db_path))

    assert metadata["path"] == str(Path(db_path))
    assert metadata["journal_mode"] == "wal"
    assert isinstance(metadata["database_bytes"], int)
    assert isinstance(metadata["wal_bytes"], int)
    assert isinstance(metadata["cache_size"], int)
    assert isinstance(metadata["mmap_size"], int)
    assert isinstance(metadata["wal_autocheckpoint"], int)
    assert "sqlite_stat1_exists" in metadata


def test_performance_probe_records_cache_copy_cost_for_page(db_path):
    result = _measure_page(
        Path(db_path),
        "Dashboard",
        warmups=0,
        runs=1,
    )

    assert result["page"] == "Dashboard"
    assert result["cold_wall_ms"] >= 0
    assert result["cache_payload_bytes"] > 0
    assert result["pickle_dump_ms"] >= 0
    assert result["pickle_load_ms"]["median"] >= 0
    assert result["wall_ms"]["median"] >= 0
    assert "total_ms" in result["section_median_ms"]


def test_performance_probe_can_measure_legacy_full_deck(db_path):
    result = _measure_page(
        Path(db_path),
        None,
        warmups=0,
        runs=1,
    )

    assert result["page"] == "FULL"
    assert result["cache_payload_bytes"] > 0
    assert "decision_ms" in result["section_median_ms"]
    assert "shadow_detail_ms" in result["section_median_ms"]


def test_performance_probe_records_daemon_activity_context(db_path):
    activity = _runtime_activity_metadata(Path(db_path))

    assert isinstance(activity["cycle_active"], bool)
    assert "latest_iteration" in activity
    assert "daemon_lock" in activity



def test_performance_probe_includes_bounded_ops_release_manifest(db_path, monkeypatch):
    from src.operations import release_manifest

    actual = release_manifest.inspect_database
    depths = []

    def spy(path=None, *, deep_integrity=True):
        depths.append(deep_integrity)
        assert not deep_integrity, "Interactive perf proof must not scan full SQLite DB"
        return actual(path, deep_integrity=False)

    monkeypatch.setattr(release_manifest, "inspect_database", spy)
    result = _measure_ops_release_manifest(Path(db_path), runs=2)
    assert result["deep_integrity"] is False
    assert result["within_budget"] is True
    assert result["median_ms"] >= 0
    assert result["budget_ms"] == 1000.0
    assert result["runs"] == 2
    assert depths == [False, False, False]

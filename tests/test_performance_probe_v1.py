from __future__ import annotations

from pathlib import Path

from christiania_performance_probe import (
    _measure_page,
    _runtime_activity_metadata,
    _sqlite_metadata,
)
from src.dashboard.read_model import export_prospective_summary_seed


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


def test_dashboard_probe_exports_serializable_prospective_seed(db_path):
    _measure_page(
        Path(db_path),
        "Dashboard",
        warmups=0,
        runs=1,
    )

    seed = export_prospective_summary_seed(Path(db_path))

    assert seed is not None
    assert seed["seed_version"] == 1
    assert seed["database_path"] == str(Path(db_path).resolve())
    assert isinstance(seed["open_run_ids"], list)
    assert isinstance(seed["part"]["dates"], list)

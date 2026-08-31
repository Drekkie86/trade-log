from pathlib import Path

import quality_gate


def test_schema_history_check_rejects_delete(tmp_path, monkeypatch):
    schema = tmp_path / "trade_log_schema.sql"
    schema.write_text(
        "DELETE FROM schema_version;",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        quality_gate,
        "ROOT",
        tmp_path,
    )

    result = (
        quality_gate.check_schema_version_history()
    )

    assert result.ok is False


def test_duplicate_test_module_detection(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_good.py").write_text(
        "",
        encoding="utf-8",
    )
    (tmp_path / "payload").mkdir()
    (
        tmp_path
        / "payload"
        / "test_good.py"
    ).write_text(
        "",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        quality_gate,
        "ROOT",
        tmp_path,
    )

    result = (
        quality_gate.check_duplicate_test_modules()
    )

    assert result.ok is False
    assert "payload/test_good.py" in result.detail


def test_migration_sequence_requires_contiguous_numbers(
    tmp_path,
    monkeypatch,
):
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()

    (
        migration_dir
        / "007_a.sql"
    ).write_text("", encoding="utf-8")

    (
        migration_dir
        / "009_c.sql"
    ).write_text("", encoding="utf-8")

    monkeypatch.setattr(
        quality_gate,
        "ROOT",
        tmp_path,
    )

    result = quality_gate.check_migration_sequence()

    assert result.ok is False

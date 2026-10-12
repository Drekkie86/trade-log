"""Fail-closed P0 backup retention: never pre-delete the 2nd recovery point."""
import sqlite3
from pathlib import Path

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import create_verified_backup, plan_backup_capacity


def make_source(path):
    with sqlite3.connect(path) as c:
        c.execute(
            "CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        c.execute(
            "INSERT INTO schema_version VALUES (?, '2026-10-12T00:00:00Z')",
            (EXPECTED_SCHEMA_VERSION,),
        )


def create_sparse_backup(path, bytes_count):
    with open(path,"wb") as f:
        f.truncate(bytes_count)


class TightDisk:
    total=100*(1024**3)
    free=int(14.5*(1024**3))
    used=total-free


def test_two_existing_backups_are_never_prepruned_when_new_backup_cannot_fit(
    tmp_path,monkeypatch
):
    import src.operations.sqlite_runtime as ops
    source=tmp_path/"source.db"
    make_source(source)
    backups=tmp_path/"backups"
    backups.mkdir()
    old=backups/"christiania_backup_20261001T000000Z.db"
    recent=backups/"christiania_backup_20261008T000000Z.db"
    create_sparse_backup(old,2*1024**3)
    create_sparse_backup(recent,2*1024**3)
    monkeypatch.setattr(ops.shutil,"disk_usage",lambda _:TightDisk())
    plan=plan_backup_capacity(source=source,target_dir=backups,retention=3)
    assert plan.current_backup_count==2
    assert plan.preprune_keep==2
    assert plan.reclaimable_bytes==0
    assert plan.feasible_after_safe_prune is False
    with pytest.raises(RuntimeError,match="Insufficient backup filesystem headroom"):
        create_verified_backup(db_path=source,backup_dir=backups,retention=3)
    assert old.stat().st_size==2*1024**3
    assert recent.stat().st_size==2*1024**3
    assert len(list(backups.iterdir()))==2


def test_two_backups_can_be_kept_if_disk_has_sufficient_headroom(
    tmp_path,monkeypatch
):
    import src.operations.sqlite_runtime as ops
    source=tmp_path/"source.db"
    make_source(source)
    backups=tmp_path/"backups"
    backups.mkdir()
    for i in range(2):
        create_sparse_backup(
            backups/f"christiania_backup_2026100{i+1}T000000Z.db",
            256*1024**2,
        )
    class EnoughDisk:
        total=100*1024**3
        free=55*1024**3
        used=total-free
    monkeypatch.setattr(ops.shutil,"disk_usage",lambda _:EnoughDisk())
    plan=plan_backup_capacity(source=source,target_dir=backups,retention=3)
    assert plan.preprune_keep==2
    assert plan.reclaimable_bytes==0
    assert plan.feasible_after_safe_prune is True


def test_retention_one_explicitly_still_keeps_single_prior_recovery_copy(
    tmp_path,monkeypatch
):
    import src.operations.sqlite_runtime as ops
    source=tmp_path/"source.db"
    make_source(source)
    backups=tmp_path/"backups"
    backups.mkdir()
    for i in range(2):
        create_sparse_backup(
            backups/f"christiania_backup_2026100{i+1}T000000Z.db",
            2*1024**3,
        )
    monkeypatch.setattr(ops.shutil,"disk_usage",lambda _:TightDisk())
    plan=plan_backup_capacity(source=source,target_dir=backups,retention=1)
    assert plan.preprune_keep==1
    assert plan.reclaimable_bytes==2*1024**3
    assert plan.feasible_after_safe_prune is True

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.operations.remote_archive import (
    RemoteArchiveConfig,
    check_remote_bucket,
    inventory_remote_archive_proofs,
    upload_and_verify_remote_archive,
    verify_remote_archive_proof,
)


class FakeS3:
    def __init__(self, *, lock_enabled: bool = True):
        self.lock_enabled = lock_enabled
        self.objects = {}
        self.version_counter = 0

    def head_bucket(self, *, Bucket):
        return {}

    def get_object_lock_configuration(self, *, Bucket):
        return {
            "ObjectLockConfiguration": {
                "ObjectLockEnabled": (
                    "Enabled"
                    if self.lock_enabled
                    else "Disabled"
                )
            }
        }

    def put_object(
        self,
        *,
        Bucket,
        Key,
        Body,
        ContentLength,
        ContentType,
        Metadata,
        ObjectLockMode,
        ObjectLockRetainUntilDate,
    ):
        self.version_counter += 1
        version_id = f"v{self.version_counter}"
        data = Body.read()
        assert len(data) == ContentLength

        self.objects[
            (Key, version_id)
        ] = {
            "data": data,
            "metadata": {
                str(k).lower(): str(v)
                for k, v in Metadata.items()
            },
            "retention_mode": ObjectLockMode,
            "retain_until": ObjectLockRetainUntilDate,
            "content_type": ContentType,
        }

        return {
            "VersionId": version_id,
        }

    def _resolve(self, key, version_id):
        if version_id is not None:
            return self.objects[
                (key, version_id)
            ]

        versions = [
            (stored_version, item)
            for (
                stored_key,
                stored_version,
            ), item in self.objects.items()
            if stored_key == key
        ]
        if not versions:
            raise KeyError(key)
        versions.sort(
            key=lambda item: int(
                item[0][1:]
            )
        )
        return versions[-1][1]

    def head_object(
        self,
        *,
        Bucket,
        Key,
        VersionId=None,
    ):
        item = self._resolve(
            Key,
            VersionId,
        )
        return {
            "ContentLength": len(
                item["data"]
            ),
            "Metadata": dict(
                item["metadata"]
            ),
        }

    def get_object_retention(
        self,
        *,
        Bucket,
        Key,
        VersionId=None,
    ):
        item = self._resolve(
            Key,
            VersionId,
        )
        return {
            "Retention": {
                "Mode": item[
                    "retention_mode"
                ],
                "RetainUntilDate": item[
                    "retain_until"
                ],
            }
        }

    def get_object(
        self,
        *,
        Bucket,
        Key,
        VersionId=None,
    ):
        item = self._resolve(
            Key,
            VersionId,
        )
        return {
            "Body": io.BytesIO(
                item["data"]
            )
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_local_archive(
    directory: Path,
) -> Path:
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    sqlite_path = (
        directory
        / "research_evidence_2026-09-01_runs_1_1.db"
    )
    conn = sqlite3.connect(
        sqlite_path
    )
    try:
        conn.execute(
            """
            CREATE TABLE research_runs(
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO research_runs(
                id,
                status
            )
            VALUES(1, 'COMPLETED');
            """
        )
        conn.commit()
    finally:
        conn.close()

    uncompressed_sha = _sha256(
        sqlite_path
    )
    uncompressed_size = (
        sqlite_path.stat().st_size
    )

    archive_path = (
        directory
        / "research_evidence_2026-09-01_runs_1_1.db.gz"
    )
    with sqlite_path.open("rb") as source:
        with archive_path.open(
            "wb"
        ) as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=6,
                fileobj=raw,
                mtime=0,
            ) as compressed:
                compressed.write(
                    source.read()
                )

    sqlite_path.unlink()

    manifest_path = (
        directory
        / "research_evidence_2026-09-01_runs_1_1.manifest.json"
    )
    manifest = {
        "format_version": 1,
        "coverage":
            "HIGH_VOLUME_RESEARCH_EVIDENCE_V1",
        "created_at":
            "2026-09-21T20:00:00Z",
        "session_date":
            "2026-09-01",
        "run_ids": [1],
        "min_run_id": 1,
        "max_run_id": 1,
        "source_schema_version": 33,
        "source_db_size_bytes":
            uncompressed_size,
        "table_counts": {
            "research_runs": 1,
        },
        "uncompressed_size_bytes":
            uncompressed_size,
        "compressed_size_bytes":
            archive_path.stat().st_size,
        "uncompressed_sha256":
            uncompressed_sha,
        "compressed_sha256":
            _sha256(archive_path),
        "compression": "gzip",
        "archive_filename":
            archive_path.name,
        "manifest_filename":
            manifest_path.name,
        "integrity_check": "ok",
        "prune_eligible": False,
        "prune_block_reason":
            "OFFHOST_IMMUTABLE_COPY_NOT_CONFIRMED",
    }
    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return manifest_path


def _config() -> RemoteArchiveConfig:
    return RemoteArchiveConfig(
        endpoint_url=(
            "https://fsn1.your-objectstorage.com"
        ),
        region="fsn1",
        bucket="christiania-test",
        access_key_id="test-access",
        secret_access_key="test-secret",
        prefix=(
            "christiania/research-evidence/v1"
        ),
        retention_days=365,
    )


def test_remote_archive_round_trip_and_proof(
    tmp_path,
):
    manifest_path = _write_local_archive(
        tmp_path
    )
    client = FakeS3()
    progress = []

    proof = upload_and_verify_remote_archive(
        manifest_path,
        config=_config(),
        client=client,
        now=datetime(
            2026,
            9,
            21,
            20,
            0,
            tzinfo=UTC,
        ),
        progress=progress.append,
    )

    assert (
        proof.pruning_gate_state
        == "OFFHOST_IMMUTABLE_RESTORE_VERIFIED"
    )
    assert (
        proof.archive_object.retention_mode
        == "COMPLIANCE"
    )
    assert proof.archive_object.version_id
    assert proof.manifest_object.version_id
    assert proof.receipt_object.version_id
    assert (
        proof.remote_restore_compressed_sha256
        == proof.local_archive_compressed_sha256
    )
    assert (
        proof.remote_restore_uncompressed_sha256
        == proof.local_archive_uncompressed_sha256
    )

    proof_path = (
        tmp_path
        / "research_evidence_2026-09-01_runs_1_1.remote-proof.json"
    )
    assert proof_path.is_file()

    verified = verify_remote_archive_proof(
        proof_path,
        config=_config(),
        client=client,
        progress=progress.append,
    )
    assert (
        verified.pruning_gate_state
        == proof.pruning_gate_state
    )

    inventory = (
        inventory_remote_archive_proofs(
            tmp_path
        )
    )
    assert inventory.proof_count == 1
    assert inventory.invalid_proofs == ()

    assert any(
        "round-trip verification passed"
        in message
        for message in progress
    )
    assert any(
        "immutable object retention"
        in message
        for message in progress
    )


def test_bucket_without_object_lock_is_rejected():
    with pytest.raises(
        RuntimeError,
        match="Object Lock enabled",
    ):
        check_remote_bucket(
            config=_config(),
            client=FakeS3(
                lock_enabled=False
            ),
        )


def test_remote_proof_is_idempotency_guard(
    tmp_path,
):
    manifest_path = _write_local_archive(
        tmp_path
    )
    client = FakeS3()

    upload_and_verify_remote_archive(
        manifest_path,
        config=_config(),
        client=client,
        now=datetime(
            2026,
            9,
            21,
            20,
            0,
            tzinfo=UTC,
        ),
    )

    with pytest.raises(
        FileExistsError,
        match="proof already exists",
    ):
        upload_and_verify_remote_archive(
            manifest_path,
            config=_config(),
            client=client,
            now=datetime(
                2026,
                9,
                21,
                20,
                0,
                tzinfo=UTC,
            ),
        )

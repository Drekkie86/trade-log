from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Callable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.config import get_runtime_setting
from src.operations.research_archive import (
    ResearchArchiveManifest,
    load_archive_manifest,
    resolve_archive_dir,
    verify_research_archive,
)


REMOTE_PROOF_FORMAT_VERSION = 1
DEFAULT_REMOTE_RETENTION_DAYS = 365
DEFAULT_REMOTE_PREFIX = "christiania/research-evidence/v1"
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class RemoteArchiveConfig:
    endpoint_url: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    prefix: str
    retention_days: int

    def public_dict(self) -> dict[str, object]:
        return {
            "endpoint_url": self.endpoint_url,
            "region": self.region,
            "bucket": self.bucket,
            "prefix": self.prefix,
            "retention_days": self.retention_days,
        }


@dataclass(frozen=True)
class RemoteObjectEvidence:
    key: str
    version_id: str | None
    size_bytes: int
    sha256: str
    retention_mode: str
    retain_until: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RemoteArchiveProof:
    format_version: int
    verified_at: str
    session_date: str
    local_manifest_filename: str
    local_manifest_sha256: str
    local_archive_filename: str
    local_archive_compressed_sha256: str
    local_archive_uncompressed_sha256: str
    bucket: str
    endpoint_url: str
    region: str
    prefix: str
    retention_days: int
    archive_object: RemoteObjectEvidence
    manifest_object: RemoteObjectEvidence
    receipt_object: RemoteObjectEvidence
    remote_restore_compressed_sha256: str
    remote_restore_uncompressed_sha256: str
    pruning_gate_state: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["archive_object"] = self.archive_object.as_dict()
        data["manifest_object"] = self.manifest_object.as_dict()
        data["receipt_object"] = self.receipt_object.as_dict()
        return data


@dataclass(frozen=True)
class RemoteArchiveInventory:
    directory: str
    proof_count: int
    proofs: tuple[RemoteArchiveProof, ...]
    invalid_proofs: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "directory": self.directory,
            "proof_count": self.proof_count,
            "proofs": [
                proof.as_dict()
                for proof in self.proofs
            ],
            "invalid_proofs": list(
                self.invalid_proofs
            ),
        }


def _required_setting(name: str) -> str:
    value = get_runtime_setting(name)
    if value in (None, ""):
        raise RuntimeError(
            f"Required remote archive setting is missing: {name}"
        )
    return str(value).strip()


def _normalize_prefix(value: str) -> str:
    return value.strip().strip("/")


def resolve_remote_archive_config() -> RemoteArchiveConfig:
    retention_raw = get_runtime_setting(
        "CHRISTIANIA_EVIDENCE_REMOTE_RETENTION_DAYS"
    )
    retention_days = (
        DEFAULT_REMOTE_RETENTION_DAYS
        if retention_raw in (None, "")
        else int(retention_raw)
    )
    if retention_days < 30:
        raise ValueError(
            "CHRISTIANIA_EVIDENCE_REMOTE_RETENTION_DAYS "
            "must be >= 30 for immutable evidence storage."
        )

    prefix = _normalize_prefix(
        str(
            get_runtime_setting(
                "CHRISTIANIA_EVIDENCE_REMOTE_PREFIX"
            )
            or DEFAULT_REMOTE_PREFIX
        )
    )
    if not prefix:
        raise ValueError(
            "CHRISTIANIA_EVIDENCE_REMOTE_PREFIX cannot be blank."
        )

    endpoint = _required_setting(
        "CHRISTIANIA_EVIDENCE_REMOTE_ENDPOINT"
    ).rstrip("/")
    if not endpoint.startswith("https://"):
        raise ValueError(
            "CHRISTIANIA_EVIDENCE_REMOTE_ENDPOINT must use HTTPS."
        )

    return RemoteArchiveConfig(
        endpoint_url=endpoint,
        region=_required_setting(
            "CHRISTIANIA_EVIDENCE_REMOTE_REGION"
        ),
        bucket=_required_setting(
            "CHRISTIANIA_EVIDENCE_REMOTE_BUCKET"
        ),
        access_key_id=_required_setting(
            "CHRISTIANIA_EVIDENCE_REMOTE_ACCESS_KEY_ID"
        ),
        secret_access_key=_required_setting(
            "CHRISTIANIA_EVIDENCE_REMOTE_SECRET_ACCESS_KEY"
        ),
        prefix=prefix,
        retention_days=retention_days,
    )


def create_s3_client(
    config: RemoteArchiveConfig,
):
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        config=Config(
            signature_version="s3v4",
            retries={
                "max_attempts": 5,
                "mode": "standard",
            },
            s3={
                "payload_signing_enabled": False,
                "addressing_style": "virtual",
            },
        ),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_stream(
    stream: BinaryIO,
    *,
    output: BinaryIO | None = None,
) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        if output is not None:
            output.write(chunk)
    return digest.hexdigest()


def _utc_iso(value: datetime) -> str:
    return (
        value.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC)


def _proof_path_for(
    manifest_path: Path,
) -> Path:
    suffix = ".manifest.json"
    if not manifest_path.name.endswith(suffix):
        raise ValueError(
            "Research archive manifest must end with "
            f"{suffix}."
        )
    stem = manifest_path.name[
        :-len(suffix)
    ]
    return manifest_path.with_name(
        stem + ".remote-proof.json"
    )


def _write_json_atomic(
    path: Path,
    payload: dict[str, object],
) -> None:
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )
    text = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    try:
        with temp.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _manifest_sha256(
    manifest_path: Path,
) -> str:
    return _sha256_file(manifest_path)


def _archive_object_key(
    config: RemoteArchiveConfig,
    manifest: ResearchArchiveManifest,
) -> str:
    return (
        f"{config.prefix}/"
        f"{manifest.session_date}/"
        f"{manifest.archive_filename}"
    )


def _manifest_object_key(
    config: RemoteArchiveConfig,
    manifest: ResearchArchiveManifest,
) -> str:
    return (
        f"{config.prefix}/"
        f"{manifest.session_date}/"
        f"{manifest.manifest_filename}"
    )


def _receipt_object_key(
    config: RemoteArchiveConfig,
    manifest: ResearchArchiveManifest,
) -> str:
    return (
        f"{config.prefix}/"
        f"{manifest.session_date}/"
        f"remote_verification_"
        f"{manifest.min_run_id}_{manifest.max_run_id}.json"
    )


def check_remote_bucket(
    *,
    config: RemoteArchiveConfig | None = None,
    client=None,
) -> dict[str, object]:
    resolved = (
        resolve_remote_archive_config()
        if config is None
        else config
    )
    s3 = (
        create_s3_client(resolved)
        if client is None
        else client
    )

    s3.head_bucket(
        Bucket=resolved.bucket
    )
    try:
        lock = s3.get_object_lock_configuration(
            Bucket=resolved.bucket
        )
    except ClientError as exc:
        raise RuntimeError(
            "Unable to confirm S3 Object Lock on the "
            "remote archive bucket."
        ) from exc
    lock_config = lock.get(
        "ObjectLockConfiguration"
    ) or {}
    if (
        str(
            lock_config.get(
                "ObjectLockEnabled"
            )
            or ""
        ).upper()
        != "ENABLED"
    ):
        raise RuntimeError(
            "Remote archive bucket does not have "
            "S3 Object Lock enabled. Christiania "
            "will not treat it as immutable."
        )

    return {
        **resolved.public_dict(),
        "object_lock_enabled": True,
        "bucket_check": "PASS",
    }


def _retention_evidence(
    *,
    s3,
    bucket: str,
    key: str,
    version_id: str | None,
    minimum_retain_until: datetime,
) -> tuple[str, datetime]:
    kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
    }
    if version_id:
        kwargs["VersionId"] = version_id

    retention = s3.get_object_retention(
        **kwargs
    ).get("Retention") or {}
    mode = str(
        retention.get("Mode") or ""
    ).upper()
    retain_until_raw = retention.get(
        "RetainUntilDate"
    )

    if mode != "COMPLIANCE":
        raise RuntimeError(
            "Remote evidence object is not protected "
            f"by COMPLIANCE retention: {key}"
        )
    if retain_until_raw is None:
        raise RuntimeError(
            "Remote evidence object has no retention expiry: "
            f"{key}"
        )

    retain_until = _parse_utc(
        retain_until_raw
    )
    if retain_until < minimum_retain_until:
        raise RuntimeError(
            "Remote evidence retention is shorter than "
            f"Christiania required: {key}"
        )

    return mode, retain_until


def _head_object(
    *,
    s3,
    bucket: str,
    key: str,
    version_id: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
    }
    if version_id:
        kwargs["VersionId"] = version_id
    return s3.head_object(**kwargs)


def _put_locked_object(
    *,
    s3,
    config: RemoteArchiveConfig,
    key: str,
    body,
    size_bytes: int,
    sha256: str,
    metadata: dict[str, str],
    retain_until: datetime,
    content_type: str,
) -> RemoteObjectEvidence:
    response = s3.put_object(
        Bucket=config.bucket,
        Key=key,
        Body=body,
        ContentLength=size_bytes,
        ContentType=content_type,
        Metadata={
            **metadata,
            "sha256": sha256,
        },
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=retain_until,
    )
    version_id = response.get(
        "VersionId"
    )
    if version_id in (None, ""):
        raise RuntimeError(
            "Remote immutable object upload did not return "
            "an S3 VersionId. Christiania requires versioned "
            "Object Lock evidence."
        )

    head = _head_object(
        s3=s3,
        bucket=config.bucket,
        key=key,
        version_id=version_id,
    )
    remote_size = int(
        head.get("ContentLength") or 0
    )
    remote_metadata = {
        str(k).lower(): str(v)
        for k, v in (
            head.get("Metadata") or {}
        ).items()
    }

    if remote_size != size_bytes:
        raise RuntimeError(
            "Remote object size mismatch after upload: "
            f"{key}: {remote_size} != {size_bytes}"
        )
    if (
        remote_metadata.get("sha256")
        != sha256
    ):
        raise RuntimeError(
            "Remote object SHA-256 metadata mismatch "
            f"after upload: {key}"
        )

    mode, confirmed_until = (
        _retention_evidence(
            s3=s3,
            bucket=config.bucket,
            key=key,
            version_id=version_id,
            minimum_retain_until=retain_until,
        )
    )

    return RemoteObjectEvidence(
        key=key,
        version_id=(
            None
            if version_id in (None, "")
            else str(version_id)
        ),
        size_bytes=remote_size,
        sha256=sha256,
        retention_mode=mode,
        retain_until=_utc_iso(
            confirmed_until
        ),
    )


def _download_object_to_file(
    *,
    s3,
    bucket: str,
    key: str,
    version_id: str | None,
    target: Path,
) -> str:
    kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
    }
    if version_id:
        kwargs["VersionId"] = version_id

    response = s3.get_object(**kwargs)
    body = response["Body"]

    with target.open("wb") as output:
        compressed_sha = _sha256_stream(
            body,
            output=output,
        )
        output.flush()
        os.fsync(output.fileno())

    close = getattr(
        body,
        "close",
        None,
    )
    if callable(close):
        close()

    return compressed_sha


def _download_object_bytes(
    *,
    s3,
    bucket: str,
    key: str,
    version_id: str | None,
) -> bytes:
    kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
    }
    if version_id:
        kwargs["VersionId"] = version_id

    response = s3.get_object(**kwargs)
    body = response["Body"]
    payload = body.read()
    close = getattr(
        body,
        "close",
        None,
    )
    if callable(close):
        close()
    return payload


def _verify_remote_restore(
    *,
    s3,
    config: RemoteArchiveConfig,
    manifest: ResearchArchiveManifest,
    archive_object: RemoteObjectEvidence,
    manifest_object: RemoteObjectEvidence,
    local_manifest_path: Path,
    progress: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(
        prefix="christiania-offhost-restore-"
    ) as temp_dir:
        remote_archive = (
            Path(temp_dir)
            / manifest.archive_filename
        )

        if progress is not None:
            progress(
                "remote-restore: downloading archive"
            )

        compressed_sha = (
            _download_object_to_file(
                s3=s3,
                bucket=config.bucket,
                key=archive_object.key,
                version_id=archive_object.version_id,
                target=remote_archive,
            )
        )
        if (
            compressed_sha
            != manifest.compressed_sha256
        ):
            raise RuntimeError(
                "Remote restore compressed SHA-256 "
                "does not match local verified manifest."
            )

        with gzip.open(
            remote_archive,
            "rb",
        ) as payload:
            uncompressed_sha = (
                _sha256_stream(payload)
            )
        if (
            uncompressed_sha
            != manifest.uncompressed_sha256
        ):
            raise RuntimeError(
                "Remote restore uncompressed SHA-256 "
                "does not match local verified manifest."
            )

        remote_manifest = _download_object_bytes(
            s3=s3,
            bucket=config.bucket,
            key=manifest_object.key,
            version_id=manifest_object.version_id,
        )
        local_manifest = (
            local_manifest_path.read_bytes()
        )
        if remote_manifest != local_manifest:
            raise RuntimeError(
                "Remote manifest bytes do not exactly match "
                "the local verified manifest."
            )

        if progress is not None:
            progress(
                "remote-restore: archive and manifest "
                "round-trip verification passed"
            )

        return (
            compressed_sha,
            uncompressed_sha,
        )


def _proof_from_dict(
    payload: dict[str, object],
) -> RemoteArchiveProof:
    def object_evidence(
        name: str,
    ) -> RemoteObjectEvidence:
        data = dict(payload[name])
        return RemoteObjectEvidence(
            key=str(data["key"]),
            version_id=(
                None
                if data.get("version_id") in (None, "")
                else str(data["version_id"])
            ),
            size_bytes=int(
                data["size_bytes"]
            ),
            sha256=str(data["sha256"]),
            retention_mode=str(
                data["retention_mode"]
            ),
            retain_until=str(
                data["retain_until"]
            ),
        )

    return RemoteArchiveProof(
        format_version=int(
            payload["format_version"]
        ),
        verified_at=str(
            payload["verified_at"]
        ),
        session_date=str(
            payload["session_date"]
        ),
        local_manifest_filename=str(
            payload["local_manifest_filename"]
        ),
        local_manifest_sha256=str(
            payload["local_manifest_sha256"]
        ),
        local_archive_filename=str(
            payload["local_archive_filename"]
        ),
        local_archive_compressed_sha256=str(
            payload[
                "local_archive_compressed_sha256"
            ]
        ),
        local_archive_uncompressed_sha256=str(
            payload[
                "local_archive_uncompressed_sha256"
            ]
        ),
        bucket=str(payload["bucket"]),
        endpoint_url=str(
            payload["endpoint_url"]
        ),
        region=str(payload["region"]),
        prefix=str(payload["prefix"]),
        retention_days=int(
            payload["retention_days"]
        ),
        archive_object=object_evidence(
            "archive_object"
        ),
        manifest_object=object_evidence(
            "manifest_object"
        ),
        receipt_object=object_evidence(
            "receipt_object"
        ),
        remote_restore_compressed_sha256=str(
            payload[
                "remote_restore_compressed_sha256"
            ]
        ),
        remote_restore_uncompressed_sha256=str(
            payload[
                "remote_restore_uncompressed_sha256"
            ]
        ),
        pruning_gate_state=str(
            payload["pruning_gate_state"]
        ),
    )


def load_remote_archive_proof(
    path: str | Path,
) -> RemoteArchiveProof:
    proof_path = Path(path).expanduser()
    proof = _proof_from_dict(
        json.loads(
            proof_path.read_text(
                encoding="utf-8"
            )
        )
    )
    if (
        proof.format_version
        != REMOTE_PROOF_FORMAT_VERSION
    ):
        raise RuntimeError(
            "Unsupported Christiania remote archive "
            f"proof format v{proof.format_version}."
        )
    if (
        proof.pruning_gate_state
        != "OFFHOST_IMMUTABLE_RESTORE_VERIFIED"
    ):
        raise RuntimeError(
            "Remote archive proof does not satisfy "
            "the immutable restore gate."
        )
    return proof


def inventory_remote_archive_proofs(
    archive_dir: str | Path | None = None,
) -> RemoteArchiveInventory:
    directory = resolve_archive_dir(
        archive_dir
    )
    if not directory.exists():
        return RemoteArchiveInventory(
            directory=str(directory),
            proof_count=0,
            proofs=(),
            invalid_proofs=(),
        )

    proofs: list[RemoteArchiveProof] = []
    invalid: list[str] = []
    for path in sorted(
        directory.glob(
            "research_evidence_*.remote-proof.json"
        )
    ):
        try:
            proofs.append(
                load_remote_archive_proof(
                    path
                )
            )
        except Exception as exc:
            invalid.append(
                f"{path}:{type(exc).__name__}:{exc}"
            )

    proofs.sort(
        key=lambda item: item.session_date
    )
    return RemoteArchiveInventory(
        directory=str(directory),
        proof_count=len(proofs),
        proofs=tuple(proofs),
        invalid_proofs=tuple(invalid),
    )


def upload_and_verify_remote_archive(
    manifest_path: str | Path,
    *,
    config: RemoteArchiveConfig | None = None,
    client=None,
    now: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> RemoteArchiveProof:
    path = Path(manifest_path).expanduser()
    manifest = verify_research_archive(
        path,
        deep_payload=True,
    )
    archive_path = (
        path.parent
        / manifest.archive_filename
    )
    if not archive_path.is_file():
        raise FileNotFoundError(
            f"Local archive payload missing: {archive_path}"
        )

    proof_path = _proof_path_for(path)
    if proof_path.exists():
        raise FileExistsError(
            "Remote archive proof already exists: "
            f"{proof_path}"
        )

    resolved = (
        resolve_remote_archive_config()
        if config is None
        else config
    )
    s3 = (
        create_s3_client(resolved)
        if client is None
        else client
    )

    check_remote_bucket(
        config=resolved,
        client=s3,
    )

    observed = (
        datetime.now(UTC)
        if now is None
        else now.astimezone(UTC)
    )
    retain_until = (
        observed
        + timedelta(
            days=resolved.retention_days
        )
    ).replace(
        microsecond=0
    )

    archive_key = _archive_object_key(
        resolved,
        manifest,
    )
    manifest_key = _manifest_object_key(
        resolved,
        manifest,
    )
    receipt_key = _receipt_object_key(
        resolved,
        manifest,
    )
    manifest_sha = _manifest_sha256(path)

    base_metadata = {
        "christiania-session-date":
            manifest.session_date,
        "christiania-format-version":
            str(manifest.format_version),
        "christiania-coverage":
            manifest.coverage,
    }

    if progress is not None:
        progress(
            "remote-upload: local archive deep verification passed"
        )

    with archive_path.open("rb") as archive_body:
        archive_object = _put_locked_object(
            s3=s3,
            config=resolved,
            key=archive_key,
            body=archive_body,
            size_bytes=manifest.compressed_size_bytes,
            sha256=manifest.compressed_sha256,
            metadata={
                **base_metadata,
                "christiania-uncompressed-sha256":
                    manifest.uncompressed_sha256,
            },
            retain_until=retain_until,
            content_type="application/gzip",
        )

    with path.open("rb") as manifest_body:
        manifest_object = _put_locked_object(
            s3=s3,
            config=resolved,
            key=manifest_key,
            body=manifest_body,
            size_bytes=path.stat().st_size,
            sha256=manifest_sha,
            metadata=base_metadata,
            retain_until=retain_until,
            content_type="application/json",
        )

    if progress is not None:
        progress(
            "remote-upload: archive and manifest "
            "uploaded with COMPLIANCE retention"
        )

    (
        restore_compressed_sha,
        restore_uncompressed_sha,
    ) = _verify_remote_restore(
        s3=s3,
        config=resolved,
        manifest=manifest,
        archive_object=archive_object,
        manifest_object=manifest_object,
        local_manifest_path=path,
        progress=progress,
    )

    verified_at = _utc_iso(
        datetime.now(UTC)
    )
    receipt_payload = {
        "format_version":
            REMOTE_PROOF_FORMAT_VERSION,
        "verified_at":
            verified_at,
        "session_date":
            manifest.session_date,
        "archive_filename":
            manifest.archive_filename,
        "manifest_filename":
            manifest.manifest_filename,
        "manifest_sha256":
            manifest_sha,
        "archive_object_key":
            archive_object.key,
        "archive_object_version_id":
            archive_object.version_id,
        "manifest_object_key":
            manifest_object.key,
        "manifest_object_version_id":
            manifest_object.version_id,
        "compressed_sha256":
            restore_compressed_sha,
        "uncompressed_sha256":
            restore_uncompressed_sha,
        "retention_mode":
            "COMPLIANCE",
        "retain_until":
            _utc_iso(retain_until),
        "result":
            "OFFHOST_IMMUTABLE_RESTORE_VERIFIED",
    }
    receipt_bytes = (
        json.dumps(
            receipt_payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    receipt_sha = _sha256_bytes(
        receipt_bytes
    )

    receipt_object = _put_locked_object(
        s3=s3,
        config=resolved,
        key=receipt_key,
        body=io.BytesIO(
            receipt_bytes
        ),
        size_bytes=len(receipt_bytes),
        sha256=receipt_sha,
        metadata=base_metadata,
        retain_until=retain_until,
        content_type="application/json",
    )

    proof = RemoteArchiveProof(
        format_version=REMOTE_PROOF_FORMAT_VERSION,
        verified_at=verified_at,
        session_date=manifest.session_date,
        local_manifest_filename=manifest.manifest_filename,
        local_manifest_sha256=manifest_sha,
        local_archive_filename=manifest.archive_filename,
        local_archive_compressed_sha256=manifest.compressed_sha256,
        local_archive_uncompressed_sha256=manifest.uncompressed_sha256,
        bucket=resolved.bucket,
        endpoint_url=resolved.endpoint_url,
        region=resolved.region,
        prefix=resolved.prefix,
        retention_days=resolved.retention_days,
        archive_object=archive_object,
        manifest_object=manifest_object,
        receipt_object=receipt_object,
        remote_restore_compressed_sha256=restore_compressed_sha,
        remote_restore_uncompressed_sha256=restore_uncompressed_sha,
        pruning_gate_state=(
            "OFFHOST_IMMUTABLE_RESTORE_VERIFIED"
        ),
    )
    _write_json_atomic(
        proof_path,
        proof.as_dict(),
    )

    if progress is not None:
        progress(
            "remote-proof: local proof promoted "
            f"path={proof_path}"
        )

    return proof


def verify_remote_archive_proof(
    proof_path: str | Path,
    *,
    config: RemoteArchiveConfig | None = None,
    client=None,
    progress: Callable[[str], None] | None = None,
) -> RemoteArchiveProof:
    path = Path(proof_path).expanduser()
    proof = load_remote_archive_proof(
        path
    )

    resolved = (
        resolve_remote_archive_config()
        if config is None
        else config
    )
    if (
        proof.bucket != resolved.bucket
        or proof.endpoint_url != resolved.endpoint_url
        or proof.region != resolved.region
    ):
        raise RuntimeError(
            "Remote proof target does not match "
            "current Christiania remote archive configuration."
        )

    local_manifest_path = (
        path.parent
        / proof.local_manifest_filename
    )
    manifest = load_archive_manifest(
        local_manifest_path
    )
    if (
        _manifest_sha256(
            local_manifest_path
        )
        != proof.local_manifest_sha256
    ):
        raise RuntimeError(
            "Local archive manifest changed after "
            "remote verification."
        )

    s3 = (
        create_s3_client(resolved)
        if client is None
        else client
    )
    check_remote_bucket(
        config=resolved,
        client=s3,
    )

    required_until = min(
        _parse_utc(
            proof.archive_object.retain_until
        ),
        _parse_utc(
            proof.manifest_object.retain_until
        ),
        _parse_utc(
            proof.receipt_object.retain_until
        ),
    )

    for item in (
        proof.archive_object,
        proof.manifest_object,
        proof.receipt_object,
    ):
        mode, retain_until = (
            _retention_evidence(
                s3=s3,
                bucket=resolved.bucket,
                key=item.key,
                version_id=item.version_id,
                minimum_retain_until=required_until,
            )
        )
        if mode != item.retention_mode:
            raise RuntimeError(
                "Remote retention mode changed after verification."
            )
        head = _head_object(
            s3=s3,
            bucket=resolved.bucket,
            key=item.key,
            version_id=item.version_id,
        )
        if int(
            head.get(
                "ContentLength"
            ) or 0
        ) != item.size_bytes:
            raise RuntimeError(
                "Remote object size changed after verification: "
                f"{item.key}"
            )

    (
        compressed_sha,
        uncompressed_sha,
    ) = _verify_remote_restore(
        s3=s3,
        config=resolved,
        manifest=manifest,
        archive_object=proof.archive_object,
        manifest_object=proof.manifest_object,
        local_manifest_path=local_manifest_path,
        progress=progress,
    )
    if (
        compressed_sha
        != proof.remote_restore_compressed_sha256
        or uncompressed_sha
        != proof.remote_restore_uncompressed_sha256
    ):
        raise RuntimeError(
            "Remote restore hashes differ from "
            "the immutable proof."
        )

    receipt_payload = _download_object_bytes(
        s3=s3,
        bucket=resolved.bucket,
        key=proof.receipt_object.key,
        version_id=proof.receipt_object.version_id,
    )
    if (
        _sha256_bytes(
            receipt_payload
        )
        != proof.receipt_object.sha256
    ):
        raise RuntimeError(
            "Remote verification receipt SHA-256 mismatch."
        )

    receipt = json.loads(
        receipt_payload.decode("utf-8")
    )
    expected_receipt = {
        "session_date": proof.session_date,
        "archive_filename":
            proof.local_archive_filename,
        "manifest_filename":
            proof.local_manifest_filename,
        "archive_object_key":
            proof.archive_object.key,
        "archive_object_version_id":
            proof.archive_object.version_id,
        "manifest_object_key":
            proof.manifest_object.key,
        "manifest_object_version_id":
            proof.manifest_object.version_id,
        "compressed_sha256":
            proof.remote_restore_compressed_sha256,
        "uncompressed_sha256":
            proof.remote_restore_uncompressed_sha256,
        "result":
            "OFFHOST_IMMUTABLE_RESTORE_VERIFIED",
    }
    for key, expected in expected_receipt.items():
        if receipt.get(key) != expected:
            raise RuntimeError(
                "Remote verification receipt semantic "
                f"mismatch for {key}."
            )

    if progress is not None:
        progress(
            "remote-proof: immutable object retention "
            "and remote restore verification passed"
        )

    return proof

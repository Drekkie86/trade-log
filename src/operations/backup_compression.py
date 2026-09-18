from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_runtime_setting
from src.database.repository import EXPECTED_SCHEMA_VERSION


BACKUP_PREFIX = "christiania_backup_"
PLAIN_SUFFIX = ".db"
COMPRESSED_SUFFIX = ".db.gz"
MANIFEST_SUFFIX = ".manifest.json"
DEFAULT_GZIP_LEVEL = 1
DEFAULT_MIN_FREE_BYTES = 15 * 1024**3
DEFAULT_MIN_FREE_FRACTION = 0.15
CHUNK_SIZE = 8 * 1024**2


@dataclass(frozen=True)
class CompressedBackupManifest:
    format_version: int
    created_at: str
    backup_filename: str
    source_filename: str
    schema_version: int
    integrity_check: str
    foreign_key_violation_count: int
    source_size_bytes: int
    compressed_size_bytes: int
    source_sha256: str
    compressed_sha256: str
    compression: str
    compression_level: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CompressionResult:
    source_path: str
    compressed_path: str
    manifest_path: str
    source_size_bytes: int
    compressed_size_bytes: int
    reclaimed_bytes: int
    schema_version: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CompressionMaintenanceResult:
    compressed_count: int
    reclaimed_bytes: int
    compressed_paths: tuple[str, ...]
    skipped_paths: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["compressed_paths"] = list(self.compressed_paths)
        data["skipped_paths"] = list(self.skipped_paths)
        return data


def _runtime_nonnegative_int(name: str, default: int) -> int:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def _runtime_nonnegative_float(name: str, default: float) -> float:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def gzip_level() -> int:
    raw = get_runtime_setting("CHRISTIANIA_BACKUP_GZIP_LEVEL")
    value = DEFAULT_GZIP_LEVEL if raw in (None, "") else int(raw)
    if value < 0 or value > 9:
        raise ValueError("CHRISTIANIA_BACKUP_GZIP_LEVEL must be between 0 and 9.")
    return value


def backup_data_files(directory: Path) -> list[Path]:
    candidates = []
    for path in directory.iterdir() if directory.exists() else ():
        name = path.name
        if (
            path.is_file()
            and name.startswith(BACKUP_PREFIX)
            and (
                name.endswith(COMPRESSED_SUFFIX)
                or name.endswith(PLAIN_SUFFIX)
            )
        ):
            candidates.append(path)
    return candidates


def manifest_path_for(compressed_path: Path) -> Path:
    return compressed_path.with_name(
        compressed_path.name + MANIFEST_SUFFIX
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


def _sha256_gzip_payload(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verify_plain_sqlite(path: Path) -> tuple[int, str, int]:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version;"
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("Backup contains no schema version.")
        version = int(row[0])
        integrity = str(
            conn.execute("PRAGMA integrity_check;").fetchone()[0]
        )
        fk_count = len(
            conn.execute("PRAGMA foreign_key_check;").fetchall()
        )
    finally:
        conn.close()

    if version != EXPECTED_SCHEMA_VERSION:
        raise RuntimeError(
            f"Backup schema v{version} does not match expected "
            f"v{EXPECTED_SCHEMA_VERSION}."
        )
    if integrity != "ok":
        raise RuntimeError(
            f"Backup integrity_check failed: {integrity}"
        )
    if fk_count:
        raise RuntimeError(
            f"Backup foreign_key_check returned {fk_count} violation(s)."
        )
    return version, integrity, fk_count


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_manifest_atomic(
    path: Path,
    manifest: CompressedBackupManifest,
) -> None:
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )
    payload = (
        json.dumps(
            manifest.as_dict(),
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
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def load_compressed_manifest(
    compressed_path: Path,
) -> CompressedBackupManifest:
    manifest_path = manifest_path_for(compressed_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Compressed backup manifest missing: {manifest_path}"
        )
    data = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    return CompressedBackupManifest(**data)


def verify_compressed_backup(
    compressed_path: str | Path,
    *,
    deep_payload: bool = True,
) -> CompressedBackupManifest:
    path = Path(compressed_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(
            f"Compressed backup not found: {path}"
        )
    if not path.name.endswith(COMPRESSED_SUFFIX):
        raise ValueError(
            f"Not a Christiania compressed backup: {path}"
        )

    manifest = load_compressed_manifest(path)

    if manifest.format_version != 1:
        raise RuntimeError(
            f"Unsupported compressed backup format v{manifest.format_version}."
        )
    if manifest.backup_filename != path.name:
        raise RuntimeError(
            "Compressed backup manifest filename mismatch."
        )
    if manifest.schema_version != EXPECTED_SCHEMA_VERSION:
        raise RuntimeError(
            f"Compressed backup schema v{manifest.schema_version} does not "
            f"match expected v{EXPECTED_SCHEMA_VERSION}."
        )
    if manifest.integrity_check != "ok":
        raise RuntimeError(
            "Compressed backup manifest does not record a clean integrity check."
        )
    if manifest.foreign_key_violation_count != 0:
        raise RuntimeError(
            "Compressed backup manifest records foreign-key violations."
        )
    if path.stat().st_size != manifest.compressed_size_bytes:
        raise RuntimeError(
            "Compressed backup size does not match manifest."
        )

    compressed_sha = _sha256_file(path)
    if compressed_sha != manifest.compressed_sha256:
        raise RuntimeError(
            "Compressed backup SHA-256 does not match manifest."
        )

    if deep_payload:
        source_sha = _sha256_gzip_payload(path)
        if source_sha != manifest.source_sha256:
            raise RuntimeError(
                "Decompressed backup SHA-256 does not match verified source hash."
            )

    return manifest


def _required_free_bytes(
    *,
    candidate_size: int,
    filesystem_total: int,
) -> int:
    reserve_bytes = _runtime_nonnegative_int(
        "CHRISTIANIA_RC0_MIN_FREE_BYTES",
        DEFAULT_MIN_FREE_BYTES,
    )
    reserve_fraction = _runtime_nonnegative_float(
        "CHRISTIANIA_RC0_MIN_FREE_FRACTION",
        DEFAULT_MIN_FREE_FRACTION,
    )
    reserve = max(
        reserve_bytes,
        int(filesystem_total * reserve_fraction),
    )
    # Gzip can be slightly larger for incompressible input, so budget the
    # entire source size plus a small framing margin before starting.
    margin = max(1024**2, int(candidate_size * 0.01))
    return reserve + candidate_size + margin


def compress_verified_backup(
    source_path: str | Path,
) -> CompressionResult:
    source = Path(source_path).expanduser()

    if not source.is_file():
        raise FileNotFoundError(
            f"Backup not found: {source}"
        )
    if not source.name.startswith(BACKUP_PREFIX):
        raise ValueError(
            f"Not a Christiania backup: {source}"
        )
    if not source.name.endswith(PLAIN_SUFFIX):
        raise ValueError(
            f"Backup is not an uncompressed .db file: {source}"
        )

    version, integrity, fk_count = _verify_plain_sqlite(source)

    usage = shutil.disk_usage(source.parent)
    required = _required_free_bytes(
        candidate_size=source.stat().st_size,
        filesystem_total=int(usage.total),
    )
    if int(usage.free) < required:
        raise RuntimeError(
            "Insufficient headroom to compress backup safely: "
            f"free={int(usage.free)} bytes, required={required} bytes. "
            "Original verified backup was left untouched."
        )

    final = source.with_name(source.name + ".gz")
    manifest_path = manifest_path_for(final)
    temp = final.with_name(
        f".{final.name}.{os.getpid()}.tmp"
    )

    if final.exists() or manifest_path.exists() or temp.exists():
        raise FileExistsError(
            f"Compressed backup target already exists for {source.name}."
        )

    source_stat = source.stat()
    source_size = source_stat.st_size
    source_atime_ns = source_stat.st_atime_ns
    source_mtime_ns = source_stat.st_mtime_ns
    source_sha = _sha256_file(source)
    level = gzip_level()

    try:
        with source.open("rb") as src:
            with temp.open("wb") as raw:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    compresslevel=level,
                    fileobj=raw,
                    mtime=0,
                ) as gz:
                    shutil.copyfileobj(
                        src,
                        gz,
                        length=CHUNK_SIZE,
                    )
                raw.flush()
                os.fsync(raw.fileno())

        payload_sha = _sha256_gzip_payload(temp)
        if payload_sha != source_sha:
            raise RuntimeError(
                "Compressed backup round-trip hash mismatch; "
                "original backup was left untouched."
            )

        compressed_sha = _sha256_file(temp)
        compressed_size = temp.stat().st_size

        manifest = CompressedBackupManifest(
            format_version=1,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            backup_filename=final.name,
            source_filename=source.name,
            schema_version=version,
            integrity_check=integrity,
            foreign_key_violation_count=fk_count,
            source_size_bytes=source_size,
            compressed_size_bytes=compressed_size,
            source_sha256=source_sha,
            compressed_sha256=compressed_sha,
            compression="gzip",
            compression_level=level,
        )

        os.replace(temp, final)
        os.utime(
            final,
            ns=(
                source_atime_ns,
                source_mtime_ns,
            ),
        )
        _fsync_directory(source.parent)

        _write_manifest_atomic(
            manifest_path,
            manifest,
        )

        # Re-read both the compressed bytes and their payload before deleting
        # the only uncompressed copy.
        verify_compressed_backup(
            final,
            deep_payload=True,
        )

        source.unlink()
        _fsync_directory(source.parent)

        reclaimed = max(
            0,
            source_size - compressed_size,
        )

        return CompressionResult(
            source_path=str(source),
            compressed_path=str(final),
            manifest_path=str(manifest_path),
            source_size_bytes=source_size,
            compressed_size_bytes=compressed_size,
            reclaimed_bytes=reclaimed,
            schema_version=version,
        )

    except BaseException:
        if temp.exists():
            temp.unlink()
        # If the final compressed file exists but verification/manifest writing
        # failed, keep the original .db and remove the incomplete replacement.
        if source.exists():
            if final.exists():
                final.unlink()
            if manifest_path.exists():
                manifest_path.unlink()
        raise


def maintain_compressed_backups(
    backup_dir: str | Path,
    *,
    keep_latest_uncompressed: int = 1,
) -> CompressionMaintenanceResult:
    directory = Path(backup_dir).expanduser()
    if keep_latest_uncompressed < 1:
        raise ValueError(
            "keep_latest_uncompressed must be >= 1."
        )
    if not directory.exists():
        return CompressionMaintenanceResult(
            compressed_count=0,
            reclaimed_bytes=0,
            compressed_paths=(),
            skipped_paths=(),
        )

    files = sorted(
        backup_data_files(directory),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )

    protected_plain: set[Path] = set()
    for path in files:
        if path.name.endswith(PLAIN_SUFFIX):
            protected_plain.add(path)
            if len(protected_plain) >= keep_latest_uncompressed:
                break

    compressed: list[str] = []
    skipped: list[str] = []
    reclaimed = 0

    for path in files:
        if not path.name.endswith(PLAIN_SUFFIX):
            continue
        if path in protected_plain:
            skipped.append(str(path))
            continue

        result = compress_verified_backup(path)
        compressed.append(result.compressed_path)
        reclaimed += result.reclaimed_bytes

    return CompressionMaintenanceResult(
        compressed_count=len(compressed),
        reclaimed_bytes=reclaimed,
        compressed_paths=tuple(compressed),
        skipped_paths=tuple(skipped),
    )


def restore_compressed_backup_to(
    compressed_path: str | Path,
    target_path: str | Path,
) -> CompressedBackupManifest:
    source = Path(compressed_path).expanduser()
    target = Path(target_path).expanduser()

    manifest = verify_compressed_backup(
        source,
        deep_payload=True,
    )

    if target.exists():
        raise FileExistsError(
            f"Restore target already exists: {target}"
        )

    with gzip.open(source, "rb") as src:
        with target.open("wb") as dst:
            shutil.copyfileobj(
                src,
                dst,
                length=CHUNK_SIZE,
            )
            dst.flush()
            os.fsync(dst.fileno())

    try:
        version, integrity, fk_count = _verify_plain_sqlite(target)
        if version != manifest.schema_version:
            raise RuntimeError(
                "Restored compressed backup schema mismatch."
            )
        if integrity != manifest.integrity_check or fk_count != 0:
            raise RuntimeError(
                "Restored compressed backup failed verification."
            )
    except BaseException:
        if target.exists():
            target.unlink()
        raise

    return manifest

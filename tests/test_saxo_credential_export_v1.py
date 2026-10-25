"""Safe, manual Saxo credential export — no secrets outside owner file."""
import os
from datetime import UTC, datetime, timedelta

import pytest

from src.operations.saxo_credential_export_v1 import (
    FIELDS, export_saxo_credentials,
)
from src.config import read_env_file


def source(tmp_path, *, expires_in_minutes=60):
    path = tmp_path / "dev-only.env"
    parts = [f"{key}=test-secret-{key}" for key in FIELDS]
    expiry = datetime.now(UTC) + timedelta(minutes=expires_in_minutes)
    parts = [
        f"SAXO_LIVE_REFRESH_EXPIRES_AT={expiry.isoformat()}"
        if item.startswith("SAXO_LIVE_REFRESH_EXPIRES_AT=") else item
        for item in parts
    ]
    parts.append("UNRELATED_API_PASSWORD=MUST_NOT_EXPORT")
    path.write_text("\n".join(parts) + "\n", encoding="utf8")
    return path


def test_only_required_saxo_keys_written_private(tmp_path, capsys):
    src = source(tmp_path)
    out = tmp_path / "saxo-transfer.env"
    assert export_saxo_credentials(out, source=src) == out
    data = read_env_file(out)
    assert set(data) == set(FIELDS)
    assert "UNRELATED" not in out.read_text()
    assert "test-secret" not in capsys.readouterr().out
    if os.name != "nt":
        assert os.stat(out).st_mode & 0o077 == 0


def test_refuses_stale_auth_and_existing_target(tmp_path):
    src = source(tmp_path, expires_in_minutes=-1)
    out = tmp_path / "export.env"
    with pytest.raises(ValueError, match="expired"):
        export_saxo_credentials(out, source=src)
    assert not out.exists()
    fresh = source(tmp_path)
    out.write_text("do not destroy")
    with pytest.raises(FileExistsError):
        export_saxo_credentials(out, source=fresh)
    assert out.read_text() == "do not destroy"


def test_export_does_not_accept_relative_file_path(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        export_saxo_credentials("secret-transfer.env", source=source(tmp_path))

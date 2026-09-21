from __future__ import annotations

from pathlib import Path

import christiania_ops


def test_operator_cli_loads_deployment_env_when_present(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / "christiania.env"
    env_file.write_text(
        "CHRISTIANIA_DB_PATH=/var/lib/christiania/data/trade_log.db\n",
        encoding="utf-8",
    )

    calls = []

    monkeypatch.setattr(
        christiania_ops,
        "DEPLOYMENT_ENV_FILE",
        env_file,
    )
    monkeypatch.setattr(
        christiania_ops,
        "load_runtime_env_file",
        lambda path, overwrite=False: calls.append(
            (Path(path), overwrite)
        ),
    )

    christiania_ops._load_deployment_env_if_present()

    assert calls == [(env_file, False)]


def test_operator_cli_does_not_require_deployment_env_locally(
    monkeypatch,
    tmp_path,
):
    missing = tmp_path / "missing.env"
    calls = []

    monkeypatch.setattr(
        christiania_ops,
        "DEPLOYMENT_ENV_FILE",
        missing,
    )
    monkeypatch.setattr(
        christiania_ops,
        "load_runtime_env_file",
        lambda path, overwrite=False: calls.append(
            (Path(path), overwrite)
        ),
    )

    christiania_ops._load_deployment_env_if_present()

    assert calls == []

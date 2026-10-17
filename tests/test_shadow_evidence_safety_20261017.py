"""Regression tests for evidence rendering and failure isolation."""
from __future__ import annotations

import ast
from pathlib import Path


def test_html_rows_escape_provider_originated_values():
    """Do not place untrusted provider/DB text into unsafe HTML."""
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app.py").read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_html_rows"
    )
    isolated = ast.Module(body=[function], type_ignores=[])
    scope = {"status_dot": lambda state: ""}
    exec(compile(ast.fix_missing_locations(isolated), "<isolated_html_rows>", "exec"), scope)
    result = scope["_html_rows"]([("<script>alert(1)</script>", "<img src=x onerror=alert(2)>", None)])
    assert "<script>" not in result and "<img " not in result
    assert "&lt;script&gt;" in result and "&lt;img" in result
    assert "&quot;" not in result


def test_atomic_local_settings_preserve_comments_and_permissions(tmp_path, monkeypatch):
    import os
    from src import config

    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nEXISTING=keep\nSAXO_REFRESH_TOKEN=old\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    config.set_local_settings({"SAXO_REFRESH_TOKEN": "new", "OTHER": "value"})
    assert env_file.read_text(encoding="utf-8") == (
        "# comment\nEXISTING=keep\nSAXO_REFRESH_TOKEN=new\nOTHER=value\n"
    )
    assert not list(tmp_path.glob(".christiania_env_*"))
    assert (tmp_path / ".env.lock").is_file()
    if os.name != "nt":
        assert env_file.stat().st_mode & 0o077 == 0


def test_atomic_local_settings_serializes_concurrent_updates(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from src import config

    env_file = tmp_path / ".env"
    env_file.write_text("KEEP=unchanged\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(
            lambda entry: config.set_local_settings(entry),
            ({"TOKEN_A": "a"}, {"TOKEN_B": "b"}),
        ))
    text = env_file.read_text(encoding="utf-8")
    assert "KEEP=unchanged" in text
    assert "TOKEN_A=a" in text and "TOKEN_B=b" in text

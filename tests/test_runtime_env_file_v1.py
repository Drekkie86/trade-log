from pathlib import Path

from src.config import load_runtime_env_file, read_env_file


def test_runtime_env_file_parser_does_not_execute_shell_syntax(tmp_path, monkeypatch):
    marker = tmp_path / "SHOULD_NOT_EXIST"
    env = tmp_path / "runtime.env"
    env.write_text(
        "SAFE=value\n"
        f"DANGEROUS=$(touch {marker})\n"
        "QUOTED='literal value'\n",
        encoding="utf-8",
    )
    parsed = read_env_file(env)
    assert parsed["SAFE"] == "value"
    assert parsed["DANGEROUS"].startswith("$(touch ")
    assert parsed["QUOTED"] == "literal value"
    assert not marker.exists()


def test_runtime_env_file_does_not_overwrite_explicit_environment_by_default(tmp_path, monkeypatch):
    env = tmp_path / "runtime.env"
    env.write_text("VALUE=file\nOTHER=loaded\n", encoding="utf-8")
    monkeypatch.setenv("VALUE", "process")
    loaded = load_runtime_env_file(env)
    assert loaded["VALUE"] == "file"
    import os
    assert os.environ["VALUE"] == "process"
    assert os.environ["OTHER"] == "loaded"

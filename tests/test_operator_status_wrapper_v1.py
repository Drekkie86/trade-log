from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_status_wrapper_checks_release_paths_as_service_account():
    script = (ROOT / "deploy/christiania-status").read_text(encoding="utf-8")

    assert 'sudo -u "${SERVICE_USER}" test -x "${APP_DIR}/.venv/bin/python"' in script
    assert 'sudo -u "${SERVICE_USER}" test -f "${APP_DIR}/christiania_status.py"' in script
    assert 'if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]' not in script
    assert 'if [[ ! -f "${APP_DIR}/christiania_status.py" ]]' not in script

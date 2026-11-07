import sys

import pytest

import run_shadow_admission


def test_manual_shadow_admission_requires_explicit_proposal_id(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_shadow_admission.py"],
    )

    with pytest.raises(SystemExit) as exc_info:
        run_shadow_admission.main()

    assert exc_info.value.code == 2

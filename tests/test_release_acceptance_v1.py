from __future__ import annotations

from src.operations.release_acceptance import assess_release_candidate


def assess(**overrides):
    values = dict(
        product_ready=True,
        runtime_ready=True,
        secure_edge_ready=True,
        restore_drill_passed=True,
        release_manifest_clean=True,
        burn_in_state="PASSED",
        reboot_proven=True,
        theta_timestamp_confidence="DOCUMENTED_AND_LIVE_VALIDATED",
    )
    values.update(overrides)
    return assess_release_candidate(**values)


def test_rc_gate_passes_only_when_every_blocking_gate_is_green():
    result = assess()
    assert result.release_candidate_ready is True
    assert result.state == "V1_RC_READY"


def test_rc_gate_blocks_on_pending_burn_in():
    result = assess(burn_in_state="ACCUMULATING")
    assert result.release_candidate_ready is False
    assert any(c.name == "burn-in" and c.state == "FAIL" for c in result.checks)


def test_rc_gate_blocks_on_missing_real_reboot_proof():
    assert assess(reboot_proven=False).release_candidate_ready is False


def test_rc_gate_blocks_on_timestamp_contract_not_live_validated():
    result = assess(theta_timestamp_confidence="DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED")
    assert result.release_candidate_ready is False


def test_explicit_development_waivers_are_nonblocking_but_not_silent():
    result = assess_release_candidate(
        product_ready=True,
        runtime_ready=True,
        secure_edge_ready=True,
        restore_drill_passed=True,
        release_manifest_clean=True,
        burn_in_state="ACCUMULATING",
        reboot_proven=False,
        theta_timestamp_confidence="DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED",
        require_burn_in=False,
        require_reboot=False,
        require_live_timestamp_validation=False,
    )
    assert result.release_candidate_ready is True
    assert sum(c.state == "INFO" for c in result.checks) == 3

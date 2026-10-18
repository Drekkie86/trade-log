from __future__ import annotations
import pytest
from src.operations.deployment_transition_gate import validate_transition

BASE_STATUS = dict(
    release_identity_state="PASS", core_services_state="PASS",
    supervisor_freshness_state="PASS", resource_policy_state="PASS",
    research_progress_state="PASS", public_edge_expected=True,
    public_edge_state="PASS", supervisor_state="UNHEALTHY",
    deployment_supervisor_state="FAIL",
)
TIMER_STATES = {
    "christiania-volume-recovery-backup.timer": ("enabled", "active"),
    "christiania-volume-recovery-audit.timer": ("enabled", "active"),
}
TRANSITION = [
    dict(name="timer:christiania-backup.timer", state="FAIL", blocking=True,
         detail="christiania-backup.timer is disabled; expected enabled."),
    dict(name="timer:christiania-restore-drill.timer", state="FAIL", blocking=True,
         detail="christiania-restore-drill.timer is disabled; expected enabled."),
    dict(name="backup-recovery-point", state="FAIL", blocking=True,
         detail="Recovery point due=True; reason=LATEST_BACKUP_SCHEMA_MISMATCH; age_hours=3."),
]

def run(*, status=None, checks=None, timers=None, backup=True):
    return validate_transition(
        status=BASE_STATUS if status is None else status,
        supervisor={"checks": TRANSITION if checks is None else checks},
        volume_timer_states=TIMER_STATES if timers is None else timers,
        recovered_backup=backup,
    )

def test_documented_backup_transition_is_accepted():
    assert run() is None

@pytest.mark.parametrize("field", [
    "release_identity_state", "core_services_state", "supervisor_freshness_state",
    "resource_policy_state", "research_progress_state", "public_edge_state",
])
def test_other_core_failures_are_not_waived(field):
    with pytest.raises(RuntimeError):
        run(status={**BASE_STATUS, field: "FAIL"})

def test_no_restore_point_is_never_accepted():
    with pytest.raises(RuntimeError, match="RECOVERY"):
        run(backup=False)

def test_both_volume_timers_are_mandatory():
    for t in TIMER_STATES:
        broken = {**TIMER_STATES, t: ("disabled", "inactive")}
        with pytest.raises(RuntimeError, match="NEW_TIMER_NOT_READY"):
            run(timers=broken)

def test_unrelated_supervisor_failure_blocks_deployment():
    with pytest.raises(RuntimeError, match="UNRECOGNISED_BLOCKER"):
        run(checks=TRANSITION + [dict(name="core-service", state="FAIL", blocking=True, detail="inactive")])

def test_bad_backup_status_does_not_bypass_verification():
    with pytest.raises(RuntimeError, match="UNRECOGNISED_BLOCKER"):
        run(checks=TRANSITION[:2] + [dict(name="backup-recovery-point", state="FAIL", blocking=True, detail="unverified backup")])

def test_mismatched_timer_detail_fails_closed():
    with pytest.raises(RuntimeError, match="UNRECOGNISED_BLOCKER"):
        run(checks=[dict(name="timer:christiania-backup.timer", state="FAIL",
                         blocking=True, detail="missing unit")])

def test_failed_supervisor_without_retired_timers_still_blocks():
    with pytest.raises(RuntimeError, match="WITHOUT_RETIRED_TIMERS"):
        run(checks=[dict(name="backup-recovery-point", state="FAIL", blocking=True,
                         detail="reason=LATEST_BACKUP_SCHEMA_MISMATCH")])

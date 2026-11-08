"""Only a real, independently verified source receipt can claim a live clock probe."""
import pytest

from src.database.repository import get_connection
from src.research.thetadata_timestamp_semantics_v1 import validate_thetadata_timestamp_semantics_v1


@pytest.mark.parametrize("claim", ["PASSED", "FAILED", "NOT_KNOWN", "", None])
def test_documentation_only_validator_rejects_claimed_live_state(db_path, claim):
    with pytest.raises(ValueError, match="LIVE_THETA_TIMESTAMP_PROBE_MUST_BE_INDEPENDENTLY_VERIFIED"):
        validate_thetadata_timestamp_semantics_v1(db_path=db_path, live_probe_state=claim)
    c = get_connection(db_path)
    try:
        assert c.execute("SELECT COUNT(*) FROM thetadata_timestamp_semantics_v1_runs").fetchone()[0] == 0
    finally:
        c.close()


def test_documentation_only_validator_is_ineligible_for_decisions(db_path):
    value=validate_thetadata_timestamp_semantics_v1(db_path=db_path)
    assert value["confidence_state"] == "DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED"
    c=get_connection(db_path)
    try:
        record=c.execute("SELECT live_probe_state,confidence_state,decision_enabled FROM thetadata_timestamp_semantics_v1_runs WHERE id=?",(value["run_id"],)).fetchone()
        assert record["live_probe_state"] == "NOT_RUN"
        assert record["decision_enabled"] == 0
    finally:
        c.close()

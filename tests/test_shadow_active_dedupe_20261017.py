"""Admit one active shadow candidate per identical contract and structure."""
from src.database.repository import get_connection
from src.research.shadow_admission import admit_shadow_proposals
from tests._shadow_admission_seed import fx
from tests.test_trade_ideas import seed_scenario


def test_duplicate_anomaly_is_blocked_without_repeated_pinning(db_path):
    slot1 = seed_scenario(db_path, with_v2=True)
    slot2 = seed_scenario(db_path, with_v2=True)

    first = admit_shadow_proposals(
        fx=fx(), proposal_ids=[slot1["proposal_id"]], db_path=db_path
    )
    second = admit_shadow_proposals(
        fx=fx(), proposal_ids=[slot2["proposal_id"]], db_path=db_path
    )

    assert first.admitted_count == 1
    assert second.blocked_count == 1
    assert second.decisions[0].reason_code == "DUPLICATE_ACTIVE_SHADOW_BET"
    assert second.decisions[0].candidate_id is None

    conn = get_connection(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM shadow_candidates").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM underlying_pin_events").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM shadow_intrinsic_admission_decisions_v1"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_dedupe_decision_is_idempotent_for_original_proposal(db_path):
    original = seed_scenario(db_path, with_v2=True)
    first = admit_shadow_proposals(
        fx=fx(), proposal_ids=[original["proposal_id"]], db_path=db_path
    )
    again = admit_shadow_proposals(
        fx=fx(), proposal_ids=[original["proposal_id"]], db_path=db_path
    )
    assert first.decisions[0].candidate_id == again.decisions[0].candidate_id
    assert again.decisions[0].decision == "ADMITTED"

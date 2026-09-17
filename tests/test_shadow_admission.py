import json

from src.database.repository import get_connection
from src.research.shadow_admission import (
    _load_proposals,
    admit_shadow_proposals,
)
from tests._shadow_admission_seed import fx, seed_proposal


def test_defined_risk_above_500_eur_is_not_blocked_by_wallet_size(db_path):
    seeded = seed_proposal(db_path, max_loss_usd_minor=70_000)

    result = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[seeded["proposal_id"]],
        db_path=db_path,
    )

    assert result.admitted_count == 1
    assert result.blocked_count == 0
    decision = result.decisions[0]
    assert decision.decision == "ADMITTED"
    assert decision.reason_code == "SHADOW_RESEARCH_ADMITTED_INTRINSIC_RISK_VALID"
    assert decision.intrinsic_risk_eur_minor > 50_000
    assert decision.candidate_id is not None

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM shadow_intrinsic_admission_decisions_v1
            WHERE proposal_id = ?;
            """,
            (seeded["proposal_id"],),
        ).fetchone()
        evidence = json.loads(row["evidence_json"])
        normalized = conn.execute(
            """
            SELECT bankroll_cap_eur_minor, decision_source
            FROM v_shadow_admission_decisions_all
            WHERE candidate_id = ?;
            """,
            (decision.candidate_id,),
        ).fetchone()
    finally:
        conn.close()

    assert "bankroll" not in evidence
    assert evidence["intrinsic_risk"]["account_balance_dependency"] is False
    assert evidence["intrinsic_risk"]["account_capacity_gate"] is False
    assert evidence["intrinsic_risk"]["probability_model"] is None
    assert evidence["intrinsic_risk"]["expected_value"] is None
    assert normalized["bankroll_cap_eur_minor"] is None
    assert normalized["decision_source"] == "INTRINSIC_RISK_POLICY_V1"


def test_aggregate_intrinsic_risk_does_not_create_portfolio_capacity_gate(db_path):
    first = seed_proposal(db_path, max_loss_usd_minor=40_000)
    second = seed_proposal(db_path, max_loss_usd_minor=40_000)
    third = seed_proposal(db_path, max_loss_usd_minor=40_000)

    result = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[
            first["proposal_id"],
            second["proposal_id"],
            third["proposal_id"],
        ],
        db_path=db_path,
    )

    assert result.admitted_count == 3
    assert result.blocked_count == 0
    assert all(item.decision == "ADMITTED" for item in result.decisions)
    assert sum(item.intrinsic_risk_eur_minor for item in result.decisions) > 50_000


def test_intrinsic_admission_remains_idempotent(db_path):
    seeded = seed_proposal(db_path, max_loss_usd_minor=20_000)

    first = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[seeded["proposal_id"]],
        db_path=db_path,
    )
    second = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[seeded["proposal_id"]],
        db_path=db_path,
    )

    assert first.decisions[0].candidate_id == second.decisions[0].candidate_id

    conn = get_connection(db_path)
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM shadow_intrinsic_admission_decisions_v1
            WHERE proposal_id = ?;
            """,
            (seeded["proposal_id"],),
        ).fetchone()[0]
        candidates = conn.execute(
            "SELECT COUNT(*) FROM shadow_candidates;"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 1
    assert candidates == 1


def test_requested_proposal_filter_scales_beyond_sqlite_parameter_limit(db_path):
    seeded = seed_proposal(db_path)
    proposal_id = seeded["proposal_id"]
    requested = [proposal_id] + list(range(100_000, 102_000))

    rows = _load_proposals(
        proposal_ids=requested,
        db_path=db_path,
    )

    assert [int(row["id"]) for row in rows] == [proposal_id]


def test_data_quality_still_blocks_admission_without_wallet_gate(db_path):
    seeded = seed_proposal(db_path)

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE provider_observation_availability
                SET state = 'MISSING'
                WHERE id = ?;
                """,
                (seeded["quote_evidence_id"],),
            )
    finally:
        conn.close()

    result = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[seeded["proposal_id"]],
        db_path=db_path,
    )

    assert result.admitted_count == 0
    assert result.blocked_count == 1
    assert result.decisions[0].reason_code == "ENTRY_QUOTE_NOT_PRESENT"
    assert result.decisions[0].candidate_id is None

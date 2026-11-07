from __future__ import annotations

import json
import sqlite3

import pytest

from src.database.repository import get_connection
from src.research.historical_replay_recovery_v1 import (
    LEGACY_POLICY_VERSION,
    NO_LOOKAHEAD_CONTRACT,
    REPLAY_VERSION,
    run_historical_replay_recovery_v1,
    theoretical_expiry_value_usd_minor,
)
from tests._shadow_admission_seed import seed_proposal


COST_MODEL_VERSION = "SAXO_BE_SHADOW_COST_CEILING_V1"
COST_PROVENANCE = "ASSUMED_PUBLIC_TARIFF_PLUS_CONTINGENCY"


def _clone_with_entry_pricing(conn, proposal_id: int, *, entry_price: float) -> int:
    source = conn.execute(
        "SELECT * FROM shadow_structure_proposals WHERE id = ?;",
        (proposal_id,),
    ).fetchone()
    structure = json.loads(source["structure_json"])
    quote_id = int(structure["legs"][0]["option_quote_id"])
    pricing = json.dumps(
        {
            "legs": [
                {
                    "option_quote_id": quote_id,
                    "entry_price": entry_price,
                }
            ]
        },
        sort_keys=True,
    )
    cursor = conn.execute(
        """
        INSERT INTO shadow_structure_proposals(
            hypothesis_evaluation_id,
            research_run_id,
            target_reference_contract_id,
            underlying,
            expiration,
            right,
            target_strike,
            builder_family_id,
            builder_version,
            builder_rule_version,
            anomaly_direction,
            proposal_state,
            reason_code,
            structure_id,
            structure_version,
            structure_json,
            entry_pricing_json,
            risk_currency,
            max_theoretical_loss_minor,
            risk_basis,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            source["hypothesis_evaluation_id"],
            source["research_run_id"],
            source["target_reference_contract_id"],
            source["underlying"],
            source["expiration"],
            source["right"],
            source["target_strike"],
            source["builder_family_id"],
            "REPLAY_TEST_V1",
            source["builder_rule_version"],
            source["anomaly_direction"],
            source["proposal_state"],
            source["reason_code"],
            source["structure_id"],
            source["structure_version"],
            source["structure_json"],
            pricing,
            source["risk_currency"],
            source["max_theoretical_loss_minor"],
            source["risk_basis"],
            "2026-09-01T18:00:07.500Z",
        ),
    )
    return int(cursor.lastrowid)


def _seed_legacy_block(
    db_path,
    *,
    reason_code: str = "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL",
    with_entry_pricing: bool = False,
) -> dict:
    seeded = seed_proposal(db_path, max_loss_usd_minor=60_000)
    conn = get_connection(db_path)
    try:
        proposal_id = int(seeded["proposal_id"])
        if with_entry_pricing:
            proposal_id = _clone_with_entry_pricing(
                conn,
                proposal_id,
                entry_price=2.0,
            )

        proposal = conn.execute(
            "SELECT * FROM shadow_structure_proposals WHERE id = ?;",
            (proposal_id,),
        ).fetchone()
        fx_id = int(
            conn.execute(
                """
                INSERT INTO fx_observations(
                    provider,
                    base_currency,
                    quote_currency,
                    rate,
                    reference_date,
                    observed_at,
                    source_url,
                    provenance
                ) VALUES (
                    'ECB', 'EUR', 'USD', 1.20,
                    '2026-09-01',
                    '2026-09-01T12:00:00Z',
                    'https://example.test/ecb',
                    'ECB_DAILY_REFERENCE_RATE'
                );
                """
            ).lastrowid
        )
        structure = json.loads(proposal["structure_json"])
        contract_sides = sum(int(leg["quantity"]) for leg in structure["legs"])
        cost_usd = contract_sides * 2 * 300
        max_loss_usd = int(proposal["max_theoretical_loss_minor"])
        risk_usd = max_loss_usd + cost_usd
        max_loss_eur = int(round(max_loss_usd / 1.20))
        cost_eur = int(round(cost_usd / 1.20))
        risk_eur = int(round(risk_usd / 1.20))
        decision_id = int(
            conn.execute(
                """
                INSERT INTO shadow_admission_decisions(
                    proposal_id,
                    fx_observation_id,
                    candidate_id,
                    sizing_policy_version,
                    cost_model_version,
                    cost_provenance,
                    proposal_max_loss_usd_minor,
                    estimated_cost_usd_minor,
                    reserved_risk_usd_minor,
                    converted_max_loss_eur_minor,
                    estimated_cost_eur_minor,
                    reserved_risk_eur_minor,
                    bankroll_cap_eur_minor,
                    decision,
                    reason_code,
                    decided_at,
                    evidence_json
                ) VALUES (
                    ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 50000,
                    'BLOCKED', ?, '2026-09-01T18:02:00Z', '{}'
                );
                """,
                (
                    proposal_id,
                    fx_id,
                    LEGACY_POLICY_VERSION,
                    COST_MODEL_VERSION,
                    COST_PROVENANCE,
                    max_loss_usd,
                    cost_usd,
                    risk_usd,
                    max_loss_eur,
                    cost_eur,
                    risk_eur,
                    reason_code,
                ),
            ).lastrowid
        )
        conn.commit()
        return {
            "proposal_id": proposal_id,
            "decision_id": decision_id,
            "fx_id": fx_id,
            "reference_id": int(proposal["target_reference_contract_id"]),
            "source_run_id": int(proposal["research_run_id"]),
            "risk_usd": risk_usd,
            "risk_eur": risk_eur,
            "cost_usd": cost_usd,
        }
    finally:
        conn.close()


def _seed_research_run(conn, *, session_date: str, ended_at: str) -> int:
    cursor = conn.execute(
        """
        INSERT INTO research_runs(
            cohort_id,
            preregistration_hash,
            code_git_sha,
            started_at,
            ended_at,
            us_session_date,
            us_session_state,
            status,
            attempted_underlyings,
            succeeded_underlyings,
            failed_underlyings
        ) VALUES (
            'INDEPENDENT_RESEARCH_RUNNER_V1',
            'replay-test-hash',
            'replay-test-sha',
            ?, ?, ?, 'INTRADAY', 'COMPLETED', 1, 1, 0
        );
        """,
        (ended_at, ended_at, session_date),
    )
    return int(cursor.lastrowid)


def _seed_theta_snapshot_with_quotes(conn, *, session_date: str) -> int:
    run_id = _seed_research_run(
        conn,
        session_date=session_date,
        ended_at=f"{session_date}T19:00:00Z",
    )
    snapshot_id = int(
        conn.execute(
            """
            INSERT INTO market_snapshots(
                captured_at,
                underlying,
                provider,
                research_run_id,
                us_session_date,
                us_session_state,
                underlying_source,
                fx_source
            ) VALUES (?, 'AAPL', 'THETADATA', ?, ?, 'INTRADAY', 'UNKNOWN', 'UNKNOWN');
            """,
            (f"{session_date}T18:59:50Z", run_id, session_date),
        ).lastrowid
    )
    for strike, bid, ask in (
        (95.0, 8.0, 8.2),
        (100.0, 4.0, 4.2),
        (105.0, 1.0, 1.2),
    ):
        conn.execute(
            """
            INSERT INTO option_quotes(
                snapshot_id,
                provider_contract_id,
                right,
                strike,
                expiration,
                quote_at,
                bid,
                bid_source,
                bid_at,
                ask,
                ask_source,
                ask_at,
                last_source,
                iv_source,
                delta_source,
                gamma_source,
                theta_source,
                vega_source,
                volume_source,
                open_interest_source
            ) VALUES (
                ?, ?, 'C', ?, '2026-09-18', ?,
                ?, 'FETCHED', ?, ?, 'FETCHED', ?,
                'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN',
                'UNKNOWN', 'UNKNOWN', 'UNKNOWN'
            );
            """,
            (
                snapshot_id,
                f"THETA:AAPL:{strike}",
                strike,
                f"{session_date}T18:59:45Z",
                bid,
                f"{session_date}T18:59:45Z",
                ask,
                f"{session_date}T18:59:45Z",
            ),
        )
    return run_id


def _seed_expiry_underlying_snapshot(conn, *, price: float) -> int:
    session_date = "2026-09-18"
    run_id = _seed_research_run(
        conn,
        session_date=session_date,
        ended_at="2026-09-18T20:00:00Z",
    )
    return int(
        conn.execute(
            """
            INSERT INTO market_snapshots(
                captured_at,
                underlying,
                provider,
                research_run_id,
                us_session_date,
                us_session_state,
                underlying_price,
                underlying_source,
                underlying_at,
                fx_source
            ) VALUES (
                '2026-09-18T19:59:55Z',
                'AAPL',
                'MASSIVE',
                ?,
                '2026-09-18',
                'INTRADAY',
                ?,
                'FETCHED',
                '2026-09-18T19:59:55Z',
                'UNKNOWN'
            );
            """,
            (run_id, price),
        ).lastrowid
    )


def test_wallet_only_replay_uses_original_decision_not_latest_entry_state(db_path):
    seeded = _seed_legacy_block(db_path)
    conn = get_connection(db_path)
    try:
        # Poison the *later* availability state. A historical replay that asks
        # for today's/latest state would now block. Correct replay never reads
        # this row because the immutable wallet-only reason already proves the
        # preceding quality gates passed at the original decision time.
        conn.execute(
            """
            INSERT INTO provider_observation_availability(
                reference_contract_id,
                provider,
                evidence_family,
                state,
                observed_at,
                ingested_at
            ) VALUES (?, 'THETADATA', 'THETADATA_QUOTE', 'ABSENT',
                      '2026-09-10T18:00:00Z', '2026-09-10T18:00:01Z');
            """,
            (seeded["reference_id"],),
        )
        conn.commit()
        candidates_before = conn.execute(
            "SELECT COUNT(*) FROM shadow_candidates;"
        ).fetchone()[0]
    finally:
        conn.close()

    result = run_historical_replay_recovery_v1(db_path=db_path)

    assert result.wallet_blocks_found == 1
    assert result.policy_replays_written == 1
    assert result.would_admit_count == 1
    assert result.would_block_count == 0

    conn = get_connection(db_path)
    try:
        replay = conn.execute(
            "SELECT * FROM historical_policy_replay_v1;"
        ).fetchone()
        original = conn.execute(
            "SELECT * FROM shadow_admission_decisions WHERE id = ?;",
            (seeded["decision_id"],),
        ).fetchone()
        candidates_after = conn.execute(
            "SELECT COUNT(*) FROM shadow_candidates;"
        ).fetchone()[0]
    finally:
        conn.close()

    evidence = json.loads(replay["evidence_json"])
    assert replay["counterfactual_decision"] == "WOULD_ADMIT"
    assert replay["intrinsic_risk_usd_minor"] == seeded["risk_usd"]
    assert replay["intrinsic_risk_eur_minor"] == seeded["risk_eur"]
    assert evidence["no_lookahead"]["contract"] == NO_LOOKAHEAD_CONTRACT
    assert evidence["no_lookahead"]["current_entry_evidence_queried"] is False
    assert evidence["no_lookahead"]["current_fx_queried"] is False
    assert original["decision"] == "BLOCKED"
    assert original["reason_code"] == "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL"
    assert candidates_after == candidates_before


def test_non_wallet_historical_block_is_not_replayed(db_path):
    _seed_legacy_block(db_path, reason_code="ENTRY_GREEK_NOT_PRESENT")

    result = run_historical_replay_recovery_v1(db_path=db_path)

    assert result.wallet_blocks_found == 0
    conn = get_connection(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM historical_policy_replay_v1;"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_replay_is_idempotent_and_original_evidence_is_immutable(db_path):
    seeded = _seed_legacy_block(db_path)

    first = run_historical_replay_recovery_v1(db_path=db_path)
    second = run_historical_replay_recovery_v1(db_path=db_path)

    assert first.policy_replays_written == 1
    assert second.policy_replays_written == 0
    assert second.replay_run_id == first.replay_run_id

    conn = get_connection(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM historical_replay_runs_v1;"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM historical_policy_replay_v1;"
        ).fetchone()[0] == 1
        original = conn.execute(
            "SELECT reason_code FROM shadow_admission_decisions WHERE id = ?;",
            (seeded["decision_id"],),
        ).fetchone()[0]
        replay_id = conn.execute(
            "SELECT id FROM historical_policy_replay_v1;"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE historical_policy_replay_v1 SET counterfactual_decision='WOULD_BLOCK' WHERE id=?;",
                (replay_id,),
            )
    finally:
        conn.close()

    assert original == "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL"


def test_replay_marks_reuse_conservative_long_bid_short_ask_economics(db_path):
    _seed_legacy_block(db_path, with_entry_pricing=True)
    conn = get_connection(db_path)
    try:
        mark_run_id = _seed_theta_snapshot_with_quotes(
            conn,
            session_date="2026-09-02",
        )
        conn.commit()
    finally:
        conn.close()

    result = run_historical_replay_recovery_v1(db_path=db_path)

    assert result.complete_replay_marks == 1
    conn = get_connection(db_path)
    try:
        mark = conn.execute(
            """
            SELECT *
            FROM historical_replay_marks_v1
            WHERE research_run_id = ?;
            """,
            (mark_run_id,),
        ).fetchone()
        candidate_count = conn.execute(
            "SELECT COUNT(*) FROM shadow_candidates;"
        ).fetchone()[0]
    finally:
        conn.close()

    # Butterfly replay: +1*95C@bid 8.0 -2*100C@ask 4.2 +1*105C@bid 1.0
    # = +$60 structure liquidation mark. Test entry pricing is symmetric, so
    # entry cashflow is $0. Estimated round-trip cost is $24.
    assert mark["structure_mark_usd_minor"] == 6_000
    assert mark["gross_pnl_usd_minor"] == 6_000
    assert mark["estimated_net_pnl_usd_minor"] == 3_600
    assert mark["estimated_net_pnl_eur_minor"] == 3_000
    assert mark["outcome_eligible"] == 0
    assert mark["measurement_role"] == "RETROSPECTIVE_CONSERVATIVE_LIQUIDATION_REPLAY"
    assert candidate_count == 0


def test_expiry_reconstruction_uses_stored_snapshot_but_never_validates_outcome(db_path):
    _seed_legacy_block(db_path, with_entry_pricing=True)
    conn = get_connection(db_path)
    try:
        snapshot_id = _seed_expiry_underlying_snapshot(conn, price=102.0)
        conn.commit()
    finally:
        conn.close()

    result = run_historical_replay_recovery_v1(db_path=db_path)

    assert result.recovered_outcomes == 1
    conn = get_connection(db_path)
    try:
        outcome = conn.execute(
            """
            SELECT *
            FROM historical_outcome_recovery_v1
            WHERE source_population = 'RETROSPECTIVE_POLICY_REPLAY';
            """
        ).fetchone()
    finally:
        conn.close()

    # At S=102 the 95/100/105 long butterfly has terminal value:
    # +$700 - 2*$200 + $0 = $300. Symmetric test entry cashflow is zero.
    assert outcome["snapshot_id"] == snapshot_id
    assert outcome["terminal_structure_value_usd_minor"] == 30_000
    assert outcome["gross_pnl_usd_minor"] == 30_000
    assert outcome["estimated_net_pnl_usd_minor"] == 27_600
    assert outcome["estimated_net_pnl_eur_minor"] == 23_000
    assert outcome["recovery_state"] == "RECOVERED"
    assert outcome["outcome_eligible"] == 0
    assert outcome["measurement_role"] == "RETROSPECTIVE_EXPIRY_RECONSTRUCTION"
    evidence = json.loads(outcome["evidence_json"])
    assert evidence["validated_package_outcome_created"] is False
    assert "not asserted to be the official settlement price" in evidence["snapshot"]["quality_note"]


def test_missing_expiry_snapshot_is_explicitly_unresolved(db_path):
    _seed_legacy_block(db_path, with_entry_pricing=True)
    conn = get_connection(db_path)
    try:
        # Advance the database beyond expiration without providing AAPL expiry
        # session underlying evidence.
        _seed_research_run(
            conn,
            session_date="2026-09-21",
            ended_at="2026-09-21T20:00:00Z",
        )
        conn.commit()
    finally:
        conn.close()

    result = run_historical_replay_recovery_v1(db_path=db_path)

    assert result.unresolved_outcomes == 1
    conn = get_connection(db_path)
    try:
        outcome = conn.execute(
            "SELECT * FROM historical_outcome_recovery_v1;"
        ).fetchone()
    finally:
        conn.close()
    assert outcome["recovery_state"] == "UNRESOLVED"
    assert outcome["reason_code"] == "MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT"
    assert outcome["terminal_underlying_price"] is None
    assert outcome["estimated_net_pnl_eur_minor"] is None


def test_theoretical_expiry_value_handles_calls_puts_and_short_legs():
    structure = {
        "legs": [
            {
                "right": "C",
                "strike": 100,
                "side": "BUY",
                "quantity": 1,
                "shares_per_contract": 100,
            },
            {
                "right": "P",
                "strike": 105,
                "side": "SELL",
                "quantity": 1,
                "shares_per_contract": 100,
            },
        ]
    }
    # S=103: call worth $3*100 and short put worth -$2*100 => +$100.
    assert theoretical_expiry_value_usd_minor(
        structure=structure,
        underlying_price=103.0,
    ) == 10_000


def test_population_view_keeps_replay_scientifically_separate(db_path):
    _seed_legacy_block(db_path)
    run_historical_replay_recovery_v1(db_path=db_path)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT population, candidate_id, policy_replay_id
            FROM v_shadow_research_populations_v1;
            """
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["population"] == "RETROSPECTIVE_POLICY_REPLAY"
    assert rows[0]["candidate_id"] is None
    assert rows[0]["policy_replay_id"] is not None


def test_replay_run_records_explicit_contract_and_version(db_path):
    _seed_legacy_block(db_path)
    result = run_historical_replay_recovery_v1(db_path=db_path)

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM historical_replay_runs_v1 WHERE id = ?;",
            (result.replay_run_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row["replay_version"] == REPLAY_VERSION
    assert row["no_lookahead_contract"] == NO_LOOKAHEAD_CONTRACT
    scope = json.loads(row["scope_json"])
    assert scope["current_entry_evidence_queries_allowed"] is False
    assert scope["current_fx_queries_allowed"] is False
    assert scope["validated_package_outcome_created"] is False

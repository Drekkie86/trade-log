from src.dashboard.research_evidence import (
    assess_replay_liquidation_stress,
)


def test_replay_stress_is_not_promoted_to_economic_pnl():
    row = {
        "policy_replay_id": 4,
        "proposal_id": 152,
        "underlying": "COIN",
        "expiration": "2026-09-25",
        "structure_id": "LONG_1_2_1_BUTTERFLY",
        "quality_state": "COMPLETE_RECONSTRUCTED_CONSERVATIVE_LIQUIDATION",
        "measurement_role": "RETROSPECTIVE_CONSERVATIVE_LIQUIDATION_REPLAY",
        "outcome_eligible": 0,
        "intrinsic_risk_eur_minor": 18527,
        "estimated_net_pnl_eur_minor": -113756,
        "estimated_cost_usd_minor": 2400,
        "entry_eur_to_usd": 1.155,
        "structure_json": """{
            "structure_id": "LONG_1_2_1_BUTTERFLY",
            "legs": [
                {
                    "strike": 202.5,
                    "right": "P",
                    "side": "BUY",
                    "quantity": 1,
                    "shares_per_contract": 100
                },
                {
                    "strike": 205.0,
                    "right": "P",
                    "side": "SELL",
                    "quantity": 2,
                    "shares_per_contract": 100
                },
                {
                    "strike": 207.5,
                    "right": "P",
                    "side": "BUY",
                    "quantity": 1,
                    "shares_per_contract": 100
                }
            ]
        }""",
        "evidence_json": """{
            "entry_cashflow_usd_minor": -19000,
            "leg_evidence": [
                {
                    "state": "COMPLETE",
                    "bid": 28.90,
                    "ask": 33.75,
                    "quote_at": "2026-09-17T15:45:31.779"
                },
                {
                    "state": "COMPLETE",
                    "bid": 31.45,
                    "ask": 36.80,
                    "quote_at": "2026-09-17T15:45:31.785"
                },
                {
                    "state": "COMPLETE",
                    "bid": 33.70,
                    "ask": 38.60,
                    "quote_at": "2026-09-17T15:45:32.043"
                }
            ]
        }""",
    }

    result = assess_replay_liquidation_stress(row)

    assert result["economic_pnl_eligible"] is False
    assert result["interpretation"] == "LEG_CROSS_LIQUIDATION_STRESS"
    assert result["package_mid_value_usd_minor"] == -7750
    assert (
        result["package_coherence_state"]
        == "MIDPOINT_OUTSIDE_BUTTERFLY_BOUNDS"
    )
    assert result["package_value_lower_bound_usd_minor"] == 0
    assert result["package_value_upper_bound_usd_minor"] == 25000
    assert result["spread_crossing_penalty_eur_minor"] == 88528
    assert result["midpoint_diagnostic_net_eur_minor"] == -25238
    assert result["stress_loss_to_intrinsic_risk"] > 6
    assert result["midpoint_loss_to_intrinsic_risk"] > 1
    assert result["max_leg_spread_to_mid"] > 0.15
    assert result["quote_time_span_seconds"] == 0.264


def test_incomplete_replay_mark_remains_not_evaluable():
    result = assess_replay_liquidation_stress(
        {
            "policy_replay_id": 99,
            "proposal_id": 100,
            "quality_state": "INCOMPLETE_LEG_MARK",
            "measurement_role": "RETROSPECTIVE_CONSERVATIVE_LIQUIDATION_REPLAY",
            "outcome_eligible": 0,
            "intrinsic_risk_eur_minor": 10000,
            "estimated_net_pnl_eur_minor": None,
            "structure_json": "{}",
            "evidence_json": "{}",
        }
    )

    assert result["economic_pnl_eligible"] is False
    assert result["package_coherence_state"] == "NOT_EVALUABLE"
    assert result["midpoint_diagnostic_net_eur_minor"] is None
    assert result["spread_crossing_penalty_eur_minor"] is None

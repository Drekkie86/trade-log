from src.decision.evidence import assess_prospective_evidence


def test_twenty_dates_is_review_trigger_not_trade_permission():
    result = assess_prospective_evidence({"similar_independent_dates": 20, "similar_candidate_count": 100, "similar_validated_outcomes": 80})
    assert result.state == "PREREG_REVIEW_THRESHOLD_REACHED"
    assert result.decision_eligible is False
    assert "does not prove edge" in result.note

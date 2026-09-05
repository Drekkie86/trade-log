from src.decision.governance import resolve_candidate_governance


def test_unknown_scanner_fails_closed():
    result = resolve_candidate_governance({"scanner_family_id": "NEW_THING"}, models=[], hypotheses=[])
    assert result.resolved is False
    assert result.decision_enabled is False
    assert result.blockers == ("UNMAPPED_CANDIDATE_GOVERNANCE",)


def test_unrelated_enabled_model_cannot_grant_permission():
    result = resolve_candidate_governance(
        {"scanner_family_id": "LOCAL_IV_RESIDUAL_V1"},
        models=[{"model_key": "SOMETHING_ELSE", "decision_enabled": True}],
        hypotheses=[],
    )
    assert result.decision_enabled is False
    assert any("LOCAL_SURFACE_QUADRATIC_V2" in item for item in result.blockers)

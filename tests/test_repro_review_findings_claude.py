"""Review-only reproductions (NOT for merge). Run against uploaded main 51c6d11."""
import pytest

import src.research.shadow_intrinsic_admission_v1 as adm
from src.database.repository import get_connection
from src.research.shadow_admission import admit_shadow_proposals
from tests._shadow_admission_seed import fx, seed_proposal


def _counts(db_path):
    conn = get_connection(db_path)
    try:
        return {
            "candidates": conn.execute("SELECT COUNT(*) FROM shadow_candidates").fetchone()[0],
            "admitted_decisions": conn.execute(
                "SELECT COUNT(*) FROM v_shadow_admission_decisions_all WHERE decision='ADMITTED'"
            ).fetchone()[0],
            "pinned_events": conn.execute(
                "SELECT COUNT(*) FROM underlying_pin_events WHERE action='PIN'"
            ).fetchone()[0],
            "tracked_without_decision": conn.execute(
                """
                WITH ls AS (SELECT candidate_id, to_state,
                       ROW_NUMBER() OVER (PARTITION BY candidate_id ORDER BY id DESC) rn
                       FROM shadow_state_events)
                SELECT COUNT(*) FROM shadow_candidates sc
                JOIN ls ON ls.candidate_id=sc.id AND ls.rn=1 AND ls.to_state='SHADOW_TRACKED'
                WHERE NOT EXISTS (SELECT 1 FROM v_shadow_admission_decisions_all d
                                  WHERE d.candidate_id=sc.id AND d.decision='ADMITTED')
                """
            ).fetchone()[0],
        }
    finally:
        conn.close()


def test_admission_crash_between_candidate_and_decision_orphans_and_duplicates(db_path, monkeypatch):
    seeded = seed_proposal(db_path, max_loss_usd_minor=20_000)
    real = adm._persist_decision

    def boom(**kw):
        if kw["decision"] == "ADMITTED":
            raise RuntimeError("simulated crash after candidate+pin were committed")
        return real(**kw)

    monkeypatch.setattr(adm, "_persist_decision", boom)
    with pytest.raises(RuntimeError):
        admit_shadow_proposals(fx=fx(), proposal_ids=[seeded["proposal_id"]], db_path=db_path)
    after_crash = _counts(db_path)
    print("AFTER CRASH:", after_crash)

    # Next daemon cycle: admission runs again for the same proposal.
    monkeypatch.setattr(adm, "_persist_decision", real)
    admit_shadow_proposals(fx=fx(), proposal_ids=[seeded["proposal_id"]], db_path=db_path)
    after_retry = _counts(db_path)
    print("AFTER RETRY:", after_retry)

    assert after_crash["candidates"] == 1 and after_crash["admitted_decisions"] == 0
    assert after_crash["tracked_without_decision"] == 1      # orphan, pinned, never marked
    assert after_retry["candidates"] == 2                    # duplicate candidate for ONE proposal
    assert after_retry["tracked_without_decision"] == 1      # the orphan is still there


def test_candidate_max_loss_column_is_eur_not_usd(db_path):
    seeded = seed_proposal(db_path, max_loss_usd_minor=20_000)
    rate = fx().rate
    admit_shadow_proposals(fx=fx(), proposal_ids=[seeded["proposal_id"]], db_path=db_path)
    conn = get_connection(db_path)
    try:
        cand = conn.execute("SELECT max_theoretical_loss_minor FROM shadow_candidates").fetchone()[0]
        usd = conn.execute(
            "SELECT proposal_max_loss_usd_minor FROM v_shadow_admission_decisions_all WHERE decision='ADMITTED'"
        ).fetchone()[0]
    finally:
        conn.close()
    print("rate", rate, "candidate col", cand, "usd", usd)
    assert usd == 20_000
    assert cand == round(20_000 / rate) and cand != usd


# ---------------------------------------------------------------------------
# Finding: an ECB FX failure on a cycle that has proposals skips lifecycle
# advancement AND shadow-mark collection for that cycle.
# ---------------------------------------------------------------------------
from tests.test_full_research_cycle import (
    FakeBridge, FakeProposal, FakeResearchCycle,
)
from src.providers.ecb_fx import EcbFxError
from src.research.research_daemon import run_one_iteration


def test_ecb_failure_skips_lifecycle_and_marks(monkeypatch, db_path):
    from src.research import full_research_cycle as frc
    calls = []
    monkeypatch.setattr(frc, "run_research_cycle", lambda **k: FakeResearchCycle())
    monkeypatch.setattr(
        frc, "build_shadow_structure_proposals",
        lambda **k: FakeBridge(1, 1, 0, (FakeProposal("PROPOSED", 5),)),
    )
    monkeypatch.setattr(frc, "advance_shadow_lifecycle", lambda **k: calls.append("lifecycle"))

    def fx_down():
        raise EcbFxError("ECB daily FX reference rate could not be fetched.")

    from src.research.research_daemon import acquire_daemon_lock
    from datetime import datetime
    from zoneinfo import ZoneInfo
    token = "repro-token"
    acquire_daemon_lock(owner_token=token, db_path=db_path)

    def runner(**kw):
        return frc.run_full_research_cycle(**kw, fx_fetcher=fx_down)

    def collector(**kw):
        calls.append("marks")
        raise AssertionError("not reached")

    summary = run_one_iteration(
        scheduled_for=datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
        owner_token=token, symbols=["AAPL"], massive_client=object(), theta_client=object(),
        db_path=db_path, full_cycle_runner=runner, mark_collector=collector,
    )
    print("SUMMARY:", summary.status, summary.error_type, "| research_run_id =", summary.research_run_id, "| calls =", calls)
    assert summary.status == "FAILED" and summary.error_type == "EcbFxError"
    assert calls == []            # neither lifecycle advancement nor mark collection ran
    assert summary.research_run_id is None   # the (committed) research run is detached from the iteration

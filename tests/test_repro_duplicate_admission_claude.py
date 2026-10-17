import json
import pytest
from src.database.repository import get_connection
from tests.test_trade_ideas import seed_scenario
from src.research.shadow_admission import admit_shadow_proposals
from tests._shadow_admission_seed import fx


@pytest.mark.xfail(strict=True, reason="REVIEW 20261017: no cross-run dedupe; a persistent anomaly is re-admitted every slot, and admission pins the underlying so it is sampled every slot")
def test_same_anomaly_in_two_slots_creates_two_active_candidates(db_path):
    a = seed_scenario(db_path, with_v2=True)          # slot 1: AAPL 18-Sep 100C rich
    b = seed_scenario(db_path, with_v2=True)          # slot 2: the same contract, still rich
    r1 = admit_shadow_proposals(fx=fx(), proposal_ids=[a["proposal_id"]], db_path=db_path)
    r2 = admit_shadow_proposals(fx=fx(), proposal_ids=[b["proposal_id"]], db_path=db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT underlying, structure_id, COUNT(*) n FROM shadow_candidates
               GROUP BY underlying, structure_id""").fetchall()
        pins = conn.execute("SELECT COUNT(*) FROM underlying_pin_events").fetchone()[0]
    finally:
        conn.close()
    print("ADMITTED:", r1.admitted_count, r2.admitted_count, "| candidates per identical structure:", [tuple(r) for r in rows], "| pin events:", pins)
    assert [d.decision for d in r1.decisions + r2.decisions] == ["ADMITTED", "ADMITTED"]
    assert rows[0]["n"] == 1   # desired behaviour: one active candidate per distinct bet

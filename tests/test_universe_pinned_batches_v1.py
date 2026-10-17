"""Pinned underlyings (actively tracked shadow candidates) are sampled every slot."""
from datetime import datetime
from zoneinfo import ZoneInfo

from src.database.repository import (
    active_pinned_underlyings,
    append_underlying_pin_event,
    get_connection,
)
from src.research.universe_profiles import (
    LIQUID_US_RESEARCH_V1,
    select_symbol_batch,
)
from tests.test_shadow_outcome_collector import seed_active_candidate

NY = ZoneInfo("America/New_York")


def _slots():
    for minute in range(0, 60 * 7, 15):  # 09:45 .. 16:30 NY
        yield datetime(2026, 10, 15, 9, 45, tzinfo=NY).replace(
            hour=9 + (45 + minute) // 60, minute=(45 + minute) % 60
        )


def test_without_pins_each_symbol_is_sampled_once_per_hour():
    seen: dict[str, int] = {}
    for at in _slots():
        batch = select_symbol_batch(
            symbols=list(LIQUID_US_RESEARCH_V1), scheduled_for=at,
            batch_size=12, interval_minutes=15,
        )
        assert batch.pinned_added == ()
        for s in batch.symbols:
            seen[s] = seen.get(s, 0) + 1
    # 28 slots / 4 batches = 7 samples per symbol; i.e. 3 of 4 cycles unsampled.
    assert set(seen.values()) == {7}


def test_pinned_symbols_are_added_to_every_slot_without_displacing_rotation():
    pinned = ["aapl", "TSLA", "NOT_IN_UNIVERSE", "AAPL"]
    for at in _slots():
        plain = select_symbol_batch(
            symbols=list(LIQUID_US_RESEARCH_V1), scheduled_for=at,
            batch_size=12, interval_minutes=15,
        )
        batch = select_symbol_batch(
            symbols=list(LIQUID_US_RESEARCH_V1), scheduled_for=at,
            batch_size=12, interval_minutes=15, pinned=pinned,
        )
        # rotation preserved as a prefix
        assert batch.symbols[: len(plain.symbols)] == plain.symbols
        assert "AAPL" in batch.symbols and "TSLA" in batch.symbols
        assert "NOT_IN_UNIVERSE" not in batch.symbols
        assert len(batch.symbols) == len(set(batch.symbols))
        assert batch.batch_size == len(batch.symbols)
        assert len(batch.symbols) <= 12 + 2
        for p in batch.pinned_added:
            assert p not in plain.symbols


def _clone_candidate(db_path, candidate_id):
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO shadow_candidates (research_run_id, reference_contract_id, underlying,
               scanner_family_id, scanner_version, scanner_rule_version, surfaced_at,
               quote_freshness_class, greek_quality_class, universe_status, structure_id, structure_version,
               structure_json, hypothesis_family, hypothesis_version, sizing_policy_version,
               max_theoretical_loss_minor, cost_model_version, cost_provenance, admission_label)
               SELECT research_run_id, reference_contract_id, underlying, scanner_family_id, scanner_version,
               scanner_rule_version, surfaced_at, quote_freshness_class, greek_quality_class, universe_status,
               structure_id, structure_version, structure_json, hypothesis_family, hypothesis_version,
               sizing_policy_version, max_theoretical_loss_minor, cost_model_version, cost_provenance,
               admission_label FROM shadow_candidates WHERE id=?""", (candidate_id,))
        conn.commit()
        return int(conn.execute("SELECT MAX(id) FROM shadow_candidates").fetchone()[0])
    finally:
        conn.close()


def test_active_pinned_underlyings_is_per_candidate(db_path):
    a, _ = seed_active_candidate(db_path)
    b = _clone_candidate(db_path, a)
    assert active_pinned_underlyings(db_path=db_path) == []
    for cid, at in ((a, "2026-09-01T14:00:00Z"), (b, "2026-09-01T14:00:01Z")):
        append_underlying_pin_event(
            underlying="AAPL", candidate_id=cid, action="PIN",
            occurred_at=at, reason="t", db_path=db_path,
        )
    assert active_pinned_underlyings(db_path=db_path) == ["AAPL"]
    # Candidate a closes and unpins; b is still tracked -> AAPL stays pinned.
    append_underlying_pin_event(
        underlying="AAPL", candidate_id=a, action="UNPIN",
        occurred_at="2026-09-20T14:00:00Z", reason="t", db_path=db_path,
    )
    assert active_pinned_underlyings(db_path=db_path) == ["AAPL"]
    append_underlying_pin_event(
        underlying="AAPL", candidate_id=b, action="UNPIN",
        occurred_at="2026-09-20T14:00:01Z", reason="t", db_path=db_path,
    )
    assert active_pinned_underlyings(db_path=db_path) == []

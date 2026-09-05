from datetime import UTC, datetime

from src.decision.market_quality import assess_market_quality


def test_fresh_tight_clean_quote_passes_market_quality():
    result = assess_market_quality(
        {"target_bid": 1.00, "target_ask": 1.02, "target_quote_at": "2026-09-05T20:00:00Z", "collection_status": "SUCCESS", "retry_count": 0},
        now=datetime(2026, 9, 5, 20, 0, 20, tzinfo=UTC),
    )
    assert result.state == "PASS"
    assert result.liquidity_pass is True


def test_stale_or_wide_quote_fails_closed():
    result = assess_market_quality(
        {"target_bid": 1.00, "target_ask": 1.50, "target_quote_at": "2026-09-05T19:00:00Z", "collection_status": "SUCCESS", "retry_count": 0},
        now=datetime(2026, 9, 5, 20, 0, 20, tzinfo=UTC),
    )
    assert result.state == "BLOCKED"
    assert "LIVE_QUOTE_NOT_FRESH" in result.blockers
    assert "BID_ASK_TOO_WIDE_OR_UNAVAILABLE" in result.blockers


def test_recovered_sample_is_visible_warning_not_silently_clean():
    result = assess_market_quality(
        {"target_bid": 1.00, "target_ask": 1.02, "target_quote_at": "2026-09-05T20:00:00Z", "collection_status": "SUCCESS", "retry_count": 1},
        now=datetime(2026, 9, 5, 20, 0, 20, tzinfo=UTC),
    )
    assert "RECOVERED_PROVIDER_SAMPLE" in result.warnings

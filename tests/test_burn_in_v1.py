from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.operations.burn_in import BurnInSample, append_burn_in_sample, read_burn_in_samples, summarize_burn_in


def sample(at: datetime, *, healthy=True, boot="boot-a") -> BurnInSample:
    return BurnInSample(
        observed_at=at.astimezone(UTC).isoformat(),
        boot_id=boot,
        database_ready=healthy,
        daemon_state="HEALTHY" if healthy else "STALE_HEARTBEAT",
        theta_state="READY" if healthy else "UNREACHABLE",
        backup_valid=healthy,
        market_state="NON_SESSION_DAY",
        latest_iteration_status="COMPLETED",
    )


def test_burn_in_passes_only_after_required_duration_without_gaps_or_failures():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    samples = [sample(start + timedelta(minutes=15 * i)) for i in range((72 * 4) + 1)]
    report = summarize_burn_in(samples, required_hours=72)
    assert report.state == "PASSED"
    assert report.duration_hours == 72.0
    assert report.unhealthy_samples == 0
    assert report.max_gap_minutes == 15.0


def test_burn_in_fails_closed_on_unhealthy_sample():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    samples = [sample(start), sample(start + timedelta(minutes=15), healthy=False)]
    assert summarize_burn_in(samples, required_hours=0).state == "UNHEALTHY_SAMPLES_PRESENT"


def test_burn_in_detects_monitoring_gap():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    samples = [sample(start), sample(start + timedelta(minutes=31))]
    assert summarize_burn_in(samples, required_hours=0).state == "OBSERVATION_GAP"


def test_burn_in_counts_real_boot_id_changes():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    samples = [sample(start, boot="a"), sample(start + timedelta(minutes=15), boot="b")]
    report = summarize_burn_in(samples, required_hours=0)
    assert report.reboot_count == 1


def test_burn_in_jsonl_roundtrip(tmp_path):
    path = tmp_path / "burn.jsonl"
    now = datetime.now(UTC)
    append_burn_in_sample(sample(now), path)
    append_burn_in_sample(sample(now + timedelta(minutes=15)), path)
    rows = read_burn_in_samples(path)
    assert len(rows) == 2
    assert rows[0].database_ready is True

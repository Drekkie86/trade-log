"""Synthetic cgroup-v2 memory classification. No live systemd changes."""
from src.operations import rc0_supervisor as s
from src.operations.service_resources import service_resource_policy

UNIT="christiania-daemon.service"

def props(current=803332096, *, policy=True):
    p=service_resource_policy(UNIT)
    return {
      "MemoryCurrent":str(current),"MemoryPeak":str(current),
      "MemoryHigh":str(p.memory_high_bytes if policy else 1),
      "MemoryMax":str(p.memory_max_bytes),
      "NRestarts":"0"
    }

def test_production_cache_footprint_not_an_anonymous_memory_failure(monkeypatch):
    # Source: read-only Oct12 cgroup memory.stat, not a source of live prices.
    monkeypatch.setattr(s,"_cgroup_inactive_file_bytes",lambda _:548634624)
    monkeypatch.setattr(s,"_cgroup_memory_high_events",lambda _:396)
    check,details=s._memory_check(UNIT,props())
    assert check.state=="PASS"
    assert details["current_bytes"]==803332096
    assert details["working_set_bytes"]==254697472
    assert details["inactive_file_bytes"]==548634624
    assert details["cumulative_memory_high_events"]==396
    assert details["cache_adjustment_used"]==1

def test_unreclaimable_memory_still_fails(monkeypatch):
    monkeypatch.setattr(s,"_cgroup_inactive_file_bytes",lambda _:100)
    monkeypatch.setattr(s,"_cgroup_memory_high_events",lambda _:0)
    p=service_resource_policy(UNIT)
    check,details=s._memory_check(UNIT,props(p.memory_warning_bytes+100))
    assert check.state=="FAIL"
    assert "EffectiveWorkingSet" in check.detail
    assert "reached warning" in check.detail

def test_unavailable_stat_preserves_conservative_existing_policy(monkeypatch):
    monkeypatch.setattr(s,"_cgroup_inactive_file_bytes",lambda _:None)
    monkeypatch.setattr(s,"_cgroup_memory_high_events",lambda _:None)
    check,details=s._memory_check(UNIT,props())
    assert check.state=="FAIL"
    assert details["cache_adjustment_used"]==0
    assert details["working_set_bytes"]==803332096

def test_invalid_inactive_cache_cannot_make_working_set_negative(monkeypatch):
    monkeypatch.setattr(s,"_cgroup_inactive_file_bytes",lambda _:999999999999)
    monkeypatch.setattr(s,"_cgroup_memory_high_events",lambda _:None)
    check,details=s._memory_check(UNIT,props())
    assert check.state=="FAIL"
    assert details["inactive_file_bytes"] is None
    assert details["working_set_bytes"]==803332096

def test_policy_drift_still_blocks_even_with_reclaimable_cache(monkeypatch):
    monkeypatch.setattr(s,"_cgroup_inactive_file_bytes",lambda _:750000000)
    monkeypatch.setattr(s,"_cgroup_memory_high_events",lambda _:396)
    check,details=s._memory_check(UNIT,props(policy=False))
    assert check.state=="FAIL"
    assert "MemoryHigh=" in check.detail
    assert "expected=" in check.detail

def test_current_unavailable_never_bluffs_healthy(monkeypatch):
    monkeypatch.setattr(s,"_cgroup_inactive_file_bytes",lambda _:1234)
    monkeypatch.setattr(s,"_cgroup_memory_high_events",lambda _:0)
    inputs=props()
    inputs["MemoryCurrent"]="not-a-number"
    check,details=s._memory_check(UNIT,inputs)
    assert check.state=="FAIL"
    assert "MemoryCurrent unavailable" in check.detail
    assert details["working_set_bytes"] is None

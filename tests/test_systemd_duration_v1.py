from src.operations import rc0_supervisor
from src.operations.service_resources import (
    service_resource_policy,
)


def test_parse_raw_systemd_microseconds():
    assert (
        rc0_supervisor._parse_systemd_usec(
            "90000000"
        )
        == 90_000_000
    )


def test_parse_real_ubuntu_systemd_timeout_format():
    assert (
        rc0_supervisor._parse_systemd_usec(
            "1min 30s"
        )
        == 90_000_000
    )


def test_parse_other_systemd_duration_shapes():
    assert (
        rc0_supervisor._parse_systemd_usec(
            "45s"
        )
        == 45_000_000
    )

    assert (
        rc0_supervisor._parse_systemd_usec(
            "2min"
        )
        == 120_000_000
    )

    assert (
        rc0_supervisor._parse_systemd_usec(
            "1h"
        )
        == 3_600_000_000
    )

    assert (
        rc0_supervisor._parse_systemd_usec(
            "1h 1min 1s"
        )
        == 3_661_000_000
    )


def test_infinity_is_not_accepted_as_finite_timeout():
    assert (
        rc0_supervisor._parse_systemd_usec(
            "infinity"
        )
        is None
    )


def test_malformed_systemd_duration_fails_closed():
    assert (
        rc0_supervisor._parse_systemd_usec(
            "ninety seconds"
        )
        is None
    )

    assert (
        rc0_supervisor._parse_systemd_usec(
            "1min nonsense 30s"
        )
        is None
    )


def test_resource_policy_accepts_exact_hetzner_systemctl_shape():
    policy = service_resource_policy(
        "christiania-app.service"
    )

    properties = {
        "MemoryCurrent": "100000000",
        "MemoryPeak": "150000000",
        "NRestarts": "0",
        "TimeoutStartUSec": "1min 30s",
        "TimeoutStopUSec": "1min 30s",
        "OOMPolicy": "stop",
        "MemoryHigh": str(
            policy.memory_high_bytes
        ),
        "MemoryMax": str(
            policy.memory_max_bytes
        ),
    }

    check = (
        rc0_supervisor._resource_policy_check(
            "christiania-app.service",
            properties,
        )
    )

    assert check.state == "PASS"


def test_resource_policy_still_detects_wrong_human_duration():
    policy = service_resource_policy(
        "christiania-app.service"
    )

    properties = {
        "MemoryCurrent": "100000000",
        "MemoryPeak": "150000000",
        "NRestarts": "0",
        "TimeoutStartUSec": "2min",
        "TimeoutStopUSec": "1min 30s",
        "OOMPolicy": "stop",
        "MemoryHigh": str(
            policy.memory_high_bytes
        ),
        "MemoryMax": str(
            policy.memory_max_bytes
        ),
    }

    check = (
        rc0_supervisor._resource_policy_check(
            "christiania-app.service",
            properties,
        )
    )

    assert check.state == "FAIL"
    assert (
        "TimeoutStartUSec"
        in check.detail
    )
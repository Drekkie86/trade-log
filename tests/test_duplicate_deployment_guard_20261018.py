"""Repeat deployment must not create a false failure for an active exact SHA."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_already_active_release_is_verified_and_noop_before_upload():
    script = (ROOT / "deploy" / "deploy_release.ps1").read_text(encoding="utf-8")
    probe = script.index('$activeTargetOutput = & ssh')
    check = script.index('if ($activeTarget -eq "/opt/christiania-releases/$head")')
    health = script.index('christiania-status --json --deployment-safe', check)
    refused = script.index("Already-active release $head failed operational readiness", health)
    no_op = script.index("result=ALREADY_ACTIVE_VERIFIED", refused)
    archive = script.index('$tempRoot = Join-Path $env:TEMP', no_op)
    assert probe < check < health < refused < no_op < archive
    assert 'if ($LASTEXITCODE -ne 0)' in script[health:no_op]
    assert 'return' in script[no_op:archive]
    assert "Refusing deployment: local HEAD is not identical to origin/main" in script[:probe]
    assert "Assert-ExactShaQualityGate -Commit $head" in script[:probe]
    assert "Performance evidence accepted" in script[:probe]
    assert "scp @SshOptions" in script[archive:]


def test_unhealthy_already_active_release_does_not_claim_success():
    script = (ROOT / "deploy" / "deploy_release.ps1").read_text(encoding="utf-8")
    body = script[script.index('if ($activeTarget -eq'):script.index('$tempRoot =')]
    assert 'throw "Already-active release' in body
    assert body.index('throw "Already-active release') < body.index('result=ALREADY_ACTIVE_VERIFIED')
    assert 'if ($LASTEXITCODE -ne 0)' in body

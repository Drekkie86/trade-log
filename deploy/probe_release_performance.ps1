param(
    [string]$Server = "2.28.76.101",
    [string]$User = "dirk",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\christiania_hetzner_ed25519"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$SshOptions = @(
    "-o", "IdentitiesOnly=yes",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=20",
    "-o", "TCPKeepAlive=yes"
)

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed."
    }
    return ($output | Out-String).Trim()
}

function Assert-ExactShaQualityGate {
    param([Parameter(Mandatory = $true)][string]$Commit)

    $headers = @{
        "User-Agent" = "Christiania-Performance-Probe"
        "Accept" = "application/vnd.github+json"
    }
    $uri = "https://api.github.com/repos/Drekkie86/trade-log/actions/runs?head_sha=$Commit&status=completed&per_page=20"
    $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get
    $run = @($response.workflow_runs) |
        Where-Object {
            $_.name -eq "Christiania Quality Gate" -and
            $_.head_sha -eq $Commit -and
            $_.event -in @("pull_request", "push") -and
            $_.conclusion -eq "success"
        } |
        Sort-Object created_at -Descending |
        Select-Object -First 1

    if ($null -eq $run) {
        throw "Exact SHA $Commit has no successful Christiania Quality Gate run."
    }

    Write-Host "quality_gate_run=$($run.id)"
}

function Write-LfNormalizedScript {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Probe script source was not found: $Source"
    }

    $text = [System.IO.File]::ReadAllText($Source)
    $text = $text.Replace([string][char]13, "")
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Destination, $text, $utf8NoBom)

    if ([System.IO.File]::ReadAllBytes($Destination) -contains 13) {
        throw "Probe script still contains CR bytes after LF normalization."
    }
}

if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$status = Invoke-Git -Arguments @("status", "--porcelain")
if ($status) {
    throw "Refusing performance probe: working tree is not clean."
}

$head = (Invoke-Git -Arguments @("rev-parse", "HEAD")).ToLowerInvariant()
if ($head -notmatch "^[0-9a-f]{40}$") {
    throw "Cannot determine a full 40-character Git commit."
}

Assert-ExactShaQualityGate -Commit $head

$probeId = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$tempRoot = Join-Path $env:TEMP "christiania-performance-$head-$probeId"
$archiveName = "christiania-$head.tar.gz"
$archivePath = Join-Path $tempRoot $archiveName
$probeSourcePath = Join-Path $PSScriptRoot "probe_release_performance.sh"
$probeUploadPath = Join-Path $tempRoot "christiania-probe-release-performance.sh"

if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    & git archive "--format=tar.gz" "--output=$archivePath" $head
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $archivePath)) {
        throw "git archive failed."
    }

    Write-LfNormalizedScript -Source $probeSourcePath -Destination $probeUploadPath
    $sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()

    $remoteArchive = "/tmp/$archiveName"
    $remoteProbe = "/tmp/christiania-probe-release-performance.sh"
    $reportPath = "/var/lib/christiania/audit/performance-probes/$head-$probeId.json"
    $unit = "christiania-performance-probe-$($head.Substring(0, 12))-$probeId.service"

    & scp @SshOptions -i $KeyPath $archivePath "${User}@${Server}:$remoteArchive"
    if ($LASTEXITCODE -ne 0) {
        throw "SCP of performance-probe archive failed."
    }

    & scp @SshOptions -i $KeyPath $probeUploadPath "${User}@${Server}:$remoteProbe"
    if ($LASTEXITCODE -ne 0) {
        throw "SCP of performance-probe script failed."
    }

    $remoteCommand = (
        "sudo systemd-run --unit=$unit " +
        "--description='Christiania performance probe $head' " +
        "--property=Type=exec --property=Restart=no --property=TimeoutStopSec=infinity --no-block " +
        "/bin/bash $remoteProbe $remoteArchive $head $sha256 $reportPath"
    )

    & ssh @SshOptions -t -i $KeyPath "${User}@${Server}" $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Server-owned performance probe failed to launch."
    }

    Write-Host ""
    Write-Host "Performance probe accepted by server."
    Write-Host "commit=$head"
    Write-Host "unit=$unit"
    Write-Host "performance_report=$reportPath"

    while ($true) {
        $probeState = & ssh @SshOptions -i $KeyPath "${User}@${Server}" (
            "if sudo test -f $reportPath; then echo COMPLETE; " +
            "elif sudo systemctl is-active --quiet $unit; then echo RUNNING; " +
            "else echo FAILED; fi"
        )
        if ($LASTEXITCODE -ne 0) {
            throw "Lost probe status access. The server-owned probe may still be running as $unit."
        }

        $state = ($probeState | Out-String).Trim()
        if ($state -eq "COMPLETE") {
            $reportText = (& ssh @SshOptions -i $KeyPath "${User}@${Server}" "sudo cat $reportPath" | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) {
                throw "Performance report exists but could not be read."
            }

            $report = $reportText | ConvertFrom-Json
            if ([string]$report.release_commit -ne $head -or -not [bool]$report.read_only) {
                throw "Performance report identity/read-only contract does not match target SHA."
            }
            if ([int]$report.probe_version -lt 5 -or -not [bool]$report.deployment_lock_held) {
                throw "Performance report does not prove serialized deployment-lock measurement."
            }
            if ($null -eq $report.runtime_activity_before -or $null -eq $report.runtime_activity_after) {
                throw "Performance report is missing daemon activity context."
            }
            if ($null -eq $report.prospective_cache_seed) {
                throw "Performance report is missing prospective cold-start cache seed."
            }
            if ([int]$report.prospective_cache_seed.seed_version -ne 1) {
                throw "Performance report prospective cache seed version is unsupported."
            }
            if ($null -eq $report.seeded_cold_dashboard -or -not [bool]$report.seeded_cold_dashboard.history_rebuild_avoided) {
                throw "Performance report does not prove seeded Dashboard cold-start behavior."
            }

            $measuredPages = @($report.pages | ForEach-Object { [string]$_.page })
            foreach ($requiredPage in @("Dashboard", "Decision Desk", "Shadow Lab", "FULL")) {
                if ($requiredPage -notin $measuredPages) {
                    throw "Performance report is missing required page: $requiredPage"
                }
            }

            Write-Host ""
            Write-Host "Christiania production performance probe completed."
            foreach ($page in $report.pages) {
                Write-Host ("{0}: median={1}ms cache={2} bytes unpickle={3}ms" -f `
                    $page.page, $page.wall_ms.median, $page.cache_payload_bytes, $page.pickle_load_ms.median)
            }
            if ($null -eq $report.ops_release_manifest -or -not [bool]$report.ops_release_manifest.within_budget -or [bool]$report.ops_release_manifest.deep_integrity) {
                throw "Performance report is missing bounded, metadata-only Ops Release evidence."
            }
            Write-Host "ops_release_manifest_median=$($report.ops_release_manifest.median_ms)ms budget=$($report.ops_release_manifest.budget_ms)ms deep_integrity=$($report.ops_release_manifest.deep_integrity)"
            Write-Host "seeded_dashboard_cold=$($report.seeded_cold_dashboard.wall_ms)ms history_rebuild_avoided=$($report.seeded_cold_dashboard.history_rebuild_avoided)"
            Write-Host "wal_delta_bytes=$($report.wal_delta_bytes)"
            Write-Host "performance_report=$reportPath"
            break
        }

        if ($state -eq "FAILED") {
            & ssh @SshOptions -i $KeyPath "${User}@${Server}" "sudo journalctl -u $unit -n 160 --no-pager"
            throw "Christiania production performance probe failed."
        }

        Start-Sleep -Seconds 5
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

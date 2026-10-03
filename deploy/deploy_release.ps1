param(
    [string]$Server = "2.28.76.101",
    [string]$User = "dirk",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\christiania_hetzner_ed25519",
    [switch]$RecoveryNoSchemaChange,
    [switch]$Detach
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
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & git @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed."
    }

    return ($output | Out-String).Trim()
}

function Assert-ExactShaQualityGate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Commit
    )

    $headers = @{
        "User-Agent" = "Christiania-Deploy"
        "Accept" = "application/vnd.github+json"
    }
    $uri = "https://api.github.com/repos/Drekkie86/trade-log/actions/runs?head_sha=$Commit&status=completed&per_page=20"

    try {
        $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get
    }
    catch {
        throw "Cannot verify GitHub quality gate for exact SHA $Commit. $($_.Exception.Message)"
    }

    $run = @($response.workflow_runs) |
        Where-Object {
            $_.name -eq "Christiania Quality Gate" -and
            $_.head_sha -eq $Commit -and
            $_.event -eq "push" -and
            $_.conclusion -eq "success"
        } |
        Sort-Object created_at -Descending |
        Select-Object -First 1

    if ($null -eq $run) {
        throw "Refusing deployment: exact main SHA $Commit has no successful push-triggered Christiania Quality Gate run."
    }

    Write-Host "quality_gate_run=$($run.id)"
}

function ConvertFrom-StatusText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $result = @{}
    foreach ($line in ($Text -split '\r?\n')) {
        if (-not $line.Contains("=")) {
            continue
        }
        $parts = $line.Split("=", 2)
        $result[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $result
}

function Write-LfNormalizedScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Release script source was not found: $Source"
    }

    $text = [System.IO.File]::ReadAllText($Source)
    $text = $text.Replace([string][char]13, "")
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Destination, $text, $utf8NoBom)

    if ([System.IO.File]::ReadAllBytes($Destination) -contains 13) {
        throw "Release script still contains CR bytes after LF normalization: $Source"
    }
}
if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$status = Invoke-Git -Arguments @(
    "status",
    "--porcelain"
)

if ($status) {
    throw "Refusing deployment: working tree is not clean."
}

$head = Invoke-Git -Arguments @(
    "rev-parse",
    "HEAD"
)

if ($head -notmatch "^[0-9a-fA-F]{40}$") {
    throw "Cannot determine a full 40-character Git commit."
}

$head = $head.ToLowerInvariant()

& git fetch origin main

if ($LASTEXITCODE -ne 0) {
    throw "git fetch origin main failed."
}

$originMain = Invoke-Git -Arguments @(
    "rev-parse",
    "origin/main"
)

$originMain = $originMain.ToLowerInvariant()

if ($head -ne $originMain) {
    throw "Refusing deployment: local HEAD is not identical to origin/main."
}

Assert-ExactShaQualityGate -Commit $head

$performanceDir = "/var/lib/christiania/audit/performance-probes"
$performancePathOutput = & ssh @SshOptions -i $KeyPath "${User}@${Server}" (
    "sudo find $performanceDir -maxdepth 1 -type f " +
    "-name '$head-*.json' -mmin -1440 -print | sort | tail -n 1"
)

if ($LASTEXITCODE -ne 0) {
    throw "Cannot verify production performance evidence for exact SHA $head."
}

$performancePath = ($performancePathOutput | Out-String).Trim()
if (-not $performancePath) {
    throw "Refusing deployment: no production performance probe from the last 24 hours exists for exact SHA $head. Run deploy/probe_release_performance.ps1 first."
}

if ($performancePath -notmatch "^/var/lib/christiania/audit/performance-probes/[0-9a-f]{40}-[A-Za-z0-9._-]+[.]json$") {
    throw "Refusing deployment: server returned an invalid performance-report path."
}

$performanceText = (& ssh @SshOptions -i $KeyPath "${User}@${Server}" "sudo cat $performancePath" | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Refusing deployment: production performance report could not be read."
}

$performanceReport = $performanceText | ConvertFrom-Json
if ([string]$performanceReport.release_commit -ne $head) {
    throw "Refusing deployment: performance report belongs to a different release SHA."
}
if (-not [bool]$performanceReport.read_only) {
    throw "Refusing deployment: performance report does not assert read-only execution."
}
if ([int]$performanceReport.probe_version -lt 3) {
    throw "Refusing deployment: performance report format is too old."
}
if (-not [bool]$performanceReport.deployment_lock_held) {
    throw "Refusing deployment: performance evidence was not serialized with the deployment lock."
}
if ($null -eq $performanceReport.runtime_activity_before -or $null -eq $performanceReport.runtime_activity_after) {
    throw "Refusing deployment: performance evidence is missing daemon activity context."
}

$measuredPages = @($performanceReport.pages | ForEach-Object { [string]$_.page })
foreach ($requiredPage in @("Dashboard", "Decision Desk", "Research Runs", "Calibration", "Observations", "Shadow Lab", "Ops", "FULL")) {
    if ($requiredPage -notin $measuredPages) {
        throw "Refusing deployment: performance evidence is missing required page $requiredPage."
    }
}

Write-Host "Performance evidence accepted: $performancePath"
Write-Host "Production timing summary:"
foreach ($page in $performanceReport.pages) {
    Write-Host ("  {0}: median={1}ms cache={2} bytes unpickle={3}ms" -f $page.page, $page.wall_ms.median, $page.cache_payload_bytes, $page.pickle_load_ms.median)
}
Write-Host "  wal_delta_bytes=$($performanceReport.wal_delta_bytes)"

$tempRoot = Join-Path $env:TEMP "christiania-release-$head"
$archiveName = "christiania-$head.tar.gz"
$archivePath = Join-Path $tempRoot $archiveName
$receiverSourcePath = Join-Path $PSScriptRoot "receive_release.sh"
$receiverUploadPath = Join-Path $tempRoot "christiania-receive-release.sh"
$launcherSourcePath = Join-Path $PSScriptRoot "start_release.sh"
$launcherUploadPath = Join-Path $tempRoot "christiania-start-release.sh"
$runnerSourcePath = Join-Path $PSScriptRoot "run_server_release.sh"
$runnerUploadPath = Join-Path $tempRoot "christiania-run-server-release.sh"

if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    & git archive "--format=tar.gz" "--output=$archivePath" $head

    if ($LASTEXITCODE -ne 0) {
        throw "git archive failed."
    }

    if (-not (Test-Path -LiteralPath $archivePath)) {
        throw "Release archive was not created."
    }

    Write-LfNormalizedScript -Source $receiverSourcePath -Destination $receiverUploadPath
    Write-LfNormalizedScript -Source $launcherSourcePath -Destination $launcherUploadPath
    Write-LfNormalizedScript -Source $runnerSourcePath -Destination $runnerUploadPath
    $sha256 = (
        Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    Write-Host ""
    Write-Host "Christiania release candidate"
    Write-Host "commit=$head"
    Write-Host "sha256=$sha256"
    Write-Host "server=$User@$Server"
    Write-Host ""

    $remoteArchive = "/tmp/$archiveName"
    $remoteReceiver = "/tmp/christiania-receive-release.sh"
    $remoteLauncher = "/tmp/christiania-start-release.sh"
    $remoteRunner = "/tmp/christiania-run-server-release.sh"

    & scp @SshOptions -i $KeyPath $archivePath "${User}@${Server}:$remoteArchive"

    if ($LASTEXITCODE -ne 0) {
        throw "SCP of release archive failed."
    }

    & scp @SshOptions -i $KeyPath $receiverUploadPath "${User}@${Server}:$remoteReceiver"

    if ($LASTEXITCODE -ne 0) {
        throw "SCP of release receiver failed."
    }

    & scp @SshOptions -i $KeyPath $launcherUploadPath "${User}@${Server}:$remoteLauncher"

    if ($LASTEXITCODE -ne 0) {
        throw "SCP of server release launcher failed."
    }

    & scp @SshOptions -i $KeyPath $runnerUploadPath "${User}@${Server}:$remoteRunner"

    if ($LASTEXITCODE -ne 0) {
        throw "SCP of server release runner failed."
    }
    $recoveryArg = if ($RecoveryNoSchemaChange) {
        " --recovery-no-schema-change"
    }
    else {
        ""
    }

    $remoteCommand = (
        "sudo bash $remoteLauncher $remoteArchive $remoteReceiver $remoteRunner " +
        "$head $sha256" +
        $recoveryArg
    )

    $launchOutput = & ssh @SshOptions -t -i $KeyPath "${User}@${Server}" $remoteCommand
    $launchExit = $LASTEXITCODE
    $launchText = ($launchOutput | Out-String).Trim()

    if ($launchText) {
        Write-Host $launchText
    }

    if ($launchExit -ne 0) {
        throw "Remote Christiania server-owned deployment launch failed."
    }

    $launchState = ConvertFrom-StatusText -Text $launchText
    $statusPath = [string]$launchState["status_path"]
    $unit = [string]$launchState["unit"]
    $activationId = [string]$launchState["activation_id"]

    if (
        $statusPath -notmatch "^/var/lib/christiania/deployments/[A-Za-z0-9._-]+/status[.]env$" -or
        $unit -notmatch "^christiania-deploy-[A-Za-z0-9._-]+[.]service$"
    ) {
        throw "Server launcher returned invalid deployment status metadata."
    }

    Write-Host ""
    Write-Host "Christiania deployment accepted by server."
    Write-Host "activation_id=$activationId"
    Write-Host "unit=$unit"
    Write-Host "status_path=$statusPath"
    Write-Host "Deployment is server-owned; losing the workstation SSH session will not stop it."

    if ($Detach) {
        Write-Host "Detached by request."
        Write-Host "Inspect later with sudo cat $statusPath and sudo journalctl -u $unit -n 80 --no-pager."
        return
    }

    $lastPhase = ""
    while ($true) {
        $statusOutput = & ssh @SshOptions -i $KeyPath "${User}@${Server}" "sudo cat $statusPath"

        if ($LASTEXITCODE -ne 0) {
            throw "Lost status access. The server-owned deployment may still be running; reconnect using unit $unit."
        }

        $deployStatus = ConvertFrom-StatusText -Text (($statusOutput | Out-String).Trim())
        $state = [string]$deployStatus["state"]
        $phase = [string]$deployStatus["phase"]
        $detail = [string]$deployStatus["detail"]

        if ($phase -and $phase -ne $lastPhase) {
            Write-Host "phase=$phase"
            $lastPhase = $phase
        }

        if ($state -eq "SUCCEEDED") {
            Write-Host ""
            Write-Host "Christiania deployment completed successfully."
            Write-Host "commit=$head"
            Write-Host "activation_id=$activationId"
            break
        }

        if ($state -eq "FAILED") {
            & ssh @SshOptions -i $KeyPath "${User}@${Server}" "sudo journalctl -u $unit -n 120 --no-pager"
            throw "Christiania deployment failed: $detail"
        }

        Start-Sleep -Seconds 5
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
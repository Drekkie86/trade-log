param(
    [string]$Server = "2.28.76.101",
    [string]$User = "dirk",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\christiania_hetzner_ed25519"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

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

$tempRoot = Join-Path $env:TEMP "christiania-release-$head"
$archiveName = "christiania-$head.tar.gz"
$archivePath = Join-Path $tempRoot $archiveName
$receiverPath = Join-Path $PSScriptRoot "receive_release.sh"

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

    & scp -i $KeyPath $archivePath "${User}@${Server}:$remoteArchive"

    if ($LASTEXITCODE -ne 0) {
        throw "SCP of release archive failed."
    }

    & scp -i $KeyPath $receiverPath "${User}@${Server}:$remoteReceiver"

    if ($LASTEXITCODE -ne 0) {
        throw "SCP of release receiver failed."
    }

    $remoteCommand = "sudo bash $remoteReceiver $remoteArchive $head $sha256"

    & ssh -t -i $KeyPath "${User}@${Server}" $remoteCommand

    if ($LASTEXITCODE -ne 0) {
        throw "Remote Christiania release activation failed."
    }

    Write-Host ""
    Write-Host "Christiania deployment completed successfully."
    Write-Host "commit=$head"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$DataRoot = $env:DATA_ROOT,
    [string]$OutputRoot = $env:OUTPUT_ROOT,
    [string]$DbPath = "",
    [string]$StatusPath = $env:BALDR_FRESHNESS_STATUS_PATH,
    [string]$LogPath = $env:BALDR_FRESHNESS_LOG_PATH,
    [int]$StaleDays = 7
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = "D:\Min\Python\Project\FA_Data"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $DataRoot "output"
}
if ([string]::IsNullOrWhiteSpace($DbPath)) {
    $DbPath = Join-Path $DataRoot "sqlite\twstock.db"
}

$RunRoot = Join-Path $OutputRoot "scheduled\data_freshness"
$LogRoot = Join-Path $RunRoot "logs"
if ([string]::IsNullOrWhiteSpace($StatusPath)) {
    $StatusPath = Join-Path $RunRoot "latest_status.json"
}
if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $LogPath = Join-Path $LogRoot "data_freshness_$Timestamp.log"
}

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}
$Probe = Join-Path $RepoRoot "scripts\scheduled\data_freshness_probe.py"
if (-not (Test-Path -LiteralPath $Probe)) {
    throw "canonical freshness probe not found: $Probe"
}

& $Python $Probe `
    --data-root $DataRoot `
    --output-root $OutputRoot `
    --db-path $DbPath `
    --status-path $StatusPath `
    --log-path $LogPath `
    --stale-days ([string]$StaleDays)

exit $LASTEXITCODE

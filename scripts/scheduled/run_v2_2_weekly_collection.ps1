param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$DataRoot = $env:DATA_ROOT,
    [string]$OutputRoot = $env:OUTPUT_ROOT,
    [string]$SourceDbPath = "",
    [string]$SidecarDbPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = "D:\Min\Python\Project\FA_Data"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $DataRoot "output"
}
if ([string]::IsNullOrWhiteSpace($SourceDbPath)) {
    $SourceDbPath = Join-Path $DataRoot "sqlite\twstock.db"
}

$RunRoot = Join-Path $OutputRoot "scheduled\v2_2_weekly_collection"
if ([string]::IsNullOrWhiteSpace($SidecarDbPath)) {
    $SidecarDbPath = Join-Path $RunRoot "evidence_scheduler.db"
}

$LogRoot = Join-Path $RunRoot "logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogRoot "v2_2_weekly_collection_$Timestamp.log"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Args = @(
    (Join-Path $RepoRoot "scripts\collect_v2_2_weekly_evidence.py"),
    "--source-db-path", $SourceDbPath,
    "--sidecar-db-path", $SidecarDbPath,
    "--output-root", $OutputRoot
)

$Output = & $Python @Args 2>&1
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogPath -Encoding utf8
$Output
exit $ExitCode

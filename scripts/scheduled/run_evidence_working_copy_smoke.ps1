param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [Parameter(Mandatory = $true)][string]$SourceDbPath,
    [Parameter(Mandatory = $true)][string]$WorkingCopyDbPath,
    [string]$DecisionDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$DataRoot = $env:DATA_ROOT,
    [string]$OutputRoot = $env:OUTPUT_ROOT,
    [int]$Repeat = 2
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = "D:\Min\Python\Project\FA_Data"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $DataRoot "output"
}
if ($Repeat -lt 2) {
    $Repeat = 2
}

$sourceResolved = [System.IO.Path]::GetFullPath($SourceDbPath)
$workingResolved = [System.IO.Path]::GetFullPath($WorkingCopyDbPath)
$defaultDb = [System.IO.Path]::GetFullPath((Join-Path $DataRoot "sqlite\twstock.db"))
if ($sourceResolved -eq $workingResolved) {
    throw "Working-copy DB must differ from source DB."
}
if ($workingResolved -eq $defaultDb) {
    throw "Working-copy DB must not be the default DATA_ROOT SQLite DB."
}

$RunRoot = Join-Path $OutputRoot "scheduled\evidence_working_copy_smoke"
$LogRoot = Join-Path $RunRoot "logs"
$ReportRoot = Join-Path $RunRoot "reports"
New-Item -ItemType Directory -Force -Path $RunRoot, $LogRoot, $ReportRoot | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StatusPath = Join-Path $RunRoot "latest_status.json"
$LogPath = Join-Path $LogRoot "evidence_working_copy_smoke_$Timestamp.log"
$ReportPath = Join-Path $ReportRoot "evidence_working_copy_smoke_$DecisionDate`_$Timestamp.md"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Args = @(
    (Join-Path $RepoRoot "scripts\smoke_evidence_pipeline_working_copy.py"),
    "--source-db-path", $SourceDbPath,
    "--working-copy-db-path", $WorkingCopyDbPath,
    "--decision-date", $DecisionDate,
    "--repeat", ([string]$Repeat),
    "--report-output", $ReportPath,
    "--json-output"
)

$Output = & $Python @Args 2>&1
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogPath -Encoding utf8

$Status = [ordered]@{
    task = "baldr-evidence-working-copy-smoke-manual"
    status = $(if ($ExitCode -eq 0) { "passed" } else { "failed" })
    manual_only = $true
    writes_source_db = $false
    writes_working_copy_db = $true
    decision_date = $DecisionDate
    source_db_path = $SourceDbPath
    working_copy_db_path = $WorkingCopyDbPath
    repeat = $Repeat
    report_path = $ReportPath
    log_path = $LogPath
    exit_code = $ExitCode
    checked_at = (Get-Date).ToString("s")
}

$Status | ConvertTo-Json -Depth 8 | Out-File -FilePath $StatusPath -Encoding utf8
$Status | ConvertTo-Json -Depth 8
exit $ExitCode

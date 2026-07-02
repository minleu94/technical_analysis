param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$DecisionDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$DataRoot = $env:DATA_ROOT,
    [string]$OutputRoot = $env:OUTPUT_ROOT,
    [string]$DbPath = "",
    [string]$Sources = "all"
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

$RunRoot = Join-Path $OutputRoot "scheduled\evidence_pipeline_dry_run"
$LogRoot = Join-Path $RunRoot "logs"
$ReportRoot = Join-Path $RunRoot "reports"
New-Item -ItemType Directory -Force -Path $RunRoot, $LogRoot, $ReportRoot | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$FreshnessPath = Join-Path $OutputRoot "scheduled\data_freshness\latest_status.json"
$StatusPath = Join-Path $RunRoot "latest_status.json"
$LogPath = Join-Path $LogRoot "evidence_pipeline_dry_run_$Timestamp.log"
$ReportPath = Join-Path $ReportRoot "evidence_pipeline_dry_run_$DecisionDate`_$Timestamp.md"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$FreshnessStatus = "missing"
if (Test-Path $FreshnessPath) {
    try {
        $Freshness = Get-Content -Raw -Path $FreshnessPath | ConvertFrom-Json
        $FreshnessStatus = [string]$Freshness.status
    } catch {
        $FreshnessStatus = "unreadable"
    }
}

$Args = @(
    (Join-Path $RepoRoot "scripts\run_evidence_pipeline.py"),
    "--decision-date", $DecisionDate,
    "--dry-run",
    "--db-path", $DbPath,
    "--sources", $Sources,
    "--report-output", $ReportPath,
    "--json-output"
)

$Output = & $Python @Args 2>&1
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogPath -Encoding utf8

$PipelineStatus = if ($ExitCode -eq 0) { "passed" } else { "failed" }
if ($PipelineStatus -eq "passed" -and $FreshnessStatus -ne "passed") {
    $PipelineStatus = "degraded"
}

$Status = [ordered]@{
    task = "baldr-evidence-pipeline-dry-run-daily"
    status = $PipelineStatus
    dry_run = $true
    writes_evidence_db = $false
    decision_date = $DecisionDate
    db_path = $DbPath
    freshness_status = $FreshnessStatus
    freshness_status_path = $FreshnessPath
    report_path = $ReportPath
    log_path = $LogPath
    exit_code = $ExitCode
    checked_at = (Get-Date).ToString("s")
}

$Status | ConvertTo-Json -Depth 8 | Out-File -FilePath $StatusPath -Encoding utf8
$Status | ConvertTo-Json -Depth 8
exit $ExitCode

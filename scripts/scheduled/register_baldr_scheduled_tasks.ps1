param(
    [ValidateSet('DryRun', 'Register')][string]$Mode = 'DryRun',
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$FreshnessAt = "07:30",
    [string]$EvidenceAt = "07:45"
)

$ErrorActionPreference = "Stop"

function New-PowerShellAction([string]$ScriptPath, [string]$ExtraArgs = "") {
    $arguments = "-NoProfile -File `"$ScriptPath`" $ExtraArgs"
    return New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
}

$freshnessScript = Join-Path $RepoRoot "scripts\scheduled\run_daily_data_freshness_check.ps1"
$evidenceScript = Join-Path $RepoRoot "scripts\scheduled\run_evidence_pipeline_dry_run.ps1"
$smokeScript = Join-Path $RepoRoot "scripts\scheduled\run_evidence_working_copy_smoke.ps1"

$tasks = @(
    [ordered]@{
        Name = "baldr-data-freshness-check-daily"
        Description = "Read-only baldr data freshness check."
        Action = New-PowerShellAction $freshnessScript
        Trigger = New-ScheduledTaskTrigger -Daily -At $FreshnessAt
        Enabled = $true
    },
    [ordered]@{
        Name = "baldr-evidence-pipeline-dry-run-daily"
        Description = "Dry-run baldr evidence pipeline report."
        Action = New-PowerShellAction $evidenceScript
        Trigger = New-ScheduledTaskTrigger -Daily -At $EvidenceAt
        Enabled = $true
    },
    [ordered]@{
        Name = "baldr-evidence-working-copy-smoke-manual"
        Description = "Manual-only working-copy evidence smoke. Requires explicit paths when run outside Task Scheduler."
        Action = New-PowerShellAction $smokeScript "-SourceDbPath `"<source-db>`" -WorkingCopyDbPath `"<working-copy-db>`""
        Trigger = New-ScheduledTaskTrigger -Once -At "2099-01-01T09:00:00"
        Enabled = $false
    }
)

foreach ($task in $tasks) {
    Write-Host "Task: $($task.Name)"
    Write-Host "  Enabled: $($task.Enabled)"
    Write-Host "  Description: $($task.Description)"
    if ($Mode -eq "Register") {
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $task.Name -Action $task.Action -Trigger $task.Trigger -Settings $settings -Description $task.Description -Force | Out-Null
        if (-not $task.Enabled) {
            Disable-ScheduledTask -TaskName $task.Name | Out-Null
        }
    }
}

if ($Mode -eq "DryRun") {
    Write-Host "DryRun only. No scheduled task was registered."
} else {
    Write-Host "Scheduled tasks registered. Working-copy smoke remains disabled."
}

param(
    [ValidateSet('DryRun', 'Register')][string]$Mode = 'DryRun',
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$UpdateAt = "04:20",
    [string]$FreshnessAt = "05:00",
    [string]$EvidenceAt = "05:15"
)

$ErrorActionPreference = "Stop"

function New-CmdAction([string]$ScriptPath) {
    $arguments = "/c `"$ScriptPath`""
    return New-ScheduledTaskAction -Execute "cmd.exe" -Argument $arguments
}

$updateScript = Join-Path $RepoRoot "scripts\scheduled\run_daily_data_update_quick.cmd"
$freshnessScript = Join-Path $RepoRoot "scripts\scheduled\run_daily_data_freshness_check.ps1"
$evidenceScript = Join-Path $RepoRoot "scripts\scheduled\run_evidence_pipeline_dry_run.ps1"
$smokeScript = Join-Path $RepoRoot "scripts\scheduled\run_evidence_working_copy_smoke.ps1"

$tasks = @(
    [ordered]@{
        Name = "baldr-data-update-quick-daily"
        Description = "Non-UI baldr quick market data update."
        Action = New-CmdAction $updateScript
        Trigger = New-ScheduledTaskTrigger -Daily -At $UpdateAt
        Enabled = $true
    },
    [ordered]@{
        Name = "baldr-data-freshness-check-daily"
        Description = "Read-only baldr data freshness check."
        Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -File `"$freshnessScript`""
        Trigger = New-ScheduledTaskTrigger -Daily -At $FreshnessAt
        Enabled = $true
    },
    [ordered]@{
        Name = "baldr-evidence-pipeline-dry-run-daily"
        Description = "Dry-run baldr evidence pipeline report."
        Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -File `"$evidenceScript`""
        Trigger = New-ScheduledTaskTrigger -Daily -At $EvidenceAt
        Enabled = $true
    },
    [ordered]@{
        Name = "baldr-evidence-working-copy-smoke-manual"
        Description = "Manual-only working-copy evidence smoke. Requires explicit paths when run outside Task Scheduler."
        Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -File `"$smokeScript`" -SourceDbPath `"<source-db>`" -WorkingCopyDbPath `"<working-copy-db>`""
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

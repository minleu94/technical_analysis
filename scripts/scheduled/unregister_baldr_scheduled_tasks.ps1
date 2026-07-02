param(
    [ValidateSet('DryRun', 'Unregister')][string]$Mode = 'DryRun'
)

$ErrorActionPreference = "Stop"

$taskNames = @(
    "baldr-data-freshness-check-daily",
    "baldr-evidence-pipeline-dry-run-daily",
    "baldr-evidence-working-copy-smoke-manual"
)

foreach ($name in $taskNames) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "Task not found: $name"
        continue
    }
    Write-Host "Task found: $name"
    if ($Mode -eq "Unregister") {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Unregistered: $name"
    }
}

if ($Mode -eq "DryRun") {
    Write-Host "DryRun only. No scheduled task was removed."
}

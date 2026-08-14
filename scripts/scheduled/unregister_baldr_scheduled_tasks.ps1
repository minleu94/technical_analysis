param(
    [ValidateSet('DryRun', 'Unregister')][string]$Mode = 'DryRun'
)

$ErrorActionPreference = "Stop"

$taskNames = @(
    "baldr-data-update-quick-daily",
    "baldr-official-market-events-daily",
    "baldr-data-freshness-check-daily",
    "baldr-ml-raw-pit-refresh-daily",
    "baldr-ml-direct-chain-maintainer",
    "baldr-recommendation-snapshot-daily",
    "baldr-evidence-pipeline-dry-run-daily",
    "baldr-ml-promotion-evidence-daily",
    "baldr-ml-promotion-authority-daily",
    "baldr-ml-allocation-copilot-daily",
    "baldr-decision-evidence-capture-daily",
    "baldr-paper-portfolio-daily",
    "baldr-v2-2-weekly-collection",
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

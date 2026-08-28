param(
    [ValidateSet('DryRun', 'Register', 'WeeklyRegister', 'RegisterAll')][string]$Mode = 'DryRun',
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$UpdateAt = "04:20",
    [string]$OfficialEventsAt = "04:50",
    [string]$FreshnessAt = "05:00",
    [string]$MLRawPitRefreshAt = "05:05",
    [string]$MLDirectChainMaintainerAt = "05:30",
    [string]$RecommendationAt = "05:10",
    [string]$EvidenceAt = "05:15",
    [string]$MLPromotionEvidenceAt = "05:17",
    [string]$MLPromotionAuthorityAt = "05:18",
    [string]$MLAllocationAt = "05:20",
    [string]$DecisionEvidenceAt = "05:25",
    [string]$PaperPortfolioAt = "05:28",
    [ValidateSet('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')]
    [string]$WeeklyDay = "Sunday",
    [string]$WeeklyAt = "18:00"
)

$ErrorActionPreference = "Stop"

function New-CmdAction([string]$ScriptPath) {
    $arguments = "/c `"$ScriptPath`""
    return New-ScheduledTaskAction -Execute "cmd.exe" -Argument $arguments
}

function New-DailyTaskSpec(
    [string]$Name,
    [string]$Description,
    [string]$ScriptPath,
    [string]$At
) {
    return [ordered]@{
        Name = $Name
        Description = $Description
        ScriptPath = $ScriptPath
        ScheduleType = "Daily"
        Schedule = "DAILY $At"
        At = $At
        DaysOfWeek = $null
        Action = "cmd.exe /c `"$ScriptPath`""
        Enabled = $true
    }
}

function New-WeeklyTaskSpec(
    [string]$Name,
    [string]$Description,
    [string]$ScriptPath,
    [string]$Day,
    [string]$At
) {
    return [ordered]@{
        Name = $Name
        Description = $Description
        ScriptPath = $ScriptPath
        ScheduleType = "Weekly"
        Schedule = "WEEKLY $($Day.ToUpperInvariant()) $At"
        At = $At
        DaysOfWeek = $Day
        Action = "cmd.exe /c `"$ScriptPath`""
        Enabled = $true
    }
}

$updateScript = Join-Path $RepoRoot "scripts\scheduled\run_daily_data_update_quick.cmd"
$officialEventsScript = Join-Path $RepoRoot "scripts\scheduled\run_official_market_event_backfill.cmd"
$freshnessScript = Join-Path $RepoRoot "scripts\scheduled\run_daily_data_freshness_check.cmd"
$mlRawPitRefreshScript = Join-Path $RepoRoot "scripts\scheduled\run_ml_raw_pit_refresh.cmd"
$mlDirectChainMaintainerScript = Join-Path $RepoRoot "scripts\scheduled\run_ml_direct_chain_maintenance.cmd"
$recommendationScript = Join-Path $RepoRoot "scripts\scheduled\run_recommendation_snapshot.cmd"
$evidenceScript = Join-Path $RepoRoot "scripts\scheduled\run_evidence_pipeline_dry_run.cmd"
$mlPromotionEvidenceScript = Join-Path $RepoRoot "scripts\scheduled\run_ml_promotion_evidence.cmd"
$mlAllocationScript = Join-Path $RepoRoot "scripts\scheduled\run_ml_allocation_copilot.cmd"
$mlPromotionAuthorityScript = Join-Path $RepoRoot "scripts\scheduled\run_ml_promotion_authority.cmd"
$decisionEvidenceScript = Join-Path $RepoRoot "scripts\scheduled\run_decision_evidence_capture.cmd"
$paperPortfolioScript = Join-Path $RepoRoot "scripts\scheduled\run_paper_portfolio_daily.cmd"
$weeklyScript = Join-Path $RepoRoot "scripts\scheduled\run_v2_2_weekly_collection.cmd"

$dailyTasks = @(
    (New-DailyTaskSpec "baldr-data-update-quick-daily" "Non-UI baldr quick market data update." $updateScript $UpdateAt),
    (New-DailyTaskSpec "baldr-official-market-events-daily" "Append-only official market event publication." $officialEventsScript $OfficialEventsAt),
    (New-DailyTaskSpec "baldr-data-freshness-check-daily" "Read-only baldr data freshness check." $freshnessScript $FreshnessAt),
    (New-DailyTaskSpec "baldr-ml-raw-pit-refresh-daily" "Automatic immutable full-market raw PIT publication after data freshness proof." $mlRawPitRefreshScript $MLRawPitRefreshAt),
    (New-DailyTaskSpec "baldr-ml-direct-chain-maintainer" "Automatic fail-closed Direct v4 to OOC v5 process-custody maintainer." $mlDirectChainMaintainerScript $MLDirectChainMaintainerAt),
    (New-DailyTaskSpec "baldr-recommendation-snapshot-daily" "Research-only baldr recommendation snapshot." $recommendationScript $RecommendationAt),
    (New-DailyTaskSpec "baldr-evidence-pipeline-dry-run-daily" "Dry-run baldr evidence pipeline report." $evidenceScript $EvidenceAt),
    (New-DailyTaskSpec "baldr-ml-promotion-evidence-daily" "Unsigned formal OOC/replay/shadow promotion evidence builder." $mlPromotionEvidenceScript $MLPromotionEvidenceAt),
    (New-DailyTaskSpec "baldr-ml-promotion-authority-daily" "Independent DPAPI-protected machine promotion authority for the next decision session." $mlPromotionAuthorityScript $MLPromotionAuthorityAt),
    (New-DailyTaskSpec "baldr-ml-allocation-copilot-daily" "Fail-closed baldr ML allocation co-pilot promotion evaluation." $mlAllocationScript $MLAllocationAt),
    (New-DailyTaskSpec "baldr-decision-evidence-capture-daily" "Idempotent Decision Desk snapshot and evidence event capture." $decisionEvidenceScript $DecisionEvidenceAt),
    (New-DailyTaskSpec "baldr-paper-portfolio-daily" "Strict T-1 append-only Paper Portfolio daily valuation." $paperPortfolioScript $PaperPortfolioAt)
)
$weeklyTasks = @(
    (New-WeeklyTaskSpec "baldr-v2-2-weekly-collection" "Append-only weekly evidence collection with automatic maturity revalidation." $weeklyScript $WeeklyDay $WeeklyAt)
)
$allTasks = @($dailyTasks) + @($weeklyTasks)

$selectedTasks = @(
    switch ($Mode) {
        "DryRun" { $allTasks }
        "Register" { $dailyTasks }
        "WeeklyRegister" { $weeklyTasks }
        "RegisterAll" { $allTasks }
    }
)

foreach ($task in $selectedTasks) {
    Write-Host "Task: $($task.Name)"
    Write-Host "  Schedule: $($task.Schedule)"
    Write-Host "  Action: $($task.Action)"
    Write-Host "  Description: $($task.Description)"
    Write-Host "  Enabled: $($task.Enabled)"
}

$missingScripts = @(
    $selectedTasks |
        Where-Object { -not (Test-Path -LiteralPath $_.ScriptPath -PathType Leaf) }
)
if ($missingScripts.Count -gt 0) {
    foreach ($task in $missingScripts) {
        Write-Host "Wrapper missing: $($task.ScriptPath)"
    }
    throw "Wrapper preflight failed. No scheduled task was registered."
}

if ($Mode -eq "DryRun") {
    Write-Host "DryRun only. No scheduled task was registered. Use RegisterAll to register all displayed tasks."
    return
}

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

foreach ($task in $selectedTasks) {
    $action = New-CmdAction $task.ScriptPath
    if ($task.ScheduleType -eq "Daily") {
        $trigger = New-ScheduledTaskTrigger -Daily -At $task.At
    } else {
        $trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $task.DaysOfWeek -At $task.At
    }
    Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger -Settings $settings -Description $task.Description -Force | Out-Null
    if (-not $task.Enabled) {
        Disable-ScheduledTask -TaskName $task.Name | Out-Null
    }
}

Write-Host "Registered $($selectedTasks.Count) scheduled task(s) in mode $Mode."

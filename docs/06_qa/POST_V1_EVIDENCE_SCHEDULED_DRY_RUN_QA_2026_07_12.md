# Post-V1 Evidence Scheduled Dry-run QA（2026-07-12）

> 最新 CMD + `schtasks.exe` 註冊紀錄見 [POST_V1_SCHEDULED_EVIDENCE_PIPELINE_QA_2026_07_12.md](POST_V1_SCHEDULED_EVIDENCE_PIPELINE_QA_2026_07_12.md)。本檔保留舊 PowerShell wrapper 被 execution policy 阻擋的歷史 QA 脈絡。

## Historical Result

`registration_blocked`：本機 PowerShell execution policy 禁止執行 repo `.ps1`，DryRun 階段即被擋住，錯誤類型為 `PSSecurityException / UnauthorizedAccess`。依安全要求，當時未使用 bypass、未修改 execution policy、未執行 Register，因此 Windows Task Scheduler 未透過 `.ps1` 建立 task。

後續處置改為使用 CMD wrapper + Windows 內建 `schtasks.exe`：

- `scripts/scheduled/run_daily_data_freshness_check.cmd`
- `scripts/scheduled/run_evidence_pipeline_dry_run.cmd`
- `scripts/scheduled/run_evidence_working_copy_smoke.cmd`
- `scripts/scheduled/register_baldr_scheduled_tasks.cmd`
- `scripts/scheduled/unregister_baldr_scheduled_tasks.cmd`
- `scripts/scheduled/query_baldr_scheduled_tasks.cmd`

## Safety Boundary

- 不使用 `Set-ExecutionPolicy`。
- 不修改 PowerShell execution policy。
- 不建立 production evidence confirm schedule。
- 不自動寫 production evidence DB。
- 不更新 production data。
- 不跑 UI。
- 不讀 UI state。
- 不改 portfolio、ScoringEngine、推薦權重或 lifecycle state。
- 不宣稱 alpha 或任一事件類型有效。

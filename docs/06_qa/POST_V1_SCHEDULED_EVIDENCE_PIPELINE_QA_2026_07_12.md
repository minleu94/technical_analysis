# Post-V1 Scheduled Evidence Pipeline QA（2026-07-12）

## Scope

本 QA 覆蓋 CMD wrapper + Windows `schtasks.exe` 註冊：

- `scripts/scheduled/run_daily_data_freshness_check.cmd`
- `scripts/scheduled/run_evidence_pipeline_dry_run.cmd`
- `scripts/scheduled/run_evidence_working_copy_smoke.cmd`
- `scripts/scheduled/register_baldr_scheduled_tasks.cmd`
- `scripts/scheduled/unregister_baldr_scheduled_tasks.cmd`
- `scripts/scheduled/query_baldr_scheduled_tasks.cmd`
- `scripts/scheduled/README.md`

本輪只允許 read-only data freshness check、evidence pipeline dry-run，以及 manual-only working-copy smoke script。PowerShell `.ps1` 被 local execution policy 擋住，因此不再用 `.ps1` 註冊，也不使用 `Set-ExecutionPolicy`。

## Scheduled Tasks

| Task | Trigger | Action | Writes |
|---|---|---|---|
| `baldr-data-freshness-check-daily` | Daily local time 05:00 | `cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_freshness_check.cmd"` | 只寫 status/log，不寫 DB |
| `baldr-evidence-pipeline-dry-run-daily` | Daily local time 05:15 | `cmd.exe /c "<repo>\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"` | 只寫 report/status/log，不寫 evidence DB |
| `baldr-evidence-working-copy-smoke-manual` | Manual only | script only | 不建立每日自動 task |

Codex app 另有 `baldr scheduled evidence morning report` automation，每日本機時間約 05:30 執行 read-only 摘要。它只查詢 Windows Task Scheduler、`latest_status.json`、最新 evidence dry-run report 與必要 log 區段，不重新執行 freshness / evidence pipeline，也不建立或修改 Windows Task Scheduler task。

## Wrapper Behavior

### Data Freshness

`run_daily_data_freshness_check.cmd` 使用 `.venv\Scripts\python.exe` 執行 read-only probe。SQLite 使用 `mode=ro` 讀取，檢查 `daily_prices` 與 `technical_indicators` 最新日期，並檢查 `DATA_ROOT` / DB path 是否存在。

輸出：

- `<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json`
- `<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log`

### Evidence Dry-run

`run_evidence_pipeline_dry_run.cmd` 自動取得本機日期 `YYYY-MM-DD` 作為 decision date，呼叫：

```cmd
scripts\run_evidence_pipeline.py --dry-run
```

此 wrapper 嚴格不包含 `--confirm`。它讀取 data freshness `latest_status.json`；若 freshness 不是 `passed`，pipeline status 會標成 `degraded` 或 `failed`。

輸出：

- `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/latest_status.json`
- `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/YYYYMMDD_evidence_pipeline_dry_run.log`
- `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/reports/YYYYMMDD_evidence_pipeline_dry_run.md`

### Working-copy Smoke

`run_evidence_working_copy_smoke.cmd` 是 manual-only。缺 source DB 或 working-copy DB path 時只顯示 usage 並 exit。Repeat 預設至少 2。這個 script 不會被 daily register script 自動呼叫。

## Registration Commands

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun
scripts\scheduled\register_baldr_scheduled_tasks.cmd register
scripts\scheduled\query_baldr_scheduled_tasks.cmd
```

刪除：

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd dryrun
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd unregister
```

## Test Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_cmd_scripts_exist.py tests/test_scheduled_cmd_scripts_no_confirm.py tests/test_scheduled_cmd_scripts_task_names.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
git diff --check
```

## Registration Result

`scripts\scheduled\register_baldr_scheduled_tasks.cmd register` 已成功建立兩個 daily tasks：

- `baldr-data-freshness-check-daily`：`Ready` / `Enabled`，下一次執行 `2026/7/3 上午 05:00:00`，Task To Run 為 `cmd.exe /c "C:\Projects\PythonProjects\technical_analysis\scripts\scheduled\run_daily_data_freshness_check.cmd"`。
- `baldr-evidence-pipeline-dry-run-daily`：`Ready` / `Enabled`，下一次執行 `2026/7/3 上午 05:15:00`，Task To Run 為 `cmd.exe /c "C:\Projects\PythonProjects\technical_analysis\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"`。
- `baldr-evidence-working-copy-smoke-manual`：未建立 Windows Task Scheduler task，維持 manual-only script。

查詢方式已以 `scripts\scheduled\query_baldr_scheduled_tasks.cmd`、`schtasks /Query /TN baldr-data-freshness-check-daily /V /FO LIST` 與 `schtasks /Query /TN baldr-evidence-pipeline-dry-run-daily /V /FO LIST` 驗證。

## Morning Check

每日檢查步驟見：

- `docs/07_guides/EVIDENCE_SCHEDULED_MORNING_CHECK.md`

## Safety Boundary

- 沒有 production evidence confirm schedule。
- 沒有自動寫 production evidence DB。
- 沒有自動交易。
- 沒有自動 lifecycle action。
- 沒有 portfolio、ScoringEngine 或推薦權重變更。
- Evidence dry-run report 只供人工 review，不宣稱 alpha、不產生買賣建議。
- Codex morning summary 只讀取既有 task/status/report/log，不使用 `--confirm`，不寫 production evidence DB。

## Known Limitations

- Data freshness task 只檢查，不更新資料。
- Evidence daily task 只 dry-run，不累積 production evidence events / outcomes。
- Working-copy smoke 預設 manual-only。
- 多日觀察仍需人工填入 dry-run record。

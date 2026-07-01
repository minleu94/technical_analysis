# Post-V1 Evidence Scheduler Dry-run QA

日期：2026-07-06

## Scope

本 QA 記錄 Round 6：Evidence Pipeline Runner dry-run v1。此工具可手動模擬每日 evidence pipeline，並輸出 JSON / Markdown diagnostics report。它不是正式 scheduler，也不啟動背景排程。

## Files Changed

新增：

- `app_module/evidence_pipeline_runner.py`
- `app_module/evidence_pipeline_runner_dtos.py`
- `scripts/run_evidence_pipeline.py`
- `tests/test_evidence_pipeline_runner.py`
- `tests/test_run_evidence_pipeline_cli.py`
- `tests/test_evidence_pipeline_report.py`
- `tests/test_evidence_pipeline_scheduler_readiness.py`
- `docs/superpowers/specs/2026-07-06-post-v1-evidence-scheduler-dry-run-design.md`
- `docs/superpowers/plans/2026-07-06-post-v1-evidence-scheduler-dry-run.md`
- `docs/06_qa/POST_V1_EVIDENCE_SCHEDULER_DRY_RUN_QA_2026_07_06.md`

修改：

- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_vision_specification.md`
- `docs/07_guides/APPLICATION_MANUAL.md`

## Runner Behavior

- CLI 預設 dry-run。
- `--dry-run` 與 `--confirm` 互斥。
- `--confirm` 必須指定 `--db-path`。
- 疑似 production/default DB confirm 需要 `--allow-production-db-confirm`，本輪測試不使用正式 DB。
- dry-run 不寫入 evidence events / outcomes；repository schema 初始化可能存在，但 business rows 不會寫入。
- confirm 可寫入 explicit working-copy DB，重複 confirm 會 idempotent skip duplicate event。

## Pipeline Steps

Runner summary 包含：

- `source_coverage_check`
- `capture_decision_desk_snapshot`
- `capture_evidence_events`
- `calculate_forward_outcomes`
- `summarize_forward_performance`
- `write_diagnostics_report`

每個 step 都輸出 status、records、warnings、errors、diagnostics 與 duration。

## Source Coverage

- `recommendation`：讀 persisted `RecommendationResultDTO`。
- `watchlist-trigger` / `portfolio-alert` / `risk-prompt`：讀 durable Daily Decision Desk snapshot；缺 snapshot 只 diagnostic，不偽造 event。
- `why-not` / `liquidity-gate`：透過 recommendation persisted optional payload；缺 payload 只列 blocking gap 或 diagnostic，不回補、不重算。

## Report

Markdown report 包含：

- Run metadata
- Source coverage
- Step summary
- Event capture summary
- Outcome calculation summary
- Forward performance summary
- Warnings / degraded sources
- Blocking gaps
- Evidence boundary
- Scheduler readiness
- Next recommended action

Evidence boundary：

- This report is research evidence only.
- Close-to-close forward return is research evidence only.
- Close-to-close forward return is not executable live performance.
- No trading recommendation is produced.

## Test Commands

已執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_pipeline_runner.py tests/test_run_evidence_pipeline_cli.py tests/test_evidence_pipeline_report.py tests/test_evidence_pipeline_scheduler_readiness.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_forward_performance_dashboard_service.py tests/test_forward_performance_read_model.py tests/test_evidence_pipeline_smoke.py tests/test_decision_desk_snapshot_repository.py -q -o addopts=
.\.venv\Scripts\python.exe scripts/check_financial_float_boundaries.py
$files = @(Get-ChildItem app_module -Filter *.py | ForEach-Object { $_.FullName }) + @(Get-ChildItem scripts -Filter *.py | ForEach-Object { $_.FullName }); .\.venv\Scripts\python.exe -m py_compile @files
git diff --check
```

PowerShell wildcard 以等價檔案清單展開後交給 `py_compile`。

## Test Results

- Round 6 runner / CLI / report / readiness tests：19 passed。
- Forward dashboard / read model / evidence smoke / snapshot repository 回歸：19 passed。
- `scripts/check_financial_float_boundaries.py`：passed。
- `py_compile app_module + scripts`：passed。
- `git diff --check`：passed；僅顯示 LF/CRLF 轉換 warning，無 whitespace error。

## Known Limitations

- 尚未建立正式 scheduler、cron、Windows Task Scheduler 或 background job。
- `ready_for_manual_confirm` 只代表可做人工 working-copy confirm，不代表 production ready。
- Why Not / Liquidity 只在 persisted payload present 時可 capture，舊 recommendation 不回補。
- Live vs Research Gap linkage、Signal Decay Monitor、Decision Quality Review 尚未完成。
- Close-to-close forward return 不是可執行實盤績效。

## Scheduler Readiness

最高狀態：`ready_for_manual_confirm`。

不得輸出：`production_ready`。

## Not Done

- 不建立正式 scheduler。
- 不做 dashboard UI 變更。
- 不修改 scoring、推薦權重、portfolio position 或 lifecycle state。
- 不宣稱 alpha 或任一 event type 有效。

## Next Increment

1. 用 working-copy DB 跑多次 dry-run / confirm smoke。
2. Live vs Research Gap linkage。
3. Signal Decay Monitor。
4. Decision Quality Review。
5. Production scheduler approval checklist。

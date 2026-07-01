# Post-V1 Live vs Research Gap Linkage QA

日期：2026-07-08

## Scope

本輪新增 Live vs Research Gap event linkage v1。它把 portfolio position source trace、Evidence Event / Outcome 與 saved source metadata 串成 append-only / idempotent gap observation。

這是 research evidence inspection layer，不是完整實帳歸因，不是 action engine。

## Files Changed

新增：

- `app_module/live_research_gap_dtos.py`
- `app_module/live_research_gap_repository.py`
- `app_module/live_research_gap_service.py`
- `scripts/capture_live_research_gap.py`
- `scripts/inspect_live_research_gap.py`
- `tests/test_live_research_gap_repository.py`
- `tests/test_live_research_gap_service.py`
- `tests/test_live_research_gap_cli.py`
- `tests/test_live_research_gap_no_trading_language.py`
- `tests/test_live_research_gap_source_matching.py`

更新：

- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_vision_specification.md`
- `docs/07_guides/APPLICATION_MANUAL.md`

## Source Trace Coverage

v1 使用 `PositionDTO.source_type`、`source_id`、`source_snapshot_hash`、`source_summary`、`trade_ids`、`opened_at`、`average_cost` 與 `current_price`。`source_summary` 可提供 `research_run_id`、`strategy_version_id`、`recommendation_result_id`、`evidence_event_id`、`evidence_outcome_id`、`expected_return_bp`、`entry_price`、`regime` 與 `portfolio_mode`。

缺 source trace 時仍保存 observation，但標示 `source_trace_gap` 與 warning，不中斷整批。

## Matching Policy

- Explicit `evidence_event_id`：confirmed link。
- Exact `source_type + source_id`：confirmed link。
- Symbol / date match：只列 candidate，`match_confidence=low`。
- 缺 outcome：`insufficient_evidence`。

## Attribution Policy

支援：

- `signal_gap`
- `execution_gap`
- `market_regime_gap`
- `liquidity_gap`
- `data_quality_gap`
- `source_trace_gap`
- `manual_override_gap`（預留）
- `insufficient_evidence`

v1 attribution 是保守 rule-based observation，不是決策建議。

## Portfolio Mode Policy

沒有真實交易與人工 override 記錄時，只能標 `simulated` 或 `unknown`。只有 source summary 明確標示真實交易已記錄時才可標 `real`。本輪不宣稱完整實帳歸因。

## CLI Examples

```powershell
.\.venv\Scripts\python.exe scripts\inspect_live_research_gap.py --observation-date 2026-07-08 --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-08 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-08 --confirm --db-path <working-copy-db> --json-output
```

## Test Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_research_gap_repository.py tests/test_live_research_gap_service.py tests/test_live_research_gap_cli.py tests/test_live_research_gap_no_trading_language.py tests/test_live_research_gap_source_matching.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_pipeline_working_copy_smoke.py tests/test_forward_performance_read_model.py tests/test_evidence_pipeline_runner.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
$files = @(Get-ChildItem app_module -Filter *.py | ForEach-Object { $_.FullName }) + @(Get-ChildItem scripts -Filter *.py | ForEach-Object { $_.FullName }); .\.venv\Scripts\python.exe -m py_compile @files
git diff --check
```

## Test Results

- Live vs Research Gap focused tests：13 passed
- Evidence working-copy / forward read model / pipeline runner regression：19 passed
- financial float boundary：exit 0
- py_compile app_module + scripts：exit 0
- git diff check：exit 0 with line-ending warnings only

## Known Limitations

- v1 不建立新的 dashboard UI。
- v1 不做完整實帳歸因。
- 沒有真實交易與人工 override 記錄時，gap 只能視為 research / simulated observation。
- Symbol / date fuzzy match 只列 candidate。
- Signal attribution confidence 必須保守。

## Not Done

- production scheduler
- Live vs Research Gap Dashboard read-only UI
- Signal Decay Monitor
- Decision Quality Review
- 自動 lifecycle action
- portfolio mutation

## Next Increment

1. Signal Decay Monitor
2. Decision Quality Review
3. Live vs Research Gap Dashboard read-only UI
4. production scheduler approval implementation only after explicit human approval

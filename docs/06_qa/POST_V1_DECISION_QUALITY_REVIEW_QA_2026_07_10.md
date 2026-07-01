# Post-V1 Decision Quality Review QA

日期：2026-07-10

## Scope

本輪新增 Decision Quality Review v1：以週 / 月 / custom 期間建立 append-only process review，檢查 portfolio / journal / evidence / live gap / signal decay 是否留下足夠流程證據。

本輪不建立 scheduler、不建立 UI、不改 portfolio、不改 Strategy Lifecycle state、不改 `ScoringEngine`、不改推薦權重，也不宣稱任何投資有效性或使用者錯誤。

## Files Changed

新增：

- `app_module/decision_quality_dtos.py`
- `app_module/decision_quality_repository.py`
- `app_module/decision_quality_service.py`
- `scripts/capture_decision_quality_review.py`
- `scripts/inspect_decision_quality.py`
- `tests/test_decision_quality_repository.py`
- `tests/test_decision_quality_service.py`
- `tests/test_decision_quality_cli.py`
- `tests/test_decision_quality_review_items.py`
- `tests/test_decision_quality_no_trading_language.py`
- `docs/superpowers/specs/2026-07-10-post-v1-decision-quality-review-design.md`
- `docs/superpowers/plans/2026-07-10-post-v1-decision-quality-review.md`
- `docs/06_qa/POST_V1_DECISION_QUALITY_REVIEW_QA_2026_07_10.md`

修改：

- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_vision_specification.md`
- `docs/07_guides/APPLICATION_MANUAL.md`

未觸碰：

- `decision_module/scoring_engine.py`
- 推薦權重契約
- portfolio mutation flow
- Strategy Lifecycle apply flow
- production scheduler / Windows Task Scheduler / cron
- UI modules

## Repository Behavior

`DecisionQualityRepository` 建立 review / item / item status history / action item tables。`review_hash` 用於 idempotent save；item status 變更會寫入 history；action item 採 append-only row。

## Service Behavior

`DecisionQualityService` 支援：

- `build_review`
- `save_review`
- `list_reviews`
- `get_review`
- `summarize_reviews`
- `mark_item_reviewed`
- `mark_item_dismissed`
- `create_action_item`

Service 只讀 portfolio / journal / evidence / live gap / signal decay，不寫 portfolio、不寫 lifecycle、不讀 UI state。

## Review Item Types

v1 覆蓋：

- `ignored_portfolio_alert`
- `manual_override_without_evidence`
- `trade_without_source_trace`
- `missed_high_quality_signal`
- `unreviewed_signal_decay`
- `large_live_research_gap`
- `low_quality_data_used`
- `regime_profile_mismatch`

每個 item 都有 suggested review question。問題只要求補充或確認流程，不輸出交易建議。

## Score Components

使用整數 bp：

- process adherence
- evidence usage
- risk discipline
- review completeness
- decision quality total

insufficient sample => `review_status=incomplete`；no journal => warning；no source trace => review gap，不代表使用者錯。

## CLI Examples

```powershell
.\.venv\Scripts\python.exe scripts\inspect_decision_quality.py --start-date 2026-06-01 --end-date 2026-06-30 --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type weekly --start-date 2026-06-24 --end-date 2026-06-30 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type monthly --start-date 2026-06-01 --end-date 2026-06-30 --confirm --db-path <working-copy-db> --json-output
```

`--confirm` 必須搭配 explicit `--db-path`；疑似正式 DB 需額外 allow flag。

## Test Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_quality_repository.py tests\test_decision_quality_service.py tests\test_decision_quality_cli.py tests\test_decision_quality_review_items.py tests\test_decision_quality_no_trading_language.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_signal_decay_service.py tests\test_live_research_gap_service.py tests\test_forward_performance_read_model.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile <expanded app_module and scripts python file list>
git diff --check
```

## Test Results

初始 TDD red：

- Decision Quality 測試因 `app_module.decision_quality_*` module 不存在而失敗，符合預期。

目前結果：

- `.\.venv\Scripts\python.exe -m pytest tests\test_decision_quality_repository.py tests\test_decision_quality_service.py tests\test_decision_quality_cli.py tests\test_decision_quality_review_items.py tests\test_decision_quality_no_trading_language.py -q -o addopts=`：16 passed。
- `.\.venv\Scripts\python.exe -m pytest tests\test_signal_decay_service.py tests\test_live_research_gap_service.py tests\test_forward_performance_read_model.py -q -o addopts=`：13 passed。
- `.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py`：exit 0。
- `.\.venv\Scripts\python.exe -m py_compile <expanded app_module and scripts python file list>`：exit 0。PowerShell 以 `Get-ChildItem app_module -Filter *.py` 與 `Get-ChildItem scripts -Filter *.py` 展開 wildcard 後傳入 `py_compile`。
- `git diff --check`：exit 0；僅出現既有 LF/CRLF 轉換 warning，無 whitespace error。

## Known Limitations

- Decision Quality Review v1 沒有 UI。
- missed high-quality signal 只在 evidence READY 且樣本足夠時產生保守 review item；它不代表漏掉進場。
- 沒有 journal 只產生 warning，不作責備。
- 沒有真實交易與人工 override linkage 時，只能檢查 simulated / unknown workflow。
- Score 是流程品質，不是投資能力。

## Scheduler Readiness

維持 `ready_for_manual_confirm`。本輪未建立正式 scheduler；production scheduler 仍需明確人工批准。

## Not Done

- 未建立 Decision Quality Dashboard UI。
- 未建立 Signal Decay Dashboard UI。
- 未建立 Live vs Research Gap Dashboard UI。
- 未啟用 production scheduler。
- 未自動套用 lifecycle action。
- 未修改 portfolio。
- 未宣稱 alpha 或任何事件類型有效。

## Next Increment

1. Decision Quality Dashboard read-only UI。
2. Signal Decay Dashboard read-only UI。
3. Live vs Research Gap Dashboard read-only UI。
4. production scheduler approval implementation only after explicit human approval。

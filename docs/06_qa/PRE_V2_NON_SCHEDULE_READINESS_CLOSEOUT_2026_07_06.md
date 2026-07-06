# Pre-V2 Non-schedule Readiness Closeout

> 日期：2026-07-06
> 範圍：V2.0 前可平行完成、非排程、非真實時間累積 gate。
> 結論：非時間型缺口已完成 working-copy closeout；剩餘項目只剩多週 weekly history、多日 dry-run 這類必須等待真實時間累積的 gate。production scheduler 仍未啟用。

## 完成項目

- Git unreachable loose objects 已清理：清理前 `count=6657`、`size=15.17 MiB`；清理後 `count=0`、`size=0 bytes`、`packs=1`、`garbage=0`。
- 清理前發現 10 個 unreachable commits，已先保留到 `refs/recovery/unreachable-*`，再執行 `git gc --prune=now`；沒有直接丟棄可疑 commit。
- 新增 `app_module/pre_v2_readiness_service.py` 與 `scripts/inspect_pre_v2_readiness.py`，可唯讀彙總 weekly history、multi-day dry-run record、source gaps 與 read-only Agent report sample。
- 補齊 RecommendationService 的 liquidity evidence：當策略結果因 `min_volume_ratio` / `volume_ratio_min` 成交量門檻而為空時，screening matrix 會標記 `liquidity_volume_ratio_below_min`，並保存 Liquidity payload。此判斷使用 `Decimal`，且沿用既有 `StrategyConfigurator` 的量比轉百分比語意。
- 在 ignored `tmp/pre_v2_source_gap_smoke/` 建立 formal DB working copy 與 output-root mirror；正式 `D:/Min/Python/Project/FA_Data/sqlite/twstock.db` 只作來源複製，不寫入正式 evidence DB。
- 使用 2026-07-03 真實 watchlist / portfolio 輸出副本與 working-copy Recommendation result 驗證 all-source source coverage：recommendation、screening matrix、why-not、liquidity、watchlist trigger、portfolio alert、risk prompt 全部 capture-ready，`blocking_gaps=[]`。
- all-source working-copy confirm smoke repeat=2 通過 idempotency：第二輪 event / outcome count 穩定，`readiness_after_smoke=ready_for_manual_confirm`。
- Evidence Review UI smoke closeout 完成：Research tab workflow suite 通過，MainWindow 可啟動、切換 8 個 top-level tabs、截圖 resize evidence、high-risk dialog cancel-only probe 未觸發 destructive action。
- read-only Agent report sample 可引用既有 evidence rows、quality、warnings、source trace、limitations 與 follow-up questions；缺 Strategy Lifecycle evidence table 時只列 diagnostic，不建立 schema。

## Working-copy Source Coverage

隔離環境：

- source DB：`D:/Min/Python/Project/FA_Data/sqlite/twstock.db`
- working-copy DB：`tmp/pre_v2_source_gap_smoke/twstock_working.db`
- smoke output-root：`tmp/pre_v2_source_gap_smoke/output`
- copied formal output inputs：`watchlist/default.json`、`portfolio/trades.jsonl`
- smoke-only recommendation result id：`pre_v2_real_recommendation_20260703_v17_payload`

關鍵結果：

- DDD snapshot `decision_date=2026-07-03`
- `sections_missing=[]`
- `sections_seen=[market_regime, market_breadth, sector_rotation, relative_strength_liquidity, watchlist_trigger, portfolio_alert, risk_prompt]`
- candidate counts：`watchlist_trigger=3`、`portfolio_alert=3`、`risk_prompt=920`
- Recommendation payload sample：`recommendations=20`、`screening_matrix_rows=120`、`why_not_rows=100`、`liquidity_gate_rows=64`
- Source coverage：`blocking_gaps=[]`、`warnings=[]`
- Capture ready：`watchlist_trigger=true`、`portfolio_alert=true`、`risk_prompt=true`、`screening_matrix=true`、`why_not=true`、`liquidity_gate=true`

## Working-copy Confirm Smoke

命令摘要：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline_working_copy.py --source-db-path D:\Min\Python\Project\FA_Data\sqlite\twstock.db --working-copy-db-path tmp\pre_v2_source_gap_smoke\twstock_working.db --decision-date 2026-07-03 --sources recommendation,watchlist-trigger,portfolio-alert,risk-prompt --repeat 2 --report-output tmp\pre_v2_source_gap_smoke\reports\all_available_sources_working_copy_smoke_after_liquidity.json --json-output --output-root tmp\pre_v2_source_gap_smoke\output
```

結果：

- `blocking_gaps=[]`
- `event_count_before=2123`
- `event_count_after_run_1=3049`
- `event_count_after_run_2=3049`
- `outcome_count_before=8492`
- `outcome_count_after_run_1=12196`
- `outcome_count_after_run_2=12196`
- `idempotency_check.passed=true`
- `readiness_after_smoke=ready_for_manual_confirm`

`overall_status=degraded` 是預期結果，原因是 2026-07-03 事件尚未累積足夠未來交易日，因此 forward outcomes 仍為 `INSUFFICIENT_SAMPLE` / `insufficient_future_data`。這不是 source coverage 缺口。

## Pre-V2 Readiness Inspector

命令摘要：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --db-path tmp\pre_v2_source_gap_smoke\twstock_working.db --research-db-path D:\Min\Python\Project\FA_Data\output\research_runs\research_runs.db --decision-date 2026-07-03 --multi-day-record-path docs\06_qa\POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md --json-output --output-root tmp\pre_v2_source_gap_smoke\output
```

結果：

| Item | Status | Evidence |
| --- | --- | --- |
| weekly_history | `waiting_for_time` | `observed_count=0` / `required_count=3` |
| multi_day_dry_run | `waiting_for_time` | `observed_count=1` / `required_count=3`，已記錄日期 `2026-07-02` |
| source_gaps | `ready` | source coverage `blocking_gaps=[]`、`warnings=[]` |
| read_only_agent_report_sample | `ready` | `observed_count=10`，只剩 `strategy_lifecycle_evidence_table_missing` diagnostic |

整體狀態：`overall_status=waiting_for_time`。

安全結論：`production_scheduler_allowed=false`。`waiting_for_time` 不可用 fixture、單次 smoke 或手動改文件取代。

## Evidence Review UI Smoke

命令摘要：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab research --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir output\qa\pre_v2_evidence_review_ui_smoke_20260706 --fail-fast
```

結果：

- Healthcheck `status=passed`
- Research suites：25 passed、6 passed、2 passed
- MainWindow smoke：啟動成功，window title `baldr`
- 切換 tabs：數據更新、市場觀察、每日決策、策略回測、推薦分析、觀察清單、持倉管理、Runtime Observatory
- `missing_tabs=[]`
- cancel-only dialog probe：`destructive_action_called=false`
- `forbidden_actions_invoked=[]`

Raw screenshots 與 result JSON 位於 ignored `output/qa/pre_v2_evidence_review_ui_smoke_20260706/`，不提交 Git；本文件只保存摘要。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_v1_7_negative_evidence.py tests\test_recommendation_exclusion_payload.py tests\test_evidence_source_coverage_service.py tests\test_evidence_source_coverage_cli.py tests\test_pre_v2_readiness_service.py tests\test_pre_v2_readiness_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_evidence_review_dashboards.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_service.py tests\test_recommendation_v1_7_negative_evidence.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
git diff --check
```

結果：

- Recommendation / source coverage / pre-v2 readiness：`18 passed`
- Evidence Review dashboard contract：`6 passed`
- `py_compile` 通過
- 量化防禦檢查通過，無 float boundary / look-ahead violation
- mypy：`Success: no issues found in 225 source files`
- `git diff --check` 無 whitespace error；僅有 Windows line ending warning

## 進 V2.0 前仍需等待或另行核准

- 多週 weekly evidence operations + history：目前 `0/3`，需繼續跨週累積。
- 3 至 5 個交易日 multi-day dry-run record：目前 `1/3`，需繼續實際交易日觀察。
- production scheduler：仍需 explicit design、backup、rollback、diagnostics 與人工 approval 文件；本 closeout 不啟用 scheduler。
- formal evidence DB confirm：本次只在 working-copy DB 驗證 all-source confirm smoke；正式 DB 寫入需另行明確批准。
- forward outcome / alpha：目前多數 2026-07-03 事件仍是 `INSUFFICIENT_SAMPLE`，不能推論投資有效性。

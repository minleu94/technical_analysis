# Healthcheck Batch 5 Performance / Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:executing-plans 依序執行本計畫。每完成一個 task 後必須跑該 task 的 verification；若測試失敗或 scope 偏離，先修正再進下一步。

**Goal:** 完成 Healthcheck Batch 5 的效能、取消、長任務可預期性與資料操作穩定性最小修復。主要落點是參數最佳化的大型範圍 UX、組合數預估、worker 數設定、SQLite / CSV 邊界說明、bounded submission 與取消訊息；Market Watch / Update 相關 issue 先做 repo evidence 排查與文件化最小界定，避免在本批引入高風險資料更新並行。

**Architecture:** 維持既有 `OptimizerService` + `ProgressTaskWorker` + `BacktestView` 架構；不改策略訊號、撮合、績效、資金帳、推薦分數或資料重建流程。最佳化仍使用 ThreadPoolExecutor，僅增加預估 / UI guard、worker 上限控制與 bounded in-flight futures，避免一次送出 8 萬多個任務。SQLite / CSV 說明只描述既有 `BacktestService._load_stock_data()` SQLite-first fallback CSV 行為。

**Tech Stack:** Python 3、PySide6、pytest、pandas、既有 Backtest / Optimizer / Update / Market Watch service boundary、Decimal / integer basis point guard。

---

## Base Branch / Commit 判斷依據

- 已執行 `git fetch --all --prune`。
- Batch 4 開始前曾確認本機工作樹 dirty 內容是前一輪 Batch 4 未提交成果；已依使用者「照你建議」先整理、驗證、commit 並 push Batch 4。
- Batch 4 已 push 分支：`origin/codex/healthcheck-batch4-research-lab-results`。
- Batch 4 commit：`d7016d32366df3e96aae094412cadb0af760e97f`，message `feat: add healthcheck batch 4 research lab results`。
- `d7016d3` 以 Batch 3 `a0e0727` 為祖先，包含 Batch 1、Batch 2、Batch 3、Batch 4，以及先前使用者已 push 的 docs / plan 更新。
- Batch 5 已從 `d7016d32366df3e96aae094412cadb0af760e97f` 開新分支：`codex/healthcheck-batch5-performance-operations`。
- 開始 Batch 5 plan 前 `git status --short --branch` 顯示工作樹乾淨。

## Scope Boundary

### In Scope

- `BACKTEST-ISSUE-010`：參數最佳化欄位寬度 / 大型範圍 UX。
  - 將範圍欄位改為較不依賴水平捲動的配置。
  - 在 UI 顯示參數組合數預估與大型掃描風險文字。
- `BACKTEST-ISSUE-011`：8 萬多組最佳化效能、worker 數、SQLite / CSV 說明、執行前預估。
  - 新增組合數估算 helper，避免只靠 materialized grid 才知道總量。
  - 新增保守 worker 數設定，限制 1 至 8。
  - 明確說明目前是 ThreadPoolExecutor、單股資料預載一次、SQLite-first fallback CSV，不宣稱 ProcessPool 或多進程。
  - 改善 `OptimizerService.grid_search()` 的任務送出策略，使用 bounded in-flight futures，避免一次 submit 所有組合。
- `BACKTEST-ISSUE-012`：大型最佳化取消流程、空錯誤訊息、UI 解鎖與安全終止提示。
  - 取消後停止提交新的參數組合。
  - 已取消 futures 不逐筆輸出空錯誤。
  - progress message 顯示取消已送出、剩餘已啟動子任務清理中。
  - UI 取消文字說明可安全等待清理；若需立即結束應關閉視窗/程序但可能放棄當次結果。
- `MARKET-ISSUE-003`：最小界定。
  - repo evidence 顯示 `StockScreener` / `IndustryMapper` 在 `config.use_sqlite=True` 時已 SQLite-first，失敗才 fallback CSV。
  - 本批不重寫 Market Watch 背景載入或快取，只在 healthcheck / Manual 記錄目前邊界與後續方向。
- `UPDATE-ISSUE-013` / `UPDATE-ISSUE-014`：最小界定。
  - 本批不新增券商分點受控並行、不改技術指標多核心計算，避免 MoneyDJ rate limit、Selenium session 與 SQLite/CSV 寫入競爭風險。
  - 在 healthcheck / Manual 記錄目前 serial / SQLite-write boundary、後續若做平行化須拆計算與單點寫入。
- 更新 `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`、`docs/07_guides/APPLICATION_MANUAL.md`、`docs/00_core/DOCUMENTATION_INDEX.md`。
- 若 Optimizer boundary 有新增 service contract，更新 `docs/01_architecture/system_architecture.md`。

### Out of Scope

- 不回頭修改 Batch 4 Research Lab 結果頁，除非 Batch 5 必要相依 bug。
- 不新增交易建議、自動下單或自動持倉調整。
- 不重建正式資料，不刪除 raw data，不跑破壞性資料更新。
- 不把最佳化改成 ProcessPool / vectorized engine / early pruning 策略搜尋，除非先另立設計與測試。
- 不新增 Market Watch 大型快取層、不改推薦分數 / Regime confidence 計算。
- 不新增券商分點下載並行、不平行寫 SQLite / CSV。

## Dirty Tree / Batch 4 Dependency Decision

- 初始檢查發現 Batch 4 分支 dirty，但 dirty files 與 Batch 4 plan / Research Lab 結果頁一致。
- 已先完成 Batch 4 focused tests、UI verification、float boundary check、mypy，並 commit/push Batch 4。
- Batch 5 不再依賴本機 dirty state；以已 push 的 Batch 4 commit `d7016d3` 為 base。
- Batch 5 不 commit / push，除非使用者另行要求。

## Look-ahead / Numeric Self-check

- 組合數預估只使用使用者在 UI 當下輸入的 min / max / step 與固定值，不讀未來行情、不改策略訊號。
- worker 數設定只影響 ThreadPool 任務排程，不改策略結果、撮合或績效公式。
- bounded futures 只改提交節奏與取消 responsiveness；單一參數組合的回測輸入、preloaded_data、actual_start_date / actual_end_date 不變。
- SQLite / CSV 說明只揭露既有資料載入路徑，不在最佳化時重建或改寫資料。
- 新增數值邏輯以整數 count、整數 worker 數與 display boundary 文字為主；不在金融核心計算加入裸 `float`。若 UI 顯示百分比或估算文字用既有 display boundary，仍需通過 `scripts/check_financial_float_boundaries.py`。

## File Map

- 修改：`app_module/optimizer_service.py`
  - 新增參數值清單 / 組合數估算 helper。
  - 新增 bounded in-flight futures 執行路徑。
  - 取消時避免空錯誤 spam，並用 progress callback 彙總清理狀態。
- 修改：`ui_qt/views/backtest/config_panel.py`
  - 新增最佳化 worker 數 spinbox。
  - 新增 ThreadPool / SQLite-first / fallback CSV / 大型掃描風險提示 label。
  - 調整最佳化範圍區塊容器尺寸與可讀性。
- 修改：`ui_qt/views/backtest_view.py`
  - 執行前顯示組合數預估與大型掃描確認。
  - 將 worker 數寫回 `OptimizerService.max_workers`。
  - 改善取消與錯誤訊息文字。
- 新增 / 修改測試：
  - `tests/test_optimizer_service.py`：組合數估算、bounded submission / cancellation focused tests。
  - `tests/test_ui_qt_research_workflow.py`：最佳化 preflight、worker spinbox、取消文字、範圍 row layout focused tests。
- 文件：
  - `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/01_architecture/system_architecture.md`（若新增 Optimizer boundary 說明）
  - `docs/00_core/DOCUMENTATION_INDEX.md`
  - `docs/superpowers/plans/2026-06-23-healthcheck-batch5-performance-operations.md`

## Rollback List

| 檔案路徑 | 變更類型 | 變更摘要 | 回滾方式 | 回滾風險 |
|---|---|---|---|---|
| `app_module/optimizer_service.py` | 修改 | 組合數估算、bounded futures、取消彙總 | `git checkout HEAD -- app_module/optimizer_service.py` | 最佳化回到一次 submit 全部任務 |
| `ui_qt/views/backtest/config_panel.py` | 修改 | worker spinbox、提示文字、最佳化區塊配置 | `git checkout HEAD -- ui_qt/views/backtest/config_panel.py` | UI 不再顯示 worker / SQLite 邊界 |
| `ui_qt/views/backtest_view.py` | 修改 | preflight、worker 寫回、取消/錯誤文字 | `git checkout HEAD -- ui_qt/views/backtest_view.py` | 大型掃描缺少預估確認 |
| `tests/test_optimizer_service.py` | 新增/修改 | Optimizer focused tests | `git checkout HEAD -- tests/test_optimizer_service.py` 或刪除新檔 | 測試覆蓋下降 |
| `tests/test_ui_qt_research_workflow.py` | 修改 | 最佳化 UI focused tests | `git checkout HEAD -- tests/test_ui_qt_research_workflow.py` | UI 回歸少一層測試 |
| `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | 修改 | Batch 5 issue 狀態與剩餘風險 | `git checkout HEAD -- docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | healthcheck 狀態回到 Batch 4 |
| `docs/07_guides/APPLICATION_MANUAL.md` | 修改 | 參數最佳化操作與安全限制 | `git checkout HEAD -- docs/07_guides/APPLICATION_MANUAL.md` | Manual 不描述新 UI |
| `docs/01_architecture/system_architecture.md` | 可能修改 | Optimizer execution boundary | `git checkout HEAD -- docs/01_architecture/system_architecture.md` | 架構文件不描述 bounded optimizer |
| `docs/00_core/DOCUMENTATION_INDEX.md` | 修改 | 新增 Batch 5 plan 索引 | `git checkout HEAD -- docs/00_core/DOCUMENTATION_INDEX.md` | plan 不在索引 |
| `docs/superpowers/plans/2026-06-23-healthcheck-batch5-performance-operations.md` | 新增 | 本計畫 | 刪除本檔 | 無資料風險 |

## TDD Steps

### Task 1: Optimizer estimation helper

- [ ] Step 1：新增 failing tests `tests/test_optimizer_service.py`
  - `test_estimate_param_grid_size_counts_int_float_and_list_ranges()`：int / float / list 組合數正確。
  - `test_estimate_param_grid_size_handles_empty_ranges_as_one_fixed_value()`：無掃描範圍時不誤報 0。
  - `test_generate_param_grid_matches_estimated_size()`：既有 materialized grid 與 estimate 一致。
- [ ] Step 2：執行 `.\.venv\Scripts\python.exe -m pytest tests\test_optimizer_service.py -q -o addopts=`，確認因 helper 不存在失敗。
- [ ] Step 3：實作 `OptimizerService.param_values_for_range()` 與 `estimate_param_grid_size()`，保留既有 `generate_param_grid()` 語意。
- [ ] Step 4：重跑同一測試。

### Task 2: Bounded futures and cancellation

- [ ] Step 1：在 `tests/test_optimizer_service.py` 增加 failing cancellation test。
  - fake backtest 讓第一批任務完成後觸發 cancel。
  - 斷言不會提交所有組合、會 raise `BacktestCancelledError`。
  - 斷言 logger 不輸出 `最佳化子任務 ... 異常:` 空訊息。
- [ ] Step 2：確認測試在現況失敗。
- [ ] Step 3：改 `grid_search()` 為 bounded in-flight queue，`max_in_flight = max(self.max_workers * 2, self.max_workers)`。
- [ ] Step 4：取消時停止 submit、cancel pending、progress callback 顯示清理訊息，並忽略 `CancelledError`。
- [ ] Step 5：重跑 optimizer focused tests。

### Task 3: Optimization UI preflight and worker setting

- [ ] Step 1：擴充 `tests/test_ui_qt_research_workflow.py`
  - worker spinbox 存在，range 1..8，預設等於 `optimizer_service.max_workers` 上限內值。
  - `_build_optimization_preflight_message()` 會包含組合數、worker 數、ThreadPool、SQLite-first、fallback CSV。
  - 大型組合數會要求確認；測試以 monkeypatch 避免實際 dialog。
  - 取消文字包含「已送出取消」與「清理已啟動子任務」。
- [ ] Step 2：確認 focused tests 失敗。
- [ ] Step 3：修改 `config_panel.py` 與 `backtest_view.py`，新增 worker spinbox、preflight helper、確認 helper、取消文案。
- [ ] Step 4：重跑 UI focused tests。

### Task 4: Docs and healthcheck

- [ ] Step 1：更新 `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - `BACKTEST-ISSUE-010` / `011` / `012` 標為 `已修正待驗證`。
  - `MARKET-ISSUE-003` 標為 `已排查待驗證`，記錄 SQLite-first evidence 與後續快取/背景載入。
  - `UPDATE-ISSUE-013` / `014` 標為 `已排查，未平行化`，記錄後續必須受控設計。
- [ ] Step 2：更新 `docs/07_guides/APPLICATION_MANUAL.md`
  - 參數最佳化 worker、組合數預估、大型掃描風險、SQLite / CSV 邊界、取消流程。
  - Market Watch / Update 效能邊界說明。
- [ ] Step 3：若 Optimizer bounded execution 成為明確 service contract，更新 `docs/01_architecture/system_architecture.md`。
- [ ] Step 4：確認 `docs/00_core/DOCUMENTATION_INDEX.md` 包含本 plan。

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_optimizer_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_workflow.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_backtest\test_parallel_safety.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\optimizer_service.py ui_qt\views\backtest\config_panel.py ui_qt\views\backtest_view.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

## Docs Update Checklist

- [x] `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`：Batch 5 issue 狀態與剩餘風險。
- [x] `docs/07_guides/APPLICATION_MANUAL.md`：參數最佳化、worker、取消、安全限制、Market/Update 邊界。
- [x] `docs/01_architecture/system_architecture.md`：bounded optimizer service contract 架構說明。
- [x] `docs/00_core/DOCUMENTATION_INDEX.md`：新增 Batch 5 plan 索引。
- [x] 依 `DOC_COVERAGE_MAP.md` 檢查是否需同步其他 UI / architecture 文件；本批以 Manual + Healthcheck + Index + Architecture 為 Must。

## Execution Summary

- [x] 已完成 Optimizer 組合數估算 helper，讓 UI preflight 與實際 grid 生成共用同一套規則。
- [x] 已完成 bounded in-flight futures：參數最佳化不再一次 submit 全部組合；取消後停止提交新組合，並將 `CancelledError` 視為正常取消。
- [x] 已完成參數最佳化 UI：1..8 worker 設定、ThreadPool / SQLite-first / fallback CSV 提示、大型掃描組合數確認、取消狀態文字與範圍列穩定寬度。
- [x] 已完成 Market Watch / Update 最小界定：Market 強弱股 / 產業確認 SQLite-first；Update 券商分點與技術指標平行化列為後續受控設計，本批不新增高風險並行。
- [x] 已同步 healthcheck、Manual、Architecture 與 Documentation Index。
- [x] 已完成 focused tests、py_compile、financial float boundary check、Update UI QA 與 mypy 驗證。

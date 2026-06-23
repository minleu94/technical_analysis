# Healthcheck Batch 6 Closeout / Regime / Research Lab Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:executing-plans 依序執行本計畫。每完成一個 task 後必須跑該 task 的 verification；若測試失敗或 scope 偏離，先修正再進下一步。

**Goal:** 收斂 Batch 1-5 後 healthcheck 母檔仍明確未完整解決的項目：Research Lab 入口 / 結果頁自動載入 / 升級後導引、healthcheck 狀態欄位一致化，以及 `MARKET-ISSUE-002` Regime confidence / 子分數計算排查。Update 受控並行仍列後續設計，不在本批直接做高風險平行化。

**Architecture:** 先處理低風險 UI / docs closeout；Regime 計算只在 characterization tests 證實「confidence 或子分數被固定成 1」時才做最小修正。不得改推薦分數、交易建議、自動下單、Portfolio 持倉或資料更新寫入策略。Research Lab auto-load 只讀既有 repositories / registry，不重新跑回測、不抓新資料。

---

## Base Branch / Commit 判斷依據

- 已完成並 push Batch 5：
  - branch：`origin/codex/healthcheck-batch5-performance-operations`
  - commit：`a0f74824e84f1a41416aff56806df10b97307d39`
  - message：`feat: add healthcheck batch 5 performance operations`
- Batch 5 包含 Batch 1 至 Batch 4 與使用者最新 docs / plan 更新。
- 已執行 `git fetch --all --prune`。
- Batch 6 已從 `a0f7482` 開新分支：`codex/healthcheck-batch6-closeout-regime-researchlab`。
- 開始 Batch 6 plan 前 `git status --short --branch` 顯示工作樹乾淨。

## Scope Boundary

### In Scope

- `BACKTEST-ISSUE-003`：推薦回放設定區寬度 / resize policy。
  - 調整推薦回放群組最小寬度、row stretch / combobox policy，避免右側內容被吃掉。
- `BACKTEST-ISSUE-004`：策略研究模式資訊架構。
  - 補強既有 Research Lab mode hint，讓策略研究模式清楚指出它用於策略模板、參數最佳化、Walk-forward 與升級證據整理。
- `BACKTEST-ISSUE-021`：歷史 / 比較 / Registry / 舊圖表首次進入自動載入。
  - `result_tabs.currentChanged` 時首次進入「歷史與比較」自動 `_refresh_history()`。
  - 首次進入「圖表」自動 `_update_chart_run_combo()`，若有既有 run 則載入第一筆或保持目前選擇。
  - Registry 比較頁沿用 Batch 4 的 first-show refresh，並確保 `BacktestView._refresh_research_registry()` 不需手動按鈕才能更新入口。
- `BACKTEST-ISSUE-023`：推薦回放 / 單股升級策略版本後導引。
  - 升級完成訊息與狀態列明確說明：版本 ID、來源 run、可在推薦分析 Profile / 策略版本相關入口看到，並提醒需刷新或重新選 Profile。
- Healthcheck status normalization。
  - 將已在 Batch 1-5 實作但 issue 狀態欄仍為 `新增` 的 rows 更新為 `已修正待驗證` 或 `部分修正待驗證`。
  - 不把需要使用者重測的項目改成 `通過`。
- `MARKET-ISSUE-002`：Regime confidence / 子分數排查。
  - 新增 characterization tests 覆蓋不同 market index shape，確認 confidence / details 子分數不是固定 1。
  - 若現有計算確實固定輸出 1，做最小修正：讓 confidence 反映 winning score margin / feature evidence coverage，而非把 normalized score 直接視為 certainty。
  - 若計算已動態但 UI 文案誤導，僅修正 UI / Manual / healthcheck 文案。

### Out of Scope

- `UPDATE-ISSUE-013` 券商分點受控並行：仍為後續設計，不在 Batch 6 實作。
- `UPDATE-ISSUE-014` 技術指標多核心：仍為後續設計，不在 Batch 6 實作。
- 不重跑正式資料、不刪除 raw data、不做 SQLite / CSV destructive migration。
- 不新增交易建議、自動下單、自動持倉調整。
- 不大改 Research Lab layout 或重建結果頁，只做最小 closeout。

## Look-ahead / Numeric Self-check

- Research Lab auto-load 只讀已保存 run metadata / chart payload / repository，不重新抓目前資料補舊 run。
- Regime characterization tests 使用測試資料或既有 market index rows，只驗證當下可見資料形成的 score；不得用未來資料校準 confidence。
- 若修 Regime confidence，使用整數 basis point 或 `Decimal` / existing presentation boundary；避免在金融核心新增裸 `float`。若只是 UI 顯示百分比，需清楚隔離並跑 float boundary check。

## File Map

- 可能修改：`ui_qt/views/backtest/result_panel.py`
  - result tabs currentChanged hook。
  - 推薦回放 / 策略研究相關控件尺寸。
- 可能修改：`ui_qt/views/backtest/config_panel.py`
  - Research Lab mode hint / recommendation replay group sizing。
- 可能修改：`ui_qt/views/backtest_view.py`
  - `_on_result_tab_changed()`、history/chart first-load guards、promotion completion guidance。
- 可能修改：`decision_module/market_regime_detector.py`
  - 只在 tests 證實 confidence 固定或子分數固定時做最小修正。
- 可能修改 / 新增測試：
  - `tests/test_ui_qt_research_workflow.py`
  - `tests/test_market_regime_detector.py` 或既有 Regime tests。
- 文件：
  - `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/01_architecture/system_architecture.md`（若 Regime confidence contract 改變）
  - `docs/00_core/DOCUMENTATION_INDEX.md`
  - 本 plan。

## Rollback List

| 檔案路徑 | 變更類型 | 回滾方式 | 風險 |
|---|---|---|---|
| `ui_qt/views/backtest/result_panel.py` | 可能修改 | `git checkout HEAD -- ui_qt/views/backtest/result_panel.py` | 移除 tab auto-load hook |
| `ui_qt/views/backtest/config_panel.py` | 可能修改 | `git checkout HEAD -- ui_qt/views/backtest/config_panel.py` | 推薦回放 / 策略研究提示回到 Batch 5 |
| `ui_qt/views/backtest_view.py` | 可能修改 | `git checkout HEAD -- ui_qt/views/backtest_view.py` | 歷史 / 圖表 / 升級導引回到 Batch 5 |
| `decision_module/market_regime_detector.py` | 可能修改 | `git checkout HEAD -- decision_module/market_regime_detector.py` | Regime confidence 修正回滾 |
| `tests/test_ui_qt_research_workflow.py` | 修改 | `git checkout HEAD -- tests/test_ui_qt_research_workflow.py` | UI closeout 覆蓋下降 |
| `tests/test_market_regime_detector.py` | 可能新增 | 刪除新檔 | Regime confidence 覆蓋下降 |
| `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | 修改 | `git checkout HEAD -- docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | healthcheck 狀態回到 Batch 5 |
| `docs/07_guides/APPLICATION_MANUAL.md` | 可能修改 | `git checkout HEAD -- docs/07_guides/APPLICATION_MANUAL.md` | Manual 缺少 Batch 6 closeout |
| `docs/01_architecture/system_architecture.md` | 可能修改 | `git checkout HEAD -- docs/01_architecture/system_architecture.md` | 架構文件不描述 Regime confidence contract |
| `docs/00_core/DOCUMENTATION_INDEX.md` | 修改 | `git checkout HEAD -- docs/00_core/DOCUMENTATION_INDEX.md` | plan 不在索引 |
| `docs/superpowers/plans/2026-06-23-healthcheck-batch6-closeout-regime-researchlab.md` | 新增 | 刪除本檔 | 無資料風險 |

## TDD Steps

### Task 1: Research Lab result tab first-load

- [ ] 新增 failing tests：
  - 首次切到「歷史與比較」呼叫 `_refresh_history()`。
  - 首次切到「圖表」呼叫 `_update_chart_run_combo()`。
  - 重複切換不重複刷到造成 UI jitter。
- [ ] 實作 `BacktestView._on_result_tab_changed()` 與 first-load guards。
- [ ] 重跑 `tests/test_ui_qt_research_workflow.py` focused tests。

### Task 2: Recommendation replay / strategy research closeout

- [ ] 新增 failing tests：
  - 推薦回放群組 / history combo / buttons 有穩定最小寬度或 expanding policy。
  - 策略研究 mode hint 包含「策略模板」「參數最佳化」「Walk-forward」「升級證據」。
  - 推薦回放升級完成訊息包含版本 ID 與後續查看入口。
- [ ] 實作最小 UI / wording。
- [ ] 重跑 focused tests。

### Task 3: Regime confidence characterization

- [ ] 新增 tests 以合成 market index data 驗證：
  - 明顯 trend / range / breakout-like 資料的 `confidence` 應落在 0..1。
  - details 中 structure / strength / distance / confidence 不應在所有情境都固定 1。
- [ ] 若測試顯示固定 1，修正 `MarketRegimeDetector` confidence / details 計算。
- [ ] 若計算已動態，改 healthcheck 為「計算排查完成待使用者重測」並補 Manual 文案。

### Task 4: Docs closeout

- [ ] 更新 healthcheck：
  - Batch 6 完成的 backtest rows 改 `已修正待驗證`。
  - `MARKET-ISSUE-002` 根據 characterization 結果更新。
  - `UPDATE-ISSUE-013/014` 保持後續設計，不宣稱已修。
- [ ] 更新 Manual / Architecture（若行為或 Regime contract 有變）。
- [ ] 更新 Documentation Index。

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_workflow.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_market_regime_detector.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest\result_panel.py ui_qt\views\backtest\config_panel.py ui_qt\views\backtest_view.py decision_module\market_regime_detector.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

## Docs Update Checklist

- [x] `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
- [x] `docs/07_guides/APPLICATION_MANUAL.md`
- [x] `docs/01_architecture/system_architecture.md`（未改 Regime 計算 contract 或模組邊界，無需更新）
- [x] `docs/00_core/DOCUMENTATION_INDEX.md`

## Execution Log（2026-06-23）

- [x] Task 1：Research Lab 結果子頁首次進入時自動載入。
  - 新增測試覆蓋歷史、圖表子頁首次進入只 refresh 一次。
  - 實作 `BacktestView._on_result_tab_changed()`，首次進入歷史與比較會 `_refresh_history()`，首次進入圖表會 `_update_chart_run_combo()`，Registry 比較 widget 若存在會 refresh。
- [x] Task 2：推薦回放 / 策略研究 closeout。
  - 策略研究 mode hint 補上策略模板、參數最佳化、Walk-forward 與升級證據。
  - 推薦回放設定群組與歷史紀錄下拉加入穩定最小寬度。
  - 推薦回放升級完成訊息補版本 ID、來源 run 與推薦分析 Profile / 策略版本入口提示。
- [x] Task 3：Regime confidence characterization。
  - 排查結論：現有 `MarketRegimeDetector` 的 confidence / subscore 是 0~1 規則匹配分，不是機率或未來勝率。
  - 本批不改核心分類計算；UI 改顯示「規則匹配度」，技術細節將 `trend_confidence` 顯示為「趨勢規則分」，並用 tooltip / Manual 說明 100% 只代表規則上限。
- [x] Task 4：Docs closeout。
  - 已更新 healthcheck 母檔、Manual 與 Documentation Index。
  - Architecture 未更新，因本批沒有改 Regime 計算 contract 或模組邊界，只改 UI 顯示語意。

## Verification Result（2026-06-23）

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_workflow.py -q -o addopts=
# 25 passed

.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_market_regime_view.py -q -o addopts=
# 2 passed

.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_run_registry_compare.py -q -o addopts=
# 6 passed

.\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest\config_panel.py ui_qt\views\backtest_view.py ui_qt\views\market_regime_view.py tests\test_ui_qt_research_workflow.py tests\test_ui_qt_market_regime_view.py
# passed

.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
# passed

.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
# 35 passed

.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
# 通過 24、失敗 0、跳過 4

.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
# Success: no issues found in 214 source files
```

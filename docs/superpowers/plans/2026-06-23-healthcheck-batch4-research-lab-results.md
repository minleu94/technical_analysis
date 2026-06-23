# Healthcheck Batch 4 Research Lab Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:executing-plans 依序執行本計畫。每完成一個 task 後必須跑該 task 的 verification；若測試失敗或 scope 偏離，先修正再進下一步。

**Goal:** 完成 Healthcheck Batch 4 的 Research Lab 結果頁修復：推薦回放結果頁重排、Registry 比較頁重設計、批次比較判讀、Train-Test / Walk-forward 樣本可靠度提示，並更新 healthcheck 狀態。

**Architecture:** 只新增結果呈現與可靠度判讀的薄型 helper / UI 組裝，不重跑回測、不重新抓目前資料、不修改 `ScoringEngine`、不改撮合 / PnL / 推薦核心邏輯。Registry 比較只讀已保存 `ResearchRunMetadataDTO`、equity curve 與 benchmark metadata；Train-Test / Walk-forward 提示只使用當次結果已提供的 fold、OOS trades、coverage 與 metrics。

**Tech Stack:** Python 3、PySide6、pytest、pandas、Decimal / integer basis point boundary、既有 `BacktestView` / `BacktestResultPanel` / `RunRegistryCompareWidget`。

---

## Base Branch / Commit 判斷依據

- 已執行 `git fetch --all --prune`。
- 已檢查 `git status --short --branch`：開分支前工作樹乾淨，位於 `codex/healthcheck-batch3-recommendation-profile-regime`。
- 已檢查 `git branch -vv` 與 `git log --oneline --decorate --graph --all --max-count=40`。
- `origin/codex/healthcheck-batch3-recommendation-profile-regime` tip 為 `a0e07273c1827f2b9c04ce1116a6b2a4465c38fb`，commit message 為 `feat: add healthcheck batch 3 recommendation profiles`。
- `origin/main` / `origin/codex/non-destructive-healthcheck-plan` tip 為 `298d613 docs: add non-destructive healthcheck runner plan`，從共同祖先 `79c9f5e` 只新增 `docs/superpowers/plans/2026-06-23-non-destructive-release-healthcheck-runner.md`。
- `a0e0727` 不是 `298d613` 的後代，但 `a0e0727` 的 tree 已包含 `docs/superpowers/plans/2026-06-23-non-destructive-release-healthcheck-runner.md`，因此實際內容已包含使用者最新 push 的 docs / plan 更新。
- `a0e0727` 也包含 Batch 1 commit `0e9a29a`、Batch 2 commit `938ad47` 與 Batch 3 實作 / 文件。
- 因此 Batch 4 base 選擇 `origin/codex/healthcheck-batch3-recommendation-profile-regime` 的 `a0e0727`，並已建立分支 `codex/healthcheck-batch4-research-lab-results`。

## Scope Boundary

### In Scope

- `BACKTEST-ISSUE-015`：推薦回放結果頁重排。
  - 摘要改為一次性、分區清楚的概況 / 風險 / 統計說明，不再 append 造成重複摘要。
  - 圖表、期間明細、個股貢獻、交易紀錄放入可掃描的子分頁或分組，避免底部內容被吃掉。
  - 補「資金使用」「Monte Carlo P05 / P50 / P95」中文語意與單位。
- `BACKTEST-ISSUE-024`：Registry 比較頁重設計。
  - run type 篩選與列表中文化，保存 raw code 在 tooltip / data role。
  - 參數差異、Metrics、Regime、Benchmark、Normalized Equity 改為中文標題與空狀態說明。
  - comparability badge 顯示中文狀態：可直接比較 / 需謹慎比較 / 不可直接比較。
  - 進入頁面時自動載入 registry runs，避免使用者以為沒有資料。
- `BACKTEST-ISSUE-022`：批次比較判讀。
  - 批次結果頁補比較目的提示：用來比較同一批股票中的報酬、風險、交易數、回撤與資料可比性，不代表直接買賣排序。
  - Registry 比較頁補「比較前先看可比性」說明。
- `BACKTEST-ISSUE-013`：Train-Test / Walk-forward 樣本可靠度提示。
  - Train-Test 顯示 train / test 交易數、測試集交易數不足提示、不直覺組合診斷。
  - Walk-forward 顯示 fold 數、OOS 交易數、positive fold coverage / confidence 文案。
  - fold 數 < 3、OOS trade count < 20、coverage 不足、勝率 100% 但最大回撤極大時，顯示「樣本不足，不宜作正式策略判斷」。
- `BACKTEST-ISSUE-003` / `BACKTEST-ISSUE-004` / `BACKTEST-ISSUE-021` / `BACKTEST-ISSUE-023` 中與結果頁可讀性、結果頁自動刷新、保存 / 升級後導引直接相關的最小修復。
- 更新 `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`。
- 因使用者可見結果判讀變更，更新 `docs/07_guides/APPLICATION_MANUAL.md`。
- 若新增 presentation helper 或比較 helper 邊界，更新 `docs/01_architecture/system_architecture.md`。
- 更新 `docs/00_core/DOCUMENTATION_INDEX.md`。

### Out of Scope

- 不處理 Batch 5 效能 / 計算排查：
  - `BACKTEST-ISSUE-010` 最佳化欄位寬度與大型參數範圍 UX。
  - `BACKTEST-ISSUE-011` ProcessPool / vectorized / worker 數 / SQLite vs CSV 效能。
  - `BACKTEST-ISSUE-012` 8 萬組參數掃描取消流程。
  - `MARKET-ISSUE-002`、`MARKET-ISSUE-003`、`UPDATE-ISSUE-013`、`UPDATE-ISSUE-014`。
- 不新增交易建議、自動下單、自動持倉調整。
- 不改回測撮合、績效計算、資金帳、推薦分數、Strategy lifecycle gate 或 Portfolio 行為。
- 不做 SQLite migration、正式資料 apply、CSV 重建或 destructive cleanup。
- 不把 fundamental factor 接入 `ScoringEngine`。

## Look-ahead / Numeric Self-check

- 推薦回放結果頁只展示 `result.summary`、`period_holdings_dataframe()`、`stock_contribution_dataframe()`、`trades`、`equity_curve` 與已存在 credibility / gap / liquidity metadata，不重新計算決策訊號或未來報酬。
- Registry 比較只讀已保存 run metadata、已保存 equity curve 與 benchmark results，不重新抓取目前資料，不用今天資料補舊 run。
- Train-Test / Walk-forward 可靠度提示只使用當次結果中的 train / test metrics、fold 數、OOS trade count、coverage / consistency；不回讀後續行情，不以未來資料補樣本。
- 新增數值判讀以整數 count、整數 basis point 或既有 DTO metric 展示為主；若 UI 呈現需格式化百分比，只在 presentation boundary 做字串格式化。
- 不在金融核心白名單新增裸 `float` 計算；本批預期只觸碰 UI / app presentation helper，但仍必跑 `scripts/check_financial_float_boundaries.py`。

## File Map

- 可能新增：`app_module/research_result_presentation.py`
  - `build_recommendation_replay_sections(result)`：整理推薦回放概況、交易假設、風險限制、Monte Carlo 說明。
  - `build_train_test_reliability_notice(train_report, test_report)`：回傳可追溯 evidence 與中文提示。
  - `build_walkforward_reliability_notice(results, summary)`：回傳 fold / OOS / coverage / confidence 文案。
- 修改：`ui_qt/views/backtest/result_panel.py`
  - 推薦回放 tab 改為摘要 + 圖表 + 明細子分頁。
  - 批次結果頁新增判讀提示。
  - Registry compare tab 掛載後保留自動刷新入口。
- 修改：`ui_qt/views/backtest_view.py`
  - `_show_recommendation_portfolio_result()` 改用 presentation helper，一次性設定摘要。
  - `_on_walkforward_finished()` 加入 Train-Test / Walk-forward reliability notice。
  - `_refresh_research_registry()` 或 tab 切換時確保 history / chart / registry 首次載入。
- 修改：`ui_qt/views/research_lab/run_registry_compare_widget.py`
  - 中文化 run type label / filter / table section title / status badge。
  - 空 normalized equity、空 metrics、空 benchmark 顯示中文空狀態。
  - `showEvent()` 首次自動 refresh。
- 可能修改：`app_module/research_run_comparison_service.py`
  - 若需要將 `ComparabilityStatus` 中文 label 或 empty normalized equity diagnosis 下放到 service，保持 DTO / metadata-only。
- 新增 / 修改測試：
  - `tests/test_research_result_presentation.py`
  - `tests/test_ui_qt_recommendation_portfolio_results.py`
  - `tests/test_ui_qt_run_registry_compare.py`
  - `tests/test_ui_qt_research_workflow.py`
  - `tests/test_research_run_comparison_service.py`
- 文件：
  - `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/01_architecture/system_architecture.md`（若新增 helper 邊界）
  - `docs/00_core/DOCUMENTATION_INDEX.md`

## Rollback List

| 檔案路徑 | 變更類型 | 變更摘要 | 回滾方式 | 回滾風險 |
|---|---|---|---|---|
| `app_module/research_result_presentation.py` | 新增 | 結果呈現與可靠度提示 helper | 刪除檔案：`Remove-Item -LiteralPath app_module\research_result_presentation.py` | 需同步還原呼叫端 import |
| `ui_qt/views/backtest/result_panel.py` | 修改 | 推薦回放 tab、批次提示、Registry 掛載行為 | `git checkout HEAD -- ui_qt/views/backtest/result_panel.py` | 會移除 Batch 4 UI 重排 |
| `ui_qt/views/backtest_view.py` | 修改 | 推薦回放摘要、Walk-forward 提示、registry refresh | `git checkout HEAD -- ui_qt/views/backtest_view.py` | 會移除 Batch 4 結果判讀 |
| `ui_qt/views/research_lab/run_registry_compare_widget.py` | 修改 | Registry 比較中文化與自動載入 | `git checkout HEAD -- ui_qt/views/research_lab/run_registry_compare_widget.py` | Registry 比較回到 Batch 3 顯示 |
| `app_module/research_run_comparison_service.py` | 可能修改 | 比較呈現 label / empty diagnosis | `git checkout HEAD -- app_module/research_run_comparison_service.py` | 若 UI 依賴 helper，需一併回滾 |
| `tests/test_research_result_presentation.py` | 新增 | helper TDD 覆蓋 | 刪除檔案：`Remove-Item -LiteralPath tests\test_research_result_presentation.py` | 無資料風險 |
| `tests/test_ui_qt_recommendation_portfolio_results.py` | 新增 | 推薦回放結果頁 UI TDD | 刪除檔案：`Remove-Item -LiteralPath tests\test_ui_qt_recommendation_portfolio_results.py` | 無資料風險 |
| `tests/test_ui_qt_run_registry_compare.py` | 修改 | Registry 比較 UI 行為測試 | `git checkout HEAD -- tests/test_ui_qt_run_registry_compare.py` | 測試覆蓋回到 Batch 3 |
| `tests/test_ui_qt_research_workflow.py` | 修改 | Walk-forward / batch 判讀測試 | `git checkout HEAD -- tests/test_ui_qt_research_workflow.py` | 測試覆蓋回到 Batch 3 |
| `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | 修改 | Batch 4 issue 狀態 | `git checkout HEAD -- docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | healthcheck 狀態回到 Batch 3 |
| `docs/07_guides/APPLICATION_MANUAL.md` | 修改 | Research Lab 結果判讀說明 | `git checkout HEAD -- docs/07_guides/APPLICATION_MANUAL.md` | Manual 不再描述 Batch 4 行為 |
| `docs/01_architecture/system_architecture.md` | 可能修改 | presentation helper 邊界 | `git checkout HEAD -- docs/01_architecture/system_architecture.md` | 架構文件不再描述 Batch 4 helper |
| `docs/00_core/DOCUMENTATION_INDEX.md` | 修改 | 新增 Batch 4 plan 索引 | `git checkout HEAD -- docs/00_core/DOCUMENTATION_INDEX.md` | 索引移除 Batch 4 plan |
| `docs/superpowers/plans/2026-06-23-healthcheck-batch4-research-lab-results.md` | 新增 | 本計畫 | 刪除檔案：`Remove-Item -LiteralPath docs\superpowers\plans\2026-06-23-healthcheck-batch4-research-lab-results.md` | 無資料風險 |

## TDD Steps

### Task 1: Research result presentation helper

- [ ] Step 1：新增 failing tests `tests/test_research_result_presentation.py`
  - `test_recommendation_replay_sections_explain_capital_and_monte_carlo()`：期望輸出「資金使用代表期間投入金額，不等同最終淨值」與 `P05 / P50 / P95` 中文說明。
  - `test_train_test_reliability_warns_when_oos_trades_are_low()`：測試集 `total_trades < 20` 時輸出「樣本不足，不宜作正式策略判斷」，evidence 包含 `test_trades`。
  - `test_walkforward_reliability_warns_when_folds_below_three()`：`total_folds=2` 時輸出 fold 數不足與 coverage 說明。
  - `test_reliability_flags_perfect_win_rate_with_large_drawdown()`：勝率 100% 且 MDD 絕對值大於 50% 時輸出不直覺指標診斷。
- [ ] Step 2：執行 `.\.venv\Scripts\python.exe -m pytest tests\test_research_result_presentation.py -q -o addopts=`，確認因 module / function 不存在而失敗。
- [ ] Step 3：實作 `app_module/research_result_presentation.py`，僅做 DTO / dict / dataclass → 中文 sections，不重新計算策略。
- [ ] Step 4：重跑同一測試，確認通過。

### Task 2: Recommendation replay result page layout

- [ ] Step 1：新增 failing tests `tests/test_ui_qt_recommendation_portfolio_results.py`
  - 建立 fake result，呼叫 `BacktestView._show_recommendation_portfolio_result()`。
  - 斷言 summary 不重複出現 `總報酬率`。
  - 斷言 summary 包含「概況」、「交易假設與可信度」、「Monte Carlo 情境」。
  - 斷言推薦回放頁內有 detail tab 或可識別分組：`圖表`、`期間明細`、`個股貢獻`、`交易紀錄`。
- [ ] Step 2：執行 `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_portfolio_results.py -q -o addopts=`，確認失敗。
- [ ] Step 3：修改 `BacktestResultPanel` 的推薦回放 tab，將圖表與三張表放入內層 `QTabWidget`，摘要固定高度但不吃掉下方內容。
- [ ] Step 4：修改 `BacktestView._show_recommendation_portfolio_result()` 使用 helper 一次性產生 summary。
- [ ] Step 5：重跑推薦回放結果頁測試與 `tests/test_ui_qt_research_workflow.py::test_backtest_view_recommendation_portfolio_summary_warns_about_same_day_close`。

### Task 3: Registry comparison redesign

- [ ] Step 1：擴充 failing tests `tests/test_ui_qt_run_registry_compare.py`
  - 斷言 run type filter 顯示「單股回測」「推薦回放」，但 data 仍為 `single_backtest` / `recommendation_portfolio`。
  - 斷言 compare badge 顯示「可直接比較」而不是 `Comparable`。
  - 斷言 tables titles 顯示「指標」「市場 Regime」「Benchmark 基準」「標準化權益」。
  - 斷言空 normalized equity 時顯示「沒有共同日期可標準化比較」。
  - 斷言 `showEvent()` 第一次會呼叫 `refresh_runs()`。
- [ ] Step 2：執行 `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_run_registry_compare.py -q -o addopts=`，確認新 assertions 失敗。
- [ ] Step 3：修改 `RunRegistryCompareWidget`，加入中文 label mapping、tooltip/raw code、empty frame message 與 first-show refresh guard。
- [ ] Step 4：若 service 需要補中文 status label，修改 `ResearchRunComparisonService` 但保持 metadata-only。
- [ ] Step 5：重跑 registry focused tests 與 `tests/test_research_run_comparison_service.py`。

### Task 4: Batch comparison and Train-Test / Walk-forward interpretation

- [ ] Step 1：擴充 failing tests `tests/test_ui_qt_research_workflow.py`
  - 批次結果頁存在「比較目的」說明。
  - Train-Test 完成 summary 包含 OOS 交易數與可靠度提示。
  - Walk-forward 完成 summary 包含 fold 數、OOS 交易數與「樣本不足」提示。
- [ ] Step 2：執行 focused pytest，確認失敗。
- [ ] Step 3：在 `BacktestResultPanel` 批次結果頁加入小型唯讀說明 label。
- [ ] Step 4：在 `BacktestView._on_walkforward_finished()` 將 helper notice append 到 Train-Test / Walk-forward summary。
- [ ] Step 5：重跑 focused pytest。

### Task 5: Docs and healthcheck

- [ ] Step 1：更新 `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - `BACKTEST-ISSUE-013`、`015`、`022`、`024` 改為 `已修正待驗證`。
  - `BACKTEST-ISSUE-003`、`004`、`021`、`023` 若僅部分處理，保留剩餘項描述，不宣稱驗證通過。
- [ ] Step 2：更新 `docs/07_guides/APPLICATION_MANUAL.md`
  - Research Lab 結果頁、Registry 比較、推薦回放、Train-Test / Walk-forward 判讀、安全限制。
- [ ] Step 3：若新增 `app_module/research_result_presentation.py`，更新 `docs/01_architecture/system_architecture.md`，說明它是 presentation boundary，不重算策略。
- [ ] Step 4：確認 `docs/00_core/DOCUMENTATION_INDEX.md` 已包含本 plan。

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_result_presentation.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_portfolio_results.py tests\test_ui_qt_run_registry_compare.py tests\test_ui_qt_research_workflow.py tests\test_research_run_comparison_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_view_charts.py tests\test_recommendation_portfolio_backtest.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\research_result_presentation.py ui_qt\views\backtest\result_panel.py ui_qt\views\backtest_view.py ui_qt\views\research_lab\run_registry_compare_widget.py app_module\research_run_comparison_service.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

## Docs Update Checklist

- [x] `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`：Batch 4 issue 狀態與剩餘範圍。
- [x] `docs/07_guides/APPLICATION_MANUAL.md`：Research Lab 結果頁、Registry 比較、推薦回放、Train-Test / Walk-forward 判讀與安全限制。
- [x] `docs/01_architecture/system_architecture.md`：若新增 presentation helper，補結果呈現邊界。
- [x] `docs/00_core/DOCUMENTATION_INDEX.md`：加入 Batch 4 plan 索引。
- [x] 依 `DOC_COVERAGE_MAP.md` 檢查 UI / service 變更是否需同步 `UI_FEATURES_DOCUMENTATION.md` 或 `PROJECT_NAVIGATION.md`；本次行為屬既有 Research Lab 結果頁判讀改善，以 Manual + Architecture + Healthcheck 為最小 Must。

## Execution Summary

- [x] 已完成推薦回放結果頁重排：摘要改為一次性段落輸出，圖表、期間明細、個股貢獻與交易紀錄改放入內部分頁。
- [x] 已完成 Registry 比較頁重設計：run type 與 badge 中文化、表格群組中文化、Normalized Equity 空狀態、首次顯示自動 refresh。
- [x] 已完成批次比較判讀：批次結果頁新增比較目的與安全限制說明。
- [x] 已完成 Train-Test / Walk-forward 樣本可靠度提示：只使用既有 result / fold / OOS metadata，不重新抓資料或重算績效。
- [x] 已同步 healthcheck、Manual、Architecture 與 Documentation Index。
- [x] 已執行 focused tests、py_compile、financial float boundary check、AGENTS UI 驗證與 mypy。

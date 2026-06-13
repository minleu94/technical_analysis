# Fixed vs Quantile 驗證報告

## 1. 驗證狀態

本文件記錄 Strategy & Scoring Governance 的機制與回歸驗證。

目前已完成：

- fixed 模式訊號相容性測試。
- quantile Expanding T-1、60 個有效觀測暖機與未來資料不變性測試。
- 推薦 eligible universe empirical CDF、同分同百分位、穩定排序與最小母體防禦測試。
- DTO / Preset / StrategyVersion round-trip。
- UI、mypy、金融 float boundary 與資料更新工作台 QA。

目前尚未完成：

- 使用指定真實股票池、資料截止日、交易成本與 walk-forward 分割，產出 fixed / quantile 的報酬、最大回撤、Sharpe、交易次數及 regime 穩定性比較。

因此，本報告不能用來宣稱 quantile 已改善績效、穩健度或統計顯著性，也不能作為把 quantile 設為預設模式的依據。

## 2. 已驗證契約

### 2.1 回測時間序列

- 未提供 `threshold_mode` 時等同 `fixed`。
- fixed 使用原始分數與 `buy_score` / `sell_score` 比較，不以量化結果改變訊號。
- quantile 的 T 日門檻只使用 T-1 以前的有效 `score_bp`。
- 暖機期固定為 60 個有效觀測值；第 61 個有效觀測才可判定。
- `buy_quantile_bp` 必須大於 `sell_quantile_bp`。
- `quantile_method` 第一版只接受 `nearest_rank`。
- 在序列尾端附加未來資料，不得改變既有日期的門檻與訊號。

### 2.2 推薦橫斷面

- 缺少 `recommendation_ranking` 時維持 fixed 排序。
- quantile 必須明確提供最低百分位、最小母體與排名方法。
- empirical CDF 使用 `bisect_right`，同分股票取得相同百分位。
- 百分位母體在套用 `top_n` 前建立。
- 母體不足時拋出 `RecommendationUniverseTooSmallError`，不降級為 fixed。
- 最終排序為 `total_score desc, stock_code asc`。

## 3. Fresh Verification

2026-06-13 收尾驗收結果：

- 核心、相容與整合測試：`82 passed`，另有 7 個既有的理想化同日收盤成交假設警告。
- 數據更新工作台 UI：`9 passed`。
- 金融 float boundary 測試：`37 passed`。
- Update Tab QA：`21 passed, 0 failed, 4 skipped`。
- Mypy：`Success: no issues found in 144 source files`。
- AST float boundary 掃描、`py_compile` 與 `git diff --check`：通過。
- 驗收修正提交：`7d94c35`。

重驗命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_score_threshold_policy.py tests\test_strategy_threshold_modes.py tests\test_backtest_diagnostics_and_date_adjustment.py tests\test_recommendation_percentile_ranker.py tests\test_recommendation_ranking_service.py tests\test_recommendation_dto_roundtrip.py tests\test_recommendation_portfolio_backtest.py tests\test_ui_qt_research_workflow.py tests\test_strategy_params_persistence_roundtrip.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_financial_float_boundary_checker.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

## 4. 實證比較待辦

正式 walk-forward 比較至少要固定：

- 股票池與資料版本。
- 訓練、驗證、測試窗口。
- 資料截止日。
- 手續費、滑價與成交價格假設。
- fixed / quantile 除門檻以外完全相同的策略設定。
- 報酬、最大回撤、Sharpe、交易次數、暖機後有效日數、推薦通過率與換手。

完成上述實證前，quantile 維持 opt-in。

# 歷史手動驗證腳本

此目錄保存早期探索性、互動式或依賴真實環境的驗證腳本，不屬於自動化
pytest 契約，也不保證可直接執行。

## 已整併移除的診斷

2026-09-07 移除 `legacy_diagnostics/` 的七份一次性腳本及重複 README：
四份硬編碼 CSV 欄位列印、兩份外部 API／正式目錄診斷，以及引用已不存在
`test_data_module` 的 runner。它們不是自動化測試，也沒有產品呼叫者。
精確清單、備份與驗證見[專案整併查核](../../docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md)。
原內容仍可由查核基線 Git commit 還原；不要恢復為預設 pytest 測試。
技術指標與欄位行為請使用 `tests/test_analysis/` 與
`tests/test_pattern_analysis/` 的合成資料測試；真實來源診斷須使用目前服務及
明確的隔離資料／輸出目錄。

## 棄用與隔離原因

- 部分腳本引用從未成為正式 API 的 `DataConfig`、`DataProcessor`。
- 部分腳本使用舊的扁平匯入路徑，例如
  `analysis_module.pattern_analyzer`，現行實作位於領域子套件。
- 部分腳本依賴固定 `D:/...` 資料路徑、外部網路、互動式 `input()`、
  長時間模型訓練或繪圖視窗，不適合作為 CI 測試。
- 腳本中的資料清理、特徵與技術分析責任，現已由
  `TWStockConfig`、`DataLoader`、`TechnicalIndicatorCalculator`、
  `PatternAnalyzer`、`TechnicalAnalyzer` 與應用服務分工承接。

正式自動測試應使用合成資料、`tmp_path` 與現行公開 API。若要恢復此處任一
情境，應先拆成可重現的單元或整合測試，而不是重新加入 pytest 自動收集。

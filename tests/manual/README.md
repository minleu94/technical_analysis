# 歷史手動驗證腳本

此目錄保存早期探索性、互動式或依賴真實環境的驗證腳本，不屬於自動化
pytest 契約，也不保證可直接執行。

## 棄用原因

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

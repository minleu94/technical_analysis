# 歷史手動驗證腳本

此目錄保存早期探索性、互動式或依賴真實環境的驗證腳本，不屬於自動化
pytest 契約，也不保證可直接執行。

## 子目錄說明

* **[legacy_diagnostics](legacy_diagnostics/)**：保存 7 個被搬移的遺留診斷腳本（含硬編碼 `D:/...` 路徑、外部 API 請求、舊模組名稱引用或診斷日誌輸出）。
  > [!NOTE]
  > 本期為確保測試清冊治理之正確性，僅針對此 7 個 legacy candidates 進行有限度的移轉，不做整個 tests/ 目錄的重構或大範圍調整，以維持現有測試穩定與路徑正確。

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

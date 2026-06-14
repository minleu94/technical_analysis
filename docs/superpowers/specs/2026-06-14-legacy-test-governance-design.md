# Legacy Test Governance Design

## 目標

讓 repository 自動測試只驗證現行正式 API，移除自初始 commit 即不存在的
`DataConfig`、`DataProcessor` 與錯誤扁平模組路徑，並將依賴人工輸入、外部網路、
固定正式資料路徑或視覺檢查的腳本排除於一般 pytest gate。

## 設計決策

1. 不新增 `DataConfig = TWStockConfig` 或 `DataProcessor` 假相容層。
2. `DataConfig` 測試直接遷移至 `TWStockConfig`，使用 `tmp_path` 與 test profile。
3. 舊 `DataProcessor.clean_data()` / `add_basic_features()` 測試依實際責任拆分：
   - 載入與 SQLite/CSV fallback 由 `DataLoader` 測試。
   - 欄位正規化與指標衍生由 `TechnicalIndicatorCalculator` 測試。
4. `PatternAnalyzer`、`TechnicalAnalyzer` 使用正式子套件入口
   `analysis_module.pattern_analysis` 與 `analysis_module.technical_analysis`。
5. 含 `input()`、固定 `D:/...`、真實 API、繪圖人工判讀或一次性診斷的檔案不作
   自動單元測試；移至 `tests/manual/`，並以 README 說明執行前提。
6. `pytest` 預設 gate 僅收集可重現的 `test_*.py` 自動測試，不以跳過方式掩蓋
   現行程式錯誤。

## 驗收

- `python -m pytest -q -o addopts=` 可完成收集。
- 不再出現 `DataConfig`、`DataProcessor`、`analysis_module.pattern_analyzer`、
  `analysis_module.technical_analyzer`、`data_module.api` 等 legacy import error。
- 自動測試不讀寫正式 `DATA_ROOT`，不要求互動輸入或外部網路。
- 現行 Pattern、Technical、DataLoader 與 TWStockConfig 至少各有自動測試覆蓋。
- mypy、金融 float boundary 與修改檔語法檢查通過。


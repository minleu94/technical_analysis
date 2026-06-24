# Relocated Legacy Diagnostics

本目錄保存 7 個從 `tests/` 根目錄與 `tests/test_data/` 子目錄移轉過來的遺留診斷與探索腳本。

## 移轉檔案列表及原因

1. **`run_market_index_test.py`**
   - 診斷原因：依賴外部 `yfinance` 網路端點及 FinMind token，不具備本地隔離性。
2. **`run_technical_calc_test.py`**
   - 診斷原因：依賴硬編碼 `D:/Min/Python/Project/FA_Data` 路徑，會檢查並建立真實資料目錄並寫入實體 `tech_test.log` 檔案。
3. **`run_tests.py`**
   - 診斷原因：舊版 `unittest` runner 腳本，引用了已不存在的歷史模組 `test_data_module`。
4. **`check_columns.py`**
   - 診斷原因：一次性診斷腳本，讀取硬編碼 `D:/.../technical_analysis/2330_indicators.csv` 資料。
5. **`check_processed_file.py`**
   - 診斷原因：一次性診斷腳本，讀取硬編碼 `D:/.../technical_analysis/2330_processed.csv` 資料。
6. **`check_saved_file.py`**
   - 診斷原因：一次性診斷腳本，讀取硬編碼 `D:/.../test_data/2330_processed.csv` 資料。
7. **`check_signals_file.py`**
   - 診斷原因：一次性診斷腳本，讀取硬編碼 `D:/.../test_data/2330_signals.csv` 資料。

## 治理規範

* 這些檔案皆不被 `pytest.ini` 正式收集範圍涵蓋，且皆不允許被非破壞式 healthcheck runner 直接呼叫。
* 如需恢復此處任何驗證功能，請重新以合成資料與 `tmp_path` 隔離重構為正式單元或整合測試。

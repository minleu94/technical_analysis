# 專案整理計劃

## 文件分類

### 1. 需要刪除的臨時/測試文件
- `update_20250828.py` - 臨時更新腳本（已整合到主模組）
- `update_daily_enhanced.py` - 增強版更新腳本（功能已整合）
- `update_daily_only.py` - 臨時更新腳本
- `test_update_20250828.py` - 臨時測試腳本
- `test_enhanced_update.py` - 臨時測試腳本
- `simple_update_test.py` - 臨時測試腳本
- `check_and_update.py` - 臨時檢查腳本
- `check_missing_data.py` - 臨時檢查腳本
- `compare_daily_data.py` - 臨時比較腳本
- `restore_industry_index.py` - 臨時恢復腳本（一次性使用）

### 2. 需要移到 tests/ 的文件
- `test_api_endpoints.py` → `tests/test_api/test_api_endpoints.py`

### 3. 需要移到 scripts/ 的文件
- `direct_update.py` → `scripts/direct_update.py`
- `execute_update.py` → `scripts/execute_update.py`
- `run_update.py` → `scripts/run_update.py`
- `run_update_with_log.py` → `scripts/run_update_with_log.py`
- `install_and_run.py` → `scripts/install_and_run.py`

### 4. 需要移到 docs/ 的文件
- `API_INVESTIGATION_REPORT.md` → `docs/API_INVESTIGATION_REPORT.md`
- `DATA_FETCHING_LOGIC.md` → `docs/DATA_FETCHING_LOGIC.md`
- `EXECUTION_GUIDE.md` → `docs/EXECUTION_GUIDE.md`
- `HOW_TO_UPDATE_DAILY_DATA.md` → `docs/HOW_TO_UPDATE_DAILY_DATA.md`
- `INDUSTRY_INDEX_UPDATE_SUMMARY.md` → `docs/INDUSTRY_INDEX_UPDATE_SUMMARY.md`
- `INSTALL_GUIDE.md` → `docs/INSTALL_GUIDE.md`
- `MERGE_AND_MARKET_INDEX_SUMMARY.md` → `docs/MERGE_AND_MARKET_INDEX_SUMMARY.md`
- `QUICK_REFERENCE.md` → `docs/QUICK_REFERENCE.md`
- `QUICK_START.md` → `docs/QUICK_START.md`
- `README_ENHANCED_UPDATE.md` → `docs/README_ENHANCED_UPDATE.md`
- `README_UPDATE.md` → `docs/README_UPDATE.md`
- `RUN_WITHOUT_VENV.md` → `docs/RUN_WITHOUT_VENV.md`
- `SOLUTION_SUMMARY.md` → `docs/SOLUTION_SUMMARY.md`
- `UPDATE_STATUS_20250828.md` → `docs/UPDATE_STATUS_20250828.md`
- `UPDATE_STATUS.md` → `docs/UPDATE_STATUS.md`
- `system_flow_end_to_end.md` → `docs/system_flow_end_to_end.md`
- `readme.txt` → `docs/readme.txt`（或整合到 README.md）

### 5. 需要檢查的文件
- `main.py` - 確認是否還在使用（可能是舊的主程式）
- `system_config.py` - 確認是否還在使用（可能已被 config.py 取代）

### 6. 需要移到適當位置的模組
- `talib_compatibility.py` → `analysis_module/technical_analysis/talib_compatibility.py`

### 7. 需要清理的目錄
- `demo_*` 目錄 - 測試用的 demo 目錄，可以刪除
- `test_data/` - 如果只是測試數據，可以清理


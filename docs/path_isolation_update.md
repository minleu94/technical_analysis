# 路徑隔離功能更新說明

## 更新概述

本次更新（v1.3.0）為台股技術分析系統新增了路徑隔離功能，確保測試環境與生產環境完全分離，同時保持向後兼容性。

## 主要功能

### 1. 路徑隔離功能
- **環境變量覆蓋**：支援 `DATA_ROOT`、`OUTPUT_ROOT`、`PROFILE` 環境變量
- **命令行參數覆蓋**：支援 `--data-root`、`--output-root`、`--profile`、`--dry-run` 參數
- **配置檔案模式**：支援 `prod`、`test`、`staging` 三種模式
- **自動後綴**：測試模式自動添加 `_test` 後綴

### 2. 原子寫入功能
- **安全寫入**：使用臨時檔案確保寫入過程的安全性
- **多格式支援**：支援 CSV、Parquet、JSON 格式的原子寫入
- **錯誤處理**：完善的錯誤處理和清理機制

### 3. 乾運行模式
- **邏輯測試**：測試腳本邏輯而不實際寫入檔案
- **路徑驗證**：驗證路徑設置是否正確
- **性能測試**：測試腳本性能而不產生實際輸出

## 使用方式

### 生產模式（預設）
```bash
# 使用預設D槽路徑
python scripts/update_all_data.py
```

### 測試模式
```bash
# 環境變量方式
export DATA_ROOT=./test_data
export OUTPUT_ROOT=./test_output
export PROFILE=test
python scripts/update_all_data.py --dry-run

# 命令行參數方式
python scripts/update_all_data.py --profile test --data-root ./sandbox_data --output-root ./sandbox_output --dry-run
```

## 更新的檔案

### 核心檔案
- `data_module/config.py` - 新增路徑覆蓋功能
- `technical_analysis/utils/io_utils.py` - 新增原子寫入工具
- `scripts/update_all_data.py` - 整合新配置系統
- `scripts/update_stock_data.py` - 整合新配置系統

### 測試檔案
- `tests/e2e/test_data_path_isolation.py` - 端到端隔離測試

### 文檔檔案
- `README.md` - 更新快速開始指南和路徑說明
- `readme.txt` - 更新數據存儲路徑說明
- `docs/scripts_readme.md` - 更新腳本使用說明
- `docs/tests_readme.md` - 更新測試文檔

## 向後兼容性

- 預設行為完全保持不變，仍使用D槽路徑
- 現有腳本無需修改即可正常運行
- 傳統配置方式仍然支援

## 測試驗證

所有功能都經過完整的測試驗證：
- 環境變量覆蓋測試
- 命令行參數覆蓋測試
- 乾運行模式測試
- 原子寫入安全性測試
- 端到端隔離測試

## 版本資訊

- **版本**：v1.3.0
- **更新日期**：2024-10-16
- **兼容性**：完全向後兼容
- **測試狀態**：所有測試通過

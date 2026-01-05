# 快速參考指南

> **注意**：本文檔提供常用命令和操作的快速參考。如需完整的文檔索引和導航，請參考 [../00_core/DOCUMENTATION_INDEX.md](../00_core/DOCUMENTATION_INDEX.md)。

## 📖 文檔導航

### 遇到問題時
1. **數據更新失敗** → 查看 `../03_data/DATA_FETCHING_LOGIC.md` 的錯誤排查指南
2. **API 連接問題** → 查看 `../03_data/TROUBLESHOOTING_DAILY_UPDATE.md`
3. **數據格式問題** → 查看 `../03_data/DATA_FETCHING_LOGIC.md` 的獲取邏輯章節

### 需要使用時
1. **更新單日數據** → 查看 `../03_data/HOW_TO_UPDATE_DAILY_DATA.md`
2. **了解數據結構** → 查看 `../01_architecture/data_collection_architecture.md`
3. **了解系統架構** → 查看 `../01_architecture/system_architecture.md`

### 開發時
1. **查看開發進度** → 查看 `../00_core/note.txt`
2. **遇到更新問題** → 查看 `../03_data/TROUBLESHOOTING_DAILY_UPDATE.md`
3. **查看數據獲取邏輯** → 查看 `../03_data/DATA_FETCHING_LOGIC.md`

## 🚀 快速開始

### 使用 UI 應用程式（最推薦）

```bash
python ui_app/main.py
```

### 更新單日股票數據

```bash
# 方法 1：使用批量更新腳本（推薦）
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 方法 2：使用單日更新腳本
python scripts/update_daily_stock_data.py --date 2025-08-28 --merge
```

### 合併數據到 meta_data

```bash
python scripts/merge_daily_data.py
```

## 🔧 常見問題快速解決

### HTTP 307 錯誤
→ 使用 UI 應用程式或主模組腳本（已包含處理）

### API 返回錯誤狀態
→ 檢查日期是否為交易日，日期格式是否正確

### 數據為空
→ 查看 `../03_data/DATA_FETCHING_LOGIC.md` 的錯誤排查指南

## 📚 主要文檔位置

- **`../03_data/DATA_FETCHING_LOGIC.md`** - 數據獲取邏輯、使用方式、錯誤排查（**最重要**）
- **`../03_data/HOW_TO_UPDATE_DAILY_DATA.md`** - 如何更新每日數據（**推薦閱讀**）
- **`../03_data/TROUBLESHOOTING_DAILY_UPDATE.md`** - 每日股票更新故障排除指南
- **`../00_core/note.txt`** - 開發進度記錄
- **`../01_architecture/data_collection_architecture.md`** - 數據收集架構說明
- **`../01_architecture/system_architecture.md`** - 系統架構說明
- **`../../ui_app/README.md`** - UI 應用程式使用說明


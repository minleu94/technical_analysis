# 每日股票數據更新指南

## 📖 快速導航

- **批量更新（推薦）** → 查看 [批量更新](#批量更新推薦) 章節
- **單日更新** → 查看 [單日更新](#單日更新) 章節
- **合併數據** → 查看 [合併數據](#合併數據) 章節
- **遇到問題** → 查看 [問題排查](#問題排查) 章節

## 概述

本文檔說明如何使用主模組更新每日股票數據。系統已實現完整的數據更新功能，包括批量更新、單日更新和數據合併。

## 批量更新（推薦 ⭐⭐⭐）

### 使用方式

```bash
# 更新從指定日期之後到今天的所有交易日
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 更新指定日期範圍
python scripts/batch_update_daily_data.py --start-date 2025-08-28 --end-date 2025-09-05

# 自訂延遲時間（更安全，避免 API 限制）
python scripts/batch_update_daily_data.py --start-date 2025-08-28 --delay-min 4 --delay-max 4
```

### 特點

- ✅ **使用主模組**（`data_module/data_loader.py`）
- ✅ 自動更新多個交易日（排除週末）
- ✅ 已包含 delay time（預設 4 秒，可調整）
- ✅ 自動跳過已存在的文件
- ✅ 顯示詳細進度和結果摘要
- ✅ 使用 Session 和 cookie 處理（避免 307 錯誤）
- ✅ 使用成功驗證的邏輯（MI_INDEX API, type=ALL）

### 輸出範例

```
準備更新從 2025-08-28 之後到 今天 的股票數據
共 73 個交易日需要更新
延遲時間: 4 秒/次（固定）
============================================================

[1/73] 正在更新 2025-08-29 的數據...
  ✓ 2025-08-29 更新成功：1059 筆記錄
  等待 4.0 秒後繼續...

[2/73] 正在更新 2025-09-01 的數據...
  ✓ 2025-09-01 更新成功：1059 筆記錄
  等待 4.0 秒後繼續...

...

============================================================
批量更新完成！
成功: 73 天
失敗: 0 天
============================================================
注意：數據已更新到 daily_price 目錄，尚未合併到 meta_data
請檢查數據無誤後，再執行合併：python scripts/merge_daily_data.py
```

## 單日更新

### 使用方式

```bash
# 更新單日數據（只更新 daily_price）
python scripts/update_daily_stock_data.py --date 2025-08-29

# 更新並自動合併到 meta_data
python scripts/update_daily_stock_data.py --date 2025-08-29 --merge
```

### 特點

- ✅ 使用主模組方法
- ✅ 已包含 delay time（1.5-2.5 秒）
- ✅ 可選擇是否自動合併
- ✅ 統一的日誌記錄

## 合併數據

### 使用方式

```bash
# 合併所有新的 daily_price 文件到 meta_data
python scripts/merge_daily_data.py
```

### 特點

- ✅ 自動檢測新的 daily_price 文件
- ✅ 增量合併（只處理新文件）
- ✅ 自動創建備份
- ✅ 顯示合併結果統計

## 完整更新流程

### 標準流程（推薦）

```bash
# 步驟 1：批量更新每日數據（只更新 daily_price）
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 步驟 2：檢查更新結果（可選）
# 檢查文件是否正確生成

# 步驟 3：合併到 meta_data
python scripts/merge_daily_data.py
```

### 一鍵更新（自動合併）

```bash
# 單日更新並自動合併
python scripts/update_daily_stock_data.py --date 2025-08-29 --merge
```

## 文件命名格式

- **正確格式**：`YYYYMMDD.csv`（如 `20250829.csv`）
- **存儲位置**：`D:/Min/Python/Project/FA_Data/daily_price/`
- **主模組會自動轉換**：`2025-08-29` → `20250829.csv`

## 問題排查

### 問題 1：HTTP 307 錯誤

**解決方案**：
- 主模組已包含 Session 和 cookie 處理
- 如果仍然失敗，使用增強版：`python update_daily_enhanced.py --date 2025-08-29`

### 問題 2：API 返回錯誤狀態

**解決方案**：
- 檢查日期是否為交易日（週末和假日會失敗）
- 檢查日期格式是否正確（必須為 `YYYY-MM-DD`）

### 問題 3：文件命名錯誤

**解決方案**：
- 主模組已自動處理日期格式轉換
- 確認使用主模組方法（`scripts/batch_update_daily_data.py` 或 `scripts/update_daily_stock_data.py`）

### 問題 4：虛擬環境問題

**解決方案**：
- 直接使用系統 Python：`python scripts/batch_update_daily_data.py --start-date 2025-08-28`
- 不需要激活虛擬環境

## 相關文檔

- **[HOW_TO_UPDATE_DAILY_DATA.md](../HOW_TO_UPDATE_DAILY_DATA.md)** - 完整更新指南
- **[DATA_FETCHING_LOGIC.md](../DATA_FETCHING_LOGIC.md)** - 數據獲取邏輯詳細說明
- **[docs/scripts_readme.md](scripts_readme.md)** - 腳本使用說明
- **[docs/data_collection_architecture.md](data_collection_architecture.md)** - 數據收集架構說明

## 技術細節

### API 資訊

- **端點**：`https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX`
- **參數**：`date` (YYYYMMDD), `type=ALL`, `response=json`
- **數據位置**：`data['tables'][8]`（第9個表格）

### 延遲時間

- **批量更新**：預設 4 秒（可調整）
- **單日更新**：1.5-2.5 秒（隨機）
- **目的**：避免 API 請求過快被限制

### 數據處理

- 只保留 4 位數股票代號
- 自動處理數值欄位（移除逗號、處理 '--'）
- 從 HTML 標籤中提取漲跌符號
- 使用 `utf-8-sig` 編碼（支援 Excel 打開）


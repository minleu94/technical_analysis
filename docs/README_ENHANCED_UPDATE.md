# 增強版數據更新腳本說明

## ⚠️ 注意

此文件描述的是舊版增強腳本 `update_daily_enhanced.py`，該腳本已被整合到主模組。

**推薦使用：**
- **UI 應用程式**：`python ui_app/main.py`（最推薦）
- **批量更新腳本**：`python scripts/batch_update_daily_data.py`（推薦）
- **單日更新腳本**：`python scripts/update_daily_stock_data.py`（推薦）

## 📋 概述

增強版更新腳本支援多種數據源和備用方案，確保在 TWSE API 不可用時仍能獲取數據。

## ✨ 功能特點

### 1. 多數據源支援
- **傳統 API**：直接使用 requests（最快）
- **Selenium**：模擬真實瀏覽器（可繞過防護）
- **FinMind**：第三方數據源（穩定可靠）

### 2. 自動降級機制
腳本會按優先順序自動嘗試不同的數據源：
1. 首先嘗試傳統 API（最快）
2. 如果失敗，嘗試 Selenium
3. 如果還是失敗，嘗試 FinMind

## 🚀 使用方式

### 基本使用

```bash
# 更新單日數據
python update_daily_enhanced.py --date 2025-08-28

# 批量更新
python update_daily_enhanced.py --start-date 2025-08-28 --end-date 2025-08-30
```

## 📊 數據源比較

| 數據源 | 速度 | 可靠性 | 安裝難度 | 備註 |
|--------|------|--------|----------|------|
| 傳統 API | ⚡⚡⚡ 快 | ⚠️ 可能被阻擋 | ✅ 簡單 | 優先使用 |
| Selenium | ⚡ 慢 | ✅ 高 | ⚠️ 需要 Chrome | 備用方案1 |
| FinMind | ⚡⚡ 中等 | ✅ 高 | ✅ 簡單 | 備用方案2 |

## ⚠️ 注意事項

1. **此腳本已整合到主模組**：建議使用主模組腳本或 UI 應用程式
2. **Selenium 速度較慢**：每次請求需要啟動瀏覽器（約 5-10 秒）
3. **FinMind 數據格式**：某些欄位可能為空

## 📚 相關文檔

- `docs/INSTALL_GUIDE.md` - 詳細安裝指南
- `docs/HOW_TO_UPDATE_DAILY_DATA.md` - 完整使用說明
- `ui_app/README.md` - UI 應用程式說明


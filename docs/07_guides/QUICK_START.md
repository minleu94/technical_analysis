# 快速開始指南

> 目前主要 UI 是 PySide6，入口為 `ui_qt/main.py`。

## 三步開始

### 1. 建立或使用虛擬環境

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

若 `.venv` 已存在且可用，可略過建立步驟。

### 2. 啟動應用程式

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

### 3. 更新並檢查資料

1. 開啟「數據更新」。
2. 點擊「檢查數據狀態」。
3. 日常使用「快速更新（僅 SQLite）」。
4. 需要完整 CSV 備份時使用「安全更新（完整 CSV + SQLite）」。
5. 確認每日股價與技術指標日期正常後，再執行推薦或回測。

## 常用命令

```powershell
# 主 UI
.\.venv\Scripts\python.exe ui_qt\main.py

# 批量更新每日股價
.\.venv\Scripts\python.exe scripts\batch_update_daily_data.py --start-date 2026-06-01

# 更新單一交易日並合併
.\.venv\Scripts\python.exe scripts\update_daily_stock_data.py --date 2026-06-12 --merge
```

## 驗證環境

```powershell
.\.venv\Scripts\python.exe -c "import pandas, PySide6; print('environment OK')"
```

## 常見問題

### PySide6 無法匯入

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### UI 啟動但資料為空

確認 `DATA_ROOT` 指向正確資料根目錄，然後在數據更新頁執行狀態檢查。

### 更新失敗

確認日期是交易日、網路可用，並查看數據更新頁底部日誌。

## 下一步

- [完整操作手冊](APPLICATION_MANUAL.md)
- [安裝指南](INSTALL_GUIDE.md)
- [每日資料更新](../03_data/HOW_TO_UPDATE_DAILY_DATA.md)
- [資料更新故障排除](../03_data/TROUBLESHOOTING_DAILY_UPDATE.md)


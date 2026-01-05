# 快速開始指南

## 🚀 三步快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

或使用安裝 notebook：
```bash
jupyter notebook install_dependencies.ipynb
```

### 2. 啟動 UI 應用程式

```bash
python ui_app/main.py
```

### 3. 在 UI 中更新數據

1. 選擇「數據更新」標籤頁
2. 選擇更新類型（每日/大盤/產業）
3. 設定日期範圍
4. 點擊「開始更新」

## 📋 完整命令選項

### 使用 UI（推薦）

```bash
python ui_app/main.py
```

### 使用命令行

```bash
# 批量更新多日數據
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 更新單日數據
python scripts/update_daily_stock_data.py --date 2025-08-28 --merge
```

## ✅ 驗證安裝

運行以下命令驗證安裝：

```bash
python -c "import pandas; print('pandas OK')"
python -c "import requests; print('requests OK')"
```

## 🔍 檢查數據狀態

使用 UI 應用程式：
1. 打開 UI
2. 選擇「數據更新」標籤頁
3. 點擊「檢查數據狀態」

## ⚠️ 常見問題

### 問題 1：pandas 未安裝

**解決**：
```bash
pip install pandas
```

### 問題 2：tkinter 未安裝

**解決**：
- Windows：通常已包含
- Linux：`sudo apt-get install python3-tk`

### 問題 3：API 連接失敗

**解決**：
- 使用 UI 應用程式（已包含錯誤處理）
- 檢查網絡連接
- 確認日期為交易日

## 📚 更多資訊

- `INSTALL_GUIDE.md` - 詳細安裝指南
- `../03_data/HOW_TO_UPDATE_DAILY_DATA.md` - 完整使用說明
- `ui_app/README.md` - UI 應用程式說明


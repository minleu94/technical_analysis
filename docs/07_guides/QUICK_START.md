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
2. 日常維護建議先設定查找範圍或日期範圍
3. 點擊「安全更新所有數據」，讓系統依序更新每日股價、大盤指數、產業指數、券商分點、合併資料並計算技術指標
4. 若只想更新單一資料來源，使用左側導覽切換到每日股價、大盤指數、產業指數、券商分點或技術指標頁面後單獨執行

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
3. 在上方狀態摘要點擊「檢查數據狀態」
4. 需要細查單一來源時，切換左側對應頁面查看更新控制與日誌

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


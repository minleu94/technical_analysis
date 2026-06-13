# 如何執行腳本（不使用虛擬環境）

## 問題說明

如果您遇到以下錯誤：
1. PowerShell 執行策略錯誤（無法激活虛擬環境）
2. 虛擬環境中缺少模組（如 pandas）

## 解決方案：直接使用系統 Python

### 方法 1：在 CMD 中執行（推薦）

```cmd
# 直接使用系統 Python（不需要激活虛擬環境）
python scripts/batch_update_daily_data.py --start-date 2025-08-28
```

### 方法 2：在 PowerShell 中執行

```powershell
# 直接使用系統 Python
python scripts/batch_update_daily_data.py --start-date 2025-08-28
```

### 方法 3：使用完整路徑

```powershell
# 使用系統 Python 的完整路徑
C:\Program Files\Python311\python.exe scripts/batch_update_daily_data.py --start-date 2025-08-28
```

## 為什麼可以這樣做？

系統 Python 已經安裝了所有需要的模組（pandas, requests 等），所以不需要使用虛擬環境。

## 檢查 Python 版本和模組

```cmd
# 檢查 Python 版本
python --version

# 檢查 pandas 是否安裝
python -c "import pandas; print('pandas OK')"
```

## 如果系統 Python 也沒有模組

```cmd
# 安裝需要的模組
pip install pandas numpy requests
```

## UI 啟動

只有在系統 Python 已安裝完整 `requirements.txt` 時才可直接啟動：

```powershell
python ui_qt/main.py
```

專案仍建議使用 `.venv`，因為系統 Python 的套件版本可能與測試環境不同。標準方式見 [INSTALL_GUIDE.md](../07_guides/INSTALL_GUIDE.md)。


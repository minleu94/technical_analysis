# 安裝與環境設定

## 1. 前置條件

- Windows PowerShell
- 可建立 Python 虛擬環境的 Python 安裝
- 可存取專案資料根目錄

以專案現有 `.venv` 的 Python 版本為優先，不要在未驗證相容性前任意更換主要版本。

## 2. 建立虛擬環境

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 已包含 PySide6、pandas、NumPy、Matplotlib、Selenium 與研究所需套件。

## 3. 設定資料目錄

預設：

```text
D:/Min/Python/Project/FA_Data
```

臨時覆蓋：

```powershell
$env:DATA_ROOT = "D:\your\data\root"
$env:OUTPUT_ROOT = "D:\your\data\root\output"
```

設定只作用於目前 PowerShell session。永久設定請使用 Windows 環境變數管理。

## 4. 啟動 PySide6 UI

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

Legacy `ui_app/main.py` 不是目前主要使用者入口。

## 5. 安裝驗證

```powershell
.\.venv\Scripts\python.exe -c "import pandas, numpy, PySide6; print('core imports OK')"
.\.venv\Scripts\python.exe -c "from data_module.config import TWStockConfig; print(TWStockConfig().data_root)"
```

## 6. 故障排除

### PySide6 或 Qt 模組缺失

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade PySide6
```

### TA-Lib 安裝失敗

先保留完整錯誤訊息，不要移除其他依賴。確認目前 Python 架構與 wheel 相容；專案也包含相容處理，但仍應以測試驗證實際路徑。

### 圖表空白

查看 terminal 是否有 QtWebEngine 匯入錯誤。回測圖表有 Matplotlib fallback，但環境仍需具備基本 Qt 顯示能力。

### 無法讀取資料

確認：

1. `DATA_ROOT` 存在。
2. 使用者有讀寫權限。
3. `<DATA_ROOT>/sqlite/twstock.db` 可存取。
4. 沒有把正式資料根目錄指向測試資料夾。

## 7. 完整使用說明

安裝完成後閱讀 [APPLICATION_MANUAL.md](APPLICATION_MANUAL.md)。


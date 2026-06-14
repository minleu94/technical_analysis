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

## 7. Windows 的 WSL 與 CodeRabbit CLI

CodeRabbit CLI 官方不支援直接在原生 Windows PowerShell 或 Git Bash 執行。
Windows 環境必須透過 WSL 2 執行；CodeRabbit Skill 只負責呼叫流程，本機仍需先安裝並登入 CLI。

> **可選工具與費用提醒**
>
> CodeRabbit 是外部審查服務，可能需要試用資格或付費方案，不是本專案的必要依賴。
> 不使用 CodeRabbit 時，不影響專案開發、測試或 Codex 人工 code review；審查報告必須清楚標示實際審查來源，不得把人工審查描述成 CodeRabbit 結果。

### 7.1 安裝 WSL 2 與 Ubuntu

以系統管理員身分開啟 PowerShell：

```powershell
wsl --install -d Ubuntu
```

若 `wsl --install` 沒有啟用功能，改用：

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

完成後重新啟動 Windows，再執行：

```powershell
wsl --update
wsl --set-default-version 2
wsl --install -d Ubuntu
wsl --list --verbose
```

第一次啟動 Ubuntu 時，依提示建立 Linux 使用者名稱與密碼。
`wsl --list --verbose` 的 Ubuntu `VERSION` 必須為 `2`。

### 7.2 在 Ubuntu 安裝 CodeRabbit CLI

開啟 Ubuntu 或在 PowerShell 執行 `wsl`，然後在 Linux shell 內執行：

```bash
sudo apt update
sudo apt install -y curl git
curl -fsSL https://cli.coderabbit.ai/install.sh | sh
source ~/.bashrc
coderabbit --version
coderabbit auth login --agent
coderabbit auth status --agent
```

登入會開啟瀏覽器。完成授權後，`coderabbit auth status --agent` 必須顯示已登入。

### 7.3 從 WSL 存取本專案

Windows 專案路徑：

```text
C:\Projects\PythonProjects\technical_analysis
```

對應的 WSL 路徑：

```text
/mnt/c/Projects/PythonProjects/technical_analysis
```

驗證 repo 與執行審查：

```bash
cd /mnt/c/Projects/PythonProjects/technical_analysis
git rev-parse --show-toplevel
git status --short
coderabbit review --agent -t uncommitted -c AGENTS.md
```

### 7.4 每次 CodeRabbit 審查前檢查

在 PowerShell：

```powershell
wsl --status
wsl --list --verbose
```

在 WSL：

```bash
coderabbit --version
coderabbit auth status --agent
cd /mnt/c/Projects/PythonProjects/technical_analysis
git status --short
```

### 7.5 CodeRabbit 故障排除

- `Unsupported operating system: mingw64_nt-*`：正在 Git Bash 執行官方安裝腳本；改到 WSL Ubuntu。
- `coderabbit: command not found`：重新載入 shell：`source ~/.bashrc`，再檢查安裝器輸出的 PATH。
- `Git repository not found`：先切換到 `/mnt/c/Projects/PythonProjects/technical_analysis`。
- CLI 未登入：執行 `coderabbit auth login --agent`。
- WSL 發行版顯示 Version 1：在 PowerShell 執行 `wsl --set-version Ubuntu 2`。
- WSL 功能剛啟用仍無法執行：必須先重新啟動 Windows。

不要使用來源不明的原生 Windows CodeRabbit Port。專案標準環境以官方 WSL 路徑為準。

### 7.6 不使用 CodeRabbit

若帳戶沒有 CodeRabbit CLI 權限或不使用付費外部服務：

1. 不需要執行 `coderabbit auth login --agent`。
2. 保留 WSL 與 Ubuntu 不會產生 CodeRabbit 費用。
3. 改由 Codex 依 repo 的 `AGENTS.md`、Agent 規範、實際 diff 與測試證據進行人工 code review。
4. 審查輸出明確標示「Codex 人工 code review」，不得宣稱來自 CodeRabbit。

## 8. 完整使用說明

安裝完成後閱讀 [APPLICATION_MANUAL.md](APPLICATION_MANUAL.md)。

## 更新記錄

- 2026-06-14：新增 Windows WSL 2、Ubuntu 與 CodeRabbit CLI 的官方安裝、驗證及排錯流程，並標示 CodeRabbit 為可能付費的可選外部服務及 Codex 人工審查替代方案。


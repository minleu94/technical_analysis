# baldr

baldr 是一套台股研究與投資決策工作台，目標是把資料更新、市場觀察、推薦分析、策略回測、每日決策、策略生命週期與持倉管理串成可驗證、可回溯、可演化的研究流程。

這個 `main` 分支保留可安裝、可啟動、可閱讀的乾淨專案入口；日常開發狀態請使用 `dev` 分支。

## 功能概覽

- 資料更新：TWSE / TPEX 每日股價、大盤、產業、券商分點、技術指標與 SQLite 同步。
- 市場觀察：Market Regime、強弱股、強弱產業與 Smart Money 主力流向。
- 推薦分析：Profile / Regime、Why / Why Not、候選池與推薦回放。
- Research Lab：單股、批次、固定組合、推薦組合、Walk-forward、參數最佳化與 Research Run Registry。
- Daily Decision Desk：Market Breadth、Sector Rotation、Relative Strength / Liquidity、Watchlist Trigger、Portfolio Alert 與 risk prompts。
- Portfolio：交易紀錄、來源追溯、停損停利、籌碼監控、生命週期回顧與 post-trade attribution。
- Runtime Observatory：唯讀觀察治理狀態、事件流與 Runtime 健康。

baldr 不保證推薦股票上漲，也不把回測結果宣稱為實盤績效。策略、回測與推薦結果都需要以資料品質、可得日、成本、成交限制與 out-of-sample 證據一起判讀。

## 快速開始

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe ui_qt\main.py
```

預設正式資料根目錄由 `data_module/config.py` 的 `TWStockConfig` 決定，通常是：

```text
D:/Min/Python/Project/FA_Data
```

可在啟動前用環境變數覆蓋：

```powershell
$env:DATA_ROOT = "D:\your\data\root"
$env:OUTPUT_ROOT = "D:\your\data\root\output"
```

完整操作步驟、參數意義、結果判讀與排錯請看 [docs/07_guides/APPLICATION_MANUAL.md](docs/07_guides/APPLICATION_MANUAL.md)。

## 分支策略

| 分支 | 用途 |
|---|---|
| `main` | 對外乾淨版本。保留必要程式碼、文件、範例與可啟動專案，不追蹤本機 QA output 或暫存 artifact。 |
| `dev` | 日常開發主線。延續目前開發狀態，包含進行中的 healthcheck、UI smoke、文件與功能深化。 |
| `codex/*` / `feature/*` | 短期工作分支。完成並合併後應刪除。 |

## 主要入口

| 目的 | 文件 |
|---|---|
| 使用系統 | [docs/07_guides/APPLICATION_MANUAL.md](docs/07_guides/APPLICATION_MANUAL.md) |
| 了解目前狀態 | [docs/00_core/PROJECT_SNAPSHOT.md](docs/00_core/PROJECT_SNAPSHOT.md) |
| 了解未來 6 個月工程路線 | [docs/00_core/ROADMAP_6M_ENGINEERING.md](docs/00_core/ROADMAP_6M_ENGINEERING.md) |
| 了解架構與模組邊界 | [docs/01_architecture/system_architecture.md](docs/01_architecture/system_architecture.md) |
| 找所有文件 | [docs/00_core/DOCUMENTATION_INDEX.md](docs/00_core/DOCUMENTATION_INDEX.md) |
| 開發者導航 | [PROJECT_NAVIGATION.md](PROJECT_NAVIGATION.md) |
| Agent / Codex 上下文 | [AGENT_CONTEXT.md](AGENT_CONTEXT.md) 與 [AGENTS.md](AGENTS.md) |

## 核心結構

| 目錄 | 角色 |
|---|---|
| `ui_qt/` | PySide6 Qt UI，主入口為 `ui_qt/main.py`。 |
| `app_module/` | Application service layer，負責 use case 編排、DTO 與 repository。 |
| `decision_module/` | Decision domain，包含推薦、打分、篩選、Regime、factor 與籌碼信號。 |
| `backtest_module/` | 回測核心、績效分析與交易模擬。 |
| `portfolio_module/` | Portfolio domain layer，含 append-only trades、positions projection 與 Decimal 邊界。 |
| `runtime/` | Governance-aware AI Runtime 狀態、事件與儲存。 |
| `data_module/` | 資料設定、載入、SQLite / CSV 邊界、基本面資料層與受控 backfill workflow。 |
| `scripts/` | 資料更新、QA 驗證與維護腳本。 |
| `docs/` | 文件系統。 |
| `tests/` | 自動化與 manual 測試。 |

## 驗證

常用 UI 修改驗證：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

文件或純索引調整不需要跑 UI QA；提交前至少檢查 Markdown 連結與 Git diff。若修改 Python 檔，另對變更檔執行 `py_compile`。若涉及策略、回測、推薦、績效、風控、資金或倉位，必須先做 Look-ahead bias 與金融數值邊界自查。

## Legacy

- `ui_app/` 是舊版 Tkinter UI，只作歷史參考。
- 過期但仍有追溯價值的文件放在 [docs/09_archive/](docs/09_archive/)。
- 本機輸出、QA artifact、log、SQLite DB 與暫存檔不應提交到 `main`。

## 更新記錄

- 2026-06-30：重整根目錄 README 為使用者導向入口；開發者與 Agent 上下文移至 `AGENT_CONTEXT.md`；明確化 `main` / `dev` 分支策略。

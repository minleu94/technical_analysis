# baldr

> **最後整理**：2026-06-18
> **目前主線**：Month 6 Strategy Lifecycle / Portfolio Feedback v1 已落地，接續全 UI 健檢與生命週期深化
> **主要入口**：`ui_qt/main.py`

baldr 是一套台股研究與投資決策工作台，目標是把資料更新、市場觀察、推薦分析、策略回測、籌碼監控、基本面因子、每日決策與持倉管理串成可驗證、可回溯、可演化的研究與決策流程。

本檔只保留專案最短入口。狀態判讀請以 [docs/00_core/PROJECT_SNAPSHOT.md](docs/00_core/PROJECT_SNAPSHOT.md) 為準；未來 6 個月工程路線請以 [docs/00_core/ROADMAP_6M_ENGINEERING.md](docs/00_core/ROADMAP_6M_ENGINEERING.md) 為準。

## 目前狀態

- 資料與市場狀態閉環：SQLite-first 更新、Market Watch、Smart Money、候選池與資料更新工作台已建立。
- 研究驗證閉環：Recommendation、Research Lab、Backtest、Replay、Walk-forward、Promote、Research Run Registry、Cross-run Comparison 與 Registry-based Promote Gate 已建立。
- 持倉檢查閉環：Portfolio、來源追溯、策略與價格監控、停損停利警示、籌碼監控、Smart Money 下鑽與生命週期回顧已建立。
- Daily Decision Desk v1：已接上主 UI，提供 Market Breadth、Sector Rotation、Relative Strength / Liquidity Ranking、Watchlist Trigger、Portfolio Alert 與 risk prompts。
- Month 5 Fundamental Layer v1：月營收、估值資料層、available_date gate、fundamental factor service 與診斷流程已收斂成 v1。
- Month 6 Strategy Lifecycle / Portfolio Feedback v1：lifecycle gate、append-only lifecycle evidence、latest state projection、drift detector、post-trade attribution、Portfolio Review snapshot 與持倉管理生命週期分頁已落地。
- UI 主題：已導入 Midnight Analyst theme tokens、全域 QSS 與設計系統文件，接下來主線是全 UI 健檢與畫面一致性整理。

## 接下來先做什麼

- 繼續全 UI 健檢，優先檢查 8 個頂層工作區的版面、文字密度、控制項一致性與狀態提示。
- Month 6.1 聚焦 lifecycle QA、manual approval workflow、Review Dashboard、Evidence Explainability 與完整驗收清單。
- 任何使用者可見流程或參數變更，都要同步 [docs/07_guides/APPLICATION_MANUAL.md](docs/07_guides/APPLICATION_MANUAL.md)。

## 快速啟動

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

常用 UI 變更驗證：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

文件或純索引調整不需要跑 UI QA；提交前至少檢查 Markdown 連結與 Git diff。

## 重要文件

- [docs/README.md](docs/README.md)：docs 總入口與資料夾歸屬。
- [docs/00_core/PROJECT_SNAPSHOT.md](docs/00_core/PROJECT_SNAPSHOT.md)：目前狀態與本週優先事項。
- [docs/00_core/ROADMAP_6M_ENGINEERING.md](docs/00_core/ROADMAP_6M_ENGINEERING.md)：未來 6 個月工程路線。
- [docs/00_core/DEVELOPMENT_ROADMAP.md](docs/00_core/DEVELOPMENT_ROADMAP.md)：Roadmap Hub。
- [docs/00_core/LEGACY_ROADMAP_CARRYOVER.md](docs/00_core/LEGACY_ROADMAP_CARRYOVER.md)：舊 Roadmap 移交與 Gate。
- [docs/00_core/DOCUMENTATION_INDEX.md](docs/00_core/DOCUMENTATION_INDEX.md)：完整文件索引。
- [docs/07_guides/APPLICATION_MANUAL.md](docs/07_guides/APPLICATION_MANUAL.md)：目前 8 個工作區的完整操作手冊。
- [docs/01_architecture/ui_design_system_midnight_analyst.md](docs/01_architecture/ui_design_system_midnight_analyst.md)：Midnight Analyst UI 設計系統。
- [AGENTS.md](AGENTS.md)：Codex repo 指令入口。

## 根目錄文件分工

| 文件 | 是否應留在根目錄 | 用途 |
|---|---|---|
| [README.md](README.md) | 是 | 專案最短入口、目前主線、啟動方式與權威文件導覽。 |
| [PROJECT_NAVIGATION.md](PROJECT_NAVIGATION.md) | 是 | 開發者用的模組導航與「我要改 X 要去哪裡」。 |
| [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) | 是 | 目前專案結構盤點，保持摘要化。 |
| [AGENTS.md](AGENTS.md) | 是 | Codex 自動讀取的 repo 指令入口，指向 `docs/agents/` 的完整 Agent 架構。 |

歷史 `readme.txt` 已封存到 [docs/09_archive/root_readme_legacy_2025_12.txt](docs/09_archive/root_readme_legacy_2025_12.txt)，只作追溯用途，不再作為目前狀態或操作入口。

## 核心結構

| 目錄 | 角色 |
|---|---|
| `ui_qt/` | PySide6 Qt UI，目前主要使用者入口。 |
| `app_module/` | Application Service Layer，負責 use case 編排與 DTO。 |
| `decision_module/` | Domain Layer，推薦、打分、篩選、Regime、因子與籌碼信號。 |
| `backtest_module/` | 回測核心、績效分析、交易模擬。 |
| `portfolio_module/` | Portfolio domain layer，含 append-only trades、positions projection 與 Decimal 邊界。 |
| `runtime/` | Governance-aware AI Runtime 狀態、事件與儲存。 |
| `data_module/` | 資料設定、載入、處理與基本面資料層。 |
| `scripts/` | 資料更新、QA 驗證與維護腳本。 |
| `docs/` | 文件系統。 |
| `tests/` | 測試。 |

## Legacy / Historical

- `ui_app/` 是舊版 Tkinter UI，僅作參考。
- notebook 匯出的根目錄參考腳本已移除；Notebook 原始參考仍在 `notebooks/`。
- 過期但仍有追溯價值的文件統一放在 [docs/09_archive/](docs/09_archive/)。

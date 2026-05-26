# 台股技術分析系統

> **最後整理**：2026-05-20
> **目前主線**：Phase 4.1 Portfolio MVP  
> **主要入口**：`ui_qt/main.py`

這是一個台股投資決策系統，核心目標是把資料更新、市場觀察、推薦分析、策略回測、籌碼分析與持倉管理串成可驗證、可回溯、可演化的研究流程。

## 目前狀態

- Phase 1 市場觀察儀：已完成。
- Phase 2 策略資料庫 / 回測基礎：已完成。
- Phase 2.5 參數設計優化：已完成。
- Phase 3.1 / 3.2 / 3.3a / 3.3b：已完成，包含推薦可用化、Profiles、研究閉環、Walk-forward、Baseline、過擬合風險與 K 線視覺驗證。
- AI Runtime Subsystem MVP：已完成。
- Smart Money Terminal MVP：已完成。
- UI Qt Backtest chart rendering：已完成 QtWebEngine + HTML5 Canvas fast renderer，回測圖表保留 Matplotlib fallback。
- 數據更新工作台：已完成左側導覽工作台重整，新增「安全更新所有數據」日常維護入口。
- Codex / Agent 指引：已新增根目錄 `AGENTS.md`，`docs/agents/` 已對齊目前 `ui_qt` 與資料路徑規則。
- Phase 4.1 Portfolio MVP：domain / service / test skeleton 已開始，`ui_qt` Portfolio Tab 與跨模組串接尚未完成。

最新進度以 [docs/00_core/DEVELOPMENT_ROADMAP.md](docs/00_core/DEVELOPMENT_ROADMAP.md) 為準。

## 快速啟動

```bash
python ui_qt/main.py
```

如需執行測試，建議使用專案虛擬環境：

```bash
.\.venv\Scripts\python.exe -m pytest -o addopts= tests\test_portfolio_mvp.py
```

## 根目錄文件分工

| 文件 | 是否應留在根目錄 | 用途 |
|---|---|---|
| [README.md](README.md) | 是 | 專案最短入口與啟動方式。 |
| [PROJECT_NAVIGATION.md](PROJECT_NAVIGATION.md) | 是 | 開發者用的模組導航與「我要改 X 要去哪裡」。 |
| [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) | 是 | 目前專案結構盤點，保持摘要化。 |
| [AGENTS.md](AGENTS.md) | 是 | Codex 自動讀取的 repo 指令入口，指向 `docs/agents/` 的完整 Agent 架構。 |

功能細節、QA、Phase 設計、資料更新與技術備忘已歸入 [docs/](docs/README.md)。

## 重要文件

- [docs/README.md](docs/README.md) - docs 總入口與資料夾歸屬。
- [docs/00_core/PROJECT_SNAPSHOT.md](docs/00_core/PROJECT_SNAPSHOT.md) - 30 秒讀完目前狀態。
- [docs/00_core/DOCUMENTATION_INDEX.md](docs/00_core/DOCUMENTATION_INDEX.md) - 完整文件索引。
- [docs/02_features/UI_FEATURES_DOCUMENTATION.md](docs/02_features/UI_FEATURES_DOCUMENTATION.md) - Qt UI 功能說明。
- [docs/02_features/USER_GUIDE.md](docs/02_features/USER_GUIDE.md) - 使用者操作指南。
- [AGENTS.md](AGENTS.md) - Codex repo 指令入口。
- [docs/03_data/HOW_TO_UPDATE_DAILY_DATA.md](docs/03_data/HOW_TO_UPDATE_DAILY_DATA.md) - 每日資料更新快速指南。
- [docs/08_technical/UI_QT_CHART_RENDERING.md](docs/08_technical/UI_QT_CHART_RENDERING.md) - Qt 回測圖表 fast Canvas renderer 與 fallback 架構。

## 核心結構

| 目錄 | 角色 |
|---|---|
| `ui_qt/` | PySide6 Qt UI，目前主要使用者入口。 |
| `app_module/` | Application Service Layer，負責 use case 編排與 DTO。 |
| `decision_module/` | Domain Layer，推薦、打分、篩選、Regime、籌碼信號。 |
| `backtest_module/` | 回測核心、績效分析、交易模擬。 |
| `portfolio_module/` | Portfolio MVP domain layer。 |
| `runtime/` | Governance-aware AI Runtime 狀態、事件與儲存。 |
| `data_module/` | 資料設定、載入與處理。 |
| `scripts/` | 資料更新、QA 驗證與維護腳本。 |
| `docs/` | 文件系統。 |
| `tests/` | 測試。 |

## Legacy / Historical

- `ui_app/` 是舊版 Tkinter UI，僅作參考。
- `recommendation_module_legacy/` 是舊版推薦模組，新功能應使用 `app_module/recommendation_service.py`。
- notebook 匯出的根目錄參考腳本已移除；Notebook 原始參考仍在 `notebooks/`。

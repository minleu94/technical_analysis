# Docs 文檔目錄

> **最後整理**：2026-06-30
> **權威判讀**：目前狀態看 `00_core/PROJECT_SNAPSHOT.md`，未來 6 個月看 `00_core/ROADMAP_6M_ENGINEERING.md`，架構看 `01_architecture/system_architecture.md`，索引只負責導航。

本目錄是專案文件的主要入口。文件已依用途分區，日常查找請優先使用：

1. [專案快照](00_core/PROJECT_SNAPSHOT.md) - 30 秒讀完的目前狀態、本週優先事項與高風險區
2. [6 個月工程路線](00_core/ROADMAP_6M_ENGINEERING.md) - 未來 6 個月的可執行工程計畫
3. [Roadmap Hub](00_core/DEVELOPMENT_ROADMAP.md) - Roadmap 入口與權威文件導覽
4. [舊 Roadmap 移交矩陣](00_core/LEGACY_ROADMAP_CARRYOVER.md) - 舊版未完成事項的新位置與驗收條件
5. [完整操作手冊](07_guides/APPLICATION_MANUAL.md) - 8 個工作區、跨頁流程、安全限制與排錯
6. [文檔索引](00_core/DOCUMENTATION_INDEX.md) - 所有保留文檔的導航
7. [文檔結構與維護規則](00_core/DOCUMENTATION_STRUCTURE.md) - 資料夾歸屬、刪除與歸檔規則
8. [文檔覆蓋矩陣](00_core/DOC_COVERAGE_MAP.md) - 文件更新時要同步哪些文檔

---

## 目錄歸屬

| 目錄 | 用途 | 狀態 |
|---|---|---|
| `00_core/` | snapshot、6 個月 roadmap、Roadmap Hub、索引、coverage 規則 | 必讀 |
| `01_architecture/` | 系統架構、資料流、Runtime 規範、多 Agent 工作流、UI 設計系統 | 長期維護 |
| `02_features/` | UI、使用者指南、回測、評分、策略規格 | 使用者與功能說明 |
| `03_data/` | 每日資料、資料流、重建與故障排除、基本面來源盤點 | 資料更新操作 |
| `04_broker_branch/` | 券商分點資料與 Smart Money 前置資料 | 籌碼資料專區 |
| `05_phases/` | Phase 設計、Phase 3.5 SOP、Phase 4 Portfolio 設計 | 階段規劃 |
| `06_qa/` | QA 問題、總結、驗證與審核報告 | 驗證紀錄 |
| `07_guides/` | 快速開始、安裝、命令、腳本與測試說明 | 操作手冊 |
| `08_technical/` | 技術優化、參數設計、路徑/環境說明 | 技術備忘 |
| `09_archive/` | 已過期但仍有歷史價值的文件 | 不作日常依據 |
| `agents/` | Agent 職責、協作規範、上下文 | Agent 工作文件 |
| `governance/` | 預留給流程治理、決策紀錄或政策文件 | 目前無 Markdown 文件 |
| `strategies/` | 策略說明文件 | StrategyRegistry / 使用者理解 |

> Codex 自動讀取入口位於 repo 根目錄 `AGENTS.md`。`docs/agents/` 保留完整 Agent 架構與 Prompt 文件。

---

## 目前狀態摘要

- 三個產品閉環已建立：資料與市場狀態、研究驗證、持倉檢查。
- Daily Decision Desk v1 已接上主 UI，形成每日決策入口。
- Strategy & Scoring Governance、10 檔 fixed / quantile OOS 實證、Research Run Registry、Cross-run Comparison 與 Registry-based Promote Gate 已完成；quantile 未優於 fixed，維持 opt-in。
- Phase 5 圖表渲染、批次並行化、SQLite 穩定分頁與規格化 Excel 報告匯出已完成；PDF 報告輸出仍在後續 backlog。
- Month 5 Fundamental Layer v1 已完成，包含 available_date gate、Fundamental SQLite workflow、Revenue / Valuation factor service 與 diagnostics。
- Month 6 Strategy Lifecycle / Portfolio Feedback v1 已落地，包含 lifecycle gate、append-only evidence、latest state projection、drift detector、post-trade attribution、Portfolio Review snapshot 與持倉管理生命週期回顧分頁。
- UI 已導入 Midnight Analyst 設計系統與全域 QSS；接下來主線是全 UI 健檢與 Month 6.1 lifecycle QA / manual approval / evidence explainability。

詳細狀態以 [PROJECT_SNAPSHOT.md](00_core/PROJECT_SNAPSHOT.md) 為準；未來方向以 [ROADMAP_6M_ENGINEERING.md](00_core/ROADMAP_6M_ENGINEERING.md) 為準。

---

## 快速閱讀路徑

### 第一次接觸

1. [PROJECT_SNAPSHOT.md](00_core/PROJECT_SNAPSHOT.md)
2. [ROADMAP_6M_ENGINEERING.md](00_core/ROADMAP_6M_ENGINEERING.md)
3. [DEVELOPMENT_ROADMAP.md](00_core/DEVELOPMENT_ROADMAP.md)
4. [DOCUMENTATION_INDEX.md](00_core/DOCUMENTATION_INDEX.md)
5. [system_architecture.md](01_architecture/system_architecture.md)

### 要查策略回測

1. [BACKTEST_LAB_FEATURES.md](02_features/BACKTEST_LAB_FEATURES.md)
2. [BACKTEST_LAB_CHECKLIST.md](02_features/BACKTEST_LAB_CHECKLIST.md)
3. [BACKTEST_LAB_FAQ.md](02_features/BACKTEST_LAB_FAQ.md)
4. [UI_QT_CHART_RENDERING.md](08_technical/UI_QT_CHART_RENDERING.md)

### 要使用系統

1. [APPLICATION_MANUAL.md](07_guides/APPLICATION_MANUAL.md)
2. [QUICK_START.md](07_guides/QUICK_START.md)
3. [USER_GUIDE.md](02_features/USER_GUIDE.md)
4. [UI_FEATURES_DOCUMENTATION.md](02_features/UI_FEATURES_DOCUMENTATION.md)
5. [HOW_TO_UPDATE_DAILY_DATA.md](03_data/HOW_TO_UPDATE_DAILY_DATA.md)

### 要開發或整理文件

1. [DOC_COVERAGE_MAP.md](00_core/DOC_COVERAGE_MAP.md)
2. [DOCUMENTATION_STRUCTURE.md](00_core/DOCUMENTATION_STRUCTURE.md)
3. [AGENT_CONTEXT.md](../AGENT_CONTEXT.md)
4. [PROJECT_NAVIGATION.md](../PROJECT_NAVIGATION.md)
5. [PROJECT_INVENTORY.md](../PROJECT_INVENTORY.md)

---

## 維護原則

- 不確定狀態時，先判斷主題：現在看 Snapshot，未來路線看 6M Roadmap，架構看 system architecture。
- 新增、刪除或搬移文件後，必須更新 `00_core/DOCUMENTATION_INDEX.md`。
- 根目錄 `README.md` 保持使用者導向；Agent / 開發者上下文放在 `../AGENT_CONTEXT.md` 與 `agents/`。
- 會影響使用者操作、參數、結果判讀或安全限制的變更，必須同步 `07_guides/APPLICATION_MANUAL.md`；專題教學或功能說明再同步 `02_features/USER_GUIDE.md`、`02_features/UI_FEATURES_DOCUMENTATION.md`。
- 過期但仍有歷史價值的文件放入 `09_archive/`；沒有引用、沒有歷史價值、且內容已被新文件取代的文件可以刪除。

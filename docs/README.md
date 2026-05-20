# Docs 文檔目錄

> **最後整理**：2026-05-19  
> **權威順序**：先看 `00_core/DEVELOPMENT_ROADMAP.md` 的 Living Section，再看 `00_core/PROJECT_SNAPSHOT.md` 和 `00_core/DOCUMENTATION_INDEX.md`。

本目錄是專案文件的主要入口。文件已依用途分區，日常查找請優先使用：

1. [開發演進地圖](00_core/DEVELOPMENT_ROADMAP.md) - Phase 狀態與下一步的 Single Source of Truth
2. [專案快照](00_core/PROJECT_SNAPSHOT.md) - 30 秒讀完的目前狀態
3. [文檔索引](00_core/DOCUMENTATION_INDEX.md) - 所有保留文檔的導航
4. [文檔結構與維護規則](00_core/DOCUMENTATION_STRUCTURE.md) - 資料夾歸屬、刪除與歸檔規則
5. [文檔覆蓋矩陣](00_core/DOC_COVERAGE_MAP.md) - 文件更新時要同步哪些文檔

---

## 目錄歸屬

| 目錄 | 用途 | 狀態 |
|---|---|---|
| `00_core/` | 權威入口、roadmap、snapshot、索引、coverage 規則 | 必讀 |
| `01_architecture/` | 系統架構、資料流、Runtime 規範、多 Agent 工作流 | 長期維護 |
| `02_features/` | UI、使用者指南、回測、評分、策略規格 | 使用者與功能說明 |
| `03_data/` | 每日資料、資料流、重建與故障排除 | 資料更新操作 |
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

- Phase 1、Phase 2、Phase 2.5 核心：已完成。
- Phase 3.1、3.2、3.3a、3.3b：已完成，包含推薦可用化、Profiles、研究閉環、Promote、Walk-forward、Baseline、過擬合風險與 K 線視覺驗證。
- AI Runtime Subsystem MVP：已完成。
- Smart Money Terminal MVP：已完成。
- UI Qt Backtest chart rendering：已完成 QtWebEngine + HTML5 Canvas fast renderer，回測圖表保留 Matplotlib fallback。
- Phase 4.1 Portfolio：服務層 / domain / 測試骨架已開始，`ui_qt` 使用者可見 Portfolio Tab 尚未完成。
- Phase 5：尚未開始，僅有部分回測/最佳化效能改善。

詳細狀態永遠以 [DEVELOPMENT_ROADMAP.md](00_core/DEVELOPMENT_ROADMAP.md) 的 Living Section 為準。

---

## 快速閱讀路徑

### 第一次接觸

1. [PROJECT_SNAPSHOT.md](00_core/PROJECT_SNAPSHOT.md)
2. [DEVELOPMENT_ROADMAP.md](00_core/DEVELOPMENT_ROADMAP.md)
3. [DOCUMENTATION_INDEX.md](00_core/DOCUMENTATION_INDEX.md)
4. [system_architecture.md](01_architecture/system_architecture.md)

### 要查策略回測

1. [BACKTEST_LAB_FEATURES.md](02_features/BACKTEST_LAB_FEATURES.md)
2. [BACKTEST_LAB_CHECKLIST.md](02_features/BACKTEST_LAB_CHECKLIST.md)
3. [BACKTEST_LAB_FAQ.md](02_features/BACKTEST_LAB_FAQ.md)
4. [UI_QT_CHART_RENDERING.md](08_technical/UI_QT_CHART_RENDERING.md)

### 要使用系統

1. [QUICK_START.md](07_guides/QUICK_START.md)
2. [USER_GUIDE.md](02_features/USER_GUIDE.md)
3. [UI_FEATURES_DOCUMENTATION.md](02_features/UI_FEATURES_DOCUMENTATION.md)
4. [HOW_TO_UPDATE_DAILY_DATA.md](03_data/HOW_TO_UPDATE_DAILY_DATA.md)

### 要開發或整理文件

1. [DOC_COVERAGE_MAP.md](00_core/DOC_COVERAGE_MAP.md)
2. [DOCUMENTATION_STRUCTURE.md](00_core/DOCUMENTATION_STRUCTURE.md)
3. [PROJECT_NAVIGATION.md](../PROJECT_NAVIGATION.md)
4. [PROJECT_INVENTORY.md](../PROJECT_INVENTORY.md)

---

## 維護原則

- 不確定狀態時，以 roadmap Living Section 為準。
- 新增、刪除或搬移文件後，必須更新 `00_core/DOCUMENTATION_INDEX.md`。
- 會影響使用者操作的變更，必須同步 `02_features/USER_GUIDE.md` 或 `02_features/UI_FEATURES_DOCUMENTATION.md`。
- 過期但仍有歷史價值的文件放入 `09_archive/`；沒有引用、沒有歷史價值、且內容已被新文件取代的文件可以刪除。

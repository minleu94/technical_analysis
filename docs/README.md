# Docs 文檔目錄

> **文檔已重新組織**（2026-01-03）
> 
> 所有文檔已按功能分類到不同目錄，請使用 [文檔索引](00_core/DOCUMENTATION_INDEX.md) 查找所需文檔。

## 📁 目錄結構

```
docs/
├── 00_core/              # 核心文檔（必讀）
│   ├── DEVELOPMENT_ROADMAP.md        # 開發路線圖（最高權威）
│   ├── PROJECT_SNAPSHOT.md           # 專案快照（開場 30 秒）
│   ├── DOCUMENTATION_INDEX.md        # 文檔索引
│   ├── DOC_COVERAGE_MAP.md           # 文檔覆蓋矩陣
│   └── note.txt                      # 開發進度記錄
│
├── 01_architecture/      # 架構文檔
│   ├── system_architecture.md
│   ├── system_flow_end_to_end.md
│   ├── data_collection_architecture.md
│   └── REFACTORING_MIGRATION_PLAN.md
│
├── 02_features/          # 功能文檔
│   ├── UI_FEATURES_DOCUMENTATION.md
│   ├── USER_GUIDE.md
│   ├── BACKTEST_LAB_FEATURES.md
│   ├── BACKTEST_LAB_COMPLETE.md
│   ├── SCORE_EXPLANATION.md
│   └── STRATEGY_DESIGN_SPECIFICATION.md
│
├── 03_data/              # 數據相關文檔
│   ├── HOW_TO_UPDATE_DAILY_DATA.md
│   ├── daily_data_update_guide.md
│   ├── DATA_FETCHING_LOGIC.md
│   ├── DATA_FLOW_LOGIC.md
│   ├── DATA_REBUILD_GUIDE.md
│   └── TROUBLESHOOTING_DAILY_UPDATE.md
│
├── 04_broker_branch/     # 券商分點相關文檔
│   └── BROKER_BRANCH_*.md
│
├── 05_phases/            # Phase 相關文檔
│   ├── PHASE2_*.md
│   ├── PHASE3_*.md
│   └── EPIC2_*.md
│
├── 06_qa/                # QA 相關文檔
│   └── QA_*.md
│
├── 07_guides/            # 指南文檔
│   ├── QUICK_START.md
│   ├── QUICK_REFERENCE.md
│   ├── INSTALL_GUIDE.md
│   └── scripts_readme.md
│
├── 08_technical/         # 技術文檔
│   └── PARAMETER_DESIGN_IMPROVEMENTS.md
│
├── 09_archive/           # 歸檔文檔（歷史記錄/總結）
│   └── DOCUMENTATION_*.md
│
├── agents/               # Agent 文檔
│   └── *.md
│
└── strategies/           # 策略文檔
    └── *.md
```

## 🚀 快速導航

### 第一次接觸系統
1. [專案快照](00_core/PROJECT_SNAPSHOT.md) ⭐ - 快速了解當前狀態（30秒）
2. [開發演進地圖](00_core/DEVELOPMENT_ROADMAP.md) - 了解系統定位和演進計劃
3. [系統架構文檔](01_architecture/system_architecture.md) - 了解技術架構

### 開始使用系統
1. [快速開始](07_guides/QUICK_START.md) - 快速上手
2. [數據更新指南](03_data/daily_data_update_guide.md) - 更新數據
3. [腳本使用說明](07_guides/scripts_readme.md) - 使用腳本

### 查找文檔
- [文檔索引](00_core/DOCUMENTATION_INDEX.md) - 完整的文檔索引和導航

## 📝 重要提醒

- **核心文檔**：所有核心文檔都在 `00_core/` 目錄
- **文檔索引**：使用 `00_core/DOCUMENTATION_INDEX.md` 查找所需文檔
- **專案快照**：每次開新對話先看 `00_core/PROJECT_SNAPSHOT.md`（30秒內讀完）


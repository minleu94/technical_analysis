# 文檔索引

> **最後整理**：2026-05-27
> **判讀規則**：Phase 狀態以 `DEVELOPMENT_ROADMAP.md` 的 Living Section 為準；本索引用於導航，不取代 roadmap。

---

## 0. 核心入口

| 文件 | 用途 |
|---|---|
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | 系統定位、Phase 狀態、Living Section、Next、Risks。最高權威。 |
| [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) | 30 秒讀完的目前狀態摘要。 |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) | 本文件，文檔導航。 |
| [DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md) | `docs/` 資料夾歸屬、生命週期、刪除/歸檔規則。 |
| [DOC_COVERAGE_MAP.md](DOC_COVERAGE_MAP.md) | 變更類型對應需要同步更新的文件。 |
| [AI_CONTEXT_PACK.md](AI_CONTEXT_PACK.md) | 給外部 AI / Agent 的高密度專案上下文。 |
| [PROJECT_NAVIGATION.md](../../PROJECT_NAVIGATION.md) | repo 根目錄的日常開發導航。 |
| [PROJECT_INVENTORY.md](../../PROJECT_INVENTORY.md) | repo 根目錄的完整專案盤點。 |
| [../../AGENTS.md](../../AGENTS.md) | Codex 自動讀取的 repo 根目錄指令入口，指向 `docs/agents/` 完整 Agent 架構。 |

---

## 1. 架構文件

| 文件 | 用途 |
|---|---|
| [system_architecture.md](../01_architecture/system_architecture.md) | 系統模組與分層架構。 |
| [system_flow_end_to_end.md](../01_architecture/system_flow_end_to_end.md) | 端到端流程。 |
| [data_collection_architecture.md](../01_architecture/data_collection_architecture.md) | 資料收集架構。 |
| [runtime_observatory_rules.md](../01_architecture/runtime_observatory_rules.md) | Runtime Observatory 架構治理規範。 |
| [multi_agent_workflow.md](../01_architecture/multi_agent_workflow.md) | 多 Agent 協作與合併規範。 |
| [REFACTORING_MIGRATION_PLAN.md](../01_architecture/REFACTORING_MIGRATION_PLAN.md) | 歷史/長期 refactor 遷移計畫。 |

---

## 2. 功能與使用者文件

| 文件 | 用途 |
|---|---|
| [UI_FEATURES_DOCUMENTATION.md](../02_features/UI_FEATURES_DOCUMENTATION.md) | Qt UI 功能完整說明，包含 Phase 3.3b、Runtime、Smart Money。 |
| [USER_GUIDE.md](../02_features/USER_GUIDE.md) | 使用者操作教學。 |
| [BACKTEST_LAB_FEATURES.md](../02_features/BACKTEST_LAB_FEATURES.md) | 策略回測實驗室功能說明。 |
| [BACKTEST_LAB_CHECKLIST.md](../02_features/BACKTEST_LAB_CHECKLIST.md) | 策略回測頁面功能清單與進度。 |
| [BACKTEST_LAB_FAQ.md](../02_features/BACKTEST_LAB_FAQ.md) | 策略回測常見問題與使用細節。 |
| [SCORE_EXPLANATION.md](../02_features/SCORE_EXPLANATION.md) | 評分系統與 buy/sell score 說明。 |
| [STRATEGY_DESIGN_SPECIFICATION.md](../02_features/STRATEGY_DESIGN_SPECIFICATION.md) | Baseline Score Threshold 策略設計規格。 |

---

## 3. 資料文件

| 文件 | 用途 |
|---|---|
| [HOW_TO_UPDATE_DAILY_DATA.md](../03_data/HOW_TO_UPDATE_DAILY_DATA.md) | 每日資料更新快速指南。 |
| [daily_data_update_guide.md](../03_data/daily_data_update_guide.md) | 每日資料更新詳細指南。 |
| [DATA_FETCHING_LOGIC.md](../03_data/DATA_FETCHING_LOGIC.md) | 資料抓取邏輯。 |
| [DATA_FLOW_LOGIC.md](../03_data/DATA_FLOW_LOGIC.md) | 推薦分析資料流程。 |
| [DATA_REBUILD_GUIDE.md](../03_data/DATA_REBUILD_GUIDE.md) | 從 daily price 重建衍生資料。 |
| [TROUBLESHOOTING_DAILY_UPDATE.md](../03_data/TROUBLESHOOTING_DAILY_UPDATE.md) | 每日資料更新故障排除。 |
| [INDUSTRY_INDEX_UPDATE_SUMMARY.md](../03_data/INDUSTRY_INDEX_UPDATE_SUMMARY.md) | 產業指數更新說明。 |
| [MERGE_AND_MARKET_INDEX_SUMMARY.md](../03_data/MERGE_AND_MARKET_INDEX_SUMMARY.md) | 市場指數與合併說明。 |

---

## 4. 券商分點 / Smart Money

| 文件 | 用途 |
|---|---|
| [BROKER_BRANCH_DATA_MODULE_DESIGN_V2.md](../04_broker_branch/BROKER_BRANCH_DATA_MODULE_DESIGN_V2.md) | 券商分點資料模組設計。 |
| [BROKER_BRANCH_IMPLEMENTATION_SUMMARY.md](../04_broker_branch/BROKER_BRANCH_IMPLEMENTATION_SUMMARY.md) | 券商分點實作總結。 |
| [BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md](../04_broker_branch/BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md) | 分點資料測試與故障排除。 |
| [BROKER_BRANCH_ERROR_DETECTION_IMPROVEMENT.md](../04_broker_branch/BROKER_BRANCH_ERROR_DETECTION_IMPROVEMENT.md) | 錯誤檢測改進記錄。 |
| [BROKER_BRANCH_PARSING_IMPROVEMENT.md](../04_broker_branch/BROKER_BRANCH_PARSING_IMPROVEMENT.md) | 對手券商/股票名稱解析改進記錄。 |

---

## 5. Phase 設計與研究 SOP

| 文件 | 用途 |
|---|---|
| [PHASE2_ARCHITECTURE.md](../05_phases/PHASE2_ARCHITECTURE.md) | Phase 2 策略架構設計。 |
| [PHASE2_STRATEGY_LIBRARY.md](../05_phases/PHASE2_STRATEGY_LIBRARY.md) | Phase 2 策略資料庫設計。 |
| [PHASE2_5_COMPLETION_STATUS.md](../05_phases/PHASE2_5_COMPLETION_STATUS.md) | Phase 2.5 完成狀態與剩餘優化。 |
| [PHASE3_3B_RESEARCH_DESIGN.md](../05_phases/PHASE3_3B_RESEARCH_DESIGN.md) | Phase 3.3b 研究設計規格。 |
| [PHASE_3_3B_IMPLEMENTATION_PLAN.md](../05_phases/PHASE_3_3B_IMPLEMENTATION_PLAN.md) | Phase 3.3b 實施規劃，現作歷史與追溯用途。 |
| [EPIC2_MVP2_ARCHITECTURE_DESIGN.md](../05_phases/EPIC2_MVP2_ARCHITECTURE_DESIGN.md) | 過擬合風險提示架構設計。 |
| [EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md](../05_phases/EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md) | 過擬合風險提示實作檢查清單。 |
| [PHASE4_PORTFOLIO_DESIGN.md](../05_phases/PHASE4_PORTFOLIO_DESIGN.md) | Phase 4 Portfolio MVP 設計。 |
| [PHASE4_STARTUP_SUMMARY.md](../05_phases/PHASE4_STARTUP_SUMMARY.md) | Phase 4 骨架啟動總結。 |
| [phase3_5_research/README.md](../05_phases/phase3_5_research/README.md) | Phase 3.5 研究 SOP 入口。 |
| [phase3_5_research/RESEARCH_ITERATION_PLAYBOOK.md](../05_phases/phase3_5_research/RESEARCH_ITERATION_PLAYBOOK.md) | 研究循環 playbook。 |
| [phase3_5_research/METRIC_INTERPRETATION_PRIORITY.md](../05_phases/phase3_5_research/METRIC_INTERPRETATION_PRIORITY.md) | 指標判讀優先順序。 |
| [phase3_5_research/BENCHMARK_PRESENTATION.md](../05_phases/phase3_5_research/BENCHMARK_PRESENTATION.md) | Benchmark 顯示與解讀規範。 |
| [phase3_5_research/PHASE4_ENTRY_CRITERIA.md](../05_phases/phase3_5_research/PHASE4_ENTRY_CRITERIA.md) | Phase 4 進入條件。 |

---

## 6. QA 與審核

| 文件 | 用途 |
|---|---|
| [QA_RECOMMENDATION_TAB_ISSUES.md](../06_qa/QA_RECOMMENDATION_TAB_ISSUES.md) | 推薦分析 Tab QA 問題。 |
| [QA_RECOMMENDATION_TAB_SUMMARY.md](../06_qa/QA_RECOMMENDATION_TAB_SUMMARY.md) | 推薦分析 Tab QA 總結。 |
| [QA_UPDATE_TAB_ISSUES.md](../06_qa/QA_UPDATE_TAB_ISSUES.md) | 數據更新 Tab QA 問題。 |
| [QA_UPDATE_TAB_SUMMARY.md](../06_qa/QA_UPDATE_TAB_SUMMARY.md) | 數據更新 Tab QA 總結。 |
| [UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md](../06_qa/UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md) | `ui_qt` 對照 roadmap 的逐項審核報表。 |

---

## 7. 操作指南

| 文件 | 用途 |
|---|---|
| [QUICK_START.md](../07_guides/QUICK_START.md) | 快速開始。 |
| [QUICK_REFERENCE.md](../07_guides/QUICK_REFERENCE.md) | 常用命令與快速查找。 |
| [INSTALL_GUIDE.md](../07_guides/INSTALL_GUIDE.md) | 安裝與環境設置。 |
| [scripts_readme.md](../07_guides/scripts_readme.md) | `scripts/` 目錄腳本說明。 |
| [tests_readme.md](../07_guides/tests_readme.md) | `tests/` 目錄測試說明。 |

---

## 8. 技術文件

| 文件 | 用途 |
|---|---|
| [PARAMETER_DESIGN_IMPROVEMENTS.md](../08_technical/PARAMETER_DESIGN_IMPROVEMENTS.md) | Phase 2.5 參數設計改進。 |
| [technical_analysis_optimizations.md](../08_technical/technical_analysis_optimizations.md) | 技術分析模組優化記錄。 |
| [UI_QT_CHART_RENDERING.md](../08_technical/UI_QT_CHART_RENDERING.md) | Qt Backtest 圖表 fast Canvas renderer、payload layer 與 Matplotlib fallback 架構。 |
| [path_isolation_update.md](../08_technical/path_isolation_update.md) | 路徑隔離與測試環境分離記錄。 |
| [RUN_WITHOUT_VENV.md](../08_technical/RUN_WITHOUT_VENV.md) | 不使用 venv 的執行說明。 |

---

## 9. Agent 與策略文件

| 文件 | 用途 |
|---|---|
| [agents/README.md](../agents/README.md) | Agent 文件入口。 |
| [agents/shared_context.md](../agents/shared_context.md) | Agent 共用上下文。 |
| [agents/git_exclusions.md](../agents/git_exclusions.md) | Git 排除與不應提交清單。 |
| [agents/tech_lead.md](../agents/tech_lead.md) | Tech Lead Agent。 |
| [agents/execution_agent.md](../agents/execution_agent.md) | Execution Agent。 |
| [agents/documentation_agent.md](../agents/documentation_agent.md) | Documentation Agent。 |
| [agents/data_audit_agent.md](../agents/data_audit_agent.md) | Data Audit Agent。 |
| [agents/data_cleanup_agent.md](../agents/data_cleanup_agent.md) | Data Cleanup Agent。 |
| [agents/CURSOR_SKILLS_DEFINITIONS.md](../agents/CURSOR_SKILLS_DEFINITIONS.md) | Cursor skills 定義。 |
| [strategies/momentum_aggressive_v1.md](../strategies/momentum_aggressive_v1.md) | 暴衝策略說明。 |
| [strategies/stable_conservative_v1.md](../strategies/stable_conservative_v1.md) | 穩健策略說明。 |

---

## 10. Archive

[09_archive/](../09_archive/README.md) 只放歷史文件、已執行提案、舊調查與不再作為日常依據的內容。Active 文件不應依賴 archive 來判斷目前狀態。

---

## 目前開發狀態

- 已完成：Phase 1、Phase 2、Phase 2.5 核心、Phase 3.1、Phase 3.2、Phase 3.3a、Phase 3.3b、Runtime Observatory MVP、Smart Money Terminal MVP、UI Qt Backtest chart fast renderer、Recommendation Portfolio Backtest MVP。
- 進行中 / 下一步：推薦組合回測穩健分析（Sortino、Sharpe、Monte Carlo）與 Phase 4.1 Portfolio MVP 的 UI / Phase 3 → Portfolio 整合。
- 待開始：Phase 5 效能與研究報告輸出。

---

## 維護提醒

- 新增或刪除任何 Markdown 後，更新本索引。
- Phase 狀態文字若與 roadmap Living Section 衝突，以 roadmap 為準並修正本索引。
- 不確定文件是否該刪除時，先移入 `09_archive/` 或在 `DOCUMENTATION_STRUCTURE.md` 記錄決策。

# 文檔索引

> **最後整理**：2026-06-13
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
| [../../GEMINI.md](../../GEMINI.md) | Antigravity 自動讀取的 repo 根目錄指令入口，指向 `docs/agents/antigravity/` 與 `.agent/rules/`。 |

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
| [SQLITE_STORAGE_GUIDE.md](../03_data/SQLITE_STORAGE_GUIDE.md) | SQLite 儲存與雙軌相容快取架構、一鍵遷移重建指南。 |

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
| [PHASE_2A_DATA_SOURCES_AUDIT.md](../05_phases/PHASE_2A_DATA_SOURCES_AUDIT.md) | Phase 2A 數據讀取來源盤點與改造規劃。 |
| [PHASE2_5_COMPLETION_STATUS.md](../05_phases/PHASE2_5_COMPLETION_STATUS.md) | Phase 2.5 完成狀態與剩餘優化。 |
| [PHASE3_3B_RESEARCH_DESIGN.md](../05_phases/PHASE3_3B_RESEARCH_DESIGN.md) | Phase 3.3b 研究設計規格。 |
| [PHASE_3_3B_IMPLEMENTATION_PLAN.md](../09_archive/PHASE_3_3B_IMPLEMENTATION_PLAN.md) | [已歸檔] Phase 3.3b 實施規劃，現作歷史與追溯用途。 |
| [EPIC2_MVP2_ARCHITECTURE_DESIGN.md](../05_phases/EPIC2_MVP2_ARCHITECTURE_DESIGN.md) | 過擬合風險提示架構設計。 |
| [EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md](../05_phases/EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md) | 過擬合風險提示實作檢查清單。 |
| [PHASE4_PORTFOLIO_DESIGN.md](../05_phases/PHASE4_PORTFOLIO_DESIGN.md) | Phase 4 Portfolio MVP 設計。 |
| [PHASE4_STARTUP_SUMMARY.md](../05_phases/PHASE4_STARTUP_SUMMARY.md) | Phase 4 骨架啟動總結。 |
| [2026-06-04-research-lab-workflow-redesign.md](../superpowers/specs/2026-06-04-research-lab-workflow-redesign.md) | Research Lab 多模式實驗室、候選池與 Phase 3 → Portfolio 來源追溯設計。 |
| [2026-06-04-research-lab-workflow-redesign.md](../superpowers/plans/2026-06-04-research-lab-workflow-redesign.md) | Research Lab 工作流重整第一階段實作計畫。 |
| [2026-06-11-financial-float-boundary-governance-design.md](../superpowers/specs/2026-06-11-financial-float-boundary-governance-design.md) | 金融核心白名單的 AST float 邊界掃描、逐行分類標記與 pytest 防回歸設計。 |
| [2026-06-13-strategy-scoring-governance-design.md](../superpowers/specs/2026-06-13-strategy-scoring-governance-design.md) | fixed / quantile 雙模式、回測 Expanding T-1 與推薦 eligible universe 橫斷面百分位設計。 |
| [2026-06-13-strategy-scoring-governance.md](../superpowers/plans/2026-06-13-strategy-scoring-governance.md) | 策略分數治理總控計畫與增量 Gate。 |
| [2026-06-13-strategy-scoring-governance-a-backtest.md](../superpowers/plans/2026-06-13-strategy-scoring-governance-a-backtest.md) | 增量 A：回測 fixed / quantile 雙模式門檻實作計畫。 |
| [2026-06-13-strategy-scoring-governance-b-recommendation.md](../superpowers/plans/2026-06-13-strategy-scoring-governance-b-recommendation.md) | 增量 B：推薦 eligible universe 橫斷面排名實作計畫。 |
| [2026-06-11-financial-float-boundary-governance.md](../superpowers/plans/2026-06-11-financial-float-boundary-governance.md) | 金融 float 邊界 AST 掃描、逐行標記與 pytest gate 實作計畫。 |
| [2026-06-11-broker-flow-sqlite-and-ui-recovery.md](../superpowers/plans/2026-06-11-broker-flow-sqlite-and-ui-recovery.md) | 券商分點 SQLite 唯一鍵、ETF 代號與 UI 復原計畫。 |
| [2026-06-12-broker-flow-ranked-metric-reconciliation.md](../superpowers/plans/2026-06-12-broker-flow-ranked-metric-reconciliation.md) | MoneyDJ E/B 獨立榜單 union、三態品質與覆蓋率治理計畫。 |
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
| [WALK_FORWARD_COMPARISON_REPORT.md](../06_qa/WALK_FORWARD_COMPARISON_REPORT.md) | Fixed vs Quantile 機制與回歸驗證；真實 walk-forward 績效比較待執行。 |

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
| [agents/skills_registry.md](../agents/skills_registry.md) | Codex / Antigravity 共用的角色選擇、流程導引與 shared context 入口。 |
| [agents/skills/team.md](../agents/skills/team.md) | Codex / Antigravity 任務分流與交接流程。 |
| [agents/antigravity/README.md](../agents/antigravity/README.md) | Antigravity Agent 入口與角色分流。 |
| [agents/antigravity/tech_lead_agent.md](../agents/antigravity/tech_lead_agent.md) | Antigravity Tech Lead Agent。 |
| [agents/antigravity/execution_agent.md](../agents/antigravity/execution_agent.md) | Antigravity Execution Agent。 |
| [agents/antigravity/documentation_agent.md](../agents/antigravity/documentation_agent.md) | Antigravity Documentation Agent。 |
| [agents/antigravity/data_audit_agent.md](../agents/antigravity/data_audit_agent.md) | Antigravity Data Audit Agent。 |
| [agents/antigravity/data_cleanup_agent.md](../agents/antigravity/data_cleanup_agent.md) | Antigravity Data Cleanup Agent。 |
| [agents/antigravity/handoff_template.md](../agents/antigravity/handoff_template.md) | Antigravity 任務交接模板。 |
| [agents/archive/CURSOR_SKILLS_DEFINITIONS.md](../agents/archive/CURSOR_SKILLS_DEFINITIONS.md) | 舊 Cursor skills 定義封存，僅保留作為遷移參考。 |
| [strategies/momentum_aggressive_v1.md](../strategies/momentum_aggressive_v1.md) | 暴衝策略說明。 |
| [strategies/stable_conservative_v1.md](../strategies/stable_conservative_v1.md) | 穩健策略說明。 |

---

## 10. Archive

[09_archive/](../09_archive/README.md) 只放歷史文件、已執行提案、舊調查與不再作為日常依據的內容。Active 文件不應依賴 archive 來判斷目前狀態。
主要封存文檔：
- [NEXT_ACTION_PLAN.md](../09_archive/NEXT_ACTION_PLAN.md)：2026-06-09 下一輪行動計畫（已執行完畢）。
- [PHASE_3_3B_IMPLEMENTATION_PLAN.md](../09_archive/PHASE_3_3B_IMPLEMENTATION_PLAN.md)：Phase 3.3b 實施規劃（已執行完畢）。

---

## 目前開發狀態

- **已完成（三個產品閉環之基礎建置與完整深化）**：資料與市場狀態閉環（SQLite DB-first/視覺化檢視/Smart Money Terminal/一鍵安全數據更新工作台/技術指標 280 萬筆全量重算）、研究驗證閉環（Research Lab 多模式實驗室/單股回測/最佳化/Walk-forward/推薦組合回測 MVP 與穩健性指標/Fast Renderer 圖表/Promote 晉升與 SOP 驗證/批次回測並行化與安全軟取消）、持倉檢查閉環（domain/service/test/Portfolio Tab/條件監控/手動與回測來源追溯及強制平倉標記/覆盤日記/策略與價格監控/停損停利警示/籌碼監控與下鑽）。
- **進行中 / 當前治理**：當前無阻礙之進行中項目。
- **待開始 (Backlog)**：Phase 5 中大表格分頁、Excel/PDF 報告輸出。

---

## 維護提醒

- 新增或刪除任何 Markdown 後，更新本索引。
- Phase 狀態文字若與 roadmap Living Section 衝突，以 roadmap 為準並修正本索引。
- 不確定文件是否該刪除時，先移入 `09_archive/` 或在 `DOCUMENTATION_STRUCTURE.md` 記錄決策。

---

## 🔄 更新記錄

- 2026-06-03：完成 Phase 2C 實作，新增 SQLite 資料庫視覺化檢視面板 (SqliteInspectorWidget) 與防禦性唯讀查詢服務 (SqliteInspectorService) 整合至數據更新工作台。
- 2026-06-03：新增 Phase 2A 數據讀取來源盤點報告 (PHASE_2A_DATA_SOURCES_AUDIT.md) 連結至文檔索引，並標記 Phase 2A/2B 已完成。
- 2026-06-04：新增 Research Lab 工作流重整 spec / plan 連結，標記候選池語意與 Phase 3 → Portfolio 來源追溯為進行中主線。
- 2026-06-06：完成策略回測驗證實驗室說明文檔（[BACKTEST_LAB_FEATURES.md](../02_features/BACKTEST_LAB_FEATURES.md)）之撮合限制、SOP 驗證、未來函數防禦與強制平倉 Portfolio 記錄機制同步更新，並優化 tab info 說明對話框文字。
- 2026-06-06：啟動策略回測視圖（`backtest_view.py`）之漸進式重構，完成 Phase 1 拆分：抽離常數、說明 Tooltip 與純計算輔助函數至 `ui_qt/views/backtest/` 目錄下。
- 2026-06-06：完成策略回測視圖（`backtest_view.py`）之漸進式重構 Phase 2 至 Phase 4：抽離右側結果面板 `BacktestResultPanel` 與左側配置面板 `BacktestConfigPanel`，採用 QWidget native 屬性安全排除的動態委派路由，並補全所有關鍵 Widget 的顯式 `@property` 宣告以取得最佳的 mypy 與 IDE autocomplete 支援，保持與現有單元測試及 QA 契約 100% 相容。
- 2026-06-09：新增 [NEXT_ACTION_PLAN.md](NEXT_ACTION_PLAN.md)，整理 Tech Lead 審查後的下一輪 Roadmap Rebaseline、回測時間軸治理、金融核心數值治理與 Agent 交接順序。
- 2026-06-09：執行 Roadmap Rebaseline，將 Living Section 改為三個產品閉環敘事，同步更新 Snapshot / AI Context Pack / Navigation / Inventory。
- 2026-06-09：更新 system_architecture.md、UI_FEATURES_DOCUMENTATION.md、BACKTEST_LAB_FEATURES.md 與 BACKTEST_LAB_CHECKLIST.md，統一產品閉環、Tab 結構、Sortino/Sharpe/Monte Carlo 指標以及參數最佳化進度與雙擊套用功能的描述，消除歷史 Phase 矛盾。
- 2026-06-11：新增金融 float 邊界治理實作計畫，依 TDD 拆分 source scanner、CLI、repository gate 與文件收尾。
- 2026-06-12：新增券商分點 SQLite/UI 復原與 E/B ranked metric reconciliation 實作計畫。
- 2026-06-13：新增策略分數治理總控計畫，拆分回測雙模式門檻與推薦橫斷面排名兩個可獨立驗收增量。
- 2026-06-11：完成 Phase 4.2 持倉層籌碼面風險提示與下鑽整合，實作 SQLite/CSV 雙軌籌碼監控服務與 UI Tab，並打通「🔍 下鑽詳細主力流向」之 Tab 切換與個股自動定位高亮連動。
- 2026-06-12：將已執行完畢的 [NEXT_ACTION_PLAN.md](../09_archive/NEXT_ACTION_PLAN.md) 移至歸檔目錄 `docs/09_archive/`，並更新文檔索引。
- 2026-06-12：完成批次回測並行化與安全軟取消實作，修復 `max_workers=None` 路徑，新增真實 BrokenProcessPool 測試；回測與最佳化採合作式取消，其他長任務頁面維持既有取消行為相容，並明確記錄 legacy `terminate()` 技術債。
- 2026-06-13：新增 Strategy & Scoring Governance 正式設計，核准 fixed / quantile 雙模式、回測 Expanding T-1、60 個有效觀測值暖機、整數基點與推薦 eligible universe 橫斷面排名契約；同步修正 Phase 2.5 分位數誤標完成與 Active 文件舊路徑。
- 2026-06-13：完成 Strategy & Scoring Governance 增量 A、B 的功能實作與機制回歸驗證；真實股票池的 fixed / quantile walk-forward 績效比較尚待執行。
- 2026-06-13：完成治理成果收尾驗收，補齊 Snapshot、Roadmap、Phase 2.5 狀態與 Project Navigation；記錄 `82 + 9 + 37` 項 pytest、Update Tab QA `21/0` 與 mypy 144 檔通過證據。




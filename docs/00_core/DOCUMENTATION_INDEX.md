# 文檔索引

> **最後整理**：2026-06-30
> **判讀規則**：本索引用於導航，不作為狀態或架構事實來源。專案改採 Scoped SSOT：目前狀態看 `PROJECT_SNAPSHOT.md`，未來 6 個月看 `ROADMAP_6M_ENGINEERING.md`，架構看 `system_architecture.md`。

---

## 0. 核心入口

| 文件 | 用途 |
|---|---|
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | Roadmap Hub，指向 Snapshot、6M Roadmap、Architecture 與歷史歸檔。 |
| [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) | 未來 6 個月可執行工程路線、里程碑、交付物與驗收標準。 |
| [system_vision_specification.md](../01_architecture/system_vision_specification.md) | baldr 產品北極星、目前邊界、Gap Register、長期能力圖像與投資有效性驗證框架；不取代 Snapshot、6M Roadmap 或 Architecture。 |
| [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md) | 舊 Roadmap 未完成事項的逐項處置、移交月份與 Month 3 前結案 Gate。 |
| [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) | 30 秒讀完的目前狀態摘要、本週優先事項與高風險區。 |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) | 本文件，文檔導航。 |
| [DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md) | `docs/` 資料夾歸屬、生命週期、刪除/歸檔規則。 |
| [DOC_COVERAGE_MAP.md](DOC_COVERAGE_MAP.md) | 變更類型對應需要同步更新的文件。 |
| [AI_CONTEXT_PACK.md](AI_CONTEXT_PACK.md) | 給外部 AI / Agent 的高密度專案上下文。 |
| [../../README.md](../../README.md) | repo 根目錄的使用者導向入口、功能概覽、啟動方式與分支策略。 |
| [../../AGENT_CONTEXT.md](../../AGENT_CONTEXT.md) | Agent / 開發者快速上下文，補充文件權威、分支策略與接手導覽。 |
| [PROJECT_NAVIGATION.md](../../PROJECT_NAVIGATION.md) | repo 根目錄的日常開發導航。 |
| [PROJECT_INVENTORY.md](../../PROJECT_INVENTORY.md) | repo 根目錄的完整專案盤點。 |
| [../../AGENTS.md](../../AGENTS.md) | Codex 自動讀取的 repo 根目錄指令入口，指向 `docs/agents/` 完整 Agent 架構。 |
| [../../GEMINI.md](../../GEMINI.md) | Antigravity 自動讀取的 repo 根目錄指令入口，指向 `docs/agents/antigravity/` 與 `.agent/rules/`。 |

---

## 1. 架構文件

| 文件 | 用途 |
|---|---|
| [system_architecture.md](../01_architecture/system_architecture.md) | 目前系統模組、分層架構、資料流與模組邊界的架構權威。 |
| [system_vision_specification.md](../01_architecture/system_vision_specification.md) | baldr 產品北極星、Current State 邊界、Evidence Requirement、Daily Decision Desk Contract、Gap Register、投資有效性驗證框架與下一階段 Evidence-Driven baldr 方向。 |
| [system_flow_end_to_end.md](../01_architecture/system_flow_end_to_end.md) | 端到端流程。 |
| [data_collection_architecture.md](../01_architecture/data_collection_architecture.md) | 資料收集架構。 |
| [runtime_observatory_rules.md](../01_architecture/runtime_observatory_rules.md) | Runtime Observatory 架構治理規範。 |
| [ui_design_system_midnight_analyst.md](../01_architecture/ui_design_system_midnight_analyst.md) | Midnight Analyst 深色 UI 設計系統規格，包含 theme tokens、全域 QSS、共用元件、效能限制與後續 agent 修改流程。 |
| [multi_agent_workflow.md](../01_architecture/multi_agent_workflow.md) | 多 Agent 協作與合併規範。 |
| [REFACTORING_MIGRATION_PLAN.md](../01_architecture/REFACTORING_MIGRATION_PLAN.md) | 歷史/長期 refactor 遷移計畫。 |

---

## 2. 功能與使用者文件

| 文件 | 用途 |
|---|---|
| [UI_FEATURES_DOCUMENTATION.md](../02_features/UI_FEATURES_DOCUMENTATION.md) | Qt UI 功能完整說明，包含 Phase 3.3b、Runtime、Smart Money。 |
| [USER_GUIDE.md](../02_features/USER_GUIDE.md) | 推薦、回測與資料治理的進階專題教學。 |
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
| [FUNDAMENTAL_SOURCE_INVENTORY.md](../03_data/FUNDAMENTAL_SOURCE_INVENTORY.md) | Month 5 Fundamental Layer 資料來源盤點，列出月營收、財報、估值、公告日 / available_date 缺口、月營收 mapping dry-run 驗證入口、official company registry 更新、valuation metrics 正式 apply、TPEX daily price backfill，以及 Fundamental SQLite 受控 migration CLI 狀態。Month 5 v1 closeout 後仍作來源與缺口盤點，不作目前狀態權威。 |
| [monthly_revenue_availability.csv](../03_data/templates/monthly_revenue_availability.csv) | 月營收公告日 / available_date mapping 欄位範本；不是正式資料。 |

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
| [2026-06-14-month-3-factor-layer-design.md](../superpowers/specs/2026-06-14-month-3-factor-layer-design.md) | Month 3 Factor Layer v1 設計，定義 Factor Contract、Registry、Look-ahead Gate 與既有技術 / 量能 / 券商分點 adapter 範圍。 |
| [2026-07-01-post-v1-evidence-event-store-design.md](../superpowers/specs/2026-07-01-post-v1-evidence-event-store-design.md) | Post-V1 Evidence Event Store / Forward Outcome Calculator v1 設計，定義 event/outcome schema、no-look-ahead、benchmark、quality、idempotency 與 migration safety。 |
| [2026-07-02-post-v1-evidence-importers-design.md](../superpowers/specs/2026-07-02-post-v1-evidence-importers-design.md) | Post-V1 Evidence Importers / Capture Pipeline v1 設計，定義 source importer、dry-run / confirm、diagnostics、unsupported source 與 DTO/repository-only 邊界。 |
| [2026-07-03-post-v1-forward-performance-read-model-design.md](../superpowers/specs/2026-07-03-post-v1-forward-performance-read-model-design.md) | Post-V1 E2E smoke / Forward Performance Read Model v1 設計，定義 tmp DB smoke、read-only aggregation、summary status、score bucket、CLI 與 scheduler not-ready 邊界。 |
| [2026-07-04-post-v1-evidence-source-persistence-design.md](../superpowers/specs/2026-07-04-post-v1-evidence-source-persistence-design.md) | Post-V1 Evidence Source Persistence 設計，定義 durable Daily Decision Desk snapshot repository、capture provider wiring、Recommendation exclusion payload partial 與 source coverage inspection。 |
| [2026-06-13-strategy-scoring-governance.md](../superpowers/plans/2026-06-13-strategy-scoring-governance.md) | 策略分數治理總控計畫與增量 Gate。 |
| [2026-06-14-month-3-factor-layer.md](../superpowers/plans/2026-06-14-month-3-factor-layer.md) | Month 3 Factor Layer v1 實作計畫，拆分 Factor Contract、Registry、Look-ahead Gate、v1 adapters 與 Research Run 追溯保存。 |
| [2026-07-01-post-v1-evidence-event-store.md](../superpowers/plans/2026-07-01-post-v1-evidence-event-store.md) | Post-V1 Evidence Event Store / Forward Outcome Calculator v1 實作計畫，拆分 DTO、repository、service、calculator、CLI、tests 與 QA 文件。 |
| [2026-07-02-post-v1-evidence-importers.md](../superpowers/plans/2026-07-02-post-v1-evidence-importers.md) | Post-V1 Evidence Importers / Capture Pipeline v1 實作計畫，拆分 importer DTO、Recommendation / DDD DTO importers、capture service、CLI、tests 與 QA。 |
| [2026-07-03-post-v1-forward-performance-read-model.md](../superpowers/plans/2026-07-03-post-v1-forward-performance-read-model.md) | Post-V1 E2E smoke / Forward Performance Read Model v1 實作計畫，拆分 smoke CLI、read model service、summary CLI、tests、docs 與 QA。 |
| [2026-07-04-post-v1-evidence-source-persistence.md](../superpowers/plans/2026-07-04-post-v1-evidence-source-persistence.md) | Post-V1 Evidence Source Persistence 實作計畫，拆分 snapshot repository、capture CLI、durable importer provider、exclusion payload 與 coverage CLI。 |
| [2026-06-14-month-3-factor-run-integration.md](../superpowers/plans/2026-06-14-month-3-factor-run-integration.md) | Month 3 Factor Run Integration 計畫，將 factor snapshot / contribution summary 接入 Research Run 實際保存流程。 |
| [2026-06-15-month-3-recommendation-factor-feed.md](../superpowers/plans/2026-06-15-month-3-recommendation-factor-feed.md) | Month 3 Recommendation Factor Feed 計畫，讓推薦組合回放產生並保存 factor snapshot / contribution metadata。 |
| [2026-06-15-decision-desk-watchlist-trigger.md](../superpowers/plans/2026-06-15-decision-desk-watchlist-trigger.md) | Daily Decision Desk Watchlist Trigger v1 接線計畫，對接 `WatchlistService` 與 SQLite `technical_indicators`，並定義日期 fallback、quality 與 warnings 契約。 |
| [2026-06-15-decision-desk-portfolio-alert-chip-provider.md](../superpowers/plans/2026-06-15-decision-desk-portfolio-alert-chip-provider.md) | Daily Decision Desk Portfolio Alert Chip Provider 實作計畫，對接 `PortfolioChipService` 籌碼資料源，並定義 quality 與 warnings 降級契約。 |
| [2026-06-15-decision-desk-relative-strength-liquidity-ranking.md](../superpowers/plans/2026-06-15-decision-desk-relative-strength-liquidity-ranking.md) | Daily Decision Desk Relative Strength / Liquidity Ranking v1 實作計畫，從 SQLite `daily_prices` 推導強弱排名、低流動性代碼與 quality / warnings 降級契約。 |
| [2026-06-15-decision-desk-risk-prompt-bridge.md](../superpowers/plans/2026-06-15-decision-desk-risk-prompt-bridge.md) | Daily Decision Desk Why Not / 風險提示橋接 v1 實作計畫，將既有 section DTO 的低流動性、弱勢、watchlist risk alert、portfolio alert 與品質缺口整理成可行動提示。 |
| [2026-06-15-decision-desk-portfolio-alert-attribution.md](../superpowers/plans/2026-06-15-decision-desk-portfolio-alert-attribution.md) | Daily Decision Desk Portfolio Alert Attribution v1 實作計畫，將持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags。 |
| [2026-06-16-month4-daily-decision-desk-closure.md](../superpowers/plans/2026-06-16-month4-daily-decision-desk-closure.md) | Month 4 Daily Decision Desk 收尾計畫，定義 reference screen、UI/service 邊界、資料品質驗收、文件關閉與 Month 5 handoff。 |
| [2026-06-16-month5-fundamental-layer-preflight.md](../superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md) | Month 5 Fundamental Layer preflight 計畫，定義資料來源盤點、available_date 契約、factor adapter 邊界、no-look-ahead 測試與非目標。 |
| [2026-06-16-month5-fundamental-main-sequence.md](../superpowers/plans/2026-06-16-month5-fundamental-main-sequence.md) | Month 5 基本面主線 sequencing memo，定義五份後續 superpowers plan 的執行順序、共用非目標與驗證規範。 |
| [2026-06-16-month5-availability-data-entrypoint.md](../superpowers/plans/2026-06-16-month5-availability-data-entrypoint.md) | Month 5 真實公告日 / available_date 資料入口 plan，建立月營收可得日 mapping 的正式驗證流程。 |
| `data_module/monthly_revenue_availability_history.py` / `scripts/build_monthly_revenue_availability_history.py` | Month 5 月營收公告日 historical dry-run builder；支援 TWSE/TPEX 最新月來源、人工官方 JSON、人工保存 MOPS HTML、MOPS static dry-run、授權 PIT CSV、期間 summary、候選 CSV 與 diagnostics，不寫正式 mapping。 |
| `data_module/monthly_revenue_snapshot_harvester.py` / `scripts/fetch_mops_monthly_revenue_snapshot.py` | Month 5 MOPS 月營收完整市場 snapshot 候選抓取器；保存 raw HTML 與營收值 candidate CSV，不推定 available_date，不寫正式 mapping 或 SQLite。 |
| `data_module/finmind_monthly_revenue_create_time.py` / `scripts/fetch_finmind_monthly_revenue_create_time.py` | Month 5 FinMind 月營收 create_time 候選抓取器；使用 DPAPI / 環境變數 token、支援 resume 與請求節流，輸出 create_time 分組候選，不寫正式 mapping 或 SQLite。 |
| [2026-06-16-month5-fundamental-sqlite-migration-v1.md](../superpowers/plans/2026-06-16-month5-fundamental-sqlite-migration-v1.md) | Month 5 Fundamental SQLite 受控 migration v1 plan，要求 working-copy dry-run、backup、rollback 與 schema preservation tests。 |
| [2026-06-16-month5-revenue-factor-pack-v1.md](../superpowers/plans/2026-06-16-month5-revenue-factor-pack-v1.md) | Month 5 Revenue Factor Pack v1 plan，實作 Revenue YoY、MoM、3M trend 與 new high factor adapters，並強制 available_date gate。 |
| [2026-06-16-month5-valuation-data-layer-v1.md](../superpowers/plans/2026-06-16-month5-valuation-data-layer-v1.md) | Month 5 Valuation Data Layer v1 plan，建立估值 metric 的 industry percentile 來源與 adapter，只輸出相對區間與 diagnostics。 |
| [2026-06-16-month5-abnormal-fundamental-diagnostics.md](../superpowers/plans/2026-06-16-month5-abnormal-fundamental-diagnostics.md) | Month 5 AbnormalFundamentalFlag 與診斷整合 plan，將基本面風險提示接入 Research Run / Daily Decision Desk diagnostics。 |
| [2026-06-16-tpex-daily-price-backfill.md](../superpowers/plans/2026-06-16-tpex-daily-price-backfill.md) | TPEX daily price backfill plan，定義官方 TPEX daily close quotes 進入 `daily_prices` 的 dry-run、confirm、backup 與驗證流程。 |
| [2026-06-23-healthcheck-issue-resolution-design.md](../superpowers/specs/2026-06-23-healthcheck-issue-resolution-design.md) | Full App Healthcheck issue resolution 設計，將 2026-06-16 healthcheck 問題拆分為 Batch 1 至 Batch 5 的修復與排查路線。 |
| [2026-06-23-healthcheck-batch1-direct-fixes.md](../superpowers/plans/2026-06-23-healthcheck-batch1-direct-fixes.md) | Healthcheck Batch 1 direct fixes 實作計畫，涵蓋 UpdateView、Portfolio、Runtime Observatory 與 Research Lab 第一批 UX 問題。 |
| [2026-06-23-healthcheck-batch2-daily-dashboard-smart-money.md](../superpowers/plans/2026-06-23-healthcheck-batch2-daily-dashboard-smart-money.md) | Healthcheck Batch 2 實作計畫，規劃 Daily Decision Desk answer-first dashboard 與 Smart Money 5 / 20 / 60 日語意診斷。 |
| [2026-06-23-non-destructive-release-healthcheck-runner.md](../superpowers/plans/2026-06-23-non-destructive-release-healthcheck-runner.md) | 非破壞式 release healthcheck runner 計畫，規劃在不改寫正式資料與不清理使用者變更的前提下執行健康檢查。 |
| [2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md](../superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md) | Testing / QA Agent 與非破壞式超級 healthcheck runner 的總控 Roadmap，收斂 runner、feature routing、result interpreter、known issue matcher 與 D-2 UI smoke 的分階段路線。 |
| [2026-06-23-healthcheck-batch3-recommendation-profile-regime.md](../superpowers/plans/2026-06-23-healthcheck-batch3-recommendation-profile-regime.md) | Healthcheck Batch 3 實作計畫，規劃推薦分析 Profile lifecycle、策略版本 gate 與 Regime match / mismatch 揭露。 |
| [2026-06-23-healthcheck-batch4-research-lab-results.md](../superpowers/plans/2026-06-23-healthcheck-batch4-research-lab-results.md) | Healthcheck Batch 4 實作計畫，規劃 Research Lab 推薦回放結果頁、Registry 比較頁、批次比較判讀與 Train-Test / Walk-forward 樣本可靠度提示。 |
| [2026-06-23-healthcheck-batch5-performance-operations.md](../superpowers/plans/2026-06-23-healthcheck-batch5-performance-operations.md) | Healthcheck Batch 5 實作計畫，規劃參數最佳化大型掃描預估、worker 設定、bounded cancellation、Market Watch SQLite-first 排查與 Update 長任務邊界。 |
| [2026-06-23-healthcheck-batch6-closeout-regime-researchlab.md](../superpowers/plans/2026-06-23-healthcheck-batch6-closeout-regime-researchlab.md) | Healthcheck Batch 6 實作計畫，規劃 Research Lab 首次載入與升級導引收尾、healthcheck 狀態一致化，以及 Regime confidence / 子分數排查。 |
| [2026-06-29-full-app-healthcheck-ui-smoke-design.md](../superpowers/specs/2026-06-29-full-app-healthcheck-ui-smoke-design.md) | Full App Healthcheck 接近真人 UI 操作測試設計，規劃 rollback 節點、分 tab runner、候選 bridge 升級與 MainWindow smoke 邊界。 |
| [2026-06-29-full-app-healthcheck-ui-smoke.md](../superpowers/plans/2026-06-29-full-app-healthcheck-ui-smoke.md) | Full App Healthcheck 分批實作計畫，拆分 tab filter、report context、opt-in MainWindow skeleton、safe candidate promotion、文檔與驗證節點。 |
| [2026-06-30-mainwindow-ui-smoke-operation-design.md](../superpowers/specs/2026-06-30-mainwindow-ui-smoke-operation-design.md) | MainWindow UI smoke 操作層設計，規劃 opt-in 啟動、tab 切換、screenshot、resize evidence、cancel-only dialog 與子程序隔離。 |
| [2026-06-30-mainwindow-ui-smoke-operation.md](../superpowers/plans/2026-06-30-mainwindow-ui-smoke-operation.md) | MainWindow UI smoke 操作層實作計畫，拆分 evidence schema、真實 Qt runner、CLI manifest opt-in、dialog cancel path、文件與驗證。 |
| [2026-06-13-strategy-scoring-governance-a-backtest.md](../superpowers/plans/2026-06-13-strategy-scoring-governance-a-backtest.md) | 增量 A：回測 fixed / quantile 雙模式門檻實作計畫。 |
| [2026-06-13-strategy-scoring-governance-b-recommendation.md](../superpowers/plans/2026-06-13-strategy-scoring-governance-b-recommendation.md) | 增量 B：推薦 eligible universe 橫斷面排名實作計畫。 |
| [2026-06-14-legacy-test-governance-design.md](../superpowers/specs/2026-06-14-legacy-test-governance-design.md) | 舊測試分類、現行模組責任與 pytest 收集邊界設計。 |
| [2026-06-14-legacy-test-governance.md](../superpowers/plans/2026-06-14-legacy-test-governance.md) | 舊測試遷移、拆分、棄用與完整驗證計畫。 |
| [2026-06-14-month-2-parameter-run-storage-governance.md](../superpowers/plans/2026-06-14-month-2-parameter-run-storage-governance.md) | Month 2 參數與權重治理、Research Run Registry、Cross-run Comparison 與 Promote Gate 總控實作計畫。 |
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
| [V1_RELEASE_CHECKLIST_2026_06_30.md](../06_qa/V1_RELEASE_CHECKLIST_2026_06_30.md) | v1.0.0-rc.1 / v1.0.0 發布前 release readiness gate，涵蓋乾淨 main、全新 clone、非破壞 healthcheck、MainWindow UI smoke 與人工 UI 驗證。 |
| [FULL_APP_HEALTHCHECK_2026_06_16.md](../06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md) | 主 UI 人工 smoke test 母檔，涵蓋數據更新、SQLite 檢視、TPEX 日價、券商分點、每日決策、研究與持倉流程。 |
| [FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md](../06_qa/FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md) | Full App Healthcheck 母檔逐列 coverage mapping，對照 direct bridge、candidate、service oracle、report-only、manual-only、write-risk manual 與 `--tab` 分頁驗證狀態。 |
| [FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md](../06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md) | Testing / QA Agent + Full App Healthcheck Runner closeout，說明 metadata / report-only 工具鏈、安全邊界、`--tab` runner 與 executable opt-in MainWindow UI smoke 狀態。 |
| [TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md](../06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md) | 測試 inventory 分類，標示 direct bridge、candidate bridge、service oracle、write-risk、manual-only、預設 pytest 收集與 runner bridge 分頁狀態。 |
| [UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md](../06_qa/UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md) | `ui_qt` 對照 roadmap 的逐項審核報表。 |
| [WALK_FORWARD_COMPARISON_REPORT.md](../06_qa/WALK_FORWARD_COMPARISON_REPORT.md) | Fixed vs Quantile 機制、時間軸回歸、10 檔 OOS 實證與 100% Regime coverage Gate 證據。 |
| [DOCUMENT_ENCODING_AUDIT_2026_06_16.md](../06_qa/DOCUMENT_ENCODING_AUDIT_2026_06_16.md) | repo 文件 UTF-8 / mojibake 稽核報告，確認顯示雜訊來自終端編碼而非文件內容損壞。 |
| [FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md](../06_qa/FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md) | Testing QA Agent 使用的 feature-to-test 測試路由與決策矩陣（測試知識庫），不包含 Agent 角色定義。 |
| [POST_V1_EVIDENCE_EVENT_STORE_QA_2026_07_01.md](../06_qa/POST_V1_EVIDENCE_EVENT_STORE_QA_2026_07_01.md) | Post-V1 Evidence Event Store v1 / Forward Outcome Calculator v1 QA 紀錄，包含 schema safety、focused tests、限制與下一增量。 |
| [POST_V1_EVIDENCE_IMPORTERS_QA_2026_07_02.md](../06_qa/POST_V1_EVIDENCE_IMPORTERS_QA_2026_07_02.md) | Post-V1 Evidence Importers / Capture Pipeline v1 QA 紀錄，包含 importer 支援邊界、CLI dry-run / confirm、unsupported source 與限制。 |
| [POST_V1_EVIDENCE_SOURCE_PERSISTENCE_QA_2026_07_04.md](../06_qa/POST_V1_EVIDENCE_SOURCE_PERSISTENCE_QA_2026_07_04.md) | Post-V1 Evidence Source Persistence QA 紀錄，包含 durable DDD snapshot repository、source coverage CLI、Recommendation exclusion payload partial 與 scheduler readiness 邊界。 |


---

## 7. 操作指南

| 文件 | 用途 |
|---|---|
| [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md) | 目前 8 個頂層工作區的完整操作手冊，包含安裝、參數、結果判讀、安全限制與排錯。 |
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
| [agents/testing_qa_agent.md](../agents/testing_qa_agent.md) | Testing / QA Agent 權威角色，負責測試路由與結果解讀。 |
| [agents/skills_registry.md](../agents/skills_registry.md) | Codex / Antigravity 共用的角色選擇、流程導引與 shared context 入口。 |
| [agents/skills/team.md](../agents/skills/team.md) | Codex / Antigravity 任務分流與交接流程。 |
| [agents/skills/quant_defense_guard.md](../agents/skills/quant_defense_guard.md) | 量化精度防禦與未來函數審查技能及一鍵式檢測工具。 |
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
- [DEVELOPMENT_ROADMAP_LEGACY_2026_06.md](../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md)：舊完整 Roadmap，包含線性 Phase、歷史 Done 與舊 Roadmap current section，只作追溯用途。
- [NEXT_ACTION_PLAN.md](../09_archive/NEXT_ACTION_PLAN.md)：2026-06-09 下一輪行動計畫（已執行完畢）。
- [PHASE_3_3B_IMPLEMENTATION_PLAN.md](../09_archive/PHASE_3_3B_IMPLEMENTATION_PLAN.md)：Phase 3.3b 實施規劃（已執行完畢）。
- [root_readme_legacy_2025_12.txt](../09_archive/root_readme_legacy_2025_12.txt)：原根目錄 `readme.txt`，內容停留在舊 Phase、舊入口與舊路徑說明，只作歷史追溯。
- [dev_progress_note_legacy_2026_01.txt](../09_archive/dev_progress_note_legacy_2026_01.txt)：原 `docs/00_core/note.txt` 歷史開發進度筆記，只作追溯，不作目前狀態權威。
- [ARCH_GOVERNANCE_CHECKLIST.md](../09_archive/ARCH_GOVERNANCE_CHECKLIST.md)：早期架構治理自檢清單，已自 `00_core/` 歸檔；目前架構權威以 `docs/01_architecture/system_architecture.md` 為準。
- [ARCH_GOVERNANCE_LIFECYCLE.md](../09_archive/ARCH_GOVERNANCE_LIFECYCLE.md)：早期架構治理生命週期備忘，已自 `00_core/` 歸檔；目前文件治理以 Coverage Map 與 Documentation Structure 為準。
- [ARCH_VIOLATION_RESPONSE_POLICY.md](../09_archive/ARCH_VIOLATION_RESPONSE_POLICY.md)：早期架構違規處理政策備忘，已自 `00_core/` 歸檔；目前架構邊界與高風險契約以 system architecture 為準。

---

## 目前開發狀態

- **已完成（三個產品閉環之基礎建置與主要深化）**：資料與市場狀態閉環（SQLite DB-first/視覺化檢視/Smart Money Terminal/快速/安全更新工作台）、研究驗證閉環（Research Lab 多模式實驗室/單股與批次回測/Walk-forward/推薦組合回測 MVP/Fast Renderer/Promote/批次並行化/Strategy & Scoring Governance 機制回歸）、持倉檢查閉環（Portfolio Tab/來源追溯/策略與價格監控/停損停利警示/籌碼監控與下鑽）、以及 SQLite 檢視器分頁與規格化 Excel 報告背景匯出。
- **進行中 / 當前治理**：fixed / quantile 實證 Gate 已通過；quantile 未優於 fixed 並維持 opt-in。Research Run Registry M2-A / M2-B / M2-C 與 final registry governance gate 已完成；Month 3 Factor Layer v1、Portfolio Replay 可信度與 Month 5 Fundamental Layer v1 已關閉；Month 6 Strategy Lifecycle / Portfolio Feedback v1 已完成第一輪 service / gate / UI 入口。
- **未來 6 個月主線**：見 [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md)，Daily Decision Desk v1 已接上主 UI，Month 6 下一步是 lifecycle 狀態持久化、demote / retire 證據保存與更完整 review workflow；零股、買賣價差、完整撮合與 Gap 實際成交模型列為執行模型深化。
- **待開始 (Backlog)**：Phase 5 中的 PDF 報告輸出。

---

## 維護提醒

- 新增或刪除任何 Markdown 後，更新本索引。
- 狀態文字若與 Snapshot、6M Roadmap 或 Architecture 衝突，以對應範圍的權威文件為準並修正本索引。
- 不確定文件是否該刪除時，先移入 `09_archive/` 或在 `DOCUMENTATION_STRUCTURE.md` 記錄決策。

---

## 🔄 更新記錄

- 2026-07-01：新增 Post-V1 Evidence Event Store design / plan 與 QA 索引，標示 Evidence Event Store v1 / Forward Outcome Calculator v1 是 forward evidence 資料底座，不是 dashboard 或投資有效性證明。
- 2026-07-02：新增 Post-V1 Evidence Importers design / plan 與 QA 索引，標示 capture pipeline v1 可累積 persisted Recommendation 與 DTO-based DDD evidence，但仍不是 dashboard 或投資有效性證明。
- 2026-07-03：新增 Post-V1 E2E smoke / Forward Performance Read Model design / plan 與 QA 索引，標示 read model v1 可唯讀彙總 outcomes，但 Dashboard UI、production scheduler 與投資有效性證明仍未完成。
- 2026-07-04：新增 Post-V1 Evidence Source Persistence design / plan 與 QA 索引，標示 durable Daily Decision Desk snapshot source 與 source coverage inspection v1 已完成；Why Not / Liquidity exclusion payload 為 optional / partial，scheduler 仍不得視為 production-ready。
- 2026-06-30：新增 v1 release checklist 索引，將 `v1.0.0-rc.1` / `v1.0.0` 發布前的自動化、非破壞 healthcheck、MainWindow UI smoke、全新 clone 與人工 UI 驗證 gate 集中管理。
- 2026-06-30：新增 MainWindow UI smoke 操作層 design / plan 索引，並同步 QA 文件對 `--ui-smoke`、screenshot / resize evidence、Update cancel-only dialog 與子程序隔離執行的狀態描述。
- 2026-06-29：新增 Full App Healthcheck 接近真人 UI smoke design / plan 索引，並同步 QA 文件對 `--tab` 分頁 runner、11 個 direct bridge、10 個 candidate bridge 與 opt-in MainWindow smoke skeleton 的狀態描述。
- 2026-06-30：將根目錄 `README.md` 定位更新為使用者入口，新增 `AGENT_CONTEXT.md` 索引；將 `docs/00_core/note.txt` 歸檔為 `docs/09_archive/dev_progress_note_legacy_2026_01.txt`，並配合 main 清理移除 raw output 追蹤。
- 2026-06-24：將 `docs/00_core/ARCH_*` 早期架構治理備忘移入 archive，補上歸檔索引；目前架構權威仍為 `docs/01_architecture/system_architecture.md`。
- 2026-06-23：新增 Testing / QA Agent Super Healthcheck Roadmap 總控計畫索引，收斂非破壞式 runner、QA Agent 調度、結果解讀與後續 D-2 UI smoke 路線。
- 2026-06-23：新增 Testing / QA Agent 權威文件與 FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md 測試路由矩陣索引。
- 2026-06-23：新增 Healthcheck Batch 3 Recommendation Profile / Regime plan 與 non-destructive release healthcheck runner plan 索引，記錄推薦分析 Profile lifecycle、Regime match / mismatch 揭露與自訂 Profile JSON 精度治理入口。
- 2026-06-18：整理根目錄 README 入口；將過期 `readme.txt` 移入 `docs/09_archive/root_readme_legacy_2025_12.txt`，並同步 docs 入口、Archive 索引與 Project Inventory。
- 2026-06-18：重構 system vision 文件定位，將 baldr 願景說明升級為 North Star / Current State / Evidence Framework，並補上投資有效性驗證框架與 v1 能力證據邊界。
- 2026-06-18：統一專案品牌命名為小寫 `baldr`，替換所有舊專案命名語彙。
- 2026-06-18：補強 system vision 的 Gap Register，集中管理主要資料、微結構、執行模型、證據與報告輸出缺口。
- 2026-06-17：完成 Month 5 Fundamental Layer v1 closeout 索引同步，將目前治理狀態轉入 Month 6 Strategy Lifecycle / Portfolio Feedback。
- 2026-06-17：完成 Month 6 Strategy Lifecycle / Portfolio Feedback v1 索引同步，標示 lifecycle gate、post-trade attribution、Portfolio Review snapshot 與持倉管理生命週期回顧分頁已落地。
- 2026-06-16：新增 Midnight Analyst UI 設計系統規格索引，作為後續深色主題、共用元件與 UI 統一工作的設計參考入口。
- 2026-06-15：完成 Daily Decision Desk Portfolio Alert Attribution v1，將持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags，並對接至主 UI 與風險提示服務。
- 2026-06-03：完成 Phase 2C 實作，新增 SQLite 資料庫視覺化檢視面板 (SqliteInspectorWidget) 與防禦性唯讀查詢服務 (SqliteInspectorService) 整合至數據更新工作台。
- 2026-06-03：新增 Phase 2A 數據讀取來源盤點報告 (PHASE_2A_DATA_SOURCES_AUDIT.md) 連結至文檔索引，並標記 Phase 2A/2B 已完成。
- 2026-06-04：新增 Research Lab 工作流重整 spec / plan 連結，標記候選池語意與 Phase 3 → Portfolio 來源追溯為進行中主線。
- 2026-06-06：完成策略回測驗證實驗室說明文檔（[BACKTEST_LAB_FEATURES.md](../02_features/BACKTEST_LAB_FEATURES.md)）之撮合限制、SOP 驗證、未來函數防禦與強制平倉 Portfolio 記錄機制同步更新，並優化 tab info 說明對話框文字。
- 2026-06-06：啟動策略回測視圖（`backtest_view.py`）之漸進式重構，完成 Phase 1 拆分：抽離常數、說明 Tooltip 與純計算輔助函數至 `ui_qt/views/backtest/` 目錄下。
- 2026-06-06：完成策略回測視圖（`backtest_view.py`）之漸進式重構 Phase 2 至 Phase 4：抽離右側結果面板 `BacktestResultPanel` 與左側配置面板 `BacktestConfigPanel`，採用 QWidget native 屬性安全排除的動態委派路由，並補全所有關鍵 Widget 的顯式 `@property` 宣告以取得最佳的 mypy 與 IDE autocomplete 支援，保持與現有單元測試及 QA 契約 100% 相容。
- 2026-06-09：新增 [NEXT_ACTION_PLAN.md](../09_archive/NEXT_ACTION_PLAN.md)，整理 Tech Lead 審查後的下一輪 Roadmap Rebaseline、回測時間軸治理、金融核心數值治理與 Agent 交接順序；該文件後續已歸檔。
- 2026-06-09：執行 Roadmap Rebaseline，將當時 Roadmap current section 改為三個產品閉環敘事，同步更新 Snapshot / AI Context Pack / Navigation / Inventory。
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
- 2026-06-13：完成 Roadmap Hub / 6M Roadmap 重構，新增 Legacy Carryover Matrix 與完整 Application Manual，修正主要 UI 入口、過期 Phase 狀態與 service 架構文件。
- 2026-06-13：修正 fixed / quantile pilot 的 OOS 時間軸與不實結論；保存資料指紋，並記錄 fixed 無交易與 regime 分層未完成，因此正式實證仍未過 Gate。
- 2026-06-14：完成 Phase 5 Month 1 SQLite 穩定分頁與規格化 Excel 報告匯出實作計畫，補齊 report payload 契約、背景寫檔、原子替換、文件 coverage 與完整 QA Gate。
- 2026-06-14：完成舊測試治理，將歷史網路／真實路徑／互動式腳本移至 `tests/manual/`，以現行 `TWStockConfig`、`DataLoader` 與分析 API 重建正式契約；pytest 完整收集與 `344` 項測試通過。
- 2026-06-14：新增並 review 量化精度與未來函數一鍵式靜態檢測工具、SQLite/Git MCP 與 `auto_state_sync.py`；補強 fail-closed、SQLite 強制唯讀、Git 輸出限制及 Codex / Antigravity 雙端註冊。
- 2026-06-14：新增 Month 2 參數與研究儲存治理總控實作計畫，拆分 M2-A、M2-B、M2-C Gate 並記錄目前 M2-A 修復狀態。
- 2026-06-14：完成 Month 2 M2-B Research Run Registry 基礎保存：新增 SQLite metadata / Parquet 明細 / hash integrity / crash reconciliation / legacy backfill，並將 Research Lab「保存結果」入口改由 `ResearchRunService` 負責。
- 2026-06-14：完成 Month 2 M2-C Cross-run Comparison 第一段：新增 `ResearchRunComparisonService`，並在 Research Lab 掛入「Registry 比較」子頁，支援篩選、分頁、2 至 5 run 多選、comparability badge、參數差異、normalized equity、metrics、Regime 與保存 benchmark 檢視。
- 2026-06-14：完成 Month 2 M2-C Registry-based Promote Gate：promotion 改可讀取 Registry run，新增策略版本 JSON 原子寫入、Registry 回填失敗補償刪除與 reconciliation 掃描，避免 SQLite/JSON 狀態不一致被靜默忽略。
- 2026-06-14：完成 Month 2 final registry governance gate 文件收尾，確認 M2-C 不再列為當前待辦，並轉向 Factor Contract / Factor Layer 前置。
- 2026-06-14：Month 3 Factor Layer v1 進入實作：新增 Factor Contract、Registry、Look-ahead Gate、既有技術 / 量能 / 券商分點 adapters、FactorService snapshot/contribution serialization、Research Run 實際寫入整合與 saved factor metadata reader。
- 2026-06-15：Month 3 推薦組合回放 factor feed：由 replay snapshot recommendations 產生 `technical.total_score` / `volume.volume_ratio` metadata，並透過既有 Research Run 保存流程落盤。
- 2026-06-15：依 baldr 願景更新文檔索引，新增 system vision 的產品北極星定位，並同步 6M Roadmap 新主線：Portfolio Replay 可信度、Daily Decision Desk、Fundamental Layer 與 Strategy Lifecycle。
- 2026-06-15：補列 Daily Decision Desk Watchlist Trigger v1 provider 接線計畫至 Superpowers plans 索引。
- 2026-06-15：補列 Daily Decision Desk Portfolio Alert v1 籌碼對接實作計畫至 Superpowers plans 索引。
- 2026-06-15：補列 Daily Decision Desk Relative Strength / Liquidity Ranking v1 實作計畫至 Superpowers plans 索引。
- 2026-06-15：補列 Daily Decision Desk Why Not / 風險提示橋接 v1 實作計畫至 Superpowers plans 索引。
- 2026-06-15：補列 Daily Decision Desk Portfolio Alert Attribution v1 實作計畫至 Superpowers plans 索引。
- 2026-06-16：新增 Month 4 Daily Decision Desk 收尾計畫，明確定義 reference screen、UI/service 邊界、資料品質驗收、文件關閉與 Month 5 handoff。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾文件同步，將 Snapshot / Roadmap / Architecture / Manual 轉向 Month 5 Fundamental Layer preflight，並記錄 UI boundary contract test。
- 2026-06-16：新增 Month 5 Fundamental Layer preflight 計畫，避免在 source inventory、available_date 與 no-look-ahead gate 定義前直接接入基本面資料。
- 2026-06-16：新增 Month 5 Fundamental Source Inventory，確認既有 `financial_data/` 只可作 raw candidate source，正式 SQLite 尚無 fundamental tables，後續必須先補 available_date contract。
- 2026-06-16：新增 Month 5 基本面主線 sequencing memo 與五份獨立 superpowers plan，拆分 available_date 資料入口、Fundamental SQLite migration、Revenue Factor Pack、Valuation Data Layer 與 AbnormalFundamentalFlag diagnostics。
- 2026-06-16：完成 Month 5 月營收 availability mapping dry-run 驗證入口文件同步，記錄 `data_module/fundamental_availability_entrypoint.py` 與 CLI 只讀驗證、拒絕未治理來源且不寫正式資料。
- 2026-06-16：完成 Fundamental SQLite 受控 migration workflow 與月營收 normalized backfill workflow 文件同步，記錄 working-copy dry-run、apply confirm、backup / restore helper；正式 `twstock.db` 已套用 fundamental schema，但尚未回填 records。
- 2026-06-16：完成 Fundamental SQLite read provider 文件同步，記錄 provider 只讀 `available_date <= decision_date` 的月營收與估值 records，避免後續服務直接讀 raw CSV。
- 2026-06-16：新增 valuation metrics backfill workflow 文件同步，記錄 `daily_prices.本益比` dry-run、`companies.csv` 產業 mapping、同產業 percentile、apply confirm、官方 company registry 更新與正式 DB 已寫入 831 筆 P/E records。
- 2026-06-16：新增 official company registry workflow 文件同步，記錄 TWSE/TPEX 官方公司基本資料更新 `companies.csv`、備份、`9935` 產業修正與 `3207` TPEX daily price 歷史缺口判讀。
- 2026-06-16：完成 Fundamental factor service 文件同步，記錄服務只串接 provider、adapters 與 FactorGate，輸出 records / diagnostics 但不接 `ScoringEngine`。
- 2026-06-16：新增月營收公告日 historical dry-run builder 索引，記錄 TWSE/TPEX 最新月 OpenAPI 與候選 mapping CLI；正式 mapping 寫入與月營收回填仍維持人工 gate。
- 2026-06-16：補充 MOPS HTML source-dir 索引，記錄 `--mops-html-dir` 可讀人工保存官方 HTML 產生候選 mapping，缺公告日欄位時 fail-closed。
- 2026-06-17：補充 MOPS static dry-run 索引，記錄 `--mops-static` 透過新版 MOPS redirectToOld / mopsov static report 驗證歷史 rows，並由 45 天合理揭露窗口拒絕重新出表日期。
- 2026-06-16：補充授權 PIT 月營收公告日 CSV 索引，記錄 `--pit-csv` / `--pit-source-version` candidate-only 匯入路徑與正式 mapping 人工 gate。
- 2026-06-16：補充 GitHub public archive source audit 索引，記錄 commit first-seen 方法可行但目前已檢查 public repos 皆不足以列為 allowed source。
- 2026-06-16：補充 MOPS snapshot / FinMind create_time 候選抓取器索引，記錄今晚可跑的兩個 candidate-only CLI 與正式 mapping / SQLite 人工 gate。
- 2026-06-16：新增 TPEX daily price backfill plan 與文件同步，記錄官方 TPEX daily close quotes 受控寫入 `daily_prices`、DB 備份、`3207` 補價與 877 筆正式寫入驗證。
- 2026-06-16：更新 Full App Healthcheck，整合 TPEX 日常管線、SQLite Inspector 顯示防護與 `broker_flows.trade_type` 主鍵治理的人工驗證入口。
- 2026-06-16：新增文件編碼稽核工具與 QA 報告，確認 repo Markdown 與 docs 文字型文件皆為 UTF-8，終端亂碼屬顯示層編碼問題。





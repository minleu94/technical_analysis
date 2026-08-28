# 文檔索引

> 2026-07-13 system integration：A～F 的 committed handoff、跨流 contracts、唯讀 smoke 與 latency 工程 Gate 已驗證；forward evidence、source acceptance、formal ML OOS／promotion 與 production automation 仍由 External Validation Register / Control Center 管理。
>
> Current engineering closeout：[V3.3 Engineering Closeout](../06_qa/V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；外部狀態仍由 External Validation Register / Control Center 管理。

> Evidence rehearsal closeout：[Evidence Rehearsal Engineering Closeout](../06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md)（`engineering_rehearsal_complete`；不是 external completion）。

> **最後整理**：2026-07-13
> **判讀規則**：本索引用於導航，不作為狀態或架構事實來源。Scoped SSOT：目前狀態看 `PROJECT_SNAPSHOT.md`，產品方向看 `PRODUCT_ROADMAP_POST_REFACTOR.md`，未來 6 個月工程看 `ROADMAP_6M_ENGINEERING.md`，North Star / Evidence 看 `system_vision_specification.md`，目前／目標架構分別看 `system_architecture.md` / `target_system_architecture.md`。

---

## 0. 核心入口

### Scoped reading order

1. 先讀 [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) 取得目前狀態；任何 dated plan／closeout 都不能覆寫它。
2. 再讀 [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) 定位權威入口；涉及產品方向讀 [PRODUCT_ROADMAP_POST_REFACTOR.md](PRODUCT_ROADMAP_POST_REFACTOR.md)，涉及六個月工程順序讀 [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md)。
3. 涉及目前模組／資料流讀 [system_architecture.md](../01_architecture/system_architecture.md)；涉及未來領域邊界才讀 [target_system_architecture.md](../01_architecture/target_system_architecture.md)，不得把 target 當 current。
4. 涉及產品原則讀 [system_vision_specification.md](../01_architecture/system_vision_specification.md)；涉及 V2.1+ maturity、外部參考或舊工作承接，再條件式讀 Version Roadmap、External Blueprint、Legacy Carryover。
5. 涉及 UI／操作／參數／結果／安全限制讀 [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md)。本 Index 與 [PROJECT_NAVIGATION.md](../../PROJECT_NAVIGATION.md) 只用於找路，不作狀態真相。

下表是入口 catalog，不另定優先順序或完成狀態。

| 文件 | 用途 |
|---|---|
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | Roadmap Hub，指向 Snapshot、6M Roadmap、Architecture 與歷史歸檔。 |
| [PRODUCT_ROADMAP_POST_REFACTOR.md](PRODUCT_ROADMAP_POST_REFACTOR.md) | 安全重構完成後的產品方向權威；定義 bounded advice、Guided / Professional、Portfolio、Exit、Evidence、Data、ML、30/60/90 日與產品 Gate。 |
| [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) | 未來六個月工程 Gate、交付物、依賴、測試、禁止事項與 Exit Criteria。 |
| [VERSION_ROADMAP_V1_1_TO_V2_0.md](VERSION_ROADMAP_V1_1_TO_V2_0.md) | V1.1 至 V2.0 已完成歷史版本與 V2.0 形成過程；不承擔目前產品 Next。 |
| [VERSION_ROADMAP_V2_1_TO_V4_0.md](VERSION_ROADMAP_V2_1_TO_V4_0.md) | V2.1 至 V4.0 長期產品成熟度；V4.0 必須由長期 Forward / Paper / Live Evidence 支持。 |
| [EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md](EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md) | 外部開源專案參考、資料源補強優先序、V1.5 至 V2.0 版本形狀與 deferred 技術邊界；作為 6M Roadmap / Version Roadmap companion，不取代 Vision。 |
| [system_vision_specification.md](../01_architecture/system_vision_specification.md) | baldr North Star、Product Principles、Bounded Advice Policy、Evidence Requirements、Success Levels 與 Non-goals。 |
| [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md) | 舊 Roadmap 未完成事項的逐項處置、移交月份與 Month 3 前結案 Gate。 |
| [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) | 30 秒讀完的目前狀態摘要、本週優先事項與高風險區。 |
| [GATE_2_DATA_GOVERNANCE_CONSOLIDATION_AUDIT_2026_07_22.md](../06_qa/GATE_2_DATA_GOVERNANCE_CONSOLIDATION_AUDIT_2026_07_22.md) | Gate 2 資料治理工程收斂稽核報告、全量 SQLite 數據與 P0 資料源缺口矩陣。 |
| [SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md](../06_qa/SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md) | 排程與日常證據可觀測性健康報告、寫入意圖與相依性過濾。 |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) | 本文件，文檔導航。 |
| [EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md](../06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md) | 唯讀 evidence rehearsal engineering closeout、四層 tier、已知缺口與 forward handoff；不改寫 external Gate。 |
| [DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md) | `docs/` 資料夾歸屬、生命週期、刪除/歸檔規則。 |
| [PROJECT_NAVIGATION.md](../../PROJECT_NAVIGATION.md) | repo 根目錄的日常開發導航。 |
| [PROJECT_INVENTORY.md](../../PROJECT_INVENTORY.md) | repo 根目錄的完整專案盤點。 |
| [../../AGENTS.md](../../AGENTS.md) | Codex 自動讀取的 repo 根目錄指令入口，指向 `docs/agents/` 完整 Agent 架構。 |
| [../../GEMINI.md](../../GEMINI.md) | Antigravity 自動讀取的 repo 根目錄指令入口，指向 `docs/agents/antigravity/` 與 `.agent/rules/`。 |

---

## 1. 架構文件

| 文件 | 用途 |
|---|---|
| [system_architecture.md](../01_architecture/system_architecture.md) | 目前系統模組、分層架構、資料流與模組邊界的架構權威。 |
| [target_system_architecture.md](../01_architecture/target_system_architecture.md) | 理想 Target Architecture；清楚區分 Current / Transitional / Target，定義模組、資料流、決策流、治理邊界與正式決策修改權限。 |
| [system_vision_specification.md](../01_architecture/system_vision_specification.md) | 產品北極星、Bounded Advice、Evidence Requirements、Success Levels 與 Non-goals。 |
| [system_flow_end_to_end.md](../01_architecture/system_flow_end_to_end.md) | 端到端流程。 |
| [data_collection_architecture.md](../01_architecture/data_collection_architecture.md) | 資料收集架構。 |
| [runtime_observatory_rules.md](../01_architecture/runtime_observatory_rules.md) | Runtime Observatory 架構治理規範。 |
| [ui_design_system_midnight_analyst.md](../01_architecture/ui_design_system_midnight_analyst.md) | Midnight Analyst 深色 UI 設計系統規格，包含 theme tokens、全域 QSS、共用元件、效能限制與後續 agent 修改流程。 |

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
| [RESEARCH_RUN_REGISTRY_SPEC.md](../02_features/RESEARCH_RUN_REGISTRY_SPEC.md) | Research Run Registry 的 schema、metadata、Parquet/SQLite 混合儲存與 Cross-run 比較設計規格。 |

---

## 3. 資料文件

| 文件 | 用途 |
|---|---|
| [HOW_TO_UPDATE_DAILY_DATA.md](../03_data/HOW_TO_UPDATE_DAILY_DATA.md) | 每日資料更新快速指南。 |
| [daily_data_update_guide.md](../03_data/daily_data_update_guide.md) | 每日資料更新詳細指南。 |
| [BACKUP_RETENTION_AUDIT_2026_07_06.md](../03_data/BACKUP_RETENTION_AUDIT_2026_07_06.md) | 2026-07-06 備份檔來源與 retention 盤點，記錄 repo / `FA_Data` 大型 DB、CSV、`.bak` 備份來源、已納入保留策略的程式入口、`_reference_fix` replay archive 位置與已清理的 C 槽 working-copy / QA raw output。 |
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

## 5. 歷史 Phase / 設計追溯與研究 SOP

> 本區文件保留為 Historical / Reference。它們說明 Phase 時期的設計、驗收與研究 SOP 脈絡，但不作目前 roadmap、目前完成狀態或下一步優先順序依據。目前狀態請看 `PROJECT_SNAPSHOT.md`，未來 6 個月路線請看 `ROADMAP_6M_ENGINEERING.md`，Post-V1 至 V2.0 版本節奏請看 `VERSION_ROADMAP_V1_1_TO_V2_0.md`，V2.0 之後長期版號階梯請看 `VERSION_ROADMAP_V2_1_TO_V4_0.md`。
>
> Post-V1 部分 design / plan / QA 檔名保留 2026-07-05 至 2026-07-12 的里程碑命名；實際時間與交付判讀仍以 Snapshot、6M Roadmap 與 Git closeout 為準，不能只憑檔名推論。

| 文件 | 用途 |
|---|---|
| [PHASE2_ARCHITECTURE.md](../05_phases/PHASE2_ARCHITECTURE.md) | [歷史] Phase 2 策略架構設計追溯。 |
| [PHASE2_STRATEGY_LIBRARY.md](../05_phases/PHASE2_STRATEGY_LIBRARY.md) | [歷史] Phase 2 策略資料庫設計追溯。 |
| [PHASE_2A_DATA_SOURCES_AUDIT.md](../05_phases/PHASE_2A_DATA_SOURCES_AUDIT.md) | [歷史] Phase 2A CSV-first 到 DB-first 過渡盤點。 |
| [PHASE2_5_COMPLETION_STATUS.md](../05_phases/PHASE2_5_COMPLETION_STATUS.md) | [歷史] Phase 2.5 完成狀態追溯；fixed / quantile 現況以 Snapshot / 6M Roadmap / QA 報告為準。 |
| [PHASE3_3B_RESEARCH_DESIGN.md](../05_phases/PHASE3_3B_RESEARCH_DESIGN.md) | [歷史] Phase 3.3b 研究設計規格追溯。 |
| [PHASE_3_3B_IMPLEMENTATION_PLAN.md](../09_archive/PHASE_3_3B_IMPLEMENTATION_PLAN.md) | [已歸檔] Phase 3.3b 實施規劃，現作歷史與追溯用途。 |
| [EPIC2_MVP2_ARCHITECTURE_DESIGN.md](../05_phases/EPIC2_MVP2_ARCHITECTURE_DESIGN.md) | [歷史] 過擬合風險提示架構設計追溯。 |
| [EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md](../05_phases/EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md) | [歷史] 過擬合風險提示實作 checklist 追溯。 |
| [PHASE4_PORTFOLIO_DESIGN.md](../05_phases/PHASE4_PORTFOLIO_DESIGN.md) | [歷史] Phase 4 Portfolio MVP 初始設計追溯。 |
| [PHASE4_STARTUP_SUMMARY.md](../05_phases/PHASE4_STARTUP_SUMMARY.md) | [歷史] Phase 4 骨架啟動總結追溯。 |
| [superpowers/README.md](../superpowers/README.md) | [歷史/實作軌跡] Superpowers specs / plans 目錄邊界，說明 spec / plan 不取代 Snapshot、6M Roadmap 或版本 roadmap。 |
| [2026-07-13-external-evidence-investment-validation-design.md](../superpowers/specs/2026-07-13-external-evidence-investment-validation-design.md) | [規劃/未執行] External Evidence 與 Investment Effectiveness Validation 核准設計；採雙時鐘並行，鎖定 EV1～EV5 的因果證據、來源治理、OOS custody、公平比較與人工 promotion 邊界，不代表 EV1～EV5 已實作或任何 external Gate 已完成。 |
| [2026-07-13-external-evidence-investment-validation-master-plan.md](../superpowers/plans/2026-07-13-external-evidence-investment-validation-master-plan.md) | [規劃/未執行] 上述設計的 task-by-task Master Plan、dependency DAG、ownership、fail-closed規則、可平行工作與 Terra 啟動 prompts；本 planning closeout 不啟動工作包、不改 Snapshot／Roadmap完成狀態。 |
| [2026-07-13-external-evidence-wave-1-authorization-addendum.md](../superpowers/specs/2026-07-13-external-evidence-wave-1-authorization-addendum.md) | [執行授權/非 Gate] 使用者明確核准 EV1-A、EV3-A、EV4-A 平行啟動的最小授權增補；EV2／EV5 未授權，`formal_oos_allowed=false`、production alpha=0 與所有 External Gate 狀態不變。 |
| [2026-07-13-oos-exposure-custody-audit-execution-plan.md](../superpowers/plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md) | [執行交接/未執行] EV3 第一個切片的 bounded execution plan；只建立不讀 2025 outcome values 的 custody auditor／CLI／tests，缺聲明或 machine evidence 時維持 `indeterminate`。 |
| [2026-07-13-terra-development-dataset-v0-design.md](../superpowers/specs/2026-07-13-terra-development-dataset-v0-design.md) | Terra Development Dataset V0 的已核准設計：2025 是 seen OOS development data、2026 僅 evaluation、四個 core source、252 日 observed universe 與 zero-formal-write 邊界。 |
| [2026-07-13-terra-development-dataset-v0.md](../superpowers/plans/2026-07-13-terra-development-dataset-v0.md) | Terra V0 的 TDD 實作計畫與驗證步驟；不取代 Snapshot 或 External Gate 狀態。 |
| [2026-07-13-terra-external-evidence-execution-handoff.md](../superpowers/prompts/2026-07-13-terra-external-evidence-execution-handoff.md) | [執行交接/未啟動] Terra 第一任務、hard gates、Executor／Independent QA prompts 與 handoff schema；worker 不操作 Git，不自動串接後續 EV tasks。 |
| [2026-06-04-research-lab-workflow-redesign.md](../superpowers/specs/2026-06-04-research-lab-workflow-redesign.md) | Research Lab 多模式實驗室、候選池與 Phase 3 → Portfolio 來源追溯設計。 |
| [2026-06-04-research-lab-workflow-redesign.md](../superpowers/plans/2026-06-04-research-lab-workflow-redesign.md) | Research Lab 工作流重整第一階段實作計畫。 |
| [2026-06-11-financial-float-boundary-governance-design.md](../superpowers/specs/2026-06-11-financial-float-boundary-governance-design.md) | 金融核心白名單的 AST float 邊界掃描、逐行分類標記與 pytest 防回歸設計。 |
| [2026-06-13-strategy-scoring-governance-design.md](../superpowers/specs/2026-06-13-strategy-scoring-governance-design.md) | fixed / quantile 雙模式、回測 Expanding T-1 與推薦 eligible universe 橫斷面百分位設計。 |
| [2026-06-14-month-3-factor-layer-design.md](../superpowers/specs/2026-06-14-month-3-factor-layer-design.md) | Month 3 Factor Layer v1 設計，定義 Factor Contract、Registry、Look-ahead Gate 與既有技術 / 量能 / 券商分點 adapter 範圍。 |
| [2026-07-01-post-v1-evidence-event-store-design.md](../superpowers/specs/2026-07-01-post-v1-evidence-event-store-design.md) | Post-V1 Evidence Event Store / Forward Outcome Calculator v1 設計，定義 event/outcome schema、no-look-ahead、benchmark、quality、idempotency 與 migration safety。 |
| [2026-07-02-post-v1-evidence-importers-design.md](../superpowers/specs/2026-07-02-post-v1-evidence-importers-design.md) | Post-V1 Evidence Importers / Capture Pipeline v1 設計，定義 source importer、dry-run / confirm、diagnostics、unsupported source 與 DTO/repository-only 邊界。 |
| [2026-07-03-post-v1-forward-performance-read-model-design.md](../superpowers/specs/2026-07-03-post-v1-forward-performance-read-model-design.md) | Post-V1 E2E smoke / Forward Performance Read Model v1 設計，定義 tmp DB smoke、read-only aggregation、summary status、score bucket、CLI 與 scheduler not-ready 邊界。 |
| [2026-07-04-post-v1-evidence-source-persistence-design.md](../superpowers/specs/2026-07-04-post-v1-evidence-source-persistence-design.md) | Post-V1 Evidence Source Persistence 設計，定義 durable Daily Decision Desk snapshot repository、capture provider wiring、Recommendation exclusion payload partial 與 source coverage inspection。 |
| [2026-07-05-post-v1-forward-performance-dashboard-design.md](../superpowers/specs/2026-07-05-post-v1-forward-performance-dashboard-design.md) | Post-V1 Forward Performance Dashboard read-only UI 設計，定義 Research Lab placement、dashboard service / DTO、filters、summary cards、table、detail panel 與 read-only 邊界。 |
| [2026-07-06-post-v1-evidence-scheduler-dry-run-design.md](../superpowers/specs/2026-07-06-post-v1-evidence-scheduler-dry-run-design.md) | Post-V1 Evidence Scheduler Dry-run 設計，定義 manual pipeline runner、dry-run / confirm gate、diagnostics report、readiness 上限與 production scheduler 門檻。 |
| [2026-07-07-post-v1-production-scheduler-approval-design.md](../superpowers/specs/2026-07-07-post-v1-production-scheduler-approval-design.md) | Post-V1 Production Scheduler Approval 設計，定義 working-copy DB smoke、scheduler readiness evaluator、人工核准清單與 production scheduler 仍未啟用邊界。 |
| [2026-07-08-post-v1-live-research-gap-linkage-design.md](../superpowers/specs/2026-07-08-post-v1-live-research-gap-linkage-design.md) | Post-V1 Live vs Research Gap linkage 設計，定義 portfolio source trace、Evidence Event / Outcome linkage、保守 matching、attribution 與 portfolio mode 邊界。 |
| [2026-07-08-v3-score-effectiveness-ml-readiness-design.md](../superpowers/specs/2026-07-08-v3-score-effectiveness-ml-readiness-design.md) | V3 Score Effectiveness / ML Readiness 設計，定義 TotalScore 分組、fixed threshold robustness、component ablation 與 ML shadow-only 前置 gate。 |
| [2026-07-09-post-v1-signal-decay-monitor-design.md](../superpowers/specs/2026-07-09-post-v1-signal-decay-monitor-design.md) | Post-V1 Signal Decay Monitor 設計，定義 decay observation、scope、window policy、rule-based score、lifecycle proposed payload 與不自動套用 action 邊界。 |
| [2026-07-09-evidence-quality-design.md](../superpowers/specs/2026-07-09-evidence-quality-design.md) | Evidence Quality Semantics 設計，定義 MoneyDJ 排行來源限制、fixed threshold 百分位不適用、advisory 與 degraded 分級。 |
| [2026-07-10-post-v1-decision-quality-review-design.md](../superpowers/specs/2026-07-10-post-v1-decision-quality-review-design.md) | Post-V1 Decision Quality Review 設計，定義 review repository、review item、process score、CLI 與非責備流程覆盤邊界。 |
| [2026-07-11-post-v1-evidence-review-dashboards-design.md](../superpowers/specs/2026-07-11-post-v1-evidence-review-dashboards-design.md) | Post-V1 Evidence Review Dashboards read-only UI pack 設計，定義 Research Lab Evidence Review placement、Decision Quality / Signal Decay / Live Gap dashboard、共用 boundary banner 與 read-only UI 邊界。 |
| [2026-07-02-v1-3-evidence-operations-design.md](../superpowers/specs/2026-07-02-v1-3-evidence-operations-design.md) | V1.3 Evidence Operations & Manual Lifecycle 設計，定義 weekly review、manual approval package、action item loop 與 production scheduler disabled 邊界。 |
| [2026-07-04-v1-5-data-credibility-design.md](../superpowers/specs/2026-07-04-v1-5-data-credibility-design.md) | V1.5 Data Credibility & Corporate Action Gate 設計，定義 source capability registry、corporate action policy、governed microstructure metadata 與 evidence source coverage 分級。 |
| [2026-07-05-v1-6-cross-sectional-factor-pipeline-design.md](../superpowers/specs/2026-07-05-v1-6-cross-sectional-factor-pipeline-design.md) | V1.6 Cross-sectional Factor Pipeline 設計，定義 daily factor snapshot storage、FactorGate-backed pipeline、concept basket available-date gate、rank / quantile persistence 與 attribution summary 邊界。 |
| [2026-07-05-v1-8-portfolio-sandbox-design.md](../superpowers/specs/2026-07-05-v1-8-portfolio-sandbox-design.md) | V1.8 Portfolio Construction & Execution Trace Sandbox 設計，定義 research-only allocation、constraints、virtual order lifecycle、Decimal / integer bp 邊界與 broker-disabled 範圍。 |
| [2026-07-06-v1-9-read-only-agent-mcp-design.md](../superpowers/specs/2026-07-06-v1-9-read-only-agent-mcp-design.md) | V1.9 Read-only Agent / MCP Evidence Access 設計，定義 evidence / research run / portfolio review saved evidence 查詢、permission model、AI report template 與 read-only 邊界。 |
| [2026-07-06-v2-0-unified-decision-workbench-design.md](../superpowers/specs/2026-07-06-v2-0-unified-decision-workbench-design.md) | V2.0 Unified Decision Workbench Phase 1 設計，定義「今日任務中控台」第一屏、Evidence mode drill-down、Daily Checklist、read-only boundary 與 `_reference_fix` replay summary input。 |
| [2026-07-07-workbench-left-navigation-ia-design.md](../superpowers/specs/2026-07-07-workbench-left-navigation-ia-design.md) | Workbench 左側主導覽 IA 設計，定義預設首頁、`每日決策` 內嵌為 `決策來源`、`市場探索` 重新定位、空狀態、session-only 已查看提示與 schedule/report contract 邊界。 |
| [2026-07-07-ui-ux-readability-polish-design.md](../superpowers/specs/2026-07-07-ui-ux-readability-polish-design.md) | UI / UX readability polish 設計，定義 Runtime compact layout、左側導覽 icon / collapse、Workbench summary / future lanes 與弱勢跌幅色彩語意。 |
| [2026-07-07-workbench-visual-hierarchy-polish-design.md](../superpowers/specs/2026-07-07-workbench-visual-hierarchy-polish-design.md) | Workbench visual hierarchy polish 設計，定義左側自製線條 SVG icon、Workbench 四格指揮台摘要列與 overview gutter 對齊。 |
| [2026-06-13-strategy-scoring-governance.md](../superpowers/plans/2026-06-13-strategy-scoring-governance.md) | 策略分數治理總控計畫與增量 Gate。 |
| [2026-06-14-month-3-factor-layer.md](../superpowers/plans/2026-06-14-month-3-factor-layer.md) | Month 3 Factor Layer v1 實作計畫，拆分 Factor Contract、Registry、Look-ahead Gate、v1 adapters 與 Research Run 追溯保存。 |
| [2026-07-01-post-v1-evidence-event-store.md](../superpowers/plans/2026-07-01-post-v1-evidence-event-store.md) | Post-V1 Evidence Event Store / Forward Outcome Calculator v1 實作計畫，拆分 DTO、repository、service、calculator、CLI、tests 與 QA 文件。 |
| [2026-07-02-post-v1-evidence-importers.md](../superpowers/plans/2026-07-02-post-v1-evidence-importers.md) | Post-V1 Evidence Importers / Capture Pipeline v1 實作計畫，拆分 importer DTO、Recommendation / DDD DTO importers、capture service、CLI、tests 與 QA。 |
| [2026-07-03-post-v1-forward-performance-read-model.md](../superpowers/plans/2026-07-03-post-v1-forward-performance-read-model.md) | Post-V1 E2E smoke / Forward Performance Read Model v1 實作計畫，拆分 smoke CLI、read model service、summary CLI、tests、docs 與 QA。 |
| [2026-07-04-post-v1-evidence-source-persistence.md](../superpowers/plans/2026-07-04-post-v1-evidence-source-persistence.md) | Post-V1 Evidence Source Persistence 實作計畫，拆分 snapshot repository、capture CLI、durable importer provider、exclusion payload 與 coverage CLI。 |
| [2026-07-05-post-v1-forward-performance-dashboard.md](../superpowers/plans/2026-07-05-post-v1-forward-performance-dashboard.md) | Post-V1 Forward Performance Dashboard read-only UI 實作計畫，拆分 dashboard service、Qt view、table model、Research Lab 掛載、tests 與 QA。 |
| [2026-07-06-post-v1-evidence-scheduler-dry-run.md](../superpowers/plans/2026-07-06-post-v1-evidence-scheduler-dry-run.md) | Post-V1 Evidence Pipeline Runner dry-run 實作計畫，拆分 runner DTO、service、CLI、report、tests 與 QA 文件。 |
| [2026-07-06-historical-evidence-replay.md](../superpowers/plans/2026-07-06-historical-evidence-replay.md) | Historical Evidence Replay 實作計畫，拆分 app-layer replay service、replay context metadata、data-as-of outcome gate、CLI、tests 與文件同步。 |
| [2026-07-07-post-v1-production-scheduler-approval.md](../superpowers/plans/2026-07-07-post-v1-production-scheduler-approval.md) | Post-V1 Production Scheduler Approval 實作計畫，拆分 working-copy smoke script、readiness evaluator、approval checklist、tests 與文件同步。 |
| [2026-07-08-post-v1-live-research-gap-linkage.md](../superpowers/plans/2026-07-08-post-v1-live-research-gap-linkage.md) | Post-V1 Live vs Research Gap linkage 實作計畫，拆分 DTO、repository、service、CLI、matching tests、安全邊界與文件同步。 |
| [2026-07-08-v3-score-effectiveness-ml-readiness.md](../superpowers/plans/2026-07-08-v3-score-effectiveness-ml-readiness.md) | V3 Score Effectiveness / ML Readiness 實作計畫，拆分 score bucket audit、threshold robustness、component ablation readiness 與 ML shadow contract。 |
| [2026-07-09-post-v1-signal-decay-monitor.md](../superpowers/plans/2026-07-09-post-v1-signal-decay-monitor.md) | Post-V1 Signal Decay Monitor 實作計畫，拆分 DTO、repository、service、CLI、lifecycle payload、tests 與文件同步。 |
| [2026-07-10-post-v1-decision-quality-review.md](../superpowers/plans/2026-07-10-post-v1-decision-quality-review.md) | Post-V1 Decision Quality Review 實作計畫，拆分 DTO、repository、service、CLI、review item tests、安全邊界與文件同步。 |
| [2026-07-11-post-v1-evidence-review-dashboards.md](../superpowers/plans/2026-07-11-post-v1-evidence-review-dashboards.md) | Post-V1 Evidence Review Dashboards read-only UI pack 實作計畫，拆分 dashboard DTO / service、Qt model / view、Research Lab 掛載、tests 與 QA。 |
| [2026-07-02-v1-3-evidence-operations.md](../superpowers/plans/2026-07-02-v1-3-evidence-operations.md) | V1.3 Evidence Operations 實作計畫，拆分 weekly package、action item loop、QA 與文件 closeout。 |
| [2026-07-04-v1-5-data-credibility.md](../superpowers/plans/2026-07-04-v1-5-data-credibility.md) | V1.5 Data Credibility & Corporate Action Gate 實作計畫，拆分 registry、corporate action policy、microstructure metadata、source coverage service、文件與 QA。 |
| [2026-07-05-v1-6-cross-sectional-factor-pipeline.md](../superpowers/plans/2026-07-05-v1-6-cross-sectional-factor-pipeline.md) | V1.6 Cross-sectional Factor Pipeline 實作計畫，拆分 snapshot DTO / repository / migration、pipeline、attribution CLI、tests、文件與 QA。 |
| [2026-07-05-v1-8-portfolio-sandbox.md](../superpowers/plans/2026-07-05-v1-8-portfolio-sandbox.md) | V1.8 Portfolio Sandbox 實作計畫，拆分 construction DTO/service、virtual execution trace、sample CLI、tests、文件與 QA。 |
| [2026-07-06-v1-9-read-only-agent-mcp.md](../superpowers/plans/2026-07-06-v1-9-read-only-agent-mcp.md) | V1.9 Read-only Agent / MCP Evidence Access 實作計畫，拆分 app-layer service、MCP wrapper、tests、文件與 QA closeout。 |
| [2026-07-06-v2-0-unified-decision-workbench.md](../superpowers/plans/2026-07-06-v2-0-unified-decision-workbench.md) | V2.0 Unified Decision Workbench Phase 1 實作計畫，拆分 DTO、read-only composer、historical replay summary adapter、prototype CLI、tests 與 QA closeout。 |
| [2026-07-07-workbench-left-navigation-ia.md](../superpowers/plans/2026-07-07-workbench-left-navigation-ia.md) | Workbench 左側主導覽 IA 實作計畫，拆分 left navigation widget、MainWindow shell、Workbench internal tabs / empty state、文檔與 QA。 |
| [2026-07-07-ui-ux-readability-polish.md](../superpowers/plans/2026-07-07-ui-ux-readability-polish.md) | UI / UX readability polish 實作計畫，拆分 Runtime、left nav、Workbench readability、weak market semantic color、文件與 QA。 |
| [2026-07-07-workbench-visual-hierarchy-polish.md](../superpowers/plans/2026-07-07-workbench-visual-hierarchy-polish.md) | Workbench visual hierarchy polish 實作計畫，拆分 SVG left nav icons、Workbench command summary layout、文件與 QA。 |
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
| `data_module/monthly_revenue_availability_merge.py` / `scripts/apply_monthly_revenue_availability_candidate.py` | 月營收 availability candidate merge plan 與明確確認後 atomic mapping apply；保留 backup、natural-key conflict 與 SQLite 分離邊界。 |
| `scripts/qa_broker_real_http_canary.py` | 單一受控 MoneyDJ real HTTP canary；需 explicit confirm，固定一個 GET、只解析 response，並可與離線 bounded baseline 合併供 readiness 讀取。 |
| `scripts/qa_technical_indicator_production_canary.py` | 單股 technical process-pool production canary；預設唯讀預演，需 owner token／無並行 writer acknowledgement／explicit confirm，先 backup、失敗可 rollback，並輸出 single-writer readiness artifact。 |
| `scripts/capture_p0_license_evidence.py` | P0 官方條款／OpenAPI 授權候選證據擷取器；預設不連線，確認後僅對 registry allowlist 的 3 個 URL 做 bounded GET，保存 response metadata／SHA-256／關鍵限制 flags，不保存頁面全文、不自動接受來源。 |
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
| [2026-07-11-safe-refactor-four-extra-cycles-design.md](../superpowers/specs/2026-07-11-safe-refactor-four-extra-cycles-design.md) | 安全重構 08:20–12:00 四個完整延長循環的時段、交接、artifact 與安全邊界設計。 |
| [2026-07-11-safe-refactor-four-extra-cycles.md](../superpowers/plans/2026-07-11-safe-refactor-four-extra-cycles.md) | 四個延長 Planner → Implementation → QA 循環與 12:00 Final Closeout 的 automation 更新計畫。 |
| [2026-07-12-gate-1-daily-usable-advice-design.md](../superpowers/specs/2026-07-12-gate-1-daily-usable-advice-design.md) | Gate 1 / V2.1 Daily Usable Advice 設計，定義平衡風險檔、Advice Policy / DTO / Composer 邊界、拒絕輸出與 weekly review 操作契約。 |
| [2026-07-12-v2-1-to-v3-0-versioned-delivery-design.md](../superpowers/specs/2026-07-12-v2-1-to-v3-0-versioned-delivery-design.md) | V2.1–V2.5 的工程 readiness／正式 closeout 雙 commit 規則、版本說明、回滾與人工 Gate 設計。 |
| [phase3_5_research/README.md](../05_phases/phase3_5_research/README.md) | [歷史 SOP] Phase 3.5 研究 SOP 入口。 |
| [phase3_5_research/RESEARCH_ITERATION_PLAYBOOK.md](../05_phases/phase3_5_research/RESEARCH_ITERATION_PLAYBOOK.md) | [歷史 SOP] 研究循環 playbook。 |
| [phase3_5_research/METRIC_INTERPRETATION_PRIORITY.md](../05_phases/phase3_5_research/METRIC_INTERPRETATION_PRIORITY.md) | [歷史 SOP] 指標判讀優先順序。 |
| [phase3_5_research/BENCHMARK_PRESENTATION.md](../05_phases/phase3_5_research/BENCHMARK_PRESENTATION.md) | [歷史 SOP] Benchmark 顯示與解讀規範。 |
| [phase3_5_research/PHASE4_ENTRY_CRITERIA.md](../05_phases/phase3_5_research/PHASE4_ENTRY_CRITERIA.md) | [歷史 SOP] Phase 4 進入條件追溯。 |

---

## 6. QA 與審核

| 文件 | 說明 |
|---|---|
| [GATE_1_ADVICE_CLOSEOUT_2026_07_12.md](../06_qa/GATE_1_ADVICE_CLOSEOUT_2026_07_12.md) | Gate 1 Daily Usable Advice closeout：契約、唯讀 UI、驗證結果與非目標。 |
| [GATE_2_TO_7_PURE_ENGINEERING_CLOSEOUT_2026_07_12.md](../06_qa/GATE_2_TO_7_PURE_ENGINEERING_CLOSEOUT_2026_07_12.md) | Gate 2–7 純工程結案證據：35/35 requirements、獨立 commit slices、驗證結果與 formal product closeout 邊界。 |
| [GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md](../06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md) | 人工補件、資料授權、真實時間、evidence maturity、ML revalidation 與正式核准的持續工作清單。 |
| [GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md](../06_qa/GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md) | 後續 agent 的 Gate 2–7 接手入口：append-only registry、Workbench projection、CLI 與文件導覽。 |
| [V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md](../06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md) | V2.3 P0 資料來源逐項人工接受台帳；含 Owner 候選稽核紀錄與尚待補證據。 |
| [GATE_7_ML_SHADOW_ENGINEERING.md](../06_qa/GATE_7_ML_SHADOW_ENGINEERING.md) | 結構化傳統 ML shadow challenger 的資料凍結、available-date、purged walk-forward、calibration、drift、promotion review 與重驗規則。 |
| [PROSPECTIVE_FORMAL_SIMULATED_PORTFOLIO_EXECUTION_PLAN_2026_08_14.md](../06_qa/PROSPECTIVE_FORMAL_SIMULATED_PORTFOLIO_EXECUTION_PLAN_2026_08_14.md) | Owner 核准的 Gate 7 prospective-only 正式模擬持倉工程計畫：no-backfill clock、Portfolio／Rule／PIT capture、frozen candidate、calibration、watcher 護欄與逐 slice 驗收。 |
| [PROSPECTIVE_FORMAL_CLOCK_ACTIVATION_2026_08_18.md](../06_qa/PROSPECTIVE_FORMAL_CLOCK_ACTIVATION_2026_08_18.md) | Owner 的 prospective clock activation handoff：保存決議時間、owner 選定的未來決策日、deferred input paths 與 zero-credit／fail-closed 邊界；不是 strict readiness 或 Formal evidence。 |
| [PROSPECTIVE_FORMAL_RESTART_DIRECTION_2026_08_19.md](../06_qa/PROSPECTIVE_FORMAL_RESTART_DIRECTION_2026_08_19.md) | Owner 鎖定的 prospective restart 方向：舊 clock 禁止回填、另建新未來 clock、Codex 提出 Rule Champion、TWSE／TPEX 官方 PIT sector、Broker 持續關閉，以及下一個長任務責任與 DoD。 |
| [PROSPECTIVE_FORMAL_RESTART_WEEKLY_UPDATE_2026_08_25.md](../06_qa/PROSPECTIVE_FORMAL_RESTART_WEEKLY_UPDATE_2026_08_25.md) | 2026-08-18 至 2026-08-24 自然週的 Prospective Formal Restart 狀態週報，含 2026-08-25 pre-open source staging、frozen identities、strict readiness 與尚未通過 gates；不授予 Formal 或 weekly credit。 |
| [V2_1_ENGINEERING_READINESS_2026_07_12.md](../06_qa/V2_1_ENGINEERING_READINESS_2026_07_12.md) | V2.1 engineering readiness：記錄 `592d3db` 的 Guided 三重門檻、最大持倉 `1..8`、Professional candidate 分區、focused suite、人工 UI 文案 smoke 與回退錨點。 |
| [V2_1_FORMAL_CLOSEOUT_2026_07_12.md](../06_qa/V2_1_FORMAL_CLOSEOUT_2026_07_12.md) | V2.1 formal closeout approval record：release owner 已於 2026-07-12 14:51:42 -07:00 `approve`，狀態為 `formal_closeout_complete`；此 bounded Advice closeout 不代表投資有效性、broker、scheduler、P0 source acceptance 或 ML production。 |
| [GEMINI_DOCUMENTATION_CROSS_AUDIT_ADJUDICATION_2026_07_13.md](../06_qa/GEMINI_DOCUMENTATION_CROSS_AUDIT_ADJUDICATION_2026_07_13.md) | Gemini A～K／P0～P3 的 repository、Git、source 與 Scoped SSOT 最終裁決；區分 false positive、historical-only、scoped-not-conflict 與 human decisions。 |
| [EXPERIMENT_V1_PREREGISTRATION_TEMPLATE.md](../06_qa/EXPERIMENT_V1_PREREGISTRATION_TEMPLATE.md) | Experiment V1 immutable preregistration 模板；Primary／Guardrail 固定，material effect 與 downside margin 必須由具名人類 owner 在 unblind 前以整數 bp 簽核。 |
| [PROJECT_SNAPSHOT_AUDIT_2026_07_12.md](../06_qa/PROJECT_SNAPSHOT_AUDIT_2026_07_12.md) | Snapshot claim 證據矩陣：保留 / 移至歷史 / 限制 / 去重判定與 Scoped SSOT 稽核。 |
| [SHIM_LEGACY_REMOVAL_AUDIT_2026-07-12.md](../06_qa/SHIM_LEGACY_REMOVAL_AUDIT_2026-07-12.md) | Wave 6 compatibility shim／legacy removal 的 consumer、dynamic import、persisted class-path 與 release closeout 證據。 |

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
| [WALK_FORWARD_COMPARISON_REPORT.md](../06_qa/WALK_FORWARD_COMPARISON_REPORT.md) | Fixed vs Quantile 機制、時間軸回歸、10 檔 OOS 實證與 100% Regime coverage Gate 證據。 |
| [DOCUMENT_ENCODING_AUDIT_2026_06_16.md](../06_qa/DOCUMENT_ENCODING_AUDIT_2026_06_16.md) | repo 文件 UTF-8 / mojibake 稽核報告，確認顯示雜訊來自終端編碼而非文件內容損壞。 |
| [DOCUMENTATION_ROADMAP_REBASELINE_AUDIT_2026_07_03.md](../06_qa/DOCUMENTATION_ROADMAP_REBASELINE_AUDIT_2026_07_03.md) | Roadmap / docs / phase 目錄整理稽核，記錄 `docs/05_phases/` 降格為 Historical / Reference、入口文件同步與後續歸檔準則。 |
| [DOCUMENTATION_PRE_PUSH_AUDIT_2026_07_06.md](../06_qa/DOCUMENTATION_PRE_PUSH_AUDIT_2026_07_06.md) | 本輪 push 前 docs 全目錄位置、索引、archive 候選、版本治理與相對連結稽核。 |
| [SUPERPOWERS_PLAN_SPEC_DATE_AUDIT_2026_07_06.md](../06_qa/SUPERPOWERS_PLAN_SPEC_DATE_AUDIT_2026_07_06.md) | `docs/superpowers/` 2026-07-06 至 2026-07-12 plan / spec / QA milestone 日期稽核，記錄 Git closeout、是否需改名、V2.0 plan/spec 最新狀態與 historical replay 對 Phase 1 的可用邊界。 |
| [FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md](../06_qa/FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md) | Testing QA Agent 使用的 feature-to-test 測試路由與決策矩陣（測試知識庫），不包含 Agent 角色定義。 |
| [POST_V1_EVIDENCE_EVENT_STORE_QA_2026_07_01.md](../06_qa/POST_V1_EVIDENCE_EVENT_STORE_QA_2026_07_01.md) | Post-V1 Evidence Event Store v1 / Forward Outcome Calculator v1 QA 紀錄，包含 schema safety、focused tests、限制與下一增量。 |
| [POST_V1_EVIDENCE_IMPORTERS_QA_2026_07_02.md](../06_qa/POST_V1_EVIDENCE_IMPORTERS_QA_2026_07_02.md) | Post-V1 Evidence Importers / Capture Pipeline v1 QA 紀錄，包含 importer 支援邊界、CLI dry-run / confirm、unsupported source 與限制。 |
| [POST_V1_FORWARD_PERFORMANCE_READ_MODEL_QA_2026_07_03.md](../06_qa/POST_V1_FORWARD_PERFORMANCE_READ_MODEL_QA_2026_07_03.md) | Post-V1 Forward Performance Read Model QA 紀錄，包含 importer-to-outcome smoke、read model filters / group by / metrics、summary CLI 與非目標邊界。 |
| [POST_V1_EVIDENCE_SOURCE_PERSISTENCE_QA_2026_07_04.md](../06_qa/POST_V1_EVIDENCE_SOURCE_PERSISTENCE_QA_2026_07_04.md) | Post-V1 Evidence Source Persistence QA 紀錄，包含 durable DDD snapshot repository、source coverage CLI、Recommendation exclusion payload partial 與 scheduler readiness 邊界。 |
| [V1_5_DATA_CREDIBILITY_CLOSEOUT_2026_07_04.md](../06_qa/V1_5_DATA_CREDIBILITY_CLOSEOUT_2026_07_04.md) | V1.5 Data Credibility & Corporate Action Gate closeout，記錄 source capability registry、corporate action policy、governed microstructure metadata、source coverage service 與驗證結果。 |
| [V1_6_CROSS_SECTIONAL_FACTOR_PIPELINE_CLOSEOUT_2026_07_05.md](../06_qa/V1_6_CROSS_SECTIONAL_FACTOR_PIPELINE_CLOSEOUT_2026_07_05.md) | V1.6 Cross-sectional Factor Pipeline closeout，記錄 factor snapshot storage、FactorGate-backed pipeline、concept available-date gate、attribution CLI、驗證命令與不改 scoring / scheduler 邊界。 |
| [V1_7_NEGATIVE_EVIDENCE_CLOSEOUT_2026_07_05.md](../06_qa/V1_7_NEGATIVE_EVIDENCE_CLOSEOUT_2026_07_05.md) | V1.7 Screening Matrix & Negative Evidence closeout，記錄 recommendation screening matrix、Why Not / Liquidity payload、screening matrix events、source coverage warning、驗證命令與不回補 / 不重算邊界。 |
| [V1_8_PORTFOLIO_SANDBOX_CLOSEOUT_2026_07_05.md](../06_qa/V1_8_PORTFOLIO_SANDBOX_CLOSEOUT_2026_07_05.md) | V1.8 Portfolio Construction & Execution Trace Sandbox closeout，記錄 research-only allocation、virtual execution trace、sample CLI、驗證命令與不下單 / 不寫正式資料邊界。 |
| [V1_9_READ_ONLY_AGENT_MCP_CLOSEOUT_2026_07_06.md](../06_qa/V1_9_READ_ONLY_AGENT_MCP_CLOSEOUT_2026_07_06.md) | V1.9 Read-only Agent / MCP Evidence Access closeout，記錄 app-layer service、MCP server、permission model、report template、驗證命令與不寫 DB / 不改策略 / 不下單邊界。 |
| [PRE_V2_NON_SCHEDULE_READINESS_CLOSEOUT_2026_07_06.md](../06_qa/PRE_V2_NON_SCHEDULE_READINESS_CLOSEOUT_2026_07_06.md) | V2.0 前非時間型 readiness closeout，記錄 Git unreachable loose objects 清理、read-only Pre-V2 inspector、source gap working-copy all-source smoke、Evidence Review UI smoke、Agent report sample、測試命令與仍需多週 / 多日累積的時間門檻。 |
| [V2_0_WORKBENCH_PHASE1_CLOSEOUT_2026_07_06.md](../06_qa/V2_0_WORKBENCH_PHASE1_CLOSEOUT_2026_07_06.md) | V2.0 Workbench Phase 1 read-only prototype closeout，記錄當時 DTO / composer / replay summary adapter / sample CLI、focused tests、CLI smoke、mypy / quant guard 與不寫 evidence / 不啟用 scheduler 邊界。 |
| [V2_0_WORKBENCH_READ_ONLY_SOURCE_ADAPTER_CLOSEOUT_2026_07_06.md](../06_qa/V2_0_WORKBENCH_READ_ONLY_SOURCE_ADAPTER_CLOSEOUT_2026_07_06.md) | V2.0 Workbench formal read-only source adapter closeout，記錄 `WorkbenchSourceService`、受控 `--db-path` / `--decision-date`、Pre-V2 readiness、DDD durable snapshot、AgentEvidenceAccess summary、optional replay JSON、missing DB / table diagnostics、focused tests 與不寫 DB / 不啟用 scheduler 邊界。 |
| [V2_1_WORKBENCH_PHASE2_CLOSEOUT_2026_07_07.md](../06_qa/V2_1_WORKBENCH_PHASE2_CLOSEOUT_2026_07_07.md) | V2.1 / Phase 2 Workbench read-only Operating Loop closeout，記錄 background evidence feed、Action Items 人工佇列、Operating Loop 操作節奏、drill-down target contract、focused QA 與 Phase 0 真實時間 gate / scheduler gate 未完成邊界。 |
| [WORKBENCH_LEFT_NAVIGATION_IA_CLOSEOUT_2026_07_07.md](../06_qa/WORKBENCH_LEFT_NAVIGATION_IA_CLOSEOUT_2026_07_07.md) | Workbench 左側主導覽 IA closeout，記錄左側主導覽、DecisionDesk 內嵌、empty state、session-only queue feedback、schedule/report regression QA 與 Phase 0 gate 未完成邊界。 |
| [UI_UX_READABILITY_POLISH_CLOSEOUT_2026_07_07.md](../06_qa/UI_UX_READABILITY_POLISH_CLOSEOUT_2026_07_07.md) | UI / UX readability polish closeout，記錄 Runtime compact layout、left nav icon / collapse、Workbench summary / future lanes、weak market semantic color、focused QA 與正式資料 gate 未完成邊界。 |
| [WORKBENCH_VISUAL_HIERARCHY_POLISH_CLOSEOUT_2026_07_07.md](../06_qa/WORKBENCH_VISUAL_HIERARCHY_POLISH_CLOSEOUT_2026_07_07.md) | Workbench visual hierarchy polish closeout，記錄左側自製線條 SVG icon、Workbench 四格指揮台摘要列、overview gutter 對齊、focused QA 與正式資料 gate 未完成邊界。 |
| [V2_2_EVIDENCE_OPERATING_LOOP_READONLY_CHECK_2026_07_07.md](../06_qa/V2_2_EVIDENCE_OPERATING_LOOP_READONLY_CHECK_2026_07_07.md) | V2.2 Evidence Operating Loop read-only check，記錄正式 DB / scheduled dry-run / Pre-V2 readiness / manual review note / action item rhythm 現況；確認 weekly history `0/3`、multi-day dry-run `1/3` 尚未被 raw scheduled reports 補齊，並列出下一次人工 read-only checklist。 |
| [V2_2_SIMULATED_PHASE_PROGRESS_QA_2026_07_07.md](../06_qa/V2_2_SIMULATED_PHASE_PROGRESS_QA_2026_07_07.md) | V2.2 simulated phase progress QA，記錄 historical replay reference-fix summary 如何標註為 `historical_replay` / `simulated_scheduler` / `official_gate_credit=false`，以及 simulated Phase 0-5 可演練但 official Phase 0 / Phase 5 gate 不變的 read-only 邊界。 |
| [V2_2_PHASE5_APPROVAL_REHEARSAL_PACKAGE_2026_07_07.md](../06_qa/V2_2_PHASE5_APPROVAL_REHEARSAL_PACKAGE_2026_07_07.md) | V2.2 Phase 5 approval rehearsal package，整理 simulated Phase 5 審核包預演、official completion waiting list、data source candidate backlog、execution realism backlog、scheduler approval rehearsal checklist 與 UI 資訊架構 follow-up；明確標示哪些項目必須等待正式資料才能標為已完成。 |
| [V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md](../06_qa/V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md) | V3.0 engineering candidate manual validation / closeout report，記錄 V3 effectiveness read model、score bucket audit、threshold robustness、component ablation readiness、ML shadow-only contract、Phase 3C source candidate readiness、`PENDING_MANUAL_VALIDATION` 與夜間 closeout 目標；不宣稱投資有效性、不啟用 scheduler。 |
| [V3_0_AUTOMATED_READINESS_2026_07_12.md](../06_qa/V3_0_AUTOMATED_READINESS_2026_07_12.md) | V3.0 自動工程 readiness 重驗證，記錄 26 passed、required artifact 檢查、sample evidence 缺口與 read-only report 入口；不建立 formal closeout。 |
| [V2_5_ENGINEERING_READINESS_2026_07_12.md](../06_qa/V2_5_ENGINEERING_READINESS_2026_07_12.md) | V2.5 Position Health Foundation engineering readiness，記錄 condition / feedback / source trace 的唯讀 HEALTHY / WATCH / EXIT_CANDIDATE 投影、sample CLI、驗證與不自動 action 邊界。 |
| [POST_V1_FORWARD_PERFORMANCE_DASHBOARD_QA_2026_07_05.md](../06_qa/POST_V1_FORWARD_PERFORMANCE_DASHBOARD_QA_2026_07_05.md) | Post-V1 Forward Performance Dashboard read-only UI QA 紀錄，包含 UI placement、read-only guarantee、filter coverage、禁用交易語氣檢查與 scheduler readiness 邊界。 |
| [POST_V1_EVIDENCE_SCHEDULER_DRY_RUN_QA_2026_07_06.md](../06_qa/POST_V1_EVIDENCE_SCHEDULER_DRY_RUN_QA_2026_07_06.md) | Post-V1 Evidence Pipeline Runner dry-run QA 紀錄，包含 dry-run / confirm 行為、report、readiness、blocking gaps 與 production scheduler 未啟用邊界。 |
| [POST_V1_HISTORICAL_EVIDENCE_REPLAY_QA_2026_07_06.md](../06_qa/POST_V1_HISTORICAL_EVIDENCE_REPLAY_QA_2026_07_06.md) | Post-V1 Historical Evidence Replay QA 紀錄，包含 working-copy replay DB、安全路徑、as-of recommendation selection、data-as-of outcome gate、reference return fix audit、`_reference_fix` rerun summary、測試命令與不取代 scheduler gate 邊界。 |
| [POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md](../06_qa/POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md) | Post-V1 Evidence Production Scheduler Approval checklist，集中管理 working-copy smoke、人工核准、rollback / recovery 與正式排程未啟用邊界。 |
| [POST_V1_LIVE_RESEARCH_GAP_LINKAGE_QA_2026_07_08.md](../06_qa/POST_V1_LIVE_RESEARCH_GAP_LINKAGE_QA_2026_07_08.md) | Post-V1 Live vs Research Gap linkage QA，包含 source trace coverage、matching policy、attribution policy、portfolio mode policy、CLI examples 與安全邊界。 |
| [POST_V1_SIGNAL_DECAY_MONITOR_QA_2026_07_09.md](../06_qa/POST_V1_SIGNAL_DECAY_MONITOR_QA_2026_07_09.md) | Post-V1 Signal Decay Monitor QA，包含 decay repository、service policy、CLI examples、lifecycle proposed payload 與安全邊界。 |
| [POST_V1_DECISION_QUALITY_REVIEW_QA_2026_07_10.md](../06_qa/POST_V1_DECISION_QUALITY_REVIEW_QA_2026_07_10.md) | Post-V1 Decision Quality Review QA，包含 review repository、service policy、CLI examples、review item coverage 與安全邊界。 |
| [POST_V1_EVIDENCE_REVIEW_DASHBOARDS_QA_2026_07_11.md](../06_qa/POST_V1_EVIDENCE_REVIEW_DASHBOARDS_QA_2026_07_11.md) | Post-V1 Evidence Review Dashboards QA，包含 UI placement、dashboard coverage、read-only guarantee、forbidden language check、test commands 與 not-done 邊界。 |
| [POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md](../06_qa/POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md) | Post-V1 Evidence Review UI 人工 smoke checklist，覆蓋四個 dashboard、boundary banner、empty/degraded states、read-only guarantee 與人工結果表。 |
| [POST_V1_V1_3_EVIDENCE_OPERATIONS_QA_2026_07_03.md](../06_qa/POST_V1_V1_3_EVIDENCE_OPERATIONS_QA_2026_07_03.md) | V1.3 Evidence Operations QA，記錄 weekly review CLI、manual approval package、action item planning、測試命令與 production scheduler disabled 邊界。 |
| [POST_V1_V1_4_EVIDENCE_REVIEW_HISTORY_QA_2026_07_03.md](../06_qa/POST_V1_V1_4_EVIDENCE_REVIEW_HISTORY_QA_2026_07_03.md) | V1.4 Evidence Review History QA，記錄 weekly review history repository、CLI save/list、Research Lab 覆盤歷史子頁、測試命令與 production scheduler disabled 邊界。 |
| [POST_V1_EVIDENCE_OPERATIONS_WEEKLY_HISTORY_RUN_2026_07_03.md](../06_qa/POST_V1_EVIDENCE_OPERATIONS_WEEKLY_HISTORY_RUN_2026_07_03.md) | 第一個 weekly evidence operations + history working-copy run 紀錄，狀態為 `coverage_only`，確認 history idempotency 與 production scheduler disabled 邊界。 |
| [POST_V1_EVIDENCE_DECISION_DESK_WORKING_COPY_SMOKE_2026_07_03.md](../06_qa/POST_V1_EVIDENCE_DECISION_DESK_WORKING_COPY_SMOKE_2026_07_03.md) | Daily Decision Desk batch snapshot follow-up QA，記錄 service-backed builder 修補、risk-prompt / recommendation working-copy confirm smoke、idempotency 與剩餘 exclusion payload / watchlist / portfolio source gaps。 |
| [POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md](../06_qa/POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md) | Evidence Pipeline 多日 dry-run 記錄模板，用於正式 scheduler 前穩定性觀察，不代表 production scheduler 已啟用。 |
| [POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md](../06_qa/POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md) | Evidence scheduler approval SOP，定義 manual run、multi-day dry-run、working-copy smoke、dashboard review、manual approval 與 explicit approval 後才 implementation 的 stage。 |
| [POST_V1_EVIDENCE_SCHEDULED_DRY_RUN_QA_2026_07_12.md](../06_qa/POST_V1_EVIDENCE_SCHEDULED_DRY_RUN_QA_2026_07_12.md) | Evidence safe scheduled wrapper 歷史 QA，記錄 PowerShell `.ps1` 註冊被 local execution policy 擋住。 |
| [POST_V1_SCHEDULED_EVIDENCE_PIPELINE_QA_2026_07_12.md](../06_qa/POST_V1_SCHEDULED_EVIDENCE_PIPELINE_QA_2026_07_12.md) | CMD wrapper + `schtasks.exe` QA，記錄 05:00 read-only freshness、05:15 evidence dry-run、05:30 Codex read-only 摘要、manual-only working-copy smoke 與 production write-mode 未啟用邊界。 |


---

## 7. 操作指南

| 文件 | 用途 |
|---|---|
| [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md) | 目前 8 個頂層工作區的完整操作手冊，包含安裝、參數、結果判讀、安全限制與排錯。 |
| [EVIDENCE_SCHEDULED_MORNING_CHECK.md](../07_guides/EVIDENCE_SCHEDULED_MORNING_CHECK.md) | Evidence scheduled dry-run 的每日早晨人工檢查步驟，包含 CMD + `schtasks.exe` 查詢、Codex read-only 摘要、freshness status、dry-run report 與停用方式。 |
| [V2_2_WEEKLY_REVIEW_RUNBOOK.md](../07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md) | V2.2 三週人工 Evidence Review 的 working-copy DB 安全操作、sidecar collection、append-only history 與 formal closeout 邊界。 |
| [P0_DAILY_SOURCE_CANDIDATE_RUNBOOK.md](../07_guides/P0_DAILY_SOURCE_CANDIDATE_RUNBOOK.md) | 13 項 P0 候選資料來源的唯讀品質稽核指令、結果判讀與排程隔離邊界。 |
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
| [MCP_YFINANCE_OPENMARKETS_PATCH_MEMO.md](../08_technical/MCP_YFINANCE_OPENMARKETS_PATCH_MEMO.md) | openmarkets / yahoo-finance MCP 相容性修補備忘，保存 `.venv` 重建後的本機 patch 與驗證方式。 |

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
| [agents/multi_agent_workflow.md](../agents/multi_agent_workflow.md) | 多 Agent 分支角色、合併前檢查與協作協議。 |
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
| [strategies/README.md](../strategies/README.md) | 策略說明文件目錄與維護規則；策略實作仍以 registry 與 `app_module/strategies/` 為準。 |
| [strategies/momentum_aggressive_v1.md](../strategies/momentum_aggressive_v1.md) | 暴衝策略說明。 |
| [strategies/stable_conservative_v1.md](../strategies/stable_conservative_v1.md) | 穩健策略說明。 |

---

## 10. Archive

[09_archive/](../09_archive/README.md) 只放歷史文件、已執行提案、舊調查與不再作為日常依據的內容。Active 文件不應依賴 archive 來判斷目前狀態。
主要封存文檔：
- [ROADMAP_6M_ENGINEERING_V1_COMPLETION_RECORD_2026_07.md](../09_archive/ROADMAP_6M_ENGINEERING_V1_COMPLETION_RECORD_2026_07.md)：原 6M Roadmap 於 V1 (Month 1-6) 的詳細完工紀錄與更新流水帳。
- [UI_QT_DEVELOPMENT_ROADMAP_AUDIT_2026_05_19.md](../09_archive/UI_QT_DEVELOPMENT_ROADMAP_AUDIT_2026_05_19.md)：2026-05-19 `ui_qt` 對照舊 roadmap 的歷史審核報表；因其中部分狀態已過時，改放 archive。
- [DEVELOPMENT_ROADMAP_LEGACY_2026_06.md](../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md)：舊完整 Roadmap，包含線性 Phase、歷史 Done 與舊 Roadmap current section，只作追溯用途。
- [NEXT_ACTION_PLAN.md](../09_archive/NEXT_ACTION_PLAN.md)：2026-06-09 下一輪行動計畫（已執行完畢）。
- [PHASE_3_3B_IMPLEMENTATION_PLAN.md](../09_archive/PHASE_3_3B_IMPLEMENTATION_PLAN.md)：Phase 3.3b 實施規劃（已執行完畢）。
- [REFACTORING_MIGRATION_PLAN_2025.md](../09_archive/REFACTORING_MIGRATION_PLAN_2025.md)：2025 年專案結構化與遷移計畫；已完成，只作架構演進追溯。
- [SAFE_REFACTORING_MASTER_REPORT_2026_07_12.md](../09_archive/SAFE_REFACTORING_MASTER_REPORT_2026_07_12.md)：Gate 0 行為不變安全重構的已完成執行紀錄、rollback 與 residual candidate companion。
- [root_readme_legacy_2025_12.txt](../09_archive/root_readme_legacy_2025_12.txt)：原根目錄 `readme.txt`，內容停留在舊 Phase、舊入口與舊路徑說明，只作歷史追溯。
- [dev_progress_note_legacy_2026_01.txt](../09_archive/dev_progress_note_legacy_2026_01.txt)：原 `docs/00_core/note.txt` 歷史開發進度筆記，只作追溯，不作目前狀態權威。
- [ARCH_GOVERNANCE_CHECKLIST.md](../09_archive/ARCH_GOVERNANCE_CHECKLIST.md)：早期架構治理自檢清單，已自 `00_core/` 歸檔；目前架構權威以 `docs/01_architecture/system_architecture.md` 為準。
- [ARCH_GOVERNANCE_LIFECYCLE.md](../09_archive/ARCH_GOVERNANCE_LIFECYCLE.md)：早期架構治理生命週期備忘，已自 `00_core/` 歸檔；目前文件治理以 Coverage Map 與 Documentation Structure 為準。
- [ARCH_VIOLATION_RESPONSE_POLICY.md](../09_archive/ARCH_VIOLATION_RESPONSE_POLICY.md)：早期架構違規處理政策備忘，已自 `00_core/` 歸檔；目前架構邊界與高風險契約以 system architecture 為準。

---

## 目前開發狀態

> 本節只作導航摘要；現況仍以 `PROJECT_SNAPSHOT.md` 為準，方向／工程／架構分別回到各自 Scoped SSOT。

- **工程狀態**：A～F committed handoff 已由 G 的跨流 composition／pure verifier 驗證；Gate 2～7 pure engineering 與 evidence rehearsal engineering 已完成，但不是 formal product closeout。
- **外部狀態**：Week 1 已完成，weekly history 為 `1/3 waiting_for_time`，multi-day dry-run 為 `3/3 ready`；forward maturity、P0 source/license decisions、paper/exit evidence、ML formal OOS／promotion 與 production automation 仍 pending。
- **產品／安全邊界**：V2.1 bounded Advice 為 `formal_closeout_complete`；`formal_oos_allowed=false`、`production_blend_alpha_bp=0`，scheduler／broker／auto action 未啟用。
- **下一階段執行入口**：先讀 [External Validation Register](../06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)；External Evidence 第一個技術切片固定是 [OOS Exposure／Custody Audit](../superpowers/plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md)，不讀 2025 outcome values，也不改 Gate。

---

## 維護提醒

- 新增或刪除任何 Markdown 後，更新本索引。
- 狀態文字若與 Snapshot、6M Roadmap 或 Architecture 衝突，以對應範圍的權威文件為準並修正本索引。
- 不確定文件是否該刪除時，先在 `DOCUMENTATION_STRUCTURE.md` 記錄生命週期決策；仍有引用或歷史脈絡價值時，優先標示 Historical / Reference，再評估是否分批搬入 `09_archive/`。

---

## 🔄 更新記錄

- 2026-07-13：完成 Gemini 文件交叉稽核裁決；校正 Scoped reading order、V2.1 closeout、目前 UI／weekly progress導航與 External Evidence 執行基線，新增 OOS Audit plan、Experiment V1 preregistration template 與 Terra handoff。External Gate、formal OOS、alpha 與 production automation 狀態不變。
- 2026-07-13：新增 External Evidence 與 Investment Effectiveness Validation 核准設計及 Master Plan 索引；文件只定義後續 EV1～EV5 執行路徑，Snapshot、Roadmap、external Gate 與正式產品狀態均未改變。
- 2026-07-12：完成全 docs 位置稽核；將 Multi-Agent workflow 移至 `docs/agents/`、Shim／Legacy removal audit 移至 `docs/06_qa/`，並將兩份已完成重構文件移至 `docs/09_archive/`，同步所有索引與引用。

- 2026-07-12：新增 Gate 1 Advice closeout 與 Project Snapshot audit QA 索引；Gate 0 / Gate 1 完成狀態仍以 Snapshot 為準，Roadmap、Architecture、Manual 各維持 scoped authority。
- 2026-07-11：新增安全重構四個延長循環的設計與實作計畫索引，並將 Master Report 執行時段延長至 12:00 Final QA / Closeout。
- 2026-07-11：新增 `PRODUCT_ROADMAP_POST_REFACTOR.md` 與 `target_system_architecture.md` 索引；重整 Vision、6M Roadmap、V1.1-V2.0 歷史定位與 V2.1-V4.0 maturity 描述，清楚分離 Current / Target 與產品 / 工程權威。
- 2026-07-11：新增 Safe Refactoring Master Report 作為行為不變重構與 Planner → Implementation → QA automation 的共用執行 companion；2026-07-12 closeout 後已移至 archive。
- 2026-07-06：完成 push 前 docs 結構稽核索引同步，新增 `DOCUMENTATION_PRE_PUSH_AUDIT_2026_07_06.md`、`superpowers/README.md`、`strategies/README.md`，將過時 UI Qt roadmap audit 歸檔，並把 MCP patch memo 移至技術文件。
- 2026-07-06：新增 V2.1 至 V4.0 長期版本路線圖索引，標示其為 6M Roadmap Phase 與 Vision 成功標準的版本 companion，不作目前狀態或工程順序權威。
- 2026-07-06：新增 V2.0 Workbench Phase 1 read-only prototype QA closeout 索引，標示當時 DTO / composer / replay summary adapter / sample CLI 已完成；formal source adapter 另見後續 closeout，Phase 2 UI / scheduler gate 仍未完成。
- 2026-07-06：新增 V2.0 Workbench formal read-only source adapter QA closeout 索引，標示 prototype CLI 已從 `--sample` 擴充到受控 `--db-path` / `--decision-date`，可讀 Pre-V2 readiness、DDD durable snapshot、AgentEvidenceAccess summary 與 optional replay JSON；Phase 0 / scheduler gate 不變。
- 2026-07-06：更新 Pre-V2 非時間型 readiness closeout 索引，標示 Git loose objects、source gaps、Evidence Review UI smoke 與 Agent sample 已收斂；多週 history、multi-day dry-run 與 production scheduler approval 仍需真實時間與人工核准。
- 2026-07-06：新增 Historical Evidence Replay plan 索引，標示 replay 只作 working-copy / simulated scheduler research evidence，不取代真實 weekly history、多日 dry-run 或 production scheduler approval。
- 2026-07-06：新增 Historical Evidence Replay QA closeout 索引，記錄 as-of recommendation selection、data-as-of outcome gate、focused tests、py_compile、quant guard 與 scheduler gate 邊界。
- 2026-07-06：補充 Phase 0A / Pre-V2.0A replay quality audit 索引，標示 benchmark reference return blocker 已解除，industry / screening matrix payload gap 保留為 V2.0 Phase 1 設計輸入。
- 2026-07-06：新增 V2.0 Unified Decision Workbench Phase 1 design / plan 索引，標示第一屏、Evidence mode、Daily Checklist 與 historical replay summary adapter 邊界。
- 2026-07-07：更新 Workbench Phase 2 索引摘要，補入 background evidence feed / read-only Action Items MVP 現況；Action Items 仍只顯示人工待處理事項，不寫 DB、不套用 lifecycle。
- 2026-07-07：補充 Workbench Action Items 人工佇列索引摘要；Action Items 已加入 severity / queue group / source label / sort rank、空 / 降級狀態與舊頁 drill-down contract，仍維持 read-only DTO payload、不寫 DB、不啟用 scheduler、不產生建議。
- 2026-07-07：新增 V2.1 / Phase 2 Workbench read-only Operating Loop closeout 索引；Phase 2 UI / read-only operating loop 可收口，但 Phase 0 weekly history `0/3`、multi-day dry-run `1/3`、V2.2 真實 evidence loop 與 production scheduler gate 仍未完成。
- 2026-07-07：新增 Workbench 左側主導覽 IA design / plan 索引；主 UI 預設進入 `決策工作台`，`每日決策` 已內嵌為 `決策來源`，`市場觀察` 改名為 `市場探索`，但 Phase 0 weekly history `0/3` 與 multi-day dry-run `1/3` 仍需正式資料累積。
- 2026-07-07：新增 Workbench 左側主導覽 IA closeout QA 索引，記錄 focused UI / Workbench / scheduled wrapper tests、Update Tab QA、py_compile 與 mypy 通過。
- 2026-07-07：新增 V2.2 Evidence Operating Loop read-only check 索引；確認 2026-07-02 至 2026-07-06 scheduled dry-run raw reports 不自動計入 Phase 0 gate，weekly history 仍為 `0/3`、multi-day dry-run record 仍為 `1/3`。
- 2026-07-07：新增 V2.2 simulated phase progress service / CLI / QA 索引；historical replay 可標註為 simulated track 並演練 Phase 0-5，但 `official_gate_credit=false`、`requires_real_world_validation=true`，official Phase 5 仍 blocked。
- 2026-07-07：新增 V2.2 Phase 5 approval rehearsal package 索引；在 Snapshot / 6M Roadmap / Version Roadmap / Manual 補上 official completion waiting list，避免把 simulated ready 誤標為已完成。
- 2026-07-05：新增 V1.6 Cross-sectional Factor Pipeline design / plan / QA closeout 索引，標示 daily factor snapshot storage、FactorGate-backed pipeline、concept available-date gate、rank / quantile persistence 與 attribution summary CLI 已完成 v1；不改 scoring、不啟用 scheduler。
- 2026-07-05：新增 V1.7 Negative Evidence QA closeout 索引，標示 recommendation screening matrix、Why Not / Liquidity payload、screening matrix evidence events 與 source coverage warning 已完成 v1；舊結果不回補、不重算，不改 scoring、不啟用 scheduler。
- 2026-07-06：新增 V1.9 Read-only Agent / MCP Evidence Access design / plan / QA closeout 索引，標示 read-only evidence service、MCP wrapper、permission model 與 AI report template 已完成 v1；不寫 DB、不改策略、不下單、不套用 lifecycle action。
- 2026-07-06：新增備份檔來源與 retention 盤點索引，記錄 `FA_Data` 大型 DB/CSV 備份堆積來源、已納入保留策略的 migration/backfill/repair 入口，以及既有大檔清理需人工確認的邊界。
- 2026-07-04：新增外部專案參考與未來版本藍圖索引，將 `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md` 定位為 6M Roadmap / Version Roadmap companion，用來承接 GitHub 專案對照、資料源補強優先序與 V1.5-V2.0 版本形狀，避免 Vision 被外部參考清單污染。
- 2026-07-04：新增 V1.5 Data Credibility design / plan / QA closeout 索引，標示 source capability registry、corporate action policy、microstructure metadata 與 shared source coverage service 已完成 v1；production scheduler 與外部資料 ingestion 仍未啟用。
- 2026-07-03：整理 Roadmap / docs / phase 判讀入口，將 `docs/05_phases/` 明確標示為 Historical / Reference，新增文件整理稽核索引，避免 Phase 文件被誤判為目前 roadmap。
- 2026-07-01：新增 Post-V1 Evidence Event Store design / plan 與 QA 索引，標示 Evidence Event Store v1 / Forward Outcome Calculator v1 是 forward evidence 資料底座，不是 dashboard 或投資有效性證明。
- 2026-07-02：新增 Post-V1 Evidence Importers design / plan 與 QA 索引，標示 capture pipeline v1 可累積 persisted Recommendation 與 DTO-based DDD evidence，但仍不是 dashboard 或投資有效性證明。
- 2026-07-03：新增 Post-V1 E2E smoke / Forward Performance Read Model design / plan 與 QA 索引，標示 read model v1 可唯讀彙總 outcomes，但 Dashboard UI、production scheduler 與投資有效性證明仍未完成。
- 2026-07-04：新增 Post-V1 Evidence Source Persistence design / plan 與 QA 索引，標示 durable Daily Decision Desk snapshot source 與 source coverage inspection v1 已完成；Why Not / Liquidity exclusion payload 為 optional / partial，scheduler 仍不得視為 production-ready。
- 2026-07-01：新增 Post-V1 Forward Performance Dashboard read-only UI design / plan 與 QA 索引，標示 Research Lab `Forward Evidence` 已完成；scheduler 仍只到 ready_for_design，不得宣稱投資有效性。
- 2026-07-01：新增 Post-V1 Evidence Scheduler Dry-run design / plan 與 QA 索引，標示 manual pipeline runner 已完成；readiness 最高只到 `ready_for_manual_confirm`，production scheduler 仍未啟用。
- 2026-07-01：新增 Post-V1 Production Scheduler Approval design / plan 與 approval checklist 索引，標示 working-copy smoke 與 readiness evaluator 已建立；production scheduler 仍未啟用，需人工核准與 rollback / recovery 檢查。
- 2026-07-01：新增 Post-V1 Live vs Research Gap linkage design / plan 與 QA 索引，標示 gap observation repository / service / CLI 已建立；此為 evidence observation，不是完整實帳歸因或 lifecycle action。
- 2026-07-01：新增 Post-V1 Signal Decay Monitor design / plan 與 QA 索引，標示 decay observation repository / service / CLI 已建立；lifecycle proposed payload 只供人工審核，不自動套用 action。
- 2026-07-01：新增 Post-V1 Decision Quality Review design / plan 與 QA 索引，標示 review repository / service / CLI 已建立；process quality score 只供流程覆盤，不是投資能力或責備判斷。
- 2026-07-01：新增 Post-V1 Evidence Review Dashboards design / plan 與 QA 索引，標示 Research Lab `Evidence Review` read-only UI pack 已建立；dashboard 只讀 evidence / observation / review，不寫 evidence、不建立 scheduler、不自動 lifecycle action。
- 2026-07-02：新增 Evidence Review UI smoke checklist、Evidence Pipeline multi-day dry-run record 與 scheduler approval SOP 索引；標示這些是 production scheduler 前的人工 QA scaffold，不啟用 scheduler、不宣稱 alpha。
- 2026-07-02：新增 Evidence scheduled dry-run wrapper QA 與 morning check guide 索引；標示每日自動任務只做 read-only freshness check 與 evidence dry-run，working-copy smoke 預設 disabled / manual-only。
- 2026-07-02：新增 CMD wrapper + `schtasks.exe` QA 索引；標示 PowerShell `.ps1` 被 execution policy 擋住後改用 CMD 註冊，時間為每日本機 05:00 / 05:15，production confirm 仍未啟用。
- 2026-07-02：補充 Codex app read-only morning report automation 索引；標示 05:30 只彙總既有 Windows Task Scheduler / status / report，不重新執行 pipeline。
- 2026-07-04：補充 Post-V1 檔名日期判讀規則；部分里程碑檔名不作目前完成狀態權威。
- 2026-07-03：新增 V1.3 Evidence Operations design / plan 與 QA 索引，標示 weekly review、manual approval package、signal decay manual lifecycle candidates 與 action item planning 已建立；production scheduler 仍未啟用。
- 2026-07-03：新增 Decision Desk working-copy smoke follow-up QA 索引，標示 batch snapshot service-backed builder 修補後 risk-prompt / recommendation evidence 可在 working-copy confirm smoke 中保存且 idempotency passed；production scheduler 仍未啟用。
- 2026-07-03：新增 V1.4 Evidence Review History QA 索引，標示 weekly review history repository、CLI save/list 與 Research Lab 覆盤歷史子頁已建立；history 只保存人工覆盤快照，不啟用 scheduler。
- 2026-07-03：新增 weekly evidence operations + history working-copy run 紀錄索引，確認第一個 operating-cycle 仍為 `coverage_only`，需繼續累積 evidence 並修 blocking gaps。
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
- 2026-07-09：新增重複計算消除設計與實作計畫；推薦衍生特徵改為 single-source、標準預設技術指標可安全 reuse，Daily Decision Desk 改為單次 snapshot 共用 read-only 市場 frame，且排程與公開 service 介面不變。
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
- 2026-07-06：新增 `ROADMAP_6M_ENGINEERING_V1_COMPLETION_RECORD_2026_07.md` 封存索引，對齊 6M Roadmap Gate-Based Active Roadmap 重構。
- 2026-07-06：更新備份 retention audit 索引，補上 `_reference_fix` replay archive 位置與 C 槽 working-copy / QA raw output cleanup 狀態。
- 2026-07-08：新增 V3 Score Effectiveness / ML Readiness design + plan 索引，將 TotalScore 分組、fixed threshold robustness、component ablation 放在 ML 前置 gate，ML 僅作 shadow-only 第二層。
- 2026-07-08：新增 V3.0 engineering candidate manual validation report 索引，標示 V3 effectiveness read model / gap classifier / review scaffold / readiness inspector 已具工程候選驗證入口，但人工驗證仍為 `PENDING_MANUAL_VALIDATION`，不啟用 scheduler、不宣稱投資有效性。
- 2026-07-12：新增 V2.1 engineering readiness 與 formal closeout approval record 索引；`592d3db` safeguards、focused suite 與 rollback 已記錄，但 release owner 的 owner / timestamp / decision 尚未提供，因此狀態為 `awaiting_release_owner_confirmation`，不宣稱正式 closeout、投資有效性或 broker execution。





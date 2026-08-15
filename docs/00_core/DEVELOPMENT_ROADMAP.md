# DEVELOPMENT_ROADMAP（Roadmap Hub）

> **2026-07-13 系統工程整合**：A～F committed handoff 已由 G 依 SHA、ownership 與 focused suite 驗證，跨流 DTO／JSON composition、唯讀 smoke 與 pure verifier 均成立。這只代表工程整合已驗證；下一步仍是 forward evidence、逐來源人工接受與正式 ML OOS／promotion review，不是 scheduler、production automation 或 formal product closeout。
>
> **最後更新**：2026-08-14
> **工程主線**：`V3.3 Engineering Complete`，進入 `V4.0 Evidence Accumulation Track`；這不是正式 V4.0。詳見 [V3.3 Engineering Closeout](../06_qa/V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)。
> **Evidence rehearsal**：唯讀 replay / shadow 工程底座另以 `engineering_rehearsal_complete` 收口；它只提供可重跑 diagnostics 與 forward handoff，不會改寫 external Gate 狀態。見 [Evidence Rehearsal Engineering Closeout](../06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md)。
> **定位**：本文件是 Roadmap Hub，不再保存完整歷史長文。它負責指向目前狀態、6 個月工程路線、系統架構與歷史歸檔。

---

## 1. 文件權威邊界

本專案改採 **Scoped SSOT（分範圍單一真相來源）**，不再由單一 Roadmap 文件承擔所有決策、歷史與架構資訊。

| 文件 | 權威範圍 |
|---|---|
| [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) | 目前狀態、當前工作模式、本週優先事項與高風險區。 |
| [PRODUCT_ROADMAP_POST_REFACTOR.md](PRODUCT_ROADMAP_POST_REFACTOR.md) | 安全重構完成後的產品方向、bounded advice、Portfolio Coach、Exit、Evidence、Data、ML 與 pruning 的產品演進。 |
| [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) | 未來 6 個月可執行工程路線、里程碑、交付物與驗收標準。 |
| [VERSION_ROADMAP_V1_1_TO_V2_0.md](VERSION_ROADMAP_V1_1_TO_V2_0.md) | V1 release 後到 V2.0 的版本化交付節奏；作為 6M Roadmap 的 companion，不取代其權威。 |
| [VERSION_ROADMAP_V2_1_TO_V4_0.md](VERSION_ROADMAP_V2_1_TO_V4_0.md) | V2.0 之後的長期版本階梯；將 6M Roadmap Phase 2-5 與 Vision Level 1-4 映射為 V2.1-V4.0 companion，不取代 6M Roadmap 或 Vision。 |
| [EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md](EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md) | 外部開源專案參考、資料源補強優先序與 V1.5 至 V2.0 版本形狀；作為 6M Roadmap / Version Roadmap companion，不取代 Vision。 |
| [system_architecture.md](../01_architecture/system_architecture.md) | 目前系統架構、模組邊界、資料流與高風險技術邊界。 |
| [target_system_architecture.md](../01_architecture/target_system_architecture.md) | Transitional / Target Architecture、產品領域邊界、治理與決策權限；不代表目前已實作。 |
| [system_vision_specification.md](../01_architecture/system_vision_specification.md) | North Star、Product Principles、Bounded Advice、Evidence Requirements、Success Levels 與 Non-goals。 |
| [GATE_2_DATA_GOVERNANCE_CONSOLIDATION_AUDIT_2026_07_22.md](../06_qa/GATE_2_DATA_GOVERNANCE_CONSOLIDATION_AUDIT_2026_07_22.md) | Gate 2 資料治理工程收斂稽核報告、全量 SQLite 統計、13 個 P0 源狀態與 PIT 安全矩陣。 |
| [SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md](../06_qa/SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md) | 排程與日常證據可觀測性健康報告、5 大任務狀態、寫入意圖劃分與運作提示。 |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) | 文檔導航與文件所在位置，不作為功能或狀態事實來源。 |
| [GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md](../06_qa/GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md) | Gate 2–7 純工程完成後的接手入口；導向外部驗證、append-only gate revisions 與 ML 重驗流程，不取代各主題 SSOT。 |
| [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md) | 舊 Roadmap 未完成事項的逐項處置、移交月份與結案 Gate。 |
| [DEVELOPMENT_ROADMAP_LEGACY_2026_06.md](../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md) | 舊線性 Phase、歷史 Done、舊 Roadmap current section；只作追溯，不作目前狀態依據。 |

若文件描述衝突，依「該主題的權威文件」判斷；例如目前狀態看 Snapshot，未來 6 個月看 6M Roadmap，架構看 system architecture。

---

## 2. 系統定位

baldr 是一套可觀察市場、產生有條件且可追溯的結構化投資建議、建立建議 Portfolio、追蹤持倉健康與退出條件，並持續驗證自身建議是否有效的台股投資決策系統。

系統可以提供 bounded investment advice，但 `Investment Advice != Broker Execution`：不保證獲利、不自動下單、不讓黑箱 AI 或未通過 Gate 的模型修改正式決策。

目前產品已形成三個已落地的產品閉環，並新增一個未來目標閉環：

1. **資料與市場狀態閉環**：Update → SQLite 狀態 → Market Watch / Smart Money → 候選池。
2. **研究驗證閉環**：Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Promote。
3. **持倉檢查閉環**：Recommendation / Backtest → Portfolio → Condition Monitor / Chip Monitor → Journal → 回到研究。
4. **每日決策閉環（v1）**：Market Intelligence → Daily Decision Desk → Watchlist Trigger / Portfolio Alert / Research Input。此閉環已整併到主 UI 預設首頁「決策工作台 > 決策來源」，其餘 section 仍逐步補齊 providers。

---

## 3. 目前執行狀態

目前狀態以 [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) 為準。Gate 2–7 純工程完成後，後續 agent 應先讀 [Engineering Control Center](../06_qa/GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md)，再依工作類型進入 [External Validation Register](../06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md) 或 [Gate 7 ML Shadow Engineering](../06_qa/GATE_7_ML_SHADOW_ENGINEERING.md)。短版摘要如下：

- 三個產品閉環的基礎與主要深化已完成。
- Strategy & Scoring Governance 增量 A / B 與 10 檔 fixed / quantile OOS 實證已完成；交易樣本與 Regime coverage Gate 通過，quantile 未優於 fixed 並維持 opt-in。
- Phase 5 已完成圖表渲染優化、批次回測並行化、大表格分頁與 Excel 報告；PDF 仍待後續。
- Month 2 M2-A / M2-B / M2-C 與 final registry governance gate 已完成：參數與權重契約、Research Run Registry 基礎保存、Comparability Service、Registry 比較子頁、Registry-based Promote Gate、補償 / reconciliation 防線與文件收尾均已落地。
- Portfolio 已具備策略/價格監控、停損停利警示、籌碼監控與 Smart Money 下鑽。
- Month 5 Fundamental Layer v1 已完成 closeout：月營收、季度財報、P/E valuation、Fundamental provider/service、available_date gate 與 abnormal diagnostics 已落地；只輸出 factor records / diagnostics 與風險提示，不接 `ScoringEngine`。
- Post-V1 V1.5 Data Credibility & Corporate Action Gate v1 已完成：source capability registry、corporate action policy、governed microstructure metadata 與 shared evidence source coverage service 已落地；不抓外部資料、不改 `ScoringEngine`、不啟用 production scheduler。
- Post-V1 V1.6 Cross-sectional Factor Pipeline v1 已完成：daily factor snapshot DTO / repository / migration、FactorGate-backed pipeline、integer rank / quantile、concept basket available-date gate 與 read-only attribution summary CLI 已落地；不把 factor rank 當推薦、不改 `ScoringEngine`、不啟用 production scheduler。
- Post-V1 V1.7 Screening Matrix & Negative Evidence v1 已完成：Recommendation result 保存 `screening_matrix_json`、pass / fail / degraded / skipped / missing matrix、Why Not / Liquidity payload 與 screening matrix evidence events；舊 recommendation 缺 matrix / payload 時只回 diagnostic，不回補、不重算。
- Post-V1 V1.8 Portfolio Construction & Execution Trace Sandbox v1 已完成：research-only allocation service 支援等權、分數權重、inverse-volatility、max position cap、整數 bp 權重、Decimal 金額與 lot sizing；virtual trace service 產生 created / submitted / partially_filled / filled / rejected 事件；不串 broker、不寫正式資料、不啟用 scheduler。
- Post-V1 V1.9 Read-only Agent / MCP Evidence Access v1 已完成：新增 app-layer read-only evidence access service 與 `twstock-evidence-access` MCP server，可查 Evidence events/outcomes、forward summary、Research Run metadata、Portfolio Review saved evidence、permission model 與 AI report template；缺 DB / table 只回 diagnostics，不建 schema、不寫 DB、不改策略、不下單、不套用 lifecycle action。
- Pre-V2 非排程 readiness inspector 已完成：新增 read-only service / CLI 彙總 weekly history、multi-day dry-run record、source gaps 與 Agent report sample；時間型 gate 不足時維持 `waiting_for_time`，`production_scheduler_allowed=false`。
- Historical Evidence Replay v1 已完成：新增 working-copy / replay DB 專用 simulated scheduler，可依歷史交易日逐日重放 evidence pipeline，事件 metadata 標示 `historical_replay` / `simulated_scheduler`，且 recommendation result 與 forward outcome 都以 replay decision date / data-as-of date 限制；此結果只作 research evidence，不取代真實 weekly history、多日 dry-run 或 production scheduler approval。
- Phase 0A Historical Replay Evidence Quality Audit 已完成：`6eb7f8e` 修正 replay reference return lookup 後，118 trading days `_reference_fix` replay 中 ready outcomes 已全部具備 benchmark return / excess；industry return / excess 只在 2,029 個具 sector mapping 的 ready outcomes 可用，其餘保留 `DEGRADED` + `missing_industry_benchmark`。此結果可作 V2.0 Phase 1 read-only Workbench 的 evidence quality input，但不構成 production scheduler 或投資有效性 gate。
- V2.0 Phase 1 read-only Workbench prototype slice、Phase 1.5 / Phase 2 前置 formal read-only source adapter 與 Phase 2 Workbench UI / read-only operating loop 已完成：新增 `WorkbenchDashboardDTO`、read-only composer、Historical Replay JSON summary adapter、`WorkbenchSourceService`、`scripts/inspect_v2_workbench_prototype.py` prototype CLI，以及 Qt `決策工作台` read-only view / table models / 左側主導覽 integration。CLI 與 UI 都只讀 existing sources / DTO，不寫 evidence、不建立 scheduler、不下單、不套用 lifecycle action；Qt Workbench 已中文優先呈現 background evidence feed / read-only Action Items / read-only Operating Loop，並將 Daily Decision 內嵌為 `決策來源`，提供 Evidence Review / Portfolio / 市場探索 read-only drill-down。Action Items 只列人工待處理事項，保留 source trace / degraded reason / drill-down target，且不建立 repository、不寫 DB、不套用 lifecycle；2026-07-07 follow-up 已補 severity / queue group / source label 顯示、穩定排序、空 / 降級狀態文案、session-only 已查看提示與 drill-down target contract，使其更接近人工處理佇列；Phase 2C/2D 已補 `WorkbenchOperatingLoopStep`，把 daily checklist、weekly review、multi-day dry-run、manual review note 與 scheduler gate 串成只讀操作節奏。Phase 2 UI 可 closeout；V2.2 真實 evidence operating loop 與 production scheduler gate 仍待 Phase 0 真實時間證據。
- 2026-07-08 V3.0 engineering candidate closeout 輸入已補齊：score bucket audit、fixed threshold robustness、component ablation readiness、ML shadow-only contract 與 Phase 3C 三大法人 / 信用交易 / TDCC source candidate readiness dry-run 已完成工程候選；下一步是 closeout/readiness report、focused verification 與 manual validation disclosure，不是啟用 ML production、正式 ingestion 或 scheduler。
- Post-V1 V1.1 / V1.2 / V1.3 / V1.4 v1 已完成：推薦 Profile / 回放 workflow bridge、Profile replay comparison、訓練 / 獨立驗證期間、推薦回放 rolling risk、microstructure preflight、relative attribution、weekly evidence operations、manual approval package、action item planning、weekly review history 與 Research Lab 覆盤歷史子頁已落地；這些仍是 research credibility / evidence operations diagnostics，不代表投資有效性。
- 後續要提升「準確度」必須先建立實證比較、factor attribution、資料因子層與實驗治理，不應直接把新資料硬塞進 scoring engine。

---

## 4. 下一步 Next

重構完成後的產品主線以 [PRODUCT_ROADMAP_POST_REFACTOR.md](PRODUCT_ROADMAP_POST_REFACTOR.md) 為準；未來 6 個月工程以 [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) 為準；產品北極星見 [system_vision_specification.md](../01_architecture/system_vision_specification.md)，理想架構見 [target_system_architecture.md](../01_architecture/target_system_architecture.md)。

目前立即順序改為：

> **目前 Gate 7 執行軌**：Owner 已採用 prospective-only、非實盤的正式模擬持倉 clock；`2014–2026` 保留 research/history，不事後回填。`PFS-01`～`PFS-09`（clock contract／唯讀 inspector、fixture-only simulated transition producer、clock-bound HMAC Rule snapshot publisher、prospective PIT sector custody、inference-level calibration policy、capture-only readiness／heavy-rebuild guard、frozen activation contract、shadow maturity gate、frozen-candidate OOS evidence contract）均已完成 focused QA；依 [Prospective Formal Simulated Portfolio Execution Plan](../06_qa/PROSPECTIVE_FORMAL_SIMULATED_PORTFOLIO_EXECUTION_PLAN_2026_08_14.md) 下一步進入 `PFS-10` promotion review package。重型 watcher 維持停止，同一 clock 不得用已消費的 Formal OOS 期間重訓。這是 Gate 7 的執行計畫，不取代 Product／6M Roadmap，也不產生 Formal OOS 或 promotion credit。

1. Gate 0 Safe Refactor 已 closeout；維持行為等價與 rollback discipline，但不再把重構當作產品主線。
2. Gate 1 Daily Usable Advice 已 closeout：Guided / Professional 共核、`NO_NEW_POSITION`、Why / Why Not / Risk / Evidence 與 Portfolio target/current/gap 已由唯讀 contract / UI 呈現。
3. 把既有 read-only / dry-run evidence 底座推進為 Gate 2 真實 weekly review、action-item、backup / rollback / recovery 與受批准 evidence write-mode。
4. P0 資料先 diagnostics / shadow / acceptance；candidate source 不接 `ScoringEngine` 或 formal Portfolio Advice。
5. 以 Equal Weight benchmark 建立 Portfolio Coach，再做 signal effectiveness / pruning 與 thesis-based Position Health / Exit；ML 只有在 rule baseline 可判讀後才進 shadow。

以下既有 V1.1-V2.0 與 V3 engineering candidate 長文保留為歷史脈絡；如與上述 Next 衝突，以 Product / 6M Roadmap 為準。
V1 release 後的版本化交付節奏見 [VERSION_ROADMAP_V1_1_TO_V2_0.md](VERSION_ROADMAP_V1_1_TO_V2_0.md)：V1.1、V1.2、V1.3、V1.4、V1.5、V1.6、V1.7、V1.8、V1.9 v1、V2.0 Phase 1 read-only prototype slice、Workbench formal read-only source adapter 與 Phase 2 Workbench MVP shell / background evidence feed / read-only Action Items / read-only Operating Loop 已完成；Action Items 已補排序、分組、來源顯示、空 / 降級狀態與舊頁導向 contract，Operating Loop 已把 daily checklist、weekly review、multi-day dry-run、manual review note 與 scheduler gate 串成只讀節奏。multi-day dry-run 已為 `3/3 ready`；下一步不是啟用 production scheduler，也不是把 replay 當成 gate，而是繼續累積 Phase 0 weekly history、manual review note 與 action-item 節奏，讓 V2.2 的真實 evidence operating loop 由實際紀錄成立。部分 Post-V1 design / QA 檔名保留後續里程碑日期，不作為 Roadmap Hub 的完成日期權威。
V2.0 之後的版本階梯見 [VERSION_ROADMAP_V2_1_TO_V4_0.md](VERSION_ROADMAP_V2_1_TO_V4_0.md)：V2.1-V2.5 對應 Workbench 主 UI、Evidence operating loop、P0 資料源 dry-run、execution realism 與 scheduler approval gate；V3.0-V4.0 對應 Vision 的 evidence-validated decision system 與投資有效性成熟度。該文件是長期版號 companion，不提前承諾 V3/V4 已具投資有效性。
V3.0 engineering candidate 的 closeout/readiness report 已完成，工程狀態為 `ready_for_manual_validation`；近期目標改為完成 `PENDING_MANUAL_VALIDATION` 的三項人工檢視（樣本門檻、signal / alert / gate 文案、dashboard disclosure），並累積 V2.2 所需的真實 weekly evidence operations history、manual review note 與 action-item 節奏。multi-day dry-run record 已為 `3/3 ready`，但 production scheduler 仍維持 `production_scheduler_allowed=false`；不得展開新 ML production、不得把 candidate source 接入核心 score。
外部開源專案對照、資料源補強優先序與 V1.5 至 V2.0 的中繼版本形狀見 [EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md](EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md)；該文件只作參考 companion，不取代 6M Roadmap 的執行順序。

目前立即執行優先順序：

1. **已完成：Fixed / Quantile 真實 Walk-forward 實證**
   - 10 檔股票、每檔 8 個 OOS fold，資料版本、成本與成交假設固定。
   - Fixed 57 筆、quantile 79 筆交易與 100% Regime coverage 通過 Gate。
   - Quantile 未優於 fixed，維持 opt-in，不宣稱改善績效或穩健度。

2. **已完成：Month 3 Factor Layer v1 與 Portfolio Replay 可信度**
   - Month 2 Registry governance gate 已關閉。
   - Factor DTO / registry / Look-ahead gate / adapters / FactorService snapshot/contribution serialization 已落地；`ResearchRunService.save_run()` 已接入 `factor_snapshot` / `factor_contributions` 實際寫入流程，推薦組合回放、單股回測、批次回測與固定組合 per-stock 保存都能供給 factor records / metadata。
   - 推薦組合回放已具備現金帳、權重、再平衡、未成交、Liquidity、成本、整股 sizing、weight exposure 與 Gap risk labels；更細的零股、價差、完整撮合與 Gap 實際成交模型列為後續深化，不阻塞 Month 4。

3. **已完成：Month 5 Fundamental Layer v1**
   - Month 4 Daily Decision Desk v1 已以 service-backed daily workflow 收尾，UI 只讀 service snapshot，不重算 scoring、screening、portfolio、broker flow 或 liquidity。
   - Month 5 已完成 Fundamental Layer 的保守接入：正式 fundamental tables、月營收 / 季度財報 / P/E records、Fundamental provider/service、Revenue / statement / valuation adapters、available_date gate 與 diagnostics 已落地。P/B、P/S presentation policy 已採 guarded ready，只接受 governed external observations 或後續明確 backfill records；官方歷史 point-in-time 公告日仍保留為後續 residual。

4. **已完成：Month 6 Strategy Lifecycle 與 Portfolio Feedback v1**
   - 已完成第一輪資料契約與 service：Promote / demote / retire rule engine、StrategyDriftDetector、Regime compatibility、append-only lifecycle evidence、Portfolio post-trade attribution、Live vs research gap report 與 Portfolio Review snapshot。
   - Registry-based Promote Gate 已改走 Month 6 lifecycle gate，成功升級後可保存 applied evidence；demote / retire 先保存 proposed evidence；持倉管理新增「生命週期回顧」分頁。v1 不直接改 scoring、回測績效、Portfolio PnL 或 fundamental factor 權重。
   - Month 6.1 相關人工審核、Review Dashboard 與 evidence explainability 後續，已被 Post-V1 V1.3 / V1.4 evidence operations 與 history 節奏承接。

5. **已完成：Post-V1 V1.1 / V1.2 / V1.3 / V1.4 / V1.5 / V1.6 / V1.7 / V1.8 / V1.9 v1**
   - V1.1 補 workflow bridge；V1.2 補 research credibility 與 execution diagnostics；V1.3 補 weekly evidence operations 與 manual lifecycle package；V1.4 補 weekly review history 與 Research Lab 覆盤歷史子頁；V1.5 補 data credibility gate；V1.6 補 cross-sectional factor snapshot / attribution pipeline；V1.7 補 screening matrix、Why Not / Liquidity payload 與 negative evidence capture；V1.8 補 research-only portfolio construction 與 virtual execution trace sandbox；V1.9 補 read-only Agent / MCP evidence access。
   - 2026-07-03 已完成第一個 weekly evidence operations + history working-copy operating-cycle，結果仍為 `coverage_only`，blocking gaps 尚未關閉。
   - 同日 follow-up 已修正 batch / CLI Daily Decision Desk snapshot wiring 與 numpy scalar JSON 序列化；working-copy confirm smoke 可寫入 `risk_prompt` evidence 且 repeat=2 idempotency passed。受控 tmp run 也已保存 working-copy Recommendation result，並驗證 `recommendation,risk-prompt` requested sources 可 idempotent confirm。`decision_desk_snapshot_missing`、`recommendation_persisted_missing` 與 `working_copy_confirm_smoke_missing_or_failed` 已收斂為真實 source gaps。
   - 目前下一步是繼續用 weekly evidence operations + history 累積多週覆盤證據，並用真實 workflow 補齊 watchlist 無項目與 portfolio 無 active positions；舊 recommendation 缺 screening matrix / exclusion payload 時仍只診斷、不回補、不重算。production scheduler 仍未啟用；V2.0/V2.1 Workbench 已有 Phase 1 read-only prototype slice、formal read-only source adapter、Phase 2 Qt MVP shell、舊頁 read-only drill-down、排序後 Action Items 人工佇列與 read-only Operating Loop。multi-day dry-run 已為 `3/3 ready`，但 V2.2 evidence operating loop 的 weekly history、manual review note 與 action-item 節奏仍需真實時間與真實流程累積。

6. **P1：V2.0 前置補強**
   - V1.5 Data Credibility & Corporate Action Gate、V1.6 Cross-sectional Factor Pipeline、V1.7 Screening Matrix & Negative Evidence、V1.8 Portfolio Construction / Execution Trace Sandbox 與 V1.9 Read-only Agent / MCP Evidence Access 已完成 v1。
   - 2026-07-06 已補 `scripts/inspect_pre_v2_readiness.py` / `PreV2ReadinessService`，可唯讀彙總 weekly history、multi-day record、source gaps 與 read-only Agent report sample；它只把非排程前置條件變成可重跑檢查，不解除多週 / 多日 / manual smoke / true workflow sample 門檻。
   - 2026-07-06 follow-up 已完成非時間型 closeout：Git unreachable loose objects 清為 0、Recommendation liquidity payload gap 修正、working-copy all-source source coverage `blocking_gaps=[]`、working-copy confirm smoke repeat=2 idempotency passed、Evidence Review UI smoke passed、read-only Agent report sample ready。正式 evidence DB 未寫入；驗證只在 working-copy DB 與 ignored output mirror 內完成。
   - 2026-07-06 Historical Evidence Replay v1 已補 `scripts/replay_historical_evidence_pipeline.py` 與 `HistoricalEvidenceReplayService`，可把 source DB 複製成 replay DB 後逐交易日重放 runner；缺 as-of recommendation result 時只記錄 diagnostic 並略過 recommendation 類來源，不用未來 result 補值。
   - 2026-07-06 Phase 0A replay quality audit 已完成，benchmark 全缺已解除；V2.0 Phase 1 read-only Workbench prototype slice 已可用 `_reference_fix` replay JSON summary 顯示 source gap、payload gap、event family、outcome maturity 與 quality boundary，不顯示成策略績效結論。
   - Phase 2 前的 background evidence / formal read-only source adapter 已完成第一版：`WorkbenchSourceService` 可讀受控 `--db-path` 的 Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary 與可選 replay JSON summary；Phase 2 Qt MVP 已接入主 UI，中文優先呈現 status strip、今日待判讀、background evidence feed、read-only Action Items、read-only Operating Loop、Evidence mode / data quality、Daily Checklist 與 warnings / degraded source，並提供 Daily Decision / Evidence Review / Portfolio read-only drill-down。Action Items 只列人工待處理事項，保留 source trace / degraded reason / drill-down target，且不建立 repository、不寫 DB、不套用 lifecycle；目前已依 severity / queue group / source label 排序並顯示來源，空狀態與降級狀態會保留只讀、非建議、不補值語氣。Operating Loop 只用 DTO payload 顯示今日要看、人工處理、等待真實時間累積、manual review note 與 scheduler gate，不寫 DB、不標記完成。若預設 `_reference_fix` replay JSON summary 存在，Workbench 會揭露 market benchmark coverage 380,736/380,736、industry benchmark coverage 2,245/380,736、pending future-data 91,488 與 screening matrix source gap 118/118 days；這只代表方向性 evidence input，不解除 Phase 0 或 scheduler gate。V2.2 evidence operating loop 與 scheduler approval 仍需後續 gate。
   - 進入 V2.0 前仍需真實時間累積：multi-day dry-run record 已為 `3/3 ready`，Week 1 已完成，weekly evidence operations + history 實際紀錄目前為 `1/3 waiting_for_time`。若要推 production scheduler，仍需 Week 2 / Week 3、explicit design / approval / rollback 文件；目前 `production_scheduler_allowed=false`。
   - `cuFOLIO`、強化學習、券商自動下單與 SQLite async / split DB 暫不納入近期 Roadmap，除非有量測證據顯示現有計算或寫入模式成為真實瓶頸。

7. **P2：Phase 5 研究輸出後續**
   - PDF 規格化報告仍待後續，屬研究輸出 backlog，不阻塞 Month 3 / Month 4。

8. **P3：文件治理持續檢查**
   - Snapshot、6M Roadmap、V2.1-V4.0 Roadmap、Architecture、Index、Agent 指引已採 Scoped SSOT；後續功能變更需依 Coverage Map 同步更新入口摘要。
   - `docs/05_phases/` 已降格為 Historical / Reference；後續若要搬移或刪除，需先修正引用並保留回滾路徑。

---

## 5. Blockers / Risks

- **回測與推薦不可宣稱更準**：真實 walk-forward 已完成，但結果未證明 quantile 優於 fixed。
- **Look-ahead bias**：任何策略、回測、推薦、factor、benchmark、停損停利與標準化改動都必須先自查資料可得日。
- **金融核心數值邊界**：核心金額、交易成本、倉位、PnL 與風控不可新增裸 `float`；必須使用 `Decimal`、整數單位或明確標示的 analytics / visualization 邊界。
- **資料因子擴充風險**：營收、財報、三大法人、估值與籌碼因子必須走 factor layer，不得直接污染既有 scoring engine。
- **Daily Decision Desk 降級顯示風險**：Daily Decision Desk v1 已完成 Month 4 收尾，但各 section 仍可能因 provider 缺值降級為 `MISSING` / `DEGRADED`；文件與 UI 必須持續揭露 quality / warnings，不得誤導為資料永遠完整。
- **文件權威混淆**：Roadmap Hub 只指向權威文件；不要把完整歷史、架構細節與長期研究筆記重新塞回本文件。

---

## 6. 歷史與追溯

- 舊版完整 Roadmap 已歸檔至 [DEVELOPMENT_ROADMAP_LEGACY_2026_06.md](../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md)。
- 舊 Roadmap 未完成事項的唯一處置見 [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md)。
- 已執行完畢的短期行動計畫見 [NEXT_ACTION_PLAN.md](../09_archive/NEXT_ACTION_PLAN.md)。
- 文檔重組與刪除規則見 [DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md)。
- `docs/05_phases/` 目前保留為 Historical / Reference 區，用於追溯 Phase 2 / Phase 3.3b / Phase 3.5 / Phase 4 的設計與 SOP；其中的「下一步」「進行中」「Phase Gate」不作目前 roadmap 或優先順序依據。

---

## 7. 更新記錄

- 2026-07-12：Gate 0 / Gate 1 已 closeout；Hub 的 Next 改為 Gate 2 Real Evidence → Gate 3 P0 Data → Portfolio / Pruning / Exit，Gate 1 證據見 `GATE_1_ADVICE_CLOSEOUT_2026_07_12.md`。
- 2026-07-11：加入 Post-Refactor Product Roadmap、Target Architecture 與新版 Vision 權威入口；Next 改為 Gate 0 closeout → Daily Advice → Real Evidence → P0 Data → Portfolio / Pruning / Exit，ML 維持 shadow-first。
- 2026-07-08：同步 V3.0 engineering candidate closeout 目標；score effectiveness / ML readiness bridge 與 Phase 3C source candidate readiness 已完成工程輸入，夜間排程應轉為 closeout 驗證與文件 / QA 一致性，不啟用 scheduler 或 production ML。
- 2026-07-07：完成 Workbench 左側主導覽 IA；Qt 主 UI 預設進入 read-only `決策工作台`，8 個主工作區改由左側導覽切換，`每日決策` 內嵌為 `決策工作台 > 決策來源`，`市場觀察` 改名為 `市場探索`。Workbench 只透過 `WorkbenchSourceService` / `WorkbenchDashboardDTO` 呈現 status strip、今日待判讀、Evidence mode / data quality、Daily Checklist 與 warnings / degraded source。Phase 0 weekly history `0/3`、multi-day dry-run `1/3` 與 Phase 5 scheduler gate 不變。
- 2026-07-07：補充 Phase 2 Workbench background evidence feed / read-only Action Items MVP；背景證據流只彙整 Daily Decision snapshot、Evidence Review readiness、Portfolio alerts 與 replay summary diagnostics，Action Items 每列保留 source trace / degraded reason / drill-down target，且不建立 repository、不寫 DB、不改 lifecycle。
- 2026-07-07：推進 Workbench Action Items 人工佇列體驗；DTO / composer / Qt model 補 severity、queue group、source label、sort rank、空 / 降級狀態文案與 drill-down target contract，仍只讀 `WorkbenchDashboardDTO` payload，不寫 DB、不啟用 scheduler、不產生建議。
- 2026-07-07：完成 Phase 2C/2D Workbench read-only operating loop 與 closeout 同步；新增 `WorkbenchOperatingLoopStep` / Qt 操作節奏表，將 daily checklist、weekly history、multi-day dry-run、manual review note 與 scheduler gate 串成只讀節奏，Phase 2 UI 可收口，但 Phase 0 `0/3`、multi-day `1/3` 與 V2.2 真實 evidence operating loop 仍需時間累積。
- 2026-07-06：新增 V2.1 至 V4.0 長期版本路線圖入口，將 V2.0 後 Phase 2-5 與 Vision Level 1-4 對應為 companion 版號階梯；Roadmap Hub 仍只作入口，不改 6M Roadmap 權威。
- 2026-07-06：完成 V2.0 Phase 1 read-only Workbench prototype slice；當時新增 DTO、composer、historical replay summary adapter、sample CLI 與 QA closeout，邊界是不寫 evidence、不啟用 scheduler、不產生交易建議。
- 2026-07-06：完成 V2.0 Workbench formal read-only source adapter；`inspect_v2_workbench_prototype.py` 可由 `--sample` 擴充到受控 `--db-path` / `--decision-date`，讀取 Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary 與可選 replay JSON summary；missing DB / table 只回 diagnostics，不寫 DB、不解除 Phase 0 / Phase 5 gate。
- 2026-07-06：新增 Historical Evidence Replay v1，定位為 research-only simulated scheduler；可輔助 Phase 0 source gap / V2.0 設計觀察，但不替代真實時間 gate 或 production scheduler approval。
- 2026-07-06：完成 Phase 0A Historical Replay Evidence Quality Audit，修正 replay benchmark reference return 全缺；`_reference_fix` replay 可作 V2.0 Phase 1 Workbench 參考輸入，industry / screening matrix 仍是 payload gap，production scheduler gate 不變。
- 2026-07-06：完成 Pre-V2 非時間型 closeout：readiness inspector、source gap working-copy all-source smoke、Evidence Review UI smoke 與 read-only Agent report sample 已可重跑驗證；多週 / 多日 / scheduler approval 門檻仍未解除。
- 2026-07-05：完成 V1.6 Cross-sectional Factor Pipeline v1，factor rank / quantile 只作研究 attribution，不改 `ScoringEngine`、不啟用 scheduler；後續由 V1.7 Negative Evidence 承接。
- 2026-07-05：完成 V1.7 Screening Matrix & Negative Evidence v1，當時 Roadmap Hub 下一步改為 evidence accumulation + V1.8 / V1.9 準備；screening matrix 與 Why Not / Liquidity payload 只作研究追溯，不改 `ScoringEngine`、不回補舊結果、不啟用 scheduler。
- 2026-07-05：完成 V1.8 Portfolio Construction & Execution Trace Sandbox v1，Roadmap Hub 下一步改為 evidence accumulation + V1.9 準備；portfolio sandbox 只作研究配置與虛擬 execution trace，不串 broker、不寫正式資料、不啟用 scheduler。
- 2026-07-06：完成 V1.9 Read-only Agent / MCP Evidence Access v1，Roadmap Hub 下一步改為 V2.0 前置補強；Agent 只能讀 evidence / source trace / quality / warnings，不寫 DB、不改策略、不下單、不套用 lifecycle action。
- 2026-07-04：新增外部專案參考與未來版本藍圖 companion 入口，確認 Vision 不大幅改寫；Roadmap Hub 只保留連結與短版 V1.5-V1.9 方向，完整外部專案對照與 deferred 技術邊界移至 `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`。
- 2026-07-04：完成 V1.5 Data Credibility & Corporate Action Gate v1，當時 Roadmap Hub 下一步改為 evidence accumulation + V1.6/V1.7 準備；production scheduler、外部資料 ingestion 與投資有效性結論仍未啟用。
- 2026-06-13：將 Roadmap 從單一最高權威文件重構為 Roadmap Hub；引入 Scoped SSOT，新增 6 個月工程 Roadmap，並將舊 Roadmap 完整歸檔。
- 2026-06-13：新增 Legacy Carryover Matrix，逐項承接舊 Roadmap 未完成事項並設定 Month 3 前結案 Gate。
- 2026-06-15：依 baldr 願景重排 Roadmap Hub 的短版 Next，將 Month 3 補強為 Factor Layer + Portfolio Replay 可信度，並將 Daily Decision Desk 明確列為 Month 4 v1 首頁，其他 section 逐步接線。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾定位，將短版 Next 轉向 Month 5 Fundamental Layer preflight，並保留 Daily Decision Desk quality / warnings 降級風險。
- 2026-06-17：完成 Month 5 Fundamental Layer v1 closeout，Roadmap Hub 的短版 Next 進入 Month 6 Strategy Lifecycle 與 Portfolio Feedback。
- 2026-06-17：啟動並完成 Month 6 Strategy Lifecycle / Portfolio Feedback v1，新增 lifecycle gate、drift detector、post-trade attribution、Portfolio Review snapshot 與持倉管理生命週期回顧分頁。
- 2026-06-17：補上 Month 6 lifecycle residual，新增 append-only lifecycle evidence、latest state projection 與 demote / retire proposed evidence 保存。
- 2026-06-17：將 Roadmap Hub 的 Month 6 Next 改為 v1 已完成後的深化路線，聚焦人工審核流程、Review Dashboard、Evidence Explainability 與 QA Checklist。
- 2026-06-17：補上 P/B / P/S valuation policy residual，確認 P/B / P/S 只走 governed external observation / future backfill presentation boundary，不進 ScoringEngine。
- 2026-07-02：新增 V1.1 至 V2.0 版本路線圖入口，將 Post-V1 主線拆為 V1.1 workflow bridge、V1.2 research credibility、V1.3 evidence operations 與 V2.0 Unified Decision Workbench 評估。
- 2026-07-03：完成 V1.3 Evidence Operations & Manual Lifecycle v1，Roadmap Hub 下一步轉為實際使用 weekly evidence operations 累積覆盤證據。
- 2026-07-03：完成 V1.4 Evidence Review History v1，Roadmap Hub 下一步轉為實際使用 weekly evidence operations + history 累積多週覆盤證據。
- 2026-07-03：整理 roadmap / docs / phase 判讀邊界，確認 `docs/05_phases/` 保留為 Historical / Reference，不作目前 roadmap。
- 2026-07-03：完成第一個 weekly evidence operations + history working-copy run，確認 history idempotency；結果仍為 `coverage_only`，production scheduler 維持未啟用。
- 2026-07-03：修正 batch / CLI Daily Decision Desk snapshot wiring 與 numpy scalar JSON 序列化；working-copy confirm smoke 可寫入 risk-prompt evidence 且 repeat=2 idempotency passed；受控 tmp run 已保存 working-copy Recommendation result，剩餘 blockers 收斂為 exclusion payload / watchlist / portfolio source gaps。

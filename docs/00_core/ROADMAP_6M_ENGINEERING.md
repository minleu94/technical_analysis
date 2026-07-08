# Active 6M Roadmap v2 (Gate-Based)

> **最後更新**：2026-07-08
> **定位**：本文件是未來 6 個月工程執行與研究能力成長的權威路線圖。本文件已重構為 Gate-based 結構，不再保留完成流水帳。
> **版本 companion**：V2.0 之後若需要版號判讀，請看 [VERSION_ROADMAP_V2_1_TO_V4_0.md](VERSION_ROADMAP_V2_1_TO_V4_0.md)。該文件只把本 Roadmap 的 Phase gate 映射為 V2.1-V4.0 產品階梯，不取代本文件的工程順序與驗收標準。
> **歷史紀錄**：V1 (Month 1-6 與 V1.1-V1.9) 的詳細完工細節已封存至 [ROADMAP_6M_ENGINEERING_V1_COMPLETION_RECORD_2026_07.md](../09_archive/ROADMAP_6M_ENGINEERING_V1_COMPLETION_RECORD_2026_07.md)。

---

## 1. Completed Baseline (V1)

截至 2026-07，系統已完成以下工程底座（皆已完成 v1 closeout，目前處於 read-only / dry-run 模式）：
- **核心閉環**：資料與市場狀態、研究驗證、持倉檢查、Daily Decision Desk (V1)。
- **治理防線**：Research Run Registry、Strategy Lifecycle rule engine、Portfolio Feedback。
- **Post-V1 增量**：
  - V1.1: Decision Workflow Integration (Profile replay comparison)
  - V1.2: Research Credibility (rolling risk, microstructure preflight, attribution)
  - V1.3: Evidence Operations & Manual Lifecycle
  - V1.4: Evidence Review History
  - V1.5: Data Credibility & Corporate Action Gate (Registry & Policy)
  - V1.6: Cross-sectional Factor Pipeline
  - V1.7: Screening Matrix & Negative Evidence
  - V1.8: Portfolio Construction & Execution Trace Sandbox
  - V1.9: Read-only Agent / MCP Evidence Access
  - Historical Evidence Replay v1: research-only simulated scheduler replay
  - V2.0 Phase 1 read-only Workbench prototype slice: DTO / composer / replay summary adapter / sample CLI / formal read-only source adapter
  - V2.1 / Phase 2 Workbench MVP shell: PySide6 read-only `決策工作台` view / table models / main-tab integration backed only by `WorkbenchSourceService` / `WorkbenchDashboardDTO`，並具備排序後 read-only Action Items 人工佇列與 Operating Loop 操作節奏。

---

## 2. Active Roadmap Phases

目前的開發主線已從「功能補齊」轉向「證據累積與決策驗證」。所有 Phase 的推進必須嚴格遵守 Gate 條件。

### 2026-07-08 Planning Note：Score Effectiveness before ML

V3.0 engineering candidate 已能提供 read-only effectiveness scaffold，但下一步不應直接跳到 ML 或 V4/V5 命名。Phase 0 的資料可信度與 daily evidence 排程，正是為了累積可驗證的真實 evidence；這些 evidence 先要拿來回答 score 是否有效，而不是立即訓練模型。

今晚以 `V3 score effectiveness audit + ML readiness bridge` 作為 active milestone 候選：

- **Score bucket audit**：依 `TotalScore` raw bucket (`0-40`, `40-50`, `50-60`, `60-70`, `70-80`, `80-100`) 檢視 forward return、max drawdown、win rate 與 benchmark / industry excess。
- **Fixed threshold robustness**：測 buy / sell score、confirmation days、cooldown days 的鄰近矩陣，辨識 stable / fragile / inconclusive，而不是找單一最佳參數。
- **Component ablation**：拆 technical、pattern、volume 及其組合，判斷哪些元件有貢獻；若舊 evidence 缺 component score，先標示 payload gap。
- **ML readiness bridge**：只定義 feature / label / split / calibration / meta-labeling / ranking 的 shadow-only contract；不得訓練 production model 或改推薦決策。

Gate：若 score bucket、threshold robustness 或 component ablation 仍不可判讀，ML 只能維持 diagnostics-only，不得進入 production roadmap。

### Phase 0：Evidence Accumulation Gate
**目標**：累積真實使用數據與多日穩定紀錄，證明流程無害且有觀察價值。
- **門檻要求**：
  - weekly history 必須達到至少 3 次（目前 `0/3`）。
  - multi-day dry-run 必須累積紀錄（2026-07-08 補入修正後歷史觀察日後，record 為 `3/3`；仍需保留 report / latest_status 來源與人工判讀註記）。
- **輔助工具**：Historical Evidence Replay 可用 working-copy / replay DB 從歷史交易日逐日重放 Evidence Pipeline，並把事件 metadata 標成 `historical_replay` / `simulated_scheduler`；它只能幫助找 source gap、payload gap 與 V2.0 設計問題，不計入 weekly history。multi-day dry-run 若採修正後歷史觀察日，必須有同日或指定觀察日 dry-run report / scheduled latest_status 作為 read-only 證據，且不得寫正式 DB。
- **輔助工具**：`scripts/inspect_simulated_phase_progress.py` 可把 replay summary 與 scheduled dry-run latest status 彙整成 simulated Phase 0-5 rehearsal；所有 replay-derived evidence 必須保留 `official_gate_credit=false` 與 `requires_real_world_validation=true`，不得標成 official completion。
- **限制**：Production scheduler 繼續維持 `false`，不寫入正式資料，不進行自動交易。

### Phase 0A：Historical Replay Evidence Quality Audit
**狀態**：2026-07-06 已完成 reference return blocker closeout，可作為 V2.0 Phase 1 的 simulated evidence input。
- **已驗證產品**：
  - `historical_replay_2026-01-06_2026-07-06_reference_fix.json` / `.md` / replay DB 已產生，cleanup 後封存於 `D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/`。
  - rerun 範圍為 2026-01-06 至 2026-07-06，共 118 個交易日。
  - replay events `118,056`，outcomes `472,224`。
  - ready outcomes `380,520`；benchmark return / excess 已補齊 `380,520 / 380,520`。
  - industry return / excess 只有 `2,029 / 2,029`，其餘 ready outcomes 保持 `DEGRADED` + `missing_industry_benchmark`，原因是舊 recommendation payload 大多沒有 sector / industry。
  - `source_missing_screening_matrix` 仍為 `118/118` days；這是舊推薦 payload 真缺口，不回補、不重算。
- **結論**：
  - benchmark 全缺已解除，raw forward return 與 benchmark excess 可作 V2.0 evidence quality / maturity 參考。
  - industry excess 只能在 sector 可映射樣本中使用；Workbench 必須清楚揭露 missing industry payload。
  - 此 closeout 不代表策略有效、不代表 Phase 0 真實時間 gate 完成、不代表 production scheduler 可啟用。

### Phase 1：V2.0 Unified Decision Workbench Design Spike
**狀態**：2026-07-06 已完成 read-only prototype slice 與 formal read-only source adapter；2026-07-07 已接入 Phase 2 Qt read-only MVP shell，後續 Phase 2C / 2D 已把 read-only Operating Loop 收口。V2.2 真實 evidence operating loop 仍需 Phase 0 真實時間證據。
**目標**：在不改動主 UI 且不新增交易能力的前提下，探索 V2.0 資訊架構。
- **工作範圍**：
  - 只做資訊架構 (Information Architecture) 與 Read-only Prototype。
  - 梳理決策畫面動線，確認 Daily Decision、Evidence Review 與 Market Watch 合併後的呈現。
  - 可讀取 Phase 0A 的 `_reference_fix` replay summary 作為 source gap、payload gap、event family、outcome maturity 與 data quality 的參考輸入；不得把 replay 包裝成 production readiness 或策略績效結論。
  - 已落地 `WorkbenchDashboardDTO`、read-only composer、replay JSON summary adapter、`WorkbenchSourceService` 與 `scripts/inspect_v2_workbench_prototype.py`；CLI 保留 `--sample`，並可用受控 `--db-path` / `--decision-date` 讀取 Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary 與可選 replay JSON summary，輸出 JSON / Markdown 的今日待判讀、Evidence mode、Daily Checklist 與 read-only access boundary。
- **限制**：不新增交易能力，不改動生產環境 UI；adapter 只讀 existing sources，missing DB / missing table / degraded source 只回 diagnostics，不建立 schema、不寫 evidence、不建立 scheduler、不套用 lifecycle action。

### Phase 2：V2.0 Workbench MVP
**狀態**：2026-07-07 已完成 read-only MVP shell、中文優先顯示、預設 replay JSON summary 分析、舊 Daily Decision / Evidence Review / Portfolio read-only drill-down、background evidence feed / read-only Action Items MVP、Action Items 的 severity / queue group / source label 排序顯示與空 / 降級狀態文案，以及 Operating Loop 操作節奏；Phase 2 UI / read-only operating loop 可 closeout，V2.2 真實 evidence operating loop 仍待 Phase 0 gate。
**目標**：建立單一決策入口。
- **工作範圍**：
  - 已落地 PySide6 `決策工作台` 分頁，呈現 status strip、今日待判讀、背景證據流、只讀 Action Items、Evidence mode / data quality、Daily Checklist、warnings / degraded source。
  - UI 只讀 `WorkbenchDashboardDTO`，或透過 `WorkbenchSourceService.inspect()` 取得 payload；UI 不直接讀 SQLite、不讀 replay DB、不寫 DB、不啟用 scheduler。
  - Background evidence feed 只彙整既有 DTO / service payload：Daily Decision snapshot、Evidence Review readiness、Portfolio alerts 與可選 replay summary diagnostics。
  - Read-only Action Items 只顯示人工待處理事項；每列必須保留 source trace、degraded reason、drill-down target、severity、queue group、source label 與 `write_intent=false`，並以穩定 sort rank 排序，不建立 repository、不寫 DB、不改 lifecycle。
  - Read-only Operating Loop 只顯示 DTO-derived 操作節奏：每日先看、人工處理佇列、weekly review history、multi-day dry-run、manual review note 與 scheduler gate；每列必須保留 source trace、linked item ids、drill-down target 與 `write_intent=false`，不標記完成、不寫 DB、不改 lifecycle。
  - Evidence Feed 與 Action Items 必須有空狀態 / 降級狀態文案；空狀態不得被解讀為 gate 通過，降級狀態不得補值或觸發 replay / pipeline。
  - 若 payload 帶 Historical Replay JSON summary，Evidence mode / data quality 必須揭露 `simulated_scheduler`、source gap / coverage、payload gap、outcome maturity、benchmark coverage、industry benchmark coverage、missing industry benchmark 與 pending future-data；replay 不得用來滿足 Phase 0 gate。
  - 已將 Daily Decision Desk、Evidence Review、Portfolio Review 轉為 Workbench read-only drill-down，仍只切到既有頁面，不寫 DB、不跑 scheduler。
  - Phase 2 已把 feed / Action Items 與 weekly review、multi-day dry-run、manual review note 串成 read-only UI operating loop；後續 V2.2 仍需真實 weekly / multi-day / manual review evidence 讓節奏可重複。
- **限制**：Workbench MVP 不重算 scoring / recommendation / portfolio / backtest / lifecycle，不輸出買賣建議，不解除 Phase 0 weekly history `0/3`、multi-day dry-run `1/3` 或 Phase 5 scheduler gate。

### Phase 3：P0 Data Source Candidate Dry-run

### Phase 3：P0 Data Source Candidate Dry-run
**狀態**：2026-07-07 已完成 Phase 3A (Corporate Action) 與 Phase 3B (Trading Restriction) Candidate Dry-run，實作 `CorporateActionPolicy` 與 `TradingRestrictionPolicy`，完善 missing DB 安全降級，並將 forward outcome 降級標記與 Portfolio Sandbox 的 rejected taxonomy (如 `rejected_price_limit_locked`, `rejected_trading_restricted`) 串接。
**目標**：引入使研究更真實的關鍵資料，但初期僅作候選測試。
- **工作範圍**：
  - 微結構資料（處置股、分盤交易、全額交割、漲跌停鎖死）。
  - Corporate action 與 PIT fundamental release date。
- **限制**：先維持 candidate-only 與 dry-run，不直接覆寫決策特徵 (ScoringEngine)，不重算歷史證據。

### Phase 4：Execution Model Realism
**狀態**：2026-07-07 已完成 research-only sandbox 買賣價差 (Taiwan stock tick slippage) 與零股 / rejected taxonomy 閉環 (Phase 4 Extension)。
**目標**：讓回測與沙盒配置更貼近真實市場限制。
- **工作範圍**：
  - 導入買賣價差 (Bid-ask spread)、零股限制、跳空實際成交價模型與完整委託簿撮合。
- **限制**：先在 research-only 的 Portfolio Sandbox 中驗證，不串接 Broker 下單。

### Phase 5：Scheduler Approval Gate
**目標**：真正啟用全自動寫入排程。
- **門檻要求**：
  - 只有在前面 Phase 0 證據足夠。
  - Rollback / backup 機制完備。
  - 取得明確的 Manual Approval。
- **放行**：進入 write-mode，開啟 Production Scheduler。
- **目前補充**：2026-07-07 已完成 simulated Phase 5 approval rehearsal package，可先檢查 approval checklist、source candidate backlog、execution realism backlog 與 scheduler risk register 草案；但 official Phase 5 仍 blocked，必須等待 weekly history `3/3`、multi-day dry-run `3/3`、真實 manual review/action item rhythm、backup / rollback / recovery evidence 與 explicit manual approval。

---

## 2.1 Phase 與長期版號對照

本節只作版本 companion 對照；工程執行仍以本文件 Phase gate 為準。

| 6M Phase | 候選版號 | 對應產品意義 |
|---|---|---|
| Phase 1 | V2.0 | Unified Decision Workbench read-only prototype 與 source adapter。 |
| Phase 2 | V2.1 | Workbench 主 UI MVP；read-only shell 已接 Qt，中文顯示、replay summary 分析、舊 Tab drill-down、background evidence feed、排序後 read-only Action Items 人工佇列、空 / 降級狀態文案與 read-only Operating Loop 已完成，可 closeout。 |
| Phase 0 + Phase 2 | V2.2 | Evidence Operating Loop，讓 weekly review、multi-day dry-run、manual review 與 action item 形成可重複節奏。 |
| Phase 3 | V2.3 | P0 Data Source Candidate Dry-run，先候選測試 microstructure、corporate action 與 PIT release date，不直接進 `ScoringEngine`。 |
| Phase 4 | V2.4 | Execution Model Realism，在 research-only sandbox 驗證買賣價差、零股、跳空與未成交原因。 |
| Phase 5 | V2.5 | Production Evidence Scheduler Approval，只開 evidence write-mode scheduler，不代表自動交易。 |
| Phase 0-5 之後 | V3.0 / V3.3 / V4.0 | V3 先驗證 score / signal / alert / gate 是否有用；ML 只可在 V3.0 score effectiveness gate 可判讀後作 V3.3 shadow layer；V4.0 仍需長期 evidence，不屬目前 6M 直接交付承諾。 |

---

## 3. 驗證規則

- **文件同步**：所有功能或政策修改，必須依據 `DOC_COVERAGE_MAP.md` 同步更新相關手冊。
- **金融邊界**：策略、回測、推薦修改，必須通過 no-look-ahead 自查與 pytest gate。金融核心數值必須維持 `Decimal` 或整數，不得新增裸 `float`。
- **資料可信度**：Daily Decision 與各儀表板需明確揭示 provider 的 quality (如 `DEGRADED`, `MISSING`)。
- **排程與自動化**：在通過 Phase 5 Gate 之前，嚴禁啟用 Production Write-mode Scheduler 或自動發送真實交易委託。
- **ML 邊界**：任何 ML 規劃必須先通過 score effectiveness / threshold robustness / component ablation 的 evidence gate；ML 輸出只能 shadow-only，不得直接改推薦、策略 lifecycle、portfolio 或 scheduler。

---

## 4. 更新記錄

- 2026-07-08：新增 `V3 score effectiveness audit + ML readiness bridge` planning note；把 ML 放在 score bucket audit、fixed threshold robustness 與 component ablation 之後，且只允許 shadow-only contract，不改推薦或 production scheduler。
- 2026-07-07：完成 Phase 3A / Phase 3B Corporate Action & Trading Restriction Candidate Dry-run；新增 `CorporateActionPolicy` 與 `TradingRestrictionPolicy`，將 forward outcome 附加 `gap_detected` warning 並降級為 `DEGRADED`。Sandbox 可透過 policy 將限制轉譯為 `rejected_price_limit_locked` 或 `rejected_trading_restricted`，完善 Phase 4 的 rejected taxonomy。此為 candidate-only 觀察層，不改分數、價格，缺表時安全 fallback 為 `source_not_ingested`。
- 2026-07-07：完成 Phase 4 Execution Model Realism Extension；在 Portfolio Sandbox 中實作台股跳動單位 (Tick) 滑價模型，並完整閉環零股限制 (Lot Sizing) 與拒絕原因 (Rejected Taxonomy)，現在歷史回放可忠實反映買賣價差摩擦與不可成交訂單。
- 2026-07-07：完成 Phase 2 Workbench MVP shell 並補上 background evidence feed / read-only Action Items MVP；新增 PySide6 read-only `決策工作台` view / table models / main-tab integration，資料只經 `WorkbenchSourceService` / `WorkbenchDashboardDTO`，Action Items 只列人工待處理事項並保留 source trace / degraded reason / drill-down target，不建立 repository、不寫 DB；Evidence mode / data quality 揭露 replay JSON summary 的 simulated scheduler、source gap、payload gap、outcome maturity、benchmark coverage、missing industry benchmark 與 pending future-data 限制；Phase 0 weekly history `0/3`、multi-day dry-run `1/3` 與 Phase 5 scheduler gate 不變。
- 2026-07-07：新增 V2.2 simulated phase progress 與 Phase 5 approval rehearsal package；historical replay 可演練到 simulated Phase 5，但 official completion 仍需等待 weekly history `3/3`、multi-day dry-run `3/3`、manual review/action item rhythm、source acceptance、execution realism acceptance、backup / rollback / recovery 與 explicit approval。
- 2026-07-07：推進 Workbench Phase 2 operating-loop queue 體驗；Action Items 新增 severity / queue group / source label 顯示、穩定排序、空 / 降級狀態文案與 drill-down target contract，仍維持 read-only DTO payload、不寫 DB、不啟用 scheduler、不產生買賣建議。
- 2026-07-07：完成 Workbench Phase 2C/2D read-only operating loop 與 closeout；新增 DTO-derived Operating Loop 操作節奏，串接 Evidence Feed、Action Items、Daily Checklist、weekly history、multi-day dry-run、manual review note 與 scheduler gate，Phase 2 UI 可收口；Phase 0 weekly history `0/3`、multi-day dry-run `1/3` 與 V2.2 evidence operating loop gate 不變。
- 2026-07-06：補上 `VERSION_ROADMAP_V2_1_TO_V4_0.md` 作為 V2.0 之後的版本 companion，並新增 Phase-to-version 對照；本文件仍保留 gate-based 工程權威。
- 2026-07-06：完成 V2.0 Phase 1 read-only Workbench prototype slice；已落地 DTO、composer、replay JSON summary adapter、sample CLI 與 focused tests，Phase 2 主 UI、Phase 0 真實時間 gate 與 Phase 5 scheduler gate 仍未完成。
- 2026-07-06：完成 Workbench formal read-only source adapter；CLI 可從 `--sample` 擴充到受控 `--db-path` / `--decision-date`，只讀既有 evidence / readiness / Agent summary / optional replay JSON，不寫 DB；Phase 0 weekly history `0/3`、multi-day dry-run `1/3` 與 Phase 5 scheduler gate 不變。
- 2026-07-06：完成 Phase 0A Historical Replay Evidence Quality Audit closeout；`ForwardPerformanceService` reference lookup 已修正 missing benchmark 預設 TAIEX、market index `收盤價` fallback 與保守 industry sector mapping。新 `_reference_fix` replay 產物確認 benchmark return / excess 全部填入 ready outcomes，industry 大量缺值保留為 payload gap；此項解除 V2.0 Phase 1 read-only design spike 的 replay input blocker，但 Phase 0 真實時間 gate 與 Phase 5 scheduler gate 仍未完成。
- 2026-07-06：新增 Historical Evidence Replay v1 作為 Phase 0 的 research-only simulated scheduler 輔助工具；可在 working-copy / replay DB 逐日重放歷史 evidence，但不取代 weekly history `0/3`、multi-day dry-run `1/3`、manual approval 或 Phase 5 production scheduler gate。
- 2026-07-06：重構為 Gate-Based Active Roadmap，將 V1 / Month 1-6 / V1.1-V1.9 的詳細完工紀錄封存至 `docs/09_archive/ROADMAP_6M_ENGINEERING_V1_COMPLETION_RECORD_2026_07.md`；目前主線改為 Phase 0 evidence accumulation、Phase 1 V2.0 read-only design spike、Phase 2 Workbench MVP、Phase 3 data source dry-run、Phase 4 execution realism 與 Phase 5 scheduler approval gate。

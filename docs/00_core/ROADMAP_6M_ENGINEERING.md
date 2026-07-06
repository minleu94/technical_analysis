# Active 6M Roadmap v2 (Gate-Based)

> **最後更新**：2026-07-06
> **定位**：本文件是未來 6 個月工程執行與研究能力成長的權威路線圖。本文件已重構為 Gate-based 結構，不再保留完成流水帳。
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

---

## 2. Active Roadmap Phases

目前的開發主線已從「功能補齊」轉向「證據累積與決策驗證」。所有 Phase 的推進必須嚴格遵守 Gate 條件。

### Phase 0：Evidence Accumulation Gate
**目標**：累積真實使用數據與多日穩定紀錄，證明流程無害且有觀察價值。
- **門檻要求**：
  - weekly history 必須達到至少 3 次（目前 `0/3`）。
  - multi-day dry-run 必須累積紀錄（目前 `1/3`）。
- **輔助工具**：Historical Evidence Replay 可用 working-copy / replay DB 從歷史交易日逐日重放 Evidence Pipeline，並把事件 metadata 標成 `historical_replay` / `simulated_scheduler`；它只能幫助找 source gap、payload gap 與 V2.0 設計問題，不計入 weekly history 或 multi-day dry-run 的真實時間門檻。
- **限制**：Production scheduler 繼續維持 `false`，不寫入正式資料，不進行自動交易。

### Phase 0A：Historical Replay Evidence Quality Audit
**狀態**：2026-07-06 已完成 reference return blocker closeout，可作為 V2.0 Phase 1 的 simulated evidence input。
- **已驗證產品**：
  - `historical_replay_2026-01-06_2026-07-06_reference_fix.json` / `.md` / replay DB 已產生。
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
**狀態**：2026-07-06 已完成 read-only prototype slice 與 formal read-only source adapter；仍未進入 Phase 2 主 UI 整合。
**目標**：在不改動主 UI 且不新增交易能力的前提下，探索 V2.0 資訊架構。
- **工作範圍**：
  - 只做資訊架構 (Information Architecture) 與 Read-only Prototype。
  - 梳理決策畫面動線，確認 Daily Decision、Evidence Review 與 Market Watch 合併後的呈現。
  - 可讀取 Phase 0A 的 `_reference_fix` replay summary 作為 source gap、payload gap、event family、outcome maturity 與 data quality 的參考輸入；不得把 replay 包裝成 production readiness 或策略績效結論。
  - 已落地 `WorkbenchDashboardDTO`、read-only composer、replay JSON summary adapter、`WorkbenchSourceService` 與 `scripts/inspect_v2_workbench_prototype.py`；CLI 保留 `--sample`，並可用受控 `--db-path` / `--decision-date` 讀取 Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary 與可選 replay JSON summary，輸出 JSON / Markdown 的今日待判讀、Evidence mode、Daily Checklist 與 read-only access boundary。
- **限制**：不新增交易能力，不改動生產環境 UI；adapter 只讀 existing sources，missing DB / missing table / degraded source 只回 diagnostics，不建立 schema、不寫 evidence、不建立 scheduler、不套用 lifecycle action。

### Phase 2：V2.0 Workbench MVP
**目標**：建立單一決策入口。
- **工作範圍**：
  - 整合 Daily Decision Desk、Evidence Review、Portfolio Review 與 Action Items。
  - 將舊 Tab 轉為 drill-down 或專家模式。

### Phase 3：P0 Data Source Candidate Dry-run
**目標**：引入使研究更真實的關鍵資料，但初期僅作候選測試。
- **工作範圍**：
  - 微結構資料（處置股、分盤交易）。
  - Corporate action 與 PIT fundamental release date。
- **限制**：先維持 candidate-only 與 dry-run，不直接覆寫決策特徵 (ScoringEngine)。

### Phase 4：Execution Model Realism
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

---

## 3. 驗證規則

- **文件同步**：所有功能或政策修改，必須依據 `DOC_COVERAGE_MAP.md` 同步更新相關手冊。
- **金融邊界**：策略、回測、推薦修改，必須通過 no-look-ahead 自查與 pytest gate。金融核心數值必須維持 `Decimal` 或整數，不得新增裸 `float`。
- **資料可信度**：Daily Decision 與各儀表板需明確揭示 provider 的 quality (如 `DEGRADED`, `MISSING`)。
- **排程與自動化**：在通過 Phase 5 Gate 之前，嚴禁啟用 Production Write-mode Scheduler 或自動發送真實交易委託。

---

## 4. 更新記錄

- 2026-07-06：完成 V2.0 Phase 1 read-only Workbench prototype slice；已落地 DTO、composer、replay JSON summary adapter、sample CLI 與 focused tests，Phase 2 主 UI、Phase 0 真實時間 gate 與 Phase 5 scheduler gate 仍未完成。
- 2026-07-06：完成 Workbench formal read-only source adapter；CLI 可從 `--sample` 擴充到受控 `--db-path` / `--decision-date`，只讀既有 evidence / readiness / Agent summary / optional replay JSON，不寫 DB；Phase 0 weekly history `0/3`、multi-day dry-run `1/3` 與 Phase 5 scheduler gate 不變。
- 2026-07-06：完成 Phase 0A Historical Replay Evidence Quality Audit closeout；`ForwardPerformanceService` reference lookup 已修正 missing benchmark 預設 TAIEX、market index `收盤價` fallback 與保守 industry sector mapping。新 `_reference_fix` replay 產物確認 benchmark return / excess 全部填入 ready outcomes，industry 大量缺值保留為 payload gap；此項解除 V2.0 Phase 1 read-only design spike 的 replay input blocker，但 Phase 0 真實時間 gate 與 Phase 5 scheduler gate 仍未完成。
- 2026-07-06：新增 Historical Evidence Replay v1 作為 Phase 0 的 research-only simulated scheduler 輔助工具；可在 working-copy / replay DB 逐日重放歷史 evidence，但不取代 weekly history `0/3`、multi-day dry-run `1/3`、manual approval 或 Phase 5 production scheduler gate。
- 2026-07-06：重構為 Gate-Based Active Roadmap，將 V1 / Month 1-6 / V1.1-V1.9 的詳細完工紀錄封存至 `docs/09_archive/ROADMAP_6M_ENGINEERING_V1_COMPLETION_RECORD_2026_07.md`；目前主線改為 Phase 0 evidence accumulation、Phase 1 V2.0 read-only design spike、Phase 2 Workbench MVP、Phase 3 data source dry-run、Phase 4 execution realism 與 Phase 5 scheduler approval gate。

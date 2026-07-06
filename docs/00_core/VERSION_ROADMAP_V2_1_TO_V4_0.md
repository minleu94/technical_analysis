# V2.1 至 V4.0 版本路線圖

> **最後更新**：2026-07-06
> **定位**：本文件是 V2.0 之後的長期版本化 companion。它把 `ROADMAP_6M_ENGINEERING.md` 的 gate-based Phase 與 `system_vision_specification.md` 的成功標準轉成可討論的產品版號階梯；不取代 6M Roadmap、Snapshot、Vision 或 Architecture。

---

## 1. 文件邊界

本文件回答三個問題：

1. V2.0 Unified Decision Workbench 之後，baldr 可以如何繼續切版本？
2. 目前 6M Roadmap 的 Phase 2 至 Phase 5，對應到哪些產品版號？
3. Vision 的四層成功標準，如何轉成 V3.0 / V4.0 的成熟度目標？

本文件不做下列事情：

- 不宣告任何投資訊號已有效。
- 不把 UI / dashboard 完成等同於 alpha 成立。
- 不覆寫 `ROADMAP_6M_ENGINEERING.md` 的 Phase gate。
- 不啟用 production scheduler、自動下單、AI 決策或自動 lifecycle action。
- 不新增外部資料 ingestion 的直接承諾；資料源仍需經 source capability、available_date、quality 與 missing policy gate。

## 2. Scoped Authority 對照

| 主題 | 權威文件 | 本文件角色 |
|---|---|---|
| 目前狀態 | `PROJECT_SNAPSHOT.md` | 只引用，不改寫。 |
| 未來 6 個月工程順序 | `ROADMAP_6M_ENGINEERING.md` | 將 Phase 對應到候選版號。 |
| V1.1 至 V2.0 節奏 | `VERSION_ROADMAP_V1_1_TO_V2_0.md` | 承接 V2.0 之後的版本階梯。 |
| 外部參考與 V1.5-V2.0 形狀 | `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md` | 只引用資料源與 deferred 技術邊界。 |
| 長期願景與成功標準 | `system_vision_specification.md` | 將 Level 1-4 映射成 V2/V3/V4 成熟度。 |
| 架構與模組邊界 | `system_architecture.md` | 不新增架構權威。 |

## 3. 版本命名規則

### V2.x：決策工作台與證據營運成熟

V2.x 的核心是「讓 daily decision workflow 真的穩定運作」。它聚焦 Workbench 主 UI、Evidence operating loop、資料可信度 dry-run、執行模型 realism 與 production evidence scheduler approval。

V2.x 的成功不是投資績效，而是：

- 每天能從單一工作台看見市場、候選、持倉、evidence、資料品質與待處理事項。
- 所有 warning、missing、degraded、manual-required 狀態都可回溯。
- Evidence pipeline 與 weekly review 能穩定累積，不再只靠一次性 CLI output。

### V3.x：Evidence-Validated Decision System

V3.x 的核心是「用累積樣本證明哪些決策輔助真的有用」。它不要求所有訊號都有效，但要求系統能清楚區分：

- 哪些 signal / alert / gate 有正向 evidence。
- 哪些只是 noise。
- 哪些條件下有效、哪些 regime 下失效。
- 哪些資料源或 dashboard 對使用者決策沒有幫助，應降級或移除。

### V4.x：Investment Effectiveness Maturity

V4.x 只在 V3.x 累積足夠 forward evidence、live-vs-research gap 與 manual review evidence 後才成立。它的目標不是保證獲利，而是讓系統可驗證地改善研究與投資決策品質。

若沒有足夠證據，V4.0 不應提前命名為正式交付。

---

## 4. 版本階梯總覽

| 版本 | 對應 6M Phase / Vision Level | 定位 | 主要 Gate |
|---|---|---|---|
| V2.0 | Phase 1 / Level 1 preflight | Unified Decision Workbench read-only prototype 與 source adapter。 | 已完成 Phase 1；Phase 2 主 UI 未完成。 |
| V2.1 | Phase 2 / Level 1 | Workbench 主 UI MVP。 | Phase 0 evidence accumulation 不得被 replay 取代；舊 Tab 需保留 expert mode。 |
| V2.2 | Phase 0 + Phase 2 / Level 1-2 | Evidence Operating Loop。 | weekly history、multi-day dry-run、manual review 與 action item 節奏可重複。 |
| V2.3 | Phase 3 / Level 2 | P0 Data Source Candidate Dry-run。 | 新資料源只作 candidate / dry-run，不進 `ScoringEngine`。 |
| V2.4 | Phase 4 / Level 2 | Execution Model Realism。 | execution realism 先在 research-only sandbox 驗證，不串 broker。 |
| V2.5 | Phase 5 / Level 1-2 governance | Production Evidence Scheduler Approval。 | explicit approval、rollback / backup、multi-day record 與 source gaps 全部通過。 |
| V3.0 | Vision Level 2-3 | Evidence-Validated Decision System。 | 事件類型、alert、gate 與 dashboard 有足夠 forward / gap / review evidence 可判讀。 |
| V3.1 | Vision Level 3 | Risk Control Effectiveness。 | Liquidity Gate、Why Not、Portfolio Alert、Fundamental diagnostics 有效果證據或降級決策。 |
| V3.2 | Vision Level 3 | Strategy Lifecycle Effectiveness。 | Signal Decay / lifecycle candidate 能降低失效策略續用風險，仍需人工核准。 |
| V4.0 | Vision Level 4 | Investment Effectiveness Maturity。 | Watchlist / Recommendation / Portfolio / Lifecycle 能以長期 evidence 支持決策改善。 |

---

## 5. V2.x 詳細規劃

### V2.0：Unified Decision Workbench 基準

狀態：Phase 1 read-only prototype 與 formal read-only source adapter 已完成。

已交付基準：

- `WorkbenchDashboardDTO`
- `WorkbenchReadOnlyComposer`
- `WorkbenchSourceService`
- `_reference_fix` historical replay summary input
- `scripts/inspect_v2_workbench_prototype.py`

仍未完成：

- 主 UI MVP。
- background evidence feed。
- Phase 0 真實 weekly / multi-day gate。
- Phase 5 production scheduler approval。

### V2.1：Workbench 主 UI MVP

目標：把 Daily Decision、Evidence Review、Portfolio Review 與 Action Items 整合成單一日常入口。

Scope In：

- 漸進改造現有 Daily Decision Desk，優先避免新增第 9 個頂層工作區。
- Workbench 第一屏呈現「今日待判讀」而不是功能清單。
- Evidence mode 成為 drill-down。
- Market Watch / Smart Money / Research Lab 保留為專家模式或下鑽入口。
- 所有 section 顯示 quality / warnings / source trace。

Scope Out：

- 不自動下單。
- 不啟用 production scheduler。
- 不自動套用 demote / retire / promote。
- 不重算 scoring、recommendation、portfolio 或 backtest。

Exit Gate：

- UI contract 測試確認 Workbench view 不直接 import domain 計算模組。
- Manual 同步入口、操作、結果判讀、安全限制與排錯。
- Phase 0 evidence gate 狀態在畫面上清楚揭露，不用漂亮 dashboard 掩蓋樣本不足。

### V2.2：Evidence Operating Loop

目標：讓 evidence operations 變成每週 / 每日可重複流程，而不是一次性報表。

Scope In：

- weekly evidence operations + history 至少累積可比較週期。
- multi-day dry-run record 從 scaffold 變成實際紀錄。
- action item planning 與 manual review note 可追蹤。
- Evidence Review UI smoke checklist 實際 closeout。
- Read-only Agent report sample 納入固定覆盤輸入。

Exit Gate：

- weekly history 達到 3 次以上，且不是 fixture 或手動改表。
- multi-day dry-run 達到 3 次以上，且 diagnostics 可比較。
- source gaps 能分成 blocking / warning / accepted residual。
- `production_scheduler_allowed=false` 仍清楚保留，直到 V2.5。

### V2.3：P0 Data Source Candidate Dry-run

目標：把 Vision / Blueprint 中最影響可信度的資料源，先以 governed candidate 方式接入。

候選資料源：

- Corporate action / adjusted price timeline。
- 處置股、分盤、全額交割、漲跌停鎖死。
- PIT fundamental release date。
- 三大法人、信用交易、TDCC 與概念籃子可作後續 candidate，但不得直接進核心 score。

Exit Gate：

- 每個資料源都有 `source_id`、`source_version`、`available_date`、`quality`、`missing_policy`。
- 缺資料時 fail-closed、degraded 或 skipped，不得靜默補成 observed。
- 候選資料只進 diagnostics / Why Not / Risk Prompt / source coverage，不直接改 `ScoringEngine`。

### V2.4：Execution Model Realism

目標：讓 research replay 與 portfolio sandbox 更接近真實市場限制。

Scope In：

- 買賣價差。
- 零股 / 整股限制。
- 跳空成交與未成交原因。
- 漲跌停鎖死與交易限制。
- 完整委託生命週期的 research-only trace。

Exit Gate：

- 所有金額與倉位維持 `Decimal` / 整數單位。
- 不串 broker，不建立 production order。
- replay credibility 明確揭露哪些成交是假設、哪些限制已模擬。

### V2.5：Production Evidence Scheduler Approval

目標：只針對 evidence write-mode scheduler 進入 production approval，不代表自動交易。

Gate：

- Phase 0 weekly / multi-day evidence 足夠。
- working-copy confirm smoke repeat idempotent。
- source gaps 無 blocking。
- rollback / backup / recovery 文件完備。
- manual approval package 明確簽核。
- scheduler 開啟後仍不得下單、不得自動 lifecycle action、不得改策略。

---

## 6. V3.x 詳細規劃

### V3.0：Evidence-Validated Decision System

目標：系統能根據累積 evidence，判斷哪些訊號、警示、排除條件與 dashboard 值得保留。

成功標準：

- Watchlist Trigger、Recommendation、Why Not、Liquidity Gate、Portfolio Alert 至少有可比較 forward outcome。
- dashboard 能顯示樣本數、confidence、regime / sector 分層與 limitations。
- 不足樣本不被包裝成結論。
- ineffective / noisy signal 可以被降級為觀察或移出第一屏。

### V3.1：Risk Control Effectiveness

目標：證明風險提示與排除機制有助於降低錯誤研究或不良候選。

候選衡量：

- Liquidity Gate 排除組的成交風險是否高於未排除組。
- Why Not 是否降低低品質候選進入研究流程的比例。
- Portfolio Alert 是否能提前辨識持倉惡化。
- Fundamental diagnostics 是否減少錯誤解讀基本面資料。

### V3.2：Strategy Lifecycle Effectiveness

目標：讓 Strategy Lifecycle 不只是保存 proposed payload，而能被 evidence 驗證其管理效果。

Scope In：

- Signal Decay 命中後的後續表現。
- demote / retire candidate 的人工審核結果。
- lifecycle action 前後的 live-vs-research gap 變化。
- 避免失效策略持續被採用的流程證據。

Scope Out：

- 不讓 AI 自動升降級。
- 不把單次 decay observation 當成策略失效證明。

---

## 7. V4.0 詳細規劃

### V4.0：Investment Effectiveness Maturity

V4.0 是願景層級，不是目前可承諾的 6M 工程交付。只有在 V2.x 建立日常工作台與 evidence operations，且 V3.x 累積出可判讀效果後，才可評估是否進入 V4.0。

成立條件：

- Watchlist Trigger 入選後的 forward return 優於合理 benchmark，且樣本足夠。
- 推薦組合扣除交易成本後仍具備穩定性，且能分辨 regime / liquidity / source quality。
- Live performance 與 Research performance 的落差可解釋並逐步縮小。
- Strategy Lifecycle 能辨識訊號衰退，降低失效策略續用。
- Decision Quality Review 能顯示使用者流程改善，而不是 hindsight blame。

V4.0 仍不代表：

- 保證獲利。
- 自動交易。
- AI 報牌。
- 免人工審核。

---

## 8. Deferred / 明確不納入近期版本

以下項目只有在後續 evidence 或量測證明需要時才重開：

- Production broker order / 自動下單。
- AI 自動產生 lifecycle action。
- 強化學習主線。
- GPU-first portfolio optimization / cuFOLIO。
- SQLite split DB / async rewrite。
- 使用 LLM output 作為 evidence。
- 未治理資料源直接進 `ScoringEngine`。

---

## 9. 更新規則

本文件應在下列情況更新：

- `ROADMAP_6M_ENGINEERING.md` 新增、重排或關閉 Phase gate。
- `system_vision_specification.md` 的成功標準或 Gap Register 改變。
- V2.1 / V2.2 / V2.3 / V2.4 / V2.5 任一版本開始實作或 closeout。
- V3.0 或 V4.0 的 evidence 標準需要量化。

不應因單一 bugfix、單次 smoke、單次 replay 或單次 dashboard polish 更新本文件的版本結論。

## 10. 更新記錄

- 2026-07-06：初版建立 V2.1 至 V4.0 版本階梯，將 6M Roadmap Phase 2-5 與 Vision Level 1-4 映射為長期產品版號；保持 production scheduler、自動交易、AI 決策與投資有效性結論在 gate 之外。

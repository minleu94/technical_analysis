# DEVELOPMENT_ROADMAP（Roadmap Hub）

> **最後更新**：2026-07-06
> **定位**：本文件是 Roadmap Hub，不再保存完整歷史長文。它負責指向目前狀態、6 個月工程路線、系統架構與歷史歸檔。

---

## 1. 文件權威邊界

本專案改採 **Scoped SSOT（分範圍單一真相來源）**，不再由單一 Roadmap 文件承擔所有決策、歷史與架構資訊。

| 文件 | 權威範圍 |
|---|---|
| [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) | 目前狀態、當前工作模式、本週優先事項與高風險區。 |
| [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) | 未來 6 個月可執行工程路線、里程碑、交付物與驗收標準。 |
| [VERSION_ROADMAP_V1_1_TO_V2_0.md](VERSION_ROADMAP_V1_1_TO_V2_0.md) | V1 release 後到 V2.0 的版本化交付節奏；作為 6M Roadmap 的 companion，不取代其權威。 |
| [EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md](EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md) | 外部開源專案參考、資料源補強優先序與 V1.5 至 V2.0 版本形狀；作為 6M Roadmap / Version Roadmap companion，不取代 Vision。 |
| [system_architecture.md](../01_architecture/system_architecture.md) | 目前系統架構、模組邊界、資料流與高風險技術邊界。 |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) | 文檔導航與文件所在位置，不作為功能或狀態事實來源。 |
| [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md) | 舊 Roadmap 未完成事項的逐項處置、移交月份與結案 Gate。 |
| [DEVELOPMENT_ROADMAP_LEGACY_2026_06.md](../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md) | 舊線性 Phase、歷史 Done、舊 Roadmap current section；只作追溯，不作目前狀態依據。 |

若文件描述衝突，依「該主題的權威文件」判斷；例如目前狀態看 Snapshot，未來 6 個月看 6M Roadmap，架構看 system architecture。

---

## 2. 系統定位

這不是每天吐股票的工具；baldr 是一套可驗證、可回溯、可演化的台股研究與投資決策工作台。

目前產品已形成三個已落地的產品閉環，並新增一個未來目標閉環：

1. **資料與市場狀態閉環**：Update → SQLite 狀態 → Market Watch / Smart Money → 候選池。
2. **研究驗證閉環**：Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Promote。
3. **持倉檢查閉環**：Recommendation / Backtest → Portfolio → Condition Monitor / Chip Monitor → Journal → 回到研究。
4. **每日決策閉環（v1）**：Market Intelligence → Daily Decision Desk → Watchlist Trigger / Portfolio Alert / Research Input。此閉環已接上主 UI 首頁（Daily Decision Desk），其餘 section 仍逐步補齊 providers。

---

## 3. 目前執行狀態

目前狀態以 [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) 為準。短版摘要如下：

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
- Post-V1 V1.1 / V1.2 / V1.3 / V1.4 v1 已完成：推薦 Profile / 回放 workflow bridge、Profile replay comparison、訓練 / 獨立驗證期間、推薦回放 rolling risk、microstructure preflight、relative attribution、weekly evidence operations、manual approval package、action item planning、weekly review history 與 Research Lab 覆盤歷史子頁已落地；這些仍是 research credibility / evidence operations diagnostics，不代表投資有效性。
- 後續要提升「準確度」必須先建立實證比較、factor attribution、資料因子層與實驗治理，不應直接把新資料硬塞進 scoring engine。

---

## 4. 下一步 Next

未來 6 個月工程主線以 [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) 為準；產品北極星與長期能力圖像見 [system_vision_specification.md](../01_architecture/system_vision_specification.md)。
V1 release 後的版本化交付節奏見 [VERSION_ROADMAP_V1_1_TO_V2_0.md](VERSION_ROADMAP_V1_1_TO_V2_0.md)：V1.1、V1.2、V1.3、V1.4、V1.5、V1.6、V1.7、V1.8 與 V1.9 v1 已完成；下一步不是直接重做 UI，而是用 weekly evidence operations 與 V1.4 history 實際累積多週覆盤證據，補齊人工 UI smoke、多日 dry-run、真實 watchlist / portfolio workflow 樣本與 source gaps 後，才評估 V2.0 Unified Decision Workbench。部分 Post-V1 design / QA 檔名保留後續里程碑日期，不作為 Roadmap Hub 的完成日期權威。
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
   - 目前下一步是繼續用 weekly evidence operations + history 累積多週覆盤證據，並用真實 workflow 補齊 watchlist 無項目與 portfolio 無 active positions；舊 recommendation 缺 screening matrix / exclusion payload 時仍只診斷、不回補、不重算。production scheduler 仍未啟用，V2.0 Unified Decision Workbench 需等 evidence 與使用節奏證明後再評估。

6. **P1：V2.0 前置補強**
   - V1.5 Data Credibility & Corporate Action Gate、V1.6 Cross-sectional Factor Pipeline、V1.7 Screening Matrix & Negative Evidence、V1.8 Portfolio Construction / Execution Trace Sandbox 與 V1.9 Read-only Agent / MCP Evidence Access 已完成 v1。
   - 2026-07-06 已補 `scripts/inspect_pre_v2_readiness.py` / `PreV2ReadinessService`，可唯讀彙總 weekly history、multi-day record、source gaps 與 read-only Agent report sample；它只把非排程前置條件變成可重跑檢查，不解除多週 / 多日 / manual smoke / true workflow sample 門檻。
   - 2026-07-06 follow-up 已完成非時間型 closeout：Git unreachable loose objects 清為 0、Recommendation liquidity payload gap 修正、working-copy all-source source coverage `blocking_gaps=[]`、working-copy confirm smoke repeat=2 idempotency passed、Evidence Review UI smoke passed、read-only Agent report sample ready。正式 evidence DB 未寫入；驗證只在 working-copy DB 與 ignored output mirror 內完成。
   - 2026-07-06 Historical Evidence Replay v1 已補 `scripts/replay_historical_evidence_pipeline.py` 與 `HistoricalEvidenceReplayService`，可把 source DB 複製成 replay DB 後逐交易日重放 runner；缺 as-of recommendation result 時只記錄 diagnostic 並略過 recommendation 類來源，不用未來 result 補值。
   - 進入 V2.0 前仍需真實時間累積：多週 weekly evidence operations + history 實際紀錄目前 `0/3`，multi-day dry-run record 目前 `1/3`。若要推 production scheduler，仍需 explicit design / approval / rollback 文件；目前 `production_scheduler_allowed=false`。
   - `cuFOLIO`、強化學習、券商自動下單與 SQLite async / split DB 暫不納入近期 Roadmap，除非有量測證據顯示現有計算或寫入模式成為真實瓶頸。

7. **P2：Phase 5 研究輸出後續**
   - PDF 規格化報告仍待後續，屬研究輸出 backlog，不阻塞 Month 3 / Month 4。

8. **P3：文件治理持續檢查**
   - Snapshot、6M Roadmap、Architecture、Index、Agent 指引已採 Scoped SSOT；後續功能變更需依 Coverage Map 同步更新入口摘要。
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

- 2026-07-06：新增 Historical Evidence Replay v1，定位為 research-only simulated scheduler；可輔助 Phase 0 source gap / V2.0 設計觀察，但不替代真實時間 gate 或 production scheduler approval。
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

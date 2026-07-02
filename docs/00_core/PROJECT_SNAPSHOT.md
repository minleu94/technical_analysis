# PROJECT_SNAPSHOT（必讀｜每次開新對話先看）

> **開場 30 秒內讀完** - 只放今天的狀態與入口，不放完整歷史細節

## 系統定位（一句話）

這不是每天吐股票的工具；baldr 是一套可驗證、可回溯、可演化的台股研究與投資決策工作台。

## 文件權威判讀

本專案已改採 **Scoped SSOT（分範圍單一真相來源）**：

- **現在狀態 / 本週優先事項 / 高風險區**：以本文件為準。
- **未來 6 個月工程路線**：以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準。
- **目前架構與模組邊界**：以 `docs/01_architecture/system_architecture.md` 為準。
- **文件導航**：以 `docs/00_core/DOCUMENTATION_INDEX.md` 為準。
- **舊 Phase 與歷史 Done**：只看 `docs/09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md`，不作目前狀態依據。
- **舊 Roadmap 未完成事項移交**：以 `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` 為準。
- **目前完整操作方式**：以 `docs/07_guides/APPLICATION_MANUAL.md` 為準。

`docs/00_core/DEVELOPMENT_ROADMAP.md` 現在是 Roadmap Hub，只負責指向上述權威文件，不再保存完整歷史長文。

## 當前狀態

專案已超出早期線性 Phase 規劃；截至 V1 release readiness closeout，實際產品主線已形成四個可操作產品閉環，並補上 Strategy Lifecycle / Portfolio Feedback 與 release QA 的治理閉環。V1 完成只代表工程入口、資料契約、操作流程與 release gate 已可用，不代表任何推薦、警示或策略已被證明具備投資有效性。

Post-V1 evidence-driven 增量已建立 Evidence Event Store v1、Forward Outcome Calculator v1、Evidence Importers / Capture Pipeline v1、E2E smoke、Forward Performance Read Model v1、Evidence Source Persistence v1、Forward Performance Dashboard read-only UI v1、Evidence Pipeline Runner dry-run v1、working-copy DB smoke v1、scheduler approval checklist v1、Live vs Research Gap linkage v1、Signal Decay Monitor v1、Decision Quality Review v1、Evidence Review Dashboards read-only UI pack v1、Evidence Review manual smoke checklist 與 multi-day dry-run record scaffold：可 append-only 保存 Recommendation、Watchlist Trigger、Portfolio Alert、Risk Prompt、Why Not / Liquidity exclusion 等事件，並以 SQLite `daily_prices` 計算 5 / 10 / 20 / 60 交易日 close-to-close forward research outcome。Recommendation importer 可從 persisted `RecommendationResultDTO` 擷取；Why Not / Liquidity exclusion 只在 Recommendation result 已保存 optional payload 時產生事件，舊結果缺 payload 仍回 `source_missing_exclusion_payload` diagnostic，不回補、不重算。Daily Decision Desk 類來源已新增 durable snapshot repository 與 capture / inspect CLI，`capture_evidence_events.py` 可從 durable snapshot 匯入 Watchlist Trigger、Portfolio Alert、Risk Prompt；若缺 snapshot 會回 `source_missing_snapshot`，不讀 UI state、不偽造事件。Read model 可依 event_type、event_family、source_type、regime、sector、profile_id、score_percentile_bucket、liquidity_state、data_quality 彙總 ready / pending / missing、return / excess return、quality 與 warning counts；Research Lab 已新增 `Evidence Review` 分頁，內含 `Forward Evidence`、`Live vs Research Gap`、`Signal Decay` 與 `Decision Quality` 四個唯讀 evidence inspection 子頁；`scripts/run_evidence_pipeline.py` 可手動串接 source coverage、snapshot capture、event capture、outcome calculation、summary 與 diagnostics report，預設 dry-run，只有 explicit `--confirm --db-path` 才寫 working-copy DB。`scripts/smoke_evidence_pipeline_working_copy.py` 可複製 source DB 至 working-copy DB 並重複 confirm smoke 檢查 idempotency；`scripts/evaluate_evidence_scheduler_readiness.py` 會彙總 source coverage、smoke report 與 dashboard availability，且固定 `production_scheduler_allowed=false`。新增 `POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md`、`POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md` 與 `POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md`，用於人工 UI smoke、多日 dry-run 穩定性觀察與未來 scheduler approval stage 管理。這仍只是 research evidence aggregation、scheduler dry-run design、人工核准準備、gap observation、decay observation、流程覆盤、唯讀檢查 UI 與 QA scaffold；正式 production scheduler、樣本累積、完整實帳歸因、人工 smoke 實際 closeout、多日 dry-run 實際記錄與投資有效性結論尚未完成。

- **閉環 1：資料與市場狀態閉環** ✅ V1 已建立
  - Update → SQLite 狀態 → Market Watch / Smart Money（市場觀察子 Tab）→ 候選池
  - Phase 1 ✅ / Phase 2 ✅ / Phase 2.5 快速/安全更新分流 ✅ / Phase 2A/2B/2C SQLite DB-first ✅ / Phase 3 CSV 手動匯出 ✅
  - 數據更新工作台（Dashboard + 快速/安全更新分流）✅ / SQLite 儲存升級 ✅ / Smart Money Terminal MVP ✅ / 券商分點長碼解密與總公司判定 ✅ / MoneyDJ HTTP fast path 與交易日預檢 ✅ / Full App Healthcheck flow model 覆蓋 ✅

- **閉環 2：研究驗證閉環** ✅ V1 已建立
  - Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Research Run Registry → Promote
  - Phase 3.1 ✅ / Phase 3.2 ✅ / Phase 3.3a ✅ / Phase 3.3b ✅ / Strategy Scoring Governance (增量 A & B) ✅
  - Research Lab 多模式實驗室 ✅ / Recommendation Portfolio Backtest credibility v1 ✅ / Backtest chart fast renderer ✅ / Research Run Registry M2-B 基礎保存 ✅ / Registry Cross-run 比較子頁 C2 ✅ / Registry-based Promote Gate C3 ✅
  - AI Runtime Subsystem MVP ✅ / Codex / Antigravity Agent 指引 ✅ / 回測 fixed-quantile 雙模式與 Expanding T-1 歷史門檻 ✅ / 推薦 eligible universe 橫斷面百分位排名與門檻限制 ✅

- **閉環 3：持倉檢查閉環** ✅ V1 已建立
  - Recommendation / Backtest → Portfolio → Condition Monitor / Chip Monitor → Journal / Lifecycle Review → 回到研究
  - Phase 4.1 Portfolio MVP 與深化 ✅：domain/service/test、Portfolio Tab、來源追溯 metadata、ConditionMonitor 複合警告與停損停利已實作
  - 策略版本與推薦來源追蹤視圖、目前價格對比、未實現損益計算已深化完成，且已修正 float 邊界合規漏洞與三層防禦策略版本串接 (2026-06-11)
  - Phase 4.2 Portfolio 籌碼監控與下鑽 ✅：新增籌碼監控 Tab 與追蹤分點表格，依淨買賣、集中度及連續天數評估風險（bullish/neutral/bearish），並實作🔍 下鑽主力流向按鈕與自動高亮定位功能 (2026-06-11)

- **效能與研究輸出（Phase 5）** ✅ SQLite 檢視器分頁與規格化 Excel 報告匯出已完成 (2026-06-14)
  - 圖表渲染優化 ✅ / 批次回測並行化 ✅ / SQLite 檢視器穩定分頁 ✅ / 規格化 Excel 報告匯出 ✅

- **閉環 4：每日決策工作台（Daily Decision Desk）** ✅ V1 已建立
  - Market Intelligence → Daily Decision Desk → Watchlist Trigger / Portfolio Alert / Research Input。
  - 目前主 UI 已接上「每日決策」工作區，各 section 已具備 snapshot 顯示框架；Market Regime、Market Breadth v1、Sector Rotation v1、Relative Strength / Liquidity Ranking v1、Watchlist Trigger v1 與 Portfolio Alert v1 已接主 UI。Market Breadth v1 由 SQLite `daily_prices` 推導多方 / 空方 / 持平、成交量擴散與新高新低等 metadata；Sector Rotation v1 由 SQLite `industry_indices` 推導領先 / 落後產業、5 / 20 日變化與輪動強度；Relative Strength / Liquidity Ranking v1 由 SQLite `daily_prices` 推導 5 / 20 日相對強度與平均成交金額，並揭露低流動性代碼；Watchlist Trigger v1 由 `WatchlistService` 與 SQLite `technical_indicators` 共同推導，可計算出個股強度 score_bp (RSI * 100) 與風險警示 risk_alert (偏離 RSI > 80 / < 20 或跌破 lowerband)。若指定日無資料或歷史不足（如 20 日相對強度未滿 21 個交易觀測值），會採用最近可用交易日或降級（quality 降級為 `DEGRADED`，並輸出 `relative_strength_liquidity_insufficient_history`）。Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，可把條件監控與籌碼風險彙總成每日持倉警示；若籌碼資料缺失、估算或不可用，會透過 `quality / warnings` 降級揭露，不補值。Portfolio Alert Attribution v1 已將每筆持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags，使 Daily Decision Desk 能辨識警示來自進場假設失效、籌碼風險或資料品質缺口。Why Not / 風險提示 v1 由 `DecisionDeskRiskPromptService` 從既有 section DTO 的 quality、warnings、低流動性、相對弱勢、watchlist risk alert 與 portfolio alert 推導，不在 UI 層重算 scoring、screening、portfolio 或 liquidity。Month 4 收尾已新增 UI boundary contract test，確認 Daily Decision Desk UI 不直接 import domain 計算模組；2026-07-02 已完成第一輪 Midnight Analyst 全 UI 低風險視覺 polish，修缺字 icon、統一 token / 表格 / 按鈕 / 空狀態，且不改資料抓取、推薦、回測、每日決策 snapshot 或持倉計算語意。

- **治理閉環：Strategy Lifecycle / Portfolio Feedback** ✅ Month 6 v1 已建立
  - Research Run Registry → Month 6 lifecycle gate → promote / hold / demote / retire evidence → Portfolio Feedback → Portfolio Review → 回到 Research。
  - 已建立 `StrategyLifecycleService`、`LifecycleEvidenceRepository`、`PortfolioFeedbackService` 與 `PortfolioReviewService`；promotion 成功後保存 applied evidence，demote / retire 先保存 proposed evidence；持倉管理「生命週期回顧」可判讀 thesis 狀態、來源追溯、執行落差、訊號 / 市場 / 資料品質歸因。

- **交付治理閉環：V1 Release / Full App Healthcheck** ✅ V1 release gate 已通過
  - Full App Healthcheck → flow diagnostics → tab full bridge → MainWindow UI smoke → 人工 UI smoke → V1 checklist → `main` / clean clone gate。
  - `docs/06_qa/V1_RELEASE_CHECKLIST_2026_06_30.md` 已記錄 quick healthcheck、逐 tab full bridge、MainWindow UI smoke、人工 8 工作區 smoke、文件一致性、`main` 合入後 release gate 與 clean clone / install gate 均通過。此閉環屬工程交付信心，不代表投資訊號有效性。


- **文件治理與 Manual** ✅ 本輪完成
  - Roadmap Hub、6M Roadmap、Legacy Carryover、Architecture、Index 與 Agent 指引已採 Scoped SSOT。
  - 已建立 8 個頂層工作區的完整操作手冊。
  - 舊 Roadmap 工程欠項已全部取得「已完成 / Month X 移交 / 被取代」唯一處置；實作進度仍依 6M Roadmap 執行。

## 現在的工作模式（你每天要用的流程）

1. Update 使用「快速更新（跳過大型合併）」或「安全更新（完整 CSV + SQLite）」補齊資料，必要時用 SQLite Inspector 唯讀確認 freshness。
2. 每日先看 Daily Decision Desk 的主結論、資料品質、Watchlist Trigger 與 Portfolio Alert，再下鑽 Market Watch / Smart Money。
3. Recommendation 用 Profile 出名單 + 看 Why / Why Not → 加入候選池，或送 Research Lab 批次回測 / 推薦回放。
4. Research Lab / Backtest 可跑單股、候選池批次、固定組合或推薦回放；成功結果可保存到 Research Run Registry，只有通過 Registry 與 Month 6 lifecycle gate 才能升級策略版本。
5. Portfolio 用來追蹤實際或模擬持倉來源、條件監控、籌碼風險與生命週期回顧；警示與失效原因應回到 Research Lab / Registry 比較 / 覆盤日誌確認。

## Tech Lead 的預設任務（開場要先做什麼）

- 給出「下一步最合理的工程行動」與原因（不寫 code）
- 如需看程式碼：先提出要 review 的檔案清單與目的，等我授權 scope

## 本週優先事項（只列 3 個）

1. **V1 release baseline 已完成**：四個產品閉環、Month 6 Strategy Lifecycle / Portfolio Feedback v1、Full App Healthcheck / MainWindow UI smoke / clean clone gate 已形成可交付基準。下一步不是宣稱投資有效，而是進入 evidence-driven 驗證。
2. **下一階段主線：Evidence-Driven baldr + V1.1 workflow bridge**：Evidence Event Store v1 / Forward Outcome Calculator v1 / Evidence Importers v1 / E2E smoke / Forward Performance Read Model v1 / Daily Decision Desk durable snapshot source / source coverage inspection v1 / Forward Performance Dashboard read-only UI v1 / Evidence Pipeline Runner dry-run v1 / working-copy DB smoke v1 / scheduler approval checklist v1 / Live vs Research Gap linkage v1 / Signal Decay Monitor v1 / Decision Quality Review v1 / Evidence Review Dashboards read-only UI pack v1 / Evidence Review UI smoke checklist / multi-day dry-run record scaffold / safe scheduled CMD wrappers 已建立；每日 05:30 Codex read-only 摘要、Evidence Review UI smoke 與 multi-day dry-run evidence 持續背景累積，不阻塞 V1.1 非破壞式 workflow bridge。V1.1 下一步是讓 Daily Decision Desk 作為入口、Market Watch / Smart Money 作為下鑽 evidence panel，先補 navigation、empty state、evidence summary 與 QA gate；完整合併為 Unified Decision Workbench 留待 V2.0 評估。Production scheduler implementation 仍需 blocking gaps 修正、人工 approval 與明確設計後才可進行。
3. **維持 V1 安全邊界與資料治理**：Month 5 retroactive baseline / statement baseline 多數仍為 `degraded`，P/B / P/S 仍只接受 governed external observations 或後續明確 backfill records；策略、回測、推薦、factor 與 portfolio 改動仍需 no-look-ahead、Decimal / 整數單位與 release healthcheck 防線。

## 高風險區（改動需謹慎）

Month 6 v1 狀態（2026-06-17）：策略生命週期判斷只讀 Research Run Registry metadata、benchmark results、factor snapshot / contribution、regime breakdown 與 Portfolio 來源追溯。Promotion 不能只靠單次正報酬；run 必須通過交易次數、總報酬、Sharpe、回撤、勝率、benchmark excess return、factor quality 與 regime compatibility gate。Lifecycle evidence 採 append-only SQLite table 保存 decision snapshot / gate reasons / version id，可投影 latest state；demote / retire 會先形成 proposed evidence，不會自動刪除策略版本。Portfolio feedback 只輸出 post-trade attribution / live-vs-research gap，不會自動下單、平倉、改寫持倉或刪除歷史策略證據。

V1 release 狀態（2026-06-30）：`main` 已通過 release gate、quick healthcheck、MainWindow UI smoke 與 clean clone / install gate。這只代表 repo 可乾淨 clone、安裝、啟動、切換 8 個頂層工作區並完成主要非破壞式驗證；不得解讀為推薦、警示、策略或基本面 diagnostics 已通過投資有效性驗證。

Post-V1 evidence 增量狀態（2026-07-11）：`app_module/evidence_event_*`、`app_module/evidence_capture_service.py`、`app_module/evidence_event_importers.py`、`app_module/forward_performance_service.py`、`app_module/forward_performance_read_model.py`、`app_module/forward_performance_dashboard_*`、`app_module/evidence_pipeline_runner.py`、`app_module/evidence_scheduler_readiness.py`、`app_module/live_research_gap_*`、`app_module/signal_decay_*`、`app_module/decision_quality_*`、`app_module/*_dashboard_*`、`app_module/decision_desk_snapshot_*`、`data_module/evidence_event_migration.py`、`ui_qt/views/evidence_review_view.py`、`ui_qt/views/forward_performance_view.py`、`ui_qt/views/live_research_gap_view.py`、`ui_qt/views/signal_decay_view.py`、`ui_qt/views/decision_quality_view.py` 與 CLI 已建立，可在受控 SQLite schema 下保存 evidence events / outcomes / Daily Decision Desk durable snapshot / live research gap observation / signal decay observation / decision quality review，於 Research Lab `Evidence Review` 分頁唯讀檢查 Forward Evidence、Live vs Research Gap、Signal Decay 與 Decision Quality 的樣本、pending / missing、benchmark / industry 缺口、source trace、match confidence、lifecycle candidate、process score、quality 與 warnings，並用 `scripts/run_evidence_pipeline.py` 手動模擬每日 evidence pipeline。CLI 預設 dry-run，只有 `--confirm --db-path` 寫入 working-copy DB；`scripts/smoke_evidence_pipeline_working_copy.py` 可在 working-copy DB 重複 confirm smoke 並檢查 source DB read-only 與 idempotency；`scripts/evaluate_evidence_scheduler_readiness.py` 會回傳 readiness、blocking gaps、manual checks 與 `production_scheduler_allowed=false`。Recommendation 可讀 persisted result，Daily Decision Desk 類來源可讀 durable snapshot；Why Not / Liquidity exclusion payload 為 optional / partial，舊結果缺 payload 時只 diagnostic。此狀態不代表任何事件類型已累積足夠樣本，也不代表 alpha 成立；scheduler readiness 最高只到 `ready_for_manual_confirm`，production scheduler 仍未啟用，完整實帳歸因、人工 workflow polish 與投資有效性結論尚未完成。

Post-V1 safe scheduled wrapper 狀態（2026-07-12）：`scripts/scheduled/` 已新增 CMD wrapper + Windows `schtasks.exe` 註冊路徑，以避開 PowerShell `.ps1` 被 local execution policy 擋住的問題；不得使用 `Set-ExecutionPolicy`。Windows Task Scheduler 已建立 `baldr-data-freshness-check-daily`（每日本機時間 05:00，只讀 freshness）與 `baldr-evidence-pipeline-dry-run-daily`（每日本機時間 05:15，只跑 dry-run report）。`baldr-evidence-working-copy-smoke-manual` 只保留 manual-only script，不建立每日自動 task。Codex app 已另建 `baldr scheduled evidence morning report` automation（約 05:30），只讀 Task Scheduler 狀態、latest status、最新 report 與必要 log，產生繁體中文摘要；它不重新執行 pipeline、不建立或修改 Windows task。這些 wrapper 與摘要 automation 只讀或只寫 `<OUTPUT_ROOT>/scheduled/...` 的 status / log / report，不更新 production data、不寫 production evidence DB、不跑 UI、不讀 UI state、不做 portfolio / lifecycle action。Production write-mode evidence schedule 仍未啟用，後續仍需 multi-day dry-run record、人工 UI smoke 與 explicit approval。

2026-07-02 scheduled evidence manual run 已記錄到 multi-day dry-run record：`baldr-data-freshness-check-daily` 與 `baldr-evidence-pipeline-dry-run-daily` 的 manual trigger 均成功且 Last Result = 0；freshness `passed`、latest date `20260702`、無 warnings / blocking gaps；evidence dry-run `passed` 但 `overall_status = degraded`，blocking gaps 為 `decision_desk_snapshot_missing`、`why_not_exclusion_payload_missing`、`liquidity_gate_payload_missing`。整體仍維持 `dry_run = true`、`confirm = false`、`writes_evidence_db = false`，沒有 production DB write、沒有 auto trading、沒有 lifecycle action、沒有買賣建議。

Month 5 Revenue Factor Pack 最新覆寫註記（2026-06-16）：正式 `fundamental_monthly_revenues` 已回填 1,848 筆 2026-05 MOPS records，不再是缺月營收狀態。新增 `scripts/inspect_fundamental_factors.py` 唯讀檢視入口後，以 `decision_date=2026-06-30` 掃描全月營收股票得到股票數 1,848、factor records 4,464、diagnostics 3,696；月營收可產生 `fundamental.revenue_3m_trend` 1,848 筆與 `fundamental.revenue_new_high` 1,848 筆，YoY / MoM 因正式 DB 目前只有 2026-05 單月而回 `fundamental_revenue.baseline_missing` diagnostics。此流程不寫資料、不接 `ScoringEngine`；後續仍須補更多月份的 governed monthly revenue baseline，不應把不足資料期間的 YoY / MoM 視為可用高信心訊號。

Month 5 retroactive baseline 最新補充（2026-06-16）：新增 `scripts/build_monthly_revenue_retroactive_baseline_mapping.py`，可從 MOPS snapshot 產生 `manual.retroactive_baseline_mapping` 候選 mapping；此 source 只代表「導入日後可使用的歷史 baseline」，不是官方歷史公告日，quality 為 `degraded`，不得用於導入日前回測。以 `2014-04..2026-04`、`available_date=2026-06-17` 產生候選時，candidate / validator accepted / dry-run normalized 均為 242,651 筆、diagnostics 0。依人工確認正式 apply 後，`fundamental_monthly_revenues` 為 244,499 筆、期間 `2014-04..2026-05`、股票數 1,848、period 數 146、0 duplicate，quality 分布為 242,651 筆 `degraded` 與 1,848 筆 `observed`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_mops_monthly_revenue_backfill_20260616_224147.db`；Revenue Factor Pack 可產生 YoY 1,843、MoM 1,842、3M trend 1,848、new high 1,848，剩餘 diagnostics 11 筆。

Month 5 季度財報 gate 最新補充（2026-06-17）：新增季度財報 availability loader / validator / normalized parser / backfill workflow，正式 mapping 預設路徑為 `DATA_ROOT/meta_data/fundamental_statement_availability.csv`。目前允許 `manual.statement_available_date_mapping`、`tej.statement_announcement_pit` 與 `manual.retroactive_statement_baseline_mapping`；raw statement CSV source 會被拒絕。以正式 `financial_data` 產生 retroactive candidate 時，raw rows 1,645,555、candidate 170,425、validator accepted 170,425、diagnostics 0；statement item backfill dry-run normalized 1,645,555、diagnostics 0。依人工確認正式 apply 後，`fundamental_statement_items` 期間 `2014-Q2..2024-Q1`、股票數 1,567、period 數 40、0 duplicate，quality 全為 `degraded`，其中 income statement 391,545、balance sheet 407,990、cash flows 846,020，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_statement_items_backfill_20260617_004912.db`。EPS / 毛利率 / 營益率 / ROE / 業外損益已接 factor records / diagnostics，但不接 `ScoringEngine`。

Month 5 基本面 factor layer 收尾（2026-06-17）：季度財報已接入 `FundamentalSQLiteProvider` 與 `FundamentalFactorService`，新增 EPS、gross margin、operating margin、ROE、non-operating income ratio factor adapters；各指標只輸出 factor records / diagnostics，不輸出 score、不接 `ScoringEngine`。正式 DB `decision_date=2026-06-30` inspection 結果為 factor records 14,840、diagnostics 812；statement factors 分別為 EPS 1,411、gross margin 1,368、operating margin 1,374、ROE 1,277、non-operating income ratio 1,261。P/B / P/S source policy inspection 已改為 guarded ready：只接受 governed external observations 或後續明確 backfill records，不在系統內推導估值分子 / 分母，也不接 ScoringEngine。

Month 5 月營收 availability mapping 最新補充（2026-06-17）：已新增 `data_module/monthly_revenue_availability_history.py` 與 `scripts/build_monthly_revenue_availability_history.py`，支援 `--start-period 2020-01`、`--end-period 2026-05`、`--markets twse,tpex`、`--stock-code`、`--mops-html-dir`、`--mops-static`、`--pit-csv` 與候選 CSV output。TWSE `/opendata/t187ap05_L` 與 TPEX `/openapi/v1/mopsfin_t187ap05_O` 最新月來源都有 `出表日期`，樣本 `2330`、`9935`、`3207` 已驗證；但 OpenAPI 未提供歷史 period query。MOPS historical static report 可透過新版 `/mops/api/redirectToOld` 取得 `mopsov.twse.com.tw/nas/t21/...` HTML，`113/04` 上市/上櫃彙總表可解析到 `2330`、`9935`、`3207` rows，但頁面 `出表日期` 是查詢當日重新出表日，不是原始公告日；builder 與 validator 已用 `as_of_date + 45 days` 合理揭露窗口擋下這類過晚日期。免費官方來源目前仍未找到可批次追溯原始歷史公告日的路徑；TEJ point-in-time 月營收公告日列為授權匯出候選來源，`--pit-csv` 必須搭配非空 `--pit-source-version`，且只產生 candidate mapping。`--mops-html-dir` 可讀人工保存且含 `出表日期` 的 MOPS 官方 HTML，source 為 `mops.monthly_revenue_announcement`，缺 `出表日期` 或公司列時 fail-closed diagnostics。本機 raw 月營收期間為 `2014-04..2024-04`，與最新月 `2026-05` 來源無交集；`2020-01..2026-05` OpenAPI dry-run 結果為 `requested_periods=77`、`fetched_periods=1`、`matched_raw_monthly_revenue_rows=0`、`missing_availability_rows=76902`、`duplicate_mapping_rows=0`。正式 mapping 寫入與 `fundamental_monthly_revenues` apply 仍需人工確認。

Month 5 月營收候選資料抓取補充（2026-06-16）：新增 `scripts/fetch_mops_monthly_revenue_snapshot.py` 與 `scripts/fetch_finmind_monthly_revenue_create_time.py`。前者抓 MOPS 完整市場月營收 snapshot，保存 raw HTML 與營收值 candidate CSV，不推定官方公告日；若自某日開始每日保存 MOPS snapshot，該日可作本機 first-seen observation candidate，並以 `first_seen+1 calendar day` 作保守 candidate mapping。後者以 FinMind token 逐檔抓 `TaiwanStockMonthRevenue.create_time`，輸出 create_time 分組與候選 `available_date_candidate=create_time+1 calendar day`，但 create_time 只代表 FinMind 觀測 / 入庫日，目前退為備用 / 交叉檢查與每月分批更新依據。MOPS snapshot 已補齊 `2014-04..2026-05`、twse/tpex 共 292 個 raw HTML，候選 CSV 244,499 rows、0 duplicate `(market, period, stock_code)`；2026-05 MOPS first-seen candidate validator accepted 1,848 筆，`--mops-snapshot-file` backfill dry-run 為 `ready_for_apply=true`、normalized 1,848 筆、diagnostics 0，且 normalized source 保留 `mops.monthly_revenue_static_snapshot`。依使用者確認後，正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 已寫入 1,848 筆 MOPS first-seen mapping，`fundamental_monthly_revenues` 已回填 1,848 筆 2026-05 records，期間 `2026-05..2026-05`、股票數 1,848、0 duplicate `(stock_code, period, source_version)`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_mops_monthly_revenue_backfill_20260616_203031.db`。主 UI「資料更新」頁已新增「月營收」分頁，可從 MOPS snapshot 執行 dry-run 或確認後正式寫入 SQLite。毛利率屬 MOPS 季度財務比率 / 財報資料，不納入今晚月營收流程。

- 金融核心數值計算與邊界（如交易成本、手續費、PnL、持倉 average_cost）：改動需極度謹慎，且必須通過 `scripts/check_financial_float_boundaries.py` 及 pytest repository gate 的自動防回歸掃描。
- `app_module/backtest_service.py` / `backtest_module/*`
- `app_module/recommendation_service.py`
- `decision_module/scoring_engine.py` / `decision_module/strategy_configurator.py`
- `decision_module/factors/*`（Factor Contract、available_date gate、fundamental adapter 邊界）
- `app_module/strategies/*`（fixed / quantile 門檻、確認天數與 Look-ahead 契約）
- `app_module/recommendation_replay_service.py` / `app_module/recommendation_portfolio_backtest_service.py`
- 推薦 / 固定組合回放的現金帳、再平衡、Liquidity / Gap 標記（Month 3 v1 已完成；後續執行模型深化仍屬高風險）
- `app_module/research_run_service.py` / `app_module/research_run_repository.py`（Research Run Registry metadata、Parquet hash、archive / promoted guard）
- Strategy registry / preset / promotion 相關服務
- UI ↔ service contract（DTO）
- `runtime/` 核心子系統與 FSM 狀態機
- `ui_qt/widgets/fast_chart_widget.py` / `ui_qt/widgets/chart_payloads.py`（回測圖表 renderer 與資料 payload contract）
- `ui_qt/views/update_view.py` / `app_module/update_service.py`（數據更新工作台與安全更新流程）
- `portfolio_module/core.py` / `app_module/portfolio_condition_monitor.py`（Portfolio domain 與條件監控）
- Daily Decision Desk / Market Breadth / Sector Rotation / Watchlist Trigger / Portfolio Alert 聚合層（`MISSING` / `DEGRADED` / `ESTIMATED` 可降級，實作時不得在 UI 複製 domain 計算）

分位數治理的額外風險：

- 回測 T 日門檻只能使用 T-1 以前的分數，禁止使用完整期間分布。
- 推薦橫斷面排名必須先固定當日 eligible universe。
- 舊策略未提供 `threshold_mode` 時必須維持 fixed，確保歷史回測可重現。

## 指定權威文件（需要細節再看）

- `DEVELOPMENT_ROADMAP.md` - Roadmap Hub，指向目前狀態、6 個月路線、架構與 archive。
- `ROADMAP_6M_ENGINEERING.md` - 未來 6 個月可執行工程路線。
- `VERSION_ROADMAP_V1_1_TO_V2_0.md` - V1 release 後至 V2.0 的版本化交付節奏，說明 V1.1 workflow bridge 與 V2.0 Unified Decision Workbench 邊界。
- `../01_architecture/system_vision_specification.md` - baldr 產品北極星、目前邊界、Gap Register 與投資有效性驗證框架；不作為目前可用功能依據。
- `LEGACY_ROADMAP_CARRYOVER.md` - 舊 Roadmap 未完成事項的逐項移交與結案 Gate。
- `DOCUMENTATION_INDEX.md` - 文檔索引。
- `DOCUMENTATION_STRUCTURE.md` - docs 資料夾歸屬、生命週期、刪除/歸檔規則。
- `DOC_COVERAGE_MAP.md` - 文檔覆蓋矩陣與 scoped authority 規則。
- `../01_architecture/system_architecture.md` - 目前系統架構與模組邊界。
- `../07_guides/APPLICATION_MANUAL.md` - 目前 8 個工作區的完整操作手冊。
- `../../PROJECT_NAVIGATION.md` / `../../PROJECT_INVENTORY.md` - 專案導航與盤點。
- `../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md` - 舊完整 Roadmap，僅供歷史追溯。
- `../superpowers/specs/2026-06-13-strategy-scoring-governance-design.md` - fixed / quantile 雙模式與分位數安全契約。
- `../06_qa/WALK_FORWARD_COMPARISON_REPORT.md` - Fixed / quantile OOS 實證、Regime 分層與 Gate 證據。

---

**注意**：此 Snapshot 是目前狀態入口；未來方向請看 6 個月工程 Roadmap，架構細節請看 system architecture，完整歷史請看 archive。

## 2026-06-14 舊測試治理與模組責任確認

- repo 根目錄已建立正式 `pytest.ini`，預設只收集可重現的自動測試；
  `tests/manual/` 與 `tests/scripts/` 明確排除。
- 早期測試引用的 `DataConfig`、`DataProcessor` 並非被移除後遺失功能的正式
  API。現行責任由 `TWStockConfig`、`DataLoader`、
  `TechnicalIndicatorCalculator` 與各領域 service 分工承接。
- `PatternAnalyzer`、`TechnicalAnalyzer` 仍為現行功能，正式路徑分別位於
  `analysis_module.pattern_analysis` 與 `analysis_module.technical_analysis`。
- 固定真實路徑、外部網路、互動輸入、繪圖與長時間訓練腳本已移至
  `tests/manual/` 並標示棄用，不再阻塞 pytest collection。
- 設定、DataLoader 與技術分析測試已改寫為現行 API、正式資料 schema 與
  `tmp_path` 隔離契約；完整 pytest 為 `344 passed`。

 
## 2026-06-09 Roadmap Rebaseline（歷史記錄）

- 當時 Roadmap current section 從舊線性 Phase 敘事重寫為三個產品閉環（資料與市場狀態、研究驗證、持倉檢查）+ Backlog + 技術治理 Next。
- Phase 4.1 已標記為「Portfolio MVP 已建立，深化仍在進行」；Phase 5 圖表渲染已標記完成，其餘項保留。
- 當時本週優先事項改為 Rebaseline → 回測時間軸契約 → 金融核心數值治理。
- Blockers / Risks 新增回測時間軸未定義、金融核心裸 float、文檔不一致三項。
- 高風險區新增 `portfolio_module/core.py` 與 `app_module/portfolio_condition_monitor.py`。
- 指定權威文件新增 `NEXT_ACTION_PLAN.md`。

## 2026-06-13 Strategy & Scoring Governance (增量 B：推薦橫斷面排名) 成果

- **橫斷面百分位排名元件實作**：實作 `calculate_score_percentiles` 函式，採用 empirical CDF 計算公式，並以 `bisect_right` 保證同分時取得相同百分位，徹底鎖定排名演算法之統計一致性與輸入順序無涉。
- **策略推薦服務與 metadata 追溯**：整合 `RecommendationService`，在合格母體大小不足時拋出 `RecommendationUniverseTooSmallError` 且拒絕降級；在符合百分位門檻下注入 `score_percentile_bp` 等元數據，並使用 total_score 降序與 stock_code 升序進行穩定化排序。
- **DTO 與儲存庫 round-trip 還原**：於 `RecommendationDTO` 擴充 metadata 欄位，實作相容英文、中文 key 且向後相容歷史 JSON 數據的 `from_dict` 方法，並經 `RecommendationResultDTO` 還原驗證。JSON 檔案自動落盤，不破壞 SQLite schemas。
- **推薦 UI 欄位與控制項整合**：重構 `RecommendationView` 於進階模式下提供門檻模式、最低百分位、最小母體數及排名方法控制項，且隨 fixed/quantile 動態隱藏與顯示；在結果表格中顯示百分位與母體，並於母體不足時發出友善警示與調整建議。
  - **測試驗證**：新增單元測試 `tests/test_recommendation_percentile_ranker.py`、`tests/test_recommendation_ranking_service.py` 與 `tests/test_recommendation_dto_roundtrip.py`，並納入 UI workflow 與推薦組合回測重播驗證。

## 2026-06-13 Strategy & Scoring Governance (增量 A：回測雙模式門檻) 成果

- **純門檻評估元件實作**：實作 `ScoreThresholdPolicy`，支援 `fixed` 與 `quantile` 雙門檻模式。在 `fixed` 下完全向後相容舊策略；在 `quantile` 下，基點範圍採 0-10000 整數以符合量化防禦條款，並實作單股 Expanding 歷史分位數計算（暖機期 60 天），徹底排除未來函數 (Look-ahead bias)。
- **策略執行器與回測整合**：將 `ScoreThresholdPolicy` 成功接入 `BaselineScoreExecutor`、`MomentumAggressiveExecutor` 與 `StableConservativeExecutor`。擴充 `BacktestService` 診斷，在 quantile 下從訊號中安全提取動態門檻、暖機狀態與命中天數等指標，不再在 service 重算分位數。
- **UI 與最佳化表單對齊**：
  - 更新正常參數表單，支援 `threshold_mode` 等 choice 下拉選單（`QComboBox`），並在模式切換時動態隱藏/顯示對應欄位。
  - 重構最佳化參數表單 `_update_optimization_params_form`，將每一行包裹在 `row_widget` 中以支援最佳化面板的行動態顯示/隱藏。Choice 參數不再生成數值範圍，僅能作為固定值進行參數掃描。
- **無交易診斷與 Preset 存取**：更新無交易診斷文案，若採用 quantile 模式，會動態顯示暖機進度與命中次數，不再建議降低 `buy_score`；完成 5 個新參數在 Preset & StrategyVersion 的 100% round-trip 一致性驗證。
  - **測試驗證**：新增單元測試 `tests/test_score_threshold_policy.py`、`tests/test_strategy_threshold_modes.py`，並在 `tests/test_ui_qt_research_workflow.py` 新增下拉選單載入、顯示切換及無交易診斷測試。

## Strategy & Scoring Governance 驗證限制

- 功能與機制回歸已完成。
- 2026-06-14 已完成 10 檔股票、每檔 8 個 OOS fold 的比較；fixed 57 筆、quantile 79 筆交易與 100% Regime coverage 均通過 Gate（詳見 [WALK_FORWARD_COMPARISON_REPORT.md](../06_qa/WALK_FORWARD_COMPARISON_REPORT.md)）。
- Quantile 平均 OOS Sharpe 未優於 fixed，因此維持 opt-in，不宣稱改善績效或穩健度。

## 2026-06-11 券商分點擴充與數據更新流程分流成果

- **券商分點擴充、長碼解密與總公司判定**：在 `BrokerBranchUpdateService` 中實作 Unicode 長碼解密 `_decode_unicode_hex` 與總公司判定邏輯，自動在載入 registry 時將 16 進位 Unicode hex 長碼（如 `003800380038004b`）解密為真實短碼（如 `888K`），並在符合條件時動態判定為總部。已完成 37 個分點的擴充。
- **資料更新流程分流（快速更新 vs 安全更新）**：將 `UpdateView` 一鍵更新按鈕重構分拆為「快速更新（跳過大型合併）」與「安全更新（完整 CSV + SQLite）」。當 SQLite 啟用時，快速更新會略過大 CSV 合併重寫以提升日常更新速度，安全更新則強制執行 CSV 合併以備份資料庫。
- **測試與驗證 100% 綠燈**：新增單元測試 `tests/test_broker_branch_decode.py` 覆蓋解密與總部判定。單元測試、mypy 型態檢查、py_compile 與 QA 驗證腳本皆順利通過。

## 2026-06-11 持倉管理籌碼面監控與下鑽 (Phase 4.2 Portfolio Chip Monitor & Drill Down) 成果

- **籌碼監控服務實作**：實作 `PortfolioChipService`，支援 SQLite 和 CSV 雙軌，計算主力淨買賣超、集中度、連續流向天數，並評估結構化籌碼風險級別（`bullish`/`neutral`/`bearish`）。
- **持倉籌碼監控 UI Tab**：在右側面板新增「籌碼監控」Tab，呈現籌碼風險警告卡片與追蹤分點近 5 日買賣明細表格。
- **雙向下鑽與定位連動**：新增「🔍 下鑽詳細主力流向」按鈕，程式化切換至「市場觀察 -> 主力流向」子 Tab；主力流向 View 實作 `select_stock` 以自動定位並高亮該股，完成下鑽閉環。
- **測試與驗證全綠**：新增 `tests/test_portfolio_chip_monitor.py` 測試。mypy、py_compile 與 `qa_validate_update_tab.py` 驗證皆綠燈通過。

## 2026-06-11 持倉管理深化 (Phase 4.1 Portfolio Deepening) 成果

- **策略版本與推薦來源追蹤視圖**：在持倉管理 UI 右側 `QTabWidget` 中，新增專屬的 **「策略與價格監控」分頁**。若持倉來自策略版本升級，會自動載入 `StrategyVersionService` 以展示其版本號、升級時間、回測績效（總報酬、Sharpe、MaxDD）及參數細節；若來自推薦引擎，則展示對應推薦 Profile 與 Regime 假設。
- **價格對照與未實現損益顯示**：在庫存持倉列表中，新增展示「目前價格」、「未實現損益」與「未實現損益%」。最新收盤價支持 SQLite 直查與 CSV 降級載入，損益計算嚴格遵循 `Decimal` 金額邊界治理。
- **持倉層複合風險提示**：重構 `PortfolioConditionMonitor.evaluate`，結合 Regime 變化、Score 退化與最新價格相對於進場平均成本的偏離度。新增支援固定百分比的 **停損（stop_loss_pct）** 與 **停利（take_profit_pct）** 監控判定。當觸發停損/停利時會自動標示為 `假設失效 (invalid)`，並提供詳細的文字與配色複合警告。
- **型態檢查與 QA 驗證全部綠燈**：Pytest 新增單元測試 `tests/test_portfolio_deepening.py` 完整覆蓋最新價格計算與 SL/TP 警告機制；mypy 零型態錯誤、py_compile 全部成功，UI 與數據庫同步測試 `qa_validate_update_tab.py` 21 項全部 passed！
- **金融數值邊界治理修補與白名單擴展**：補齊 `portfolio_service.py` 與 `portfolio_condition_monitor.py` 缺失的 `# numeric-boundary: dto`，並將 monitor 納入白名單，徹底通過靜態邊界合規門禁（Repository Gate）。
- **策略版本與回測深度串接**：實作了三層防禦查找機制（`source_summary` ➔ `BacktestRunRepository` ➔ `StrategyVersionService`），解決從 Backtest 匯入持倉時 UI 無法直接關聯策略版本資訊的 Gap，並為未升級的回測 run 持倉提供專屬 UI Fallback 展示。

## 2026-06-11 技術治理進展

- 金融 float 邊界與防回歸掃描治理已完成：建立固定金融核心白名單（6 個核心檔案），利用 AST 靜態解析掃描未標記的 `float` 邊界，實行 `dto` / `analytics` / `visualization` 註解分類管制（`# numeric-boundary: <category>`），並加入 pytest repository gate 以防回歸。
- 回測時間軸契約治理已建立初版防線：`BrokerSimulator` 的 `next_open` 帳務錯位已修正，T 日訊號不再提前反映 T+1 成交；`close` 模式與推薦組合回測同日收盤成交假設已加入 warning / metadata。
- 金融核心數值治理核心金額邊界已完成：以 `Decimal`、整數股數與基點處理交易成本、整股邊界與金額量化。`BrokerSimulator`、`portfolio_module/core.py`、`backtest_module/performance_metrics.py`、`app_module/recommendation_portfolio_backtest_service.py` / DTO、`app_module/portfolio_service.py` 的核心金額與持倉平均成本等皆已改用 Decimal 計算，已徹底排除裸 `float` 帶來的精準度風險。

## 2026-05-27 補充狀態

- Recommendation Portfolio Backtest 已開始補強穩健性分析：目前已加入 Sharpe Ratio、Sortino Ratio 與 Monte Carlo P05/P50/P95 模擬報酬，並顯示在 Backtest 的「推薦組合」總覽。後續若要再深化，下一步是做 rolling Sharpe/Sortino、VaR/CVaR 或更完整的 metric/factor layer。
- Recommendation Portfolio Backtest 的 portfolio value 已改為每日 mark-to-market，Backtest「推薦組合」結果頁新增 Portfolio Value / Drawdown 圖表，並會嘗試載入大盤基準線做比較；目前停損/停利與策略學習閉環尚未納入推薦組合路徑。
- Recommendation Portfolio Backtest 已接入停損 (%) / 停利 (%) 提前出場，並在結果總覽顯示出場原因統計、虧損交易占比與最拖累股票；策略版本儲存與自動學習閉環仍待下一步。
- Recommendation Portfolio Backtest 已新增獨立 research run 保存庫，可保存/載入/刪除推薦組合回測結果，產生 rule-based 改善建議，並可將通過最低條件的推薦組合 run 升級為策略版本；此保存模型與一般單股 BacktestRunRepository 分離。

## 2026-05-30 SQLite 儲存、Bug 修復與全量技術指標重算升級成果

- **SQLite 資料庫儲存升級與全量遷移 (research/sqlite-storage) 圓滿完成**：已成功在分支上完成 CSV 到 SQLite 升級與無縫向後相容層重構。
- **大盤指數與日期標準化 Bug 完美修復**：修復了西元年無補零被民國年錯誤加 1911 的解析大 Bug（產業指數結束日期完美修正為 `2026-05-29`，無任何髒數據）；修復了大盤指數 KeyError Bug，成功導入 **3,008 筆** 歷史加權指數記錄（覆蓋 `2014-01-02` 至 `2026-05-29`）。
- **技術指標全量重新計算並高速寫入 SQLite**：重構了指標計算腳本與 UI 服務層，成功執行一鍵全量指標重新計算（1,157 檔個股，僅耗時 1 分 51 秒），成功將 **2,802,159 筆新重算的技術指標資料** 同步批次寫入 SQLite 資料庫的 `technical_indicators` 表，數據對比 100% 精準吻合。
- **322 倍回測資料載入加速**：回測載入單股價格歷史時間由大 CSV 的 **8.37 秒** 直降至 SQLite 複合索引查詢的 **0.025 秒 (25 毫秒)**，效能飆升 **322.9 倍**！
- **UI 狀態加載毫秒級「秒開」優化**：重構 `check_data_status` 等數據狀態統計方法，當 SQLite 啟用時 100% 改由 SQL 極速聚合統計，徹底避開幾百 MB 的 CSV 硬碟掃描。
- **UI ↔ Service 合規性 100% 通過**：通過 `test_ui_qt_update_view_workbench.py` (7/7 passed) 與 `qa_validate_update_tab.py` (21 passed, 0 failed)，系統完好無損，穩定性極佳。

## 2026-06-02 安全更新 Phase 1 DB 同步補強

- **安全更新補上 CSV → SQLite 同步鏈**：日常「安全更新所有數據」仍保留既有 CSV 下載、合併與人工檢查習慣，但會在每日股價、大盤、產業、合併每日資料與合併券商分點成功後，同步寫入 `daily_prices`、`market_indices`、`industry_indices` 與 `broker_flows`，降低 UI 狀態 DB-first 與更新流程 CSV-first 之間的分岔風險。

## 2026-06-03 SQLite DB-first 讀取改造與視覺化 Table 檢視 (Phase 2A, 2B & 2C) 成果

- **SQLite 視覺查詢資料表 (Phase 2C) 實作完成**：實作了 `SqliteInspectorService` 與 `SqliteInspectorWidget` 並將其整合至數據更新工作台中。支援資料表 Preview、欄位定義 (Schema) 檢視、自訂唯讀 SQL 執行展示、錯誤輸出、以及非同步載入防止 UI 假死，並配備嚴格的安全防禦機制（僅允許唯讀的 SELECT 查詢且強制進行 Limit 限制，防範 SQL Injection 與大數據崩潰）。
- **數據讀取 SQLite 優先 (DB-first) 圓滿完成**：重構了強勢股篩選 (StockScreener)、市場狀態偵測 (MarketRegimeDetector)、產業映射器 (IndustryMapper) 及推薦服務 (RecommendationService)，數據載入 100% 實現 SQLite 優先與 CSV 備用降級，徹底消除遍歷讀取磁碟小 CSV 的 I/O 毒瘤。
- **一鍵安全更新效能 Hotfix 完美修復**：優化了 `_date_key` 日期格式解析函數，避免在百萬行資料中因逐行呼叫 `pd.to_datetime` 造成的嚴重的 CPU 與 I/O 開銷。產業指數日期轉換由 13.19 秒縮短至 **0.136 秒** (提速 100 倍)，286 萬筆每日股價同步寫入 SQLite 僅需 **59.35 秒**。所有單元測試與 QA 驗證全部通過。

## 2026-06-03 CSV 手動匯出與更新流程優化 (Phase 3) 成果

- **停止日常更新大型 CSV 重寫**：當啟用 SQLite 時，日常安全更新直接將新下載的單日 CSV 同步寫入 SQLite 庫（包含個股價格與主力分點），跳過重寫 `stock_data_whole.csv` 與主力分點大合併 CSV 等大型檔案，避免磁碟 I/O 重擔。
- **技術指標增量同步優化**：增量計算技術指標時，略過保存 `all_stocks_data.csv`，並在同步 SQLite `technical_indicators` 表時，改為只針對有更新的 `(證券代號, 日期)` 組合進行舊記錄刪除後追加寫入，不執行全表 `DELETE`。
- **各 subtab 加入「匯出 CSV」**：在數據更新工作台的五大數據 subtab 中新增「匯出 CSV」按鈕，支援非同步匯出指定範圍或全量 SQLite 記錄至 CSV 備案，檔名與日期格式（`YYYY-MM-DD`）符合人工檢查需求，且使用 UTF-8 with BOM 避免 Excel 亂碼。
- **測試與驗證 100% 綠燈**：Pytest 與 QA 驗證全部安全通過，mypy 零新增錯誤。

## 2026-06-03 主力流向 (Smart Money Flow) 視覺重構與排版優化成果

- **UI 左右分欄與架構重構**：將主力流向 Tab 重構為左右分欄布局（左側主表佔 65%，右側詳情面板佔 35%）。右側面板新增「選中股雷達摘要卡片」與「訊號原因解析」，改善籌碼流向的可讀性與解釋性。
- **中文化玻璃擬態卡片**：將頂部四張小卡片（市場趨勢、熱度、多空個股數、異常警示）完全繁體中文化，並放大標題（11px）與數值（15/16px）字型，提升視覺質感與操作清晰度。
- **Sparklines 漸層與 ToolTip 懸浮提示**：為 Sparkline 微型圖表實作漸層面積填色（`QLinearGradient`），並收緊為顯示「最近 5 筆交易明細」，解決不同週期切換導致空白或不規律的問題。實作全列 `Qt.ToolTipRole` 強制觸發，使滑鼠懸停於表格任何單元格時皆能顯示詳細的最近交易明細。
- **排序功能與 Bug 修復**：
  - 修復點擊表格標頭無法排序的問題（在 `TerminalTableModel` 與 `BranchTrackerTableModel` 中實作 `sort()` 方法）。
  - 修復多空個股數中「偏空個股數恆定為 0」與「市場熱度恆定為 100%」的 Bug（改由 unfiltered 數據重新統計多空家數，並收緊偏多異常判定至 `score >= 80` 且 `net_qty >= 500`）。
  - 完整重構說明對話框（InfoButton），提供功能說明的繁體中文對齊。

## 2026-06-03 數據更新工作台 (UpdateView) 視覺重構與架構優化成果

- **主看板升級與狀態卡片 (`StatusCard`)**：將「全部資料」頁面重構為極簡數據看板，移除了所有手動配置與雜亂按鈕。設計了 StatusCard 元件（圓角、Hover 漸變與陰影效果），整合四色狀態指示燈（🟢/🟡/🔴/⚪）顯示最新日期與筆數，與原 `QTextEdit` 介面相容度 100%。
- **進階與手動操作配置歸位**：解耦原有界面，將下載日期範圍、手動下載與合併按鈕搬移至個別專屬分頁（每日股價、大盤、產業、券商分點、技術指標）。每日股價分頁中，以紅色警示邊框封裝了 **Danger Zone (高風險區)** 存放強制重新合併按鈕。
- **全域底部日誌 Console 與進度條共享**：將 QProgressBar、進度 Label 以及 Terminal 日誌輸出框移至最外層佈局的最下方，實作分頁切換時日誌與進度的全域共享。Console 採用深色背景、Consolas 等寬 11px 字型與微型清除按鈕。
- **日期聯動同步與委派更新**：在 `UpdateView` 中實作了日期聯動邏輯，任何分頁修改日期皆會透過 blockSignals 同步更新其他分頁元件。手動更新按鈕透過 `_dispatch_update()` 自適應設定隱藏的對應 RadioButton 狀態，實現 UI 與原 Service 業務代碼的無縫相容。
- **自動與 QA 測試 100% 綠燈**：通過 mypy 無新增錯誤，`tests/test_ui_qt_update_view_workbench.py` (9 passed) 與 `scripts/qa_validate_update_tab.py` (21 passed, 0 failed) 順利通過。

## 2026-06-04 Research Lab 工作流重整

- Research Lab 第一階段開始將回測頁定位為多模式研究實驗室，區分單股回測、批次股票回測、固定組合回測、推薦系統回放與策略研究。
- 觀察清單在研究流程中重新定位為候選池 / 實驗 Universe，用於回答「我要測哪一批」。
- Recommendation / Backtest 記錄到 Portfolio 時將保留來源 metadata，讓交易紀錄可追溯到推薦結果或回測 run。

## 2026-06-11 券商分點單位契約修正

- 既有爬蟲固定使用 MoneyDJ `c=B`，其數值是仟元，不是張數。
- 更新流程改為同時抓取 `c=E` 張數與 `c=B` 仟元並分欄保存。
- 舊 B-only 資料保留，但不再進入 Phase 4.2 張數判斷；重新抓取 E 後才具備有效籌碼訊號。

## 2026-06-12 券商分點 Ranked Metric 資料品質治理

- MoneyDJ `c=E` 張數與 `c=B` 金額確認為各自獨立 Top 50 榜單，資料層採 union 並保存 observed 狀態、方向與 rank。
- Smart Money 與 Portfolio Chip Monitor 使用 observed / estimated / unavailable 三態，單筆不可用不再污染同股票其他事件。
- 正式 `broker_flows` 已由既有 daily 檔無破壞重建為 104,986 筆、158 天，rank 範圍 1 至 50，唯一鍵與 NULL 契約檢查均通過。

## 2026-06-24 券商分點 MoneyDJ HTTP fast path

- MoneyDJ 券商分點更新改為先使用 HTTP fast path 抓取 Big5 HTML，正常頁面不再先啟動 Selenium；HTTP 失敗或解析不到資料時才退回 Selenium fallback。
- 預設請求間隔由 4.0 秒調整為 0.5 秒，仍維持序列更新，暫不啟用多 worker 併發。
- 更新日期會先以每日股價日檔或 SQLite `daily_prices` 作交易日預檢；沒有行情證據的日期會整天跳過 MoneyDJ，避免 40 個分點各自重試非交易日。
- 小樣本 live 驗證：`1440_1440` / `2026-05-29` 在暫存資料根目錄中不啟動 Selenium，約 1.62 秒寫出 141 筆 daily CSV。


## 2026-06-12 批次回測並行化與安全軟取消成果

- **批次回測並行化實作**：實作 ProcessPoolExecutor 並行處理機制，當回測個股數大於 threshold 時自動並行，並支援 `max_workers=None` 自適應調整 CPU 核心數。
- **合作式軟取消**：實作非暴力 cooperative 取消機制，取消時停止向進程池提交新任務，且 Worker 等待 active 子行程清空後才發送 `cancelled` 信號並恢復 UI 按鈕，避免 UI 提前解鎖造成新舊任務重疊。
- **唯一性 run_id 寫入**：在循序與並行路徑皆引入 UUID 來生成唯一 `run_id`，避免 SQLite 與 parquet 同秒覆寫衝突。
- **TaskWorker 軟取消回歸防護**：保留 `TaskWorker` 取消時的 legacy `terminate()` 行為，並將新合作式軟取消限制在回測專用 Worker，維持 Update、Recommendation 與 SQLite Inspector 等既有頁面的行為相容；legacy 強制終止風險列為後續技術債。
- **測試與驗證**：新增單元測試 `tests/test_backtest/test_parallel_safety.py`，覆蓋 UUID 唯一性、軟取消、自適應循序分流、非法股票處理、真實 `BrokenProcessPool` 異常重現及 `max_workers=None`。

## 2026-06-14 SQLite 檢視器穩定分頁與規格化 Excel 報告匯出成果

- **SQLite 檢視器資料庫層分頁**：
  - 於 `SqliteInspectorService` 實作 count 與 offset 穩定分頁，共用 filter builder。
  - 設計 `日期 DESC, 證券代號 ASC` 搭配 `rowid ASC` 穩定排序，保證跨頁無重複與遺漏。
  - UI 介面整合「上一頁/下一頁/跳頁/當前與總頁碼」控制列，並在篩選變更時自動重設回第一頁，且快取 schema 避免重複拉取。
  - 實作單調遞增 `request_id` 防 stale 異步查詢覆蓋最新結果；快速連續查詢會保留各執行中 worker 至自然結束，避免斷開或提前銷毀 `QThread`。
- **四種規格化 Excel 報告背景匯出**：
  - 定義防禦性複製 payload DTO 快照 (`report_export_dtos.py`)：單股、批次、組合回放、目前推薦結果。
  - 於 `ReportExportService` 實作 Excel workbook 的資料格式化 (金額/百分比/天數/日期)、自適應欄寬上限與凍結/自動篩選。
  - 開闢「資料完整性」專用區域，在缺少追溯元數據時明確標註 `N/A` 並列出缺失欄位清單。
  - 整合 Pyside6 `TaskWorker` 於背景線程寫入暫存檔，完成後採原子替換 (`os.replace`)，保障 UI 介面不假死且不破壞原有報告。
  - 匯出 payload 直接使用正式 `BacktestReportDTO` / `BatchBacktestResultDTO` 欄位與推薦回放執行快照；缺失 metadata 不以 UI 當前值或預設常數偽裝。
  - equity curve 支援 `日期`、`date` 欄位與日期 index，批次排行榜由正式 `stock_results` 建構。
  - **測試與 QA 覆蓋**：包含原檔替換失敗保留、快速連續分頁、正式 DTO、equity curve 真實形狀等回歸案例；完整 gate 以本次 commit 驗證記錄為準。

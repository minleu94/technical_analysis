# 6 個月可執行工程路線（2026-06 至 2026-12）

> **最後更新**：2026-07-04
> **定位**：本文件是未來 6 個月工程執行與研究能力成長的權威路線圖。當它與短期 Snapshot 衝突時，以 Snapshot 的「本週優先事項」決定今天先做什麼；當它與產品願景文件衝突時，本文件決定可執行交付順序。

---

## 1. 目標

6 個月內把系統從「功能已形成研究與持倉閉環」推進到「每天能產生可驗證、可回溯、可解釋的投資決策摘要」，並在 V1 release 後進一步驗證這些摘要、警示與策略生命週期判斷是否真的改善決策品質。

核心成果：

1. 保留 fixed / quantile 與後續策略變體的真實 walk-forward 實證基準線。
2. 完成研究 run、資料版本、策略版本與因子貢獻的可追溯治理。
3. 補強 Factor Layer 與推薦組合回放，使組合績效具備現金、權重、再平衡、流動性與可得日防線。
4. 建立 Daily Decision Desk，讓市場狀態、候選股票、持倉警示與研究輸入在同一個每日決策入口收斂。
5. 將營收、基本面與估值納入可插拔 factor layer，採取先標記、降權與提示風險的保守策略。
6. 建立 promote / demote / retire 與 Portfolio post-trade attribution，讓策略能被系統性升級、降級或淘汰。

V1 closeout baseline（2026-06-30）：

- 四個產品閉環已形成可操作 V1：資料與市場狀態、研究驗證、持倉檢查、每日決策。
- Strategy Lifecycle / Portfolio Feedback v1 已補上 lifecycle gate、append-only evidence、post-trade attribution 與持倉管理生命週期回顧入口。
- Full App Healthcheck / MainWindow UI smoke / clean clone gate 已形成 release QA 閉環；這是工程交付證據，不是投資有效性證明。
- 下一階段主線轉向 Evidence-Driven baldr：Forward Performance、Live vs Research Gap、Signal Decay、Decision Quality Review 與台股微結構治理。
- Post-V1 第一批 evidence 增量已完成 Evidence Event Store v1 / Forward Outcome Calculator v1 / Evidence Importers v1 / E2E smoke / Forward Performance Read Model v1 / Evidence Source Persistence v1 / Forward Performance Dashboard read-only UI v1 / Evidence Pipeline Runner dry-run v1 / working-copy DB smoke v1 / Live vs Research Gap linkage v1；這是 forward evidence 的資料底座、source capture 起點、durable Daily Decision Desk snapshot source、唯讀彙總層、Research Lab evidence inspection layer、手動 dry-run orchestration 與 gap observation linkage，不是 production scheduler 完成，也不是投資有效性證明。

---

## 2. 不做什麼

- 不把 quantile 設成預設；2026-06-14 真實股票池實證未證明 quantile 優於 fixed，維持 opt-in。
- 不把營收、財報、三大法人或估值資料直接硬塞進 `ScoringEngine`。
- 不把推薦組合回測結果宣稱為實盤績效，除非成交假設、現金帳、流動性限制與再平衡規則完整揭露。
- 不導入黑箱 ML 作為主線；若未建立資料版本、OOS、因子歸因與漂移監控，ML 只會增加不可解釋風險。
- 不重建或破壞正式資料；所有資料新增必須非破壞性、可回溯、可降級。
- Daily Decision Desk 已接上主 UI v1 首頁；Market Breadth v1 已由 SQLite `daily_prices` provider 接線，Sector Rotation v1 已由 SQLite `industry_indices` provider 接線，Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` provider 接線，Watchlist Trigger v1 已由 `WatchlistService` 與 SQLite `technical_indicators` 共同推導接線，Portfolio Alert v1 已由 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService` 共同接線。
- 不把 V1 release readiness、healthcheck 通過或 UI smoke 通過解讀為策略有效、警示有效或推薦具備正向期望值；V1 後必須以 forward evidence 與 live-vs-research evidence 驗證。

---

## 3. 工程主線

### Track A：實證與回測可信度

目的：讓每一個策略改善都有 OOS 證據，而不是只看單次回測。

已完成基礎：

- fixed / quantile walk-forward 比較報告。
- Research Run Registry 的 metadata、Parquet 明細、hash integrity、comparison 與 Promote Gate。
- 推薦組合 / 固定組合回放 credibility v1，含現金帳、權重、未成交、Liquidity、成本、整股 sizing、weight exposure 與 gap risk labels。

後續交付：

- Portfolio Replay execution model 深化：零股、買賣價差、完整撮合、跳空成交限制、成交率與未成交原因。
- rolling risk metrics：Rolling Sharpe / Sortino、VaR / CVaR、drawdown duration、turnover。
- benchmark-relative attribution、factor attribution 與 forward performance 的保存後讀取與儀表化。

### Track B：Factor Layer 與資料治理

目的：讓新資料能被安全接入，不污染既有 scoring 與回測核心。

已完成基礎：

- Factor contract：`factor_name`、`as_of_date`、`available_date`、`value`、`score_bp`、`quality`、`missing_policy`、`source_version`。
- Factor registry / gate / adapters：技術、量能、券商分點 v1。
- Research Run 保存 `factor_snapshot` / `factor_contributions` 的基礎流程。
- Fundamental Layer v1：月營收、季度財報、P/E valuation records、Fundamental provider/service、Revenue / statement / valuation adapters、available_date gate 與 diagnostics；不接 `ScoringEngine`。

後續交付：

- P/B / P/S governed external observations 或明確 backfill records；不得在系統內推導 book value、share count、market cap 或 TTM sales。
- Missing / neutral / stale / skip 的 UI diagnostics 持續深化。
- 三大法人、信用交易與處置股等新資料因子接入前，必須先補 source、available_date、quality 與 missing policy。
- 所有 factor 都必須通過 `available_date <= decision_date` 或依政策 fail-closed / neutralize / skip。

### Track C：Market Intelligence 與 Daily Decision Desk

目的：把既有市場觀察、推薦、持倉監控與研究輸入整合成每日決策入口。

V1 已完成交付：

- Daily Decision Desk 首頁。
- Market Regime Summary。
- Market Breadth：上漲 / 下跌家數、20 / 60 日新高新低、漲停 / 跌停、成交量擴散率。
- Sector Rotation：產業相對強度、5 / 20 日變化、產業內擴散率與背離。
- Relative Strength 與 Liquidity Ranking。
- Watchlist Trigger：新進候選、移除候選、強度提升 / 下降、量能 / 籌碼 / 風險條件。
- Portfolio Alert 初版：把價格、策略條件與籌碼警示整理到每日摘要。
- Why Not / 風險提示與 fundamental diagnostics prompts。

後續交付：

- Forward Performance Dashboard：Evidence Importers v1 已可將 persisted Recommendation result 與 durable Daily Decision Desk snapshot source 轉為 events；Forward Performance Read Model v1 已可唯讀彙總 ready / pending / missing outcomes、return / excess return、quality 與 warnings。Daily Decision Desk snapshot repository / capture CLI / source coverage inspection v1 已完成；Why Not / Liquidity exclusion payload 為 optional / partial。Research Lab 已新增 `Forward Evidence` read-only UI v1，可檢查 Watchlist Trigger、Recommendation、Why Not / Liquidity Gate、Portfolio Alert 後續 5 / 10 / 20 / 60 日 close-to-close research outcome、benchmark / industry 缺口與資料品質；`scripts/run_evidence_pipeline.py` 已可手動執行 scheduler dry-run runner，串接 source coverage、snapshot capture、event capture、outcome calculation、summary 與 diagnostics report，預設 dry-run，confirm 只允許 explicit working-copy DB。
- Concept Basket / 題材籃子，補官方產業分類無法捕捉台股題材輪動的限制。
- Decision Desk 的 evidence summary：每個提示能回到樣本數、forward evidence、資料品質與適用限制。

### Track D：資料擴充與保守基本面

目的：建立能支援基本面與估值研究的資料底座，但不做過度自信的自動財報修正。

V1 已完成交付：

- 月營收資料表：MoM、YoY、累計營收、資料公告日。
- 基本面資料表：EPS、ROE、毛利率、營益率、負債比、現金流、股本。
- 估值資料表或視圖：P/E、P/B、P/S、殖利率、產業相對估值分位。
- AbnormalFundamentalFlag：標記營收與獲利背離、業外損益異常、匯兌或投資收益影響。

後續交付：

- 官方歷史 point-in-time 公告日或授權 PIT 匯出來源補強；retroactive baseline / statement baseline 仍須揭露 degraded 邊界。
- P/B / P/S 僅以 governed external observations 或明確 backfill records 呈現。
- 後續三大法人資料可接入為籌碼因子，但必須保留資料品質、單位與可得日。

### Track E：Portfolio 回饋與策略生命週期

目的：讓實際交易 / 模擬持倉能反饋研究，而不只是持倉監控。

V1 已完成交付：

- 持倉原因與現況差異歸因：Regime、Score、Factor、籌碼、估值。
- 實際交易 vs 回測預期落差：進場價差、滑價、出場原因、持有天數、最大不利走勢。
- Promote / demote / retire 規則：以 OOS、持倉後驗、風險與資料品質決定策略生命週期。
- Portfolio Review Dashboard。

後續交付：

- Live vs Research Gap Dashboard：比較研究預期、推薦回放與實際 / 模擬持倉落差。
- Signal Decay Monitor：追蹤策略與訊號近期是否失效，支援 hold / demote / retire 判斷。
- Manual Approval Workflow 與 Evidence Explainability：任何改變策略狀態、策略版本可用性或 portfolio 行為的動作都需人工確認與證據摘要。

---

## 4. 月度里程碑

### Month 1：實證基準線與文件治理完成

> 2026-06-14 狀態：10 檔 fixed / quantile OOS 實證、100% Regime coverage、SQLite 穩定分頁與規格化 Excel 報告背景原子寫入均已完成。Quantile 未優於 fixed，維持 opt-in。

交付物：

- 更新 [WALK_FORWARD_COMPARISON_REPORT.md](../06_qa/WALK_FORWARD_COMPARISON_REPORT.md)，加入真實股票池比較結果。
- SQLite Inspector 穩定分頁。
- 回測 run / 推薦回放的規格化 Excel 匯出。
- Active docs 不再把舊 Roadmap 當單一最高權威。

驗收標準：

- fixed / quantile 使用同一資料版本、成本模型、成交假設與股票池。
- 報告明確列出 quantile 是否改善，若沒有改善也要保留結果。
- Phase 5 最小輸出可實際操作，且報告包含資料、策略、參數、成本、成交假設、Regime、benchmark、風險與驗證狀態。

### Month 2：參數治理、Research Run Registry 與 Cross-run Comparison

> 2026-06-14 狀態：M2-A、M2-B、M2-C 與 final registry governance gate 已完成。Month 2 後續只保留缺陷修補與回歸驗證。

交付物：

- Indicator Parameter Registry。
- Recommendation Weight Contract。
- Research Run Registry immutable save：SQLite metadata、Parquet 明細、hash 驗證、crash reconciliation、legacy backfill 與 UI 保存入口。
- Cross-run comparison UI 與服務。
- Strategy promote gate 改為讀取 registry，不只讀單次 summary。

驗收標準：

- 任一 promoted strategy 都能追溯到當時資料、參數、成本模型與結果。
- 至少能比較 3 個策略版本或 3 組參數的 OOS 指標。
- 任一推薦或策略研究 run 都能還原當時的指標參數與權重版本。

### Month 3：Factor Layer 與 Portfolio Replay 可信度

> 2026-06-15 狀態：Month 3 v1 已關閉。Factor Contract / Registry / Look-ahead Gate / v1 adapters / FactorService snapshot/contribution serialization 已落地；`ResearchRunService.save_run()` 可在實際寫入流程保存 factor snapshot 與 contribution summary。推薦組合回放、單股回測、批次回測與固定組合 per-stock 保存都能供給 factor records / metadata。推薦組合回放已輸出 `portfolio_credibility`、缺價型 `unfilled_orders`、entry-day liquidity gate、cash-gated holding creation、optional bps execution costs、optional full-lot sizing、target / executable `weight_exposure` 與 partial `gap_risk` labels。v1 不接營收、法人或估值新資料源，也不改 `ScoringEngine` 核心；零股、買賣價差、完整撮合與 Gap 實際成交模型列為後續執行模型深化。

目標：

- 完成 Factor Layer v1 的保存覆蓋。
- 補強推薦組合與固定組合回放可信度，避免後續策略生命週期建立在不完整績效上。

交付物：

- 推薦組合回放、單股回測、批次回測與固定組合 per-stock factor records / metadata 供給已接入 Registry 保存路徑。
- Factor Gate / adapters focused regression 與 no-look-ahead tests。
- 推薦組合回放已具備 `portfolio_credibility` 限制揭露、缺價型 `unfilled_orders`、entry-day 成交量參與率檢查、cash-gated holding creation、optional bps execution costs、optional full-lot sizing、target / executable weight exposure 與 partial gap risk labels；後續補零股、買賣價差、完整撮合與 Gap 實際成交模型。
- Liquidity / Gap 風險在回放結果摘要中可追溯。
- PDF 報告輸出可保留為研究輸出 backlog，不阻塞 Month 3。

驗收標準：

- 缺少某因子資料時回傳 `missing`、`neutral` 或 `skip`，不讓流程中斷且留下 diagnostics。
- factor `available_date` 晚於決策日時必須 fail-closed、neutralize 或 skip，依 factor policy 處理且留下 diagnostics。
- `ScoringEngine` 不直接依賴新資料表。
- 推薦組合 / 固定組合回放結果能揭露現金、權重、再平衡、成交限制與風險標記。

### Month 4：Market Intelligence 與 Daily Decision Desk（v1 已上線首頁）

目標：

- 讓系統每天打開就能回答「今天市場怎麼了、我該研究誰、我的持倉有沒有問題」。

交付物：

- Daily Decision Desk 首頁或等價頂層工作區（已上線 v1）。
- `DecisionDeskSnapshot` / `DecisionDeskSnapshotBuilder` 或等價 DTO / service。
- Market Breadth service（v1 已接 SQLite `daily_prices`，輸出多方 / 空方 / 持平與新高新低、成交量擴散等 metadata）。
- Sector Rotation service（v1 已接 SQLite `industry_indices`，輸出領先 / 落後產業、5 / 20 日變化與輪動強度）。
- Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` 接線，推導強弱與低流動性股。
- Watchlist Trigger service。
- Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`。
- Why Not / 風險提示 v1 已接 Daily Decision Desk，由既有 section DTO 的 quality、warnings 與屬性欄位推導，提供可行動風險提示，不重算既有邏輯。
- Manual 與 UI docs 完整描述新首頁入口、參數、結果判讀與限制（含 `OBSERVED`、`ESTIMATED`、`DEGRADED`、`MISSING`）。

驗收標準：

- Daily Decision Desk 不重算 UI 各頁資料；它透過 service snapshot 聚合已治理的結果。
- 所有市場寬度、產業輪動與 watchlist trigger 都有資料日期與品質標示。
- Liquidity Gate 結果能進入 Why Not 或風險提示，不只是回測內部限制。
- 持倉警示能回到原始來源與目前狀態差異。

### Month 5：Fundamental Layer 初版

> 2026-06-17 狀態：Month 5 v1 已關閉。Fundamental SQLite schema、月營收 baseline、季度財報 items、P/E valuation records、Fundamental provider/service、Revenue / statement / valuation adapters、available_date gate 與 abnormal diagnostics 已落地。v1 只輸出 factor records / diagnostics 與 Daily Decision Desk risk prompts，不接 `ScoringEngine`，不輸出目標價、合理價、上漲空間或交易建議。P/B、P/S presentation policy 已改為 guarded ready：只接受 governed external observations 或後續明確 backfill records；官方歷史 point-in-time 公告日仍為治理 residual，不阻塞 Month 6。

目標：

- 加入基本面觀察，但採取保守、可追溯、先標記後清洗的方式。

交付物：

- 月營收資料與公告日欄位。
- Revenue YoY / MoM / 3M trend / revenue new high factor（v1 adapter 已完成；正式 baseline 可產生 YoY、MoM、3M trend、new high records；僅輸出 factor records / diagnostics，不接 `ScoringEngine`）。
- 第一版估值視圖：P/E、P/B、P/S presentation policy 已 ready；P/B / P/S 只接受 governed external observations 或 future backfill records，不在系統內推導 book value、share count、market cap 或 TTM sales。valuation data layer v1 已可建立 governed observations 與同產業整數基點分位；輸出仍只走 presentation policy。
- AbnormalFundamentalFlag（v1 diagnostics 已完成；只作 Research metadata 與 Daily Decision Desk risk prompts）。
- Fundamental factor adapters 與 available_date gate（季度財報 EPS、gross margin、operating margin、ROE、non-operating income ratio adapters 已完成）。

驗收標準：

- 回測使用營收與估值因子時只讀 `available_date <= decision_date` 的資料。
- 估值先以相對分位與區間呈現，不輸出未驗證的單點目標價。
- 異常基本面只標記、降權或提示風險，不自動扣除業外或改寫財報；v1 已先以 diagnostics / risk prompts 呈現，不自動扣分。

### Month 6：Strategy Lifecycle 與 Portfolio Feedback

> 2026-06-17 狀態：Month 6 v1 已完成第一輪可用閉環並補上 append-only lifecycle evidence。`StrategyLifecycleService` 已提供 Promote / hold / demote / retire rule engine、`StrategyDriftDetector` 與 Regime compatibility；`LifecycleEvidenceRepository` 可保存 decision snapshot / gate reasons / version id 並投影 latest state；`PromotionReconciliationService` 的 Registry-based Promote Gate 已改用 Month 6 lifecycle gate，成功升級後會保存 applied evidence；`LifecycleEvidenceGovernanceService` 可把 demote / retire 判斷保存為 proposed evidence；`PortfolioFeedbackService` 已能輸出 post-trade attribution / live-vs-research gap；`PortfolioReviewService` 已能聚合 lifecycle summary、drift reports 與持倉 gap snapshot；持倉管理 UI 已新增「生命週期回顧」分頁。v1 仍不自動刪除、降級或淘汰策略版本，不修改 `ScoringEngine`，不把 fundamental factor 納入推薦權重。

目標：

- 讓策略與持倉進入可監控、可降級、可淘汰的生命週期。

交付物：

- Promote / demote / retire 規則（v1 rule engine 已完成；append-only evidence 與 latest state projection 已完成；demote / retire 先保存 proposed evidence，不自動刪除或覆寫策略版本）。
- StrategyDriftDetector（v1 已完成，讀兩個已保存 run 的 metrics / factor metadata）。
- Portfolio post-trade attribution（v1 已完成，拆分 source / execution / signal / market / data quality）。
- Regime compatibility（v1 已完成，以 `regime_breakdown` 與 expected regimes 計算 coverage bp）。
- Live vs research gap report（v1 已完成，從 Portfolio position / condition monitor / drift report 聚合）。
- Portfolio Review Dashboard（v1 service snapshot 與持倉管理「生命週期回顧」分頁已完成）。
- 6 個月成果回顧與下一版 roadmap 草案。

驗收標準：

- 策略不能只靠單次高報酬被升級；必須通過 OOS、風險、交易次數與資料品質門檻。
- 被淘汰策略保留原因與證據，不刪除歷史。
- Portfolio 能回答「這筆交易原始假設是否仍成立」與「落差來自訊號、執行、資料或市場」。

#### Month 6.1：人工審核層與可驗證操作流程深化

定位：Month 6 v1 已有底層 service / evidence / UI entry；下一步不是重做 lifecycle engine，而是把它整理成可人工檢查、可解釋、可驗證、可安全批准的工作流。

優先交付：

- 生命週期回顧 UI 完整 QA：逐項驗證策略狀態、gate reason、drift report、regime compatibility、portfolio gap 與 evidence projection 是否能被使用者判讀。
- Manual Approval Workflow：promote / demote / retire 預設只產生建議與 proposed / applied evidence；任何會改變策略狀態、策略版本可用性或 portfolio 行為的動作都必須經人工確認。
- Portfolio Review Dashboard 深化：讓使用者能從同一個 review snapshot 回答「原始持倉理由是否仍成立」、「目前落差來自訊號、執行、資料品質或市場 regime」。
- Strategy Evidence Explainability：每個 promote / hold / demote / retire 判斷都要能列出依據、門檻、資料品質與相關 run / portfolio source trace。
- Month 6 QA Checklist：建立人工驗證清單，覆蓋 lifecycle service、evidence repository、portfolio feedback、UI 分頁與資料品質降級情境。
- 下一版 Roadmap 草案：在完成 Month 6 人工審核流程驗證後，再決定後續主線要優先深化 execution model、factor governance、PDF report 或策略研究工廠。

不做與安全邊界：

- 不把 demote / retire 自動套用成策略刪除或策略版本覆寫。
- 不用目前 live data 取代已保存 Research Run Registry / factor metadata / portfolio source trace。
- 不因 fundamental diagnostics 存在就直接改變 `ScoringEngine` 或推薦權重。
- 不把 Portfolio Review Dashboard 的 gap report 解讀為實盤績效宣稱；execution gap、零股、bid-ask spread、完整撮合仍列後續 execution model 深化。

#### Post-V1：Evidence-Driven baldr

定位：V1 已完成工程閉環與 release readiness；下一階段的成功標準不是增加更多入口，而是證明既有訊號、警示、排除規則與策略生命週期判斷是否真的改善決策品質。

優先交付：

- Forward Performance Dashboard：Evidence Event Store v1 / Forward Outcome Calculator v1 / Evidence Importers v1 / Forward Performance Read Model v1 / Evidence Source Persistence v1 / Forward Performance Dashboard read-only UI v1 / Evidence Pipeline Runner dry-run v1 已完成資料底座、capture pipeline、durable Daily Decision Desk snapshot source、唯讀彙總、Research Lab evidence inspection layer 與手動 dry-run orchestration；後續需用 working-copy DB 做多次 dry-run / confirm smoke，持續追蹤 Watchlist Trigger、Recommendation、Why Not / Liquidity Gate、Portfolio Alert 事件後 5 / 10 / 20 / 60 日 forward return、benchmark excess return、industry / concept excess return、樣本數與資料品質。
- Live vs Research Gap：linkage v1 已可保存 portfolio source trace、Research Run / strategy version id 與 Evidence Event / Outcome 的 gap observation；後續仍需 read-only UI 與更完整人工 override 記錄，才可深化實帳歸因。
- Signal Decay Monitor：追蹤策略、因子與提示近期是否失效，提供 hold / demote / retire 的 evidence，但不自動刪除或覆寫策略版本。
- Decision Quality Review：建立週 / 月覆盤紀錄，追蹤錯誤交易、未遵守系統建議、手動 override、錯過訊號與事後歸因。
- 台股微結構治理：處置股、分盤、全額交割、跳空鎖死、除權息 / 還原價時間軸、三大法人與信用交易資料接入。

驗收標準：

- 任一 dashboard 或 review 只保存可追溯事件、結果與 evidence，不把統計觀察包裝成買賣建議。
- 所有 forward / live-vs-research 分析都保留當時資料版本、訊號來源、quality / warnings 與 benchmark 定義。
- 若 evidence 顯示某訊號、警示或 gate 無效，必須能回到 Research Lab / lifecycle review 調整或降權，而不是只增加更多提示。

---

## 5. 立即待辦清單

1. V1 release baseline 已完成；Post-V1 Evidence Event Store v1 / Forward Outcome Calculator v1 / Evidence Importers v1 / E2E smoke / Forward Performance Read Model v1 / Evidence Source Persistence v1 / Forward Performance Dashboard read-only UI v1 / Evidence Pipeline Runner dry-run v1 / working-copy DB smoke v1 / scheduler approval checklist v1 / Live vs Research Gap linkage v1 已落地。下一步優先做 Signal Decay Monitor、Decision Quality Review 與 Live vs Research Gap read-only UI。
2. Month 6.1 仍保留為 lifecycle / feedback 的人工審核深化：Manual Approval Workflow、Strategy Evidence Explainability、Portfolio Review Dashboard 深化與 QA checklist。
3. Month 5 residual 仍為治理限制：retroactive baseline / statement baseline 多數為 `degraded`，不可被誤解為官方歷史公告日；P/B、P/S policy 已關閉為 guarded external-observation 邊界；免費官方歷史月營收公告日端點仍未找到。
4. 維持 Month 2 / Month 3 / Month 5 / Month 6 的防線回歸：immutable registry save、hash integrity、registry-based promote gate、FactorGate `available_date <= decision_date`、append-only lifecycle evidence、量化 float boundary 與 no-look-ahead tests。
5. 將零股、買賣價差、完整撮合與 Gap 實際成交模型、處置股 / 分盤 / 全額交割、三大法人與信用交易資料列入後續執行模型與資料治理深化；PDF 報告輸出仍在研究輸出 backlog。


---

## 6. 驗證規則

- UI 修改：依專案規範執行 Update Tab pytest、QA script、mypy 與 py_compile。
- 策略 / 回測 / 推薦 / factor 修改：必須先寫 Look-ahead 自查，並新增 no-look-ahead 測試。
- 金融核心數值：必須通過 `scripts/check_financial_float_boundaries.py` 與對應 pytest gate。
- 資料 schema：必須提供 migration / fallback / 資料品質驗證，且不得破壞正式資料。
- Daily Decision Desk：必須以 service snapshot 聚合，不得在 UI 層複製 scoring、screening、portfolio 或 broker flow 計算。
- Post-V1 evidence dashboard：必須保存事件日期、決策日可得資料、資料版本、benchmark 定義、quality / warnings 與 forward window，不得把觀察結果包裝成交易建議。
- Evidence Event Store / Forward Outcome Calculator：schema migration 必須 dry-run / backup safe；forward return 一律標示 close-to-close research basis，不得稱為可執行績效。
- Forward Performance Read Model / Evidence Pipeline Runner：read model 只可唯讀彙總已保存 events / outcomes；ready sample 才能計入 return metric，pending / missing 只能進覆蓋率、品質與 warning。Runner 預設 dry-run，`--confirm` 必須指定 working-copy DB；working-copy smoke 必須確認 source DB read-only、重複 confirm idempotency 與 diagnostics report；scheduler readiness 最高只到 `ready_for_manual_confirm`，正式 production schedule 仍需人工批准、rollback / recovery 檢查與多次 dry-run 穩定紀錄。
- Live vs Research Gap linkage：只能保存 gap observation，不得改 portfolio / Research Run / Strategy Lifecycle；沒有真實交易與人工 override 記錄時，只能稱為 research / simulated gap；symbol/date fuzzy match 只能列 candidate，不能當作 confirmed link。
- Evidence Source Persistence：Daily Decision Desk snapshot capture 預設 dry-run、`--confirm` 才寫入；缺 durable snapshot 時 capture CLI 必須 diagnostic，不得 fallback UI 或偽造 event；Why Not / Liquidity exclusion 只可消費已保存 payload，不可重算。
- Release / healthcheck：Full App Healthcheck、MainWindow UI smoke 與 clean clone gate 只能證明工程交付可用，不得作為投資有效性證據。

---

## 7. 更新記錄

- 2026-07-05：完成 Forward Performance Dashboard read-only UI v1，新增 Research Lab `Forward Evidence` 分頁、dashboard service / DTO / Qt table model 與禁用交易語氣測試；Dashboard 只檢查已保存 evidence outcomes，不寫 evidence、不做 scheduler、不宣稱 alpha。
- 2026-07-06：完成 Evidence Pipeline Runner dry-run v1，新增 manual runner service / DTO / CLI、diagnostics Markdown/JSON report、confirm gate、production-like DB guard 與 readiness summary；scheduler 最高只到 `ready_for_manual_confirm`，production scheduler 仍未啟用。
- 2026-07-07：完成 working-copy DB smoke v1、scheduler readiness evaluator 與 production scheduler approval checklist；可在 working-copy DB 重複 confirm 檢查 idempotency，readiness evaluator 固定 `production_scheduler_allowed=false`，正式 scheduler 仍未啟用。
- 2026-07-08：完成 Live vs Research Gap linkage v1，新增 gap DTO / repository / service / capture / inspect CLI 與 matching policy；gap observation 是 evidence，不是完整實帳歸因或 lifecycle action。
- 2026-07-04：完成 Post-V1 Evidence Source Persistence v1，新增 durable Daily Decision Desk snapshot repository / capture CLI / inspect CLI、capture evidence durable provider wiring、Recommendation exclusion payload optional fields 與 source coverage CLI；Why Not / Liquidity payload 為 partial，scheduler 仍只到 `ready_for_design`，不具 production readiness。
- 2026-07-03：完成 Post-V1 E2E smoke 與 Forward Performance Read Model v1，新增 smoke CLI、read-only aggregate service、summary CLI、score percentile bucket、summary status 與 focused QA；仍未完成 dashboard UI、durable DDD snapshot source、scheduler 或投資有效性驗證。
- 2026-07-02：完成 Post-V1 Evidence Importers / Capture Pipeline v1，新增 recommendation persisted importer、watchlist / portfolio alert / risk prompt DTO importers、dry-run / confirm CLI、duplicate summary 與 unsupported-source diagnostics；當時仍未完成 dashboard read model 或投資有效性驗證。
- 2026-07-01：完成 Post-V1 第一增量 Evidence Event Store v1 / Forward Outcome Calculator v1，新增 append-only events、forward outcomes、migration safety、inspection CLI 與 focused tests；Forward Performance Dashboard、source importer 與投資有效性驗證仍未完成。
- 2026-07-01：更新 V1 closeout baseline，確認四個產品閉環、Strategy Lifecycle / Portfolio Feedback v1 與 release QA 閉環已完成；Roadmap 下一階段轉向 Evidence-Driven baldr，優先 Forward Performance、Live vs Research Gap、Signal Decay、Decision Quality Review 與台股微結構治理。
- 2026-06-17：完成 Month 5 Fundamental Layer v1 closeout，確認 fundamental schema / 月營收 / 季度財報 / P/E valuation / provider / adapters / diagnostics 已達保守接入驗收；工程主線轉向 Month 6 Strategy Lifecycle 與 Portfolio Feedback。
- 2026-06-17：完成 Month 6 Strategy Lifecycle / Portfolio Feedback v1，新增 lifecycle rule engine、drift detector、Portfolio post-trade attribution、Portfolio Review snapshot、Registry-based Promote lifecycle gate 與持倉管理生命週期回顧分頁。
- 2026-06-17：補上 Month 6 lifecycle residual，新增 append-only lifecycle evidence repository、current state projection 與 demote / retire proposed evidence 保存；Promotion 成功後會記錄 applied evidence。
- 2026-06-17：補上 Month 6.1 深化規劃，將下一步明確定位為人工審核層、Portfolio Review Dashboard、Strategy Evidence Explainability 與 Month 6 QA Checklist；保持 promote / demote / retire 不自動破壞既有策略版本。
- 2026-06-17：補上 P/B / P/S valuation policy residual，將 source policy 改為 guarded ready：僅接受 governed external observations 或後續明確 backfill records，不在系統內推導估值分子 / 分母。
- 2026-06-15：完成 Daily Decision Desk Portfolio Alert Attribution v1，將持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags，並整合至主 UI 與風險提示。
- 2026-06-15：完成 Daily Decision Desk Relative Strength / Liquidity Ranking v1，從 SQLite `daily_prices` 推導 5 / 20 日相對強度與平均成交金額，並揭露低流動性股，不重算且以 quality / warnings 呈現品質缺口與歷史不足警告。

- 2026-06-15：完成 Daily Decision Desk Portfolio Alert v1 籌碼對接，整合 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，使持倉失效/警告與 bearish/extreme/risk 籌碼風險能彙總為持倉警示，並以 quality / warnings 呈現資料品質缺口。
- 2026-06-15：完成 Daily Decision Desk Watchlist Trigger v1 provider 接線，對接 `WatchlistService` 與 SQLite `technical_indicators` 以產生強度 `score_bp` 與風險 `risk_alert` 統計；非交易日採最近可用交易日並以 warnings 揭露，quality 降級為 `DEGRADED`。
- 2026-06-15：依 baldr 最終樣貌重排 Month 3 至 Month 6；Month 3 聚焦 Factor Layer 與 Portfolio Replay 可信度，Month 4 改為 Market Intelligence / Daily Decision Desk，Month 5 改為 Fundamental Layer 初版，Month 6 聚焦 Strategy Lifecycle 與 Portfolio Feedback。
- 2026-06-15：完成 Daily Decision Desk Market Breadth v1 provider 接線，從 SQLite `daily_prices` 產生多方 / 空方 / 持平、成交量擴散與新高新低 metadata；非交易日採最近可用交易日並以 warnings 揭露。
- 2026-06-15：完成 Daily Decision Desk Sector Rotation v1 provider 接線，從 SQLite `industry_indices` 產生領先 / 落後產業、5 / 20 日變化與輪動強度；非交易日採最近可用交易日並以 warnings 揭露。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾驗收，確認 v1 為 service-backed daily workflow，新增 UI boundary contract test，並將立即待辦轉向 Month 5 Fundamental Layer preflight。
- 2026-06-16：啟動 Month 5 Fundamental Layer preflight，新增 Fundamental Source Inventory、raw 月營收唯讀正規化契約、受治理公告日 / available_date mapping 契約、月營收公告日 mapping CSV loader、正式 mapping dry-run 驗證入口與 CLI、公告日 / available_date 初版政策、候選 SQLite schema dry-run 模組、暫時 connection / 正式 DB working copy dry-run report API、Fundamental SQLite 受控 migration service/CLI、月營收 normalized backfill workflow、Fundamental SQLite read provider、Fundamental factor service、Revenue Factor Pack v1 adapter contract 測試，確認缺 `available_date` 不產生 normalized record / factor record，未來資料由 FactorGate 跳過；正式 `twstock.db` 複本 dry-run 已確認候選 schema 不修改既有核心表，正式 DB 已套用 schema 但尚未回填 records，Revenue factors 尚未接入策略評分。
- 2026-06-16：新增估值呈現政策 v1，採相對分位區間與 forbidden-output regression，缺 `industry_percentile_bp` 時只回 `UNAVAILABLE` 或 diagnostics，不回中性，不輸出目標價或交易建議。
- 2026-06-16：新增 valuation data layer v1，建立受治理估值 observation 與同產業整數基點分位，並以既有 relative valuation adapter 驗證缺分位時只輸出 diagnostics。
- 2026-06-16：新增 valuation metrics backfill workflow，將 `daily_prices.本益比` 轉為可 dry-run / confirm / backup 的 P/E governed records；更新官方 company registry 後已正式 apply 寫入 831 筆 records。
- 2026-06-16：新增 Abnormal Fundamental diagnostics v1，將營收/獲利背離、一次性收益風險與資料品質缺口序列化為 Research metadata，並接入 Daily Decision Desk fundamental risk prompts。
- 2026-06-16：新增 TPEX daily price backfill workflow，將官方 TPEX daily close quotes 以 dry-run / confirm / backup 流程補入 `daily_prices`；正式 DB 已寫入 `20260616` 上櫃四碼普通股日價 877 筆並補齊 `3207`。
- 2026-06-18：TPEX official daily close quotes 已改走 afterTrading historical endpoint；日常每日股價、手動每日股價、快速 / 安全更新與背景補齊流程皆可補缺少的 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`，再與 TWSE 一併 upsert SQLite `daily_prices` 並接續技術指標增量。2026-06-17 排查確認 `3207` 已補至 `20140102..20260617`、共 2,907 筆。
- 2026-06-16：新增 TWSE/TPEX 月營收 historical dry-run builder，支援 `2020-01..2026-05` summary、單股篩選、候選 CSV 與 diagnostics；真實 dry-run 確認 OpenAPI 最新月與正式 raw 歷史期間無交集，未寫入正式 monthly revenue availability mapping。
- 2026-06-16：補上 MOPS 官方 HTML parser 與 `--mops-html-dir` source-dir workflow；可由人工保存的官方 HTML 產生候選 mapping，缺 `出表日期` 或公司列時只輸出 diagnostics。
- 2026-06-17：新增 MOPS `--mops-static` dry-run source 與 45 天合理揭露窗口 gate；確認 historical static report 的 `出表日期` 為查詢當日，不能直接作原始公告日 mapping。
- 2026-06-16：新增授權 PIT 月營收公告日 CSV 匯入路徑；免費官方來源目前仍未找到可批次追溯原始歷史公告日的端點，後續可由 TEJ point-in-time 匯出搭配 `--pit-csv` / `--pit-source-version` 產生 candidate mapping，正式 mapping 與月營收 backfill 仍需人工 gate。
- 2026-06-16：補齊日常更新與 UI 驗證收尾；TPEX endpoint timeout 改為 warning、SQLite Inspector 修正日期控件與重複欄名顯示錯誤、`broker_flows` 同步前可受控升級主鍵納入 `trade_type`，並將人工驗證重點整合回 Full App Healthcheck。
- 2026-06-14：完成 Phase 5 Month 1 的 SQLite 檢視器分頁與規格化 Excel 報告匯出，並更新 6M Roadmap、Snapshot 及 Architecture。
- 2026-06-13：建立 6 個月可執行工程路線，作為未來方向的 scoped authority。
- 2026-06-13：加入 Legacy Carryover Gate，明確承接指標參數治理、推薦權重治理、Phase 5 輸出與穩定性驗證。

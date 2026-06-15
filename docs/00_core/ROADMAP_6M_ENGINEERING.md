# 6 個月可執行工程路線（2026-06 至 2026-12）

> **最後更新**：2026-06-15
> **定位**：本文件是未來 6 個月工程執行與研究能力成長的權威路線圖。當它與短期 Snapshot 衝突時，以 Snapshot 的「本週優先事項」決定今天先做什麼；當它與產品願景文件衝突時，本文件決定可執行交付順序。

---

## 1. 目標

6 個月內把系統從「功能已形成研究與持倉閉環」推進到「每天能產生可驗證、可回溯、可解釋的投資決策摘要」。

核心成果：

1. 保留 fixed / quantile 與後續策略變體的真實 walk-forward 實證基準線。
2. 完成研究 run、資料版本、策略版本與因子貢獻的可追溯治理。
3. 補強 Factor Layer 與推薦組合回放，使組合績效具備現金、權重、再平衡、流動性與可得日防線。
4. 建立 Daily Decision Desk，讓市場狀態、候選股票、持倉警示與研究輸入在同一個每日決策入口收斂。
5. 將營收、基本面與估值納入可插拔 factor layer，採取先標記、降權與提示風險的保守策略。
6. 建立 promote / demote / retire 與 Portfolio post-trade attribution，讓策略能被系統性升級、降級或淘汰。

---

## 2. 不做什麼

- 不把 quantile 設成預設；2026-06-14 真實股票池實證未證明 quantile 優於 fixed，維持 opt-in。
- 不把營收、財報、三大法人或估值資料直接硬塞進 `ScoringEngine`。
- 不把推薦組合回測結果宣稱為實盤績效，除非成交假設、現金帳、流動性限制與再平衡規則完整揭露。
- 不導入黑箱 ML 作為主線；若未建立資料版本、OOS、因子歸因與漂移監控，ML 只會增加不可解釋風險。
- 不重建或破壞正式資料；所有資料新增必須非破壞性、可回溯、可降級。
- 不把 Daily Decision Desk 寫成已完成首頁；它是 Month 4 交付物。

---

## 3. 工程主線

### Track A：實證與回測可信度

目的：讓每一個策略改善都有 OOS 證據，而不是只看單次回測。

已完成基礎：

- fixed / quantile walk-forward 比較報告。
- Research Run Registry 的 metadata、Parquet 明細、hash integrity、comparison 與 Promote Gate。

後續交付：

- Portfolio Replay credibility：現金帳、再平衡、買不到 / 賣不掉、流動性限制與 gap 風險揭露。
- rolling risk metrics：Rolling Sharpe / Sortino、VaR / CVaR、drawdown duration、turnover。
- benchmark-relative attribution 與 factor attribution 的保存後讀取。

### Track B：Factor Layer 與資料治理

目的：讓新資料能被安全接入，不污染既有 scoring 與回測核心。

已完成基礎：

- Factor contract：`factor_name`、`as_of_date`、`available_date`、`value`、`score_bp`、`quality`、`missing_policy`、`source_version`。
- Factor registry / gate / adapters：技術、量能、券商分點 v1。
- Research Run 保存 `factor_snapshot` / `factor_contributions` 的基礎流程。

後續交付：

- 固定組合與更多 Research Lab 路徑 factor records 供給。
- Fundamental / valuation adapters。
- Missing / neutral / stale / skip 的 UI diagnostics。
- 所有 factor 都必須通過 `available_date <= decision_date` 或依政策 fail-closed / neutralize / skip。

### Track C：Market Intelligence 與 Daily Decision Desk

目的：把既有市場觀察、推薦、持倉監控與研究輸入整合成每日決策入口。

交付物：

- Daily Decision Desk 首頁。
- Market Regime Summary。
- Market Breadth：上漲 / 下跌家數、20 / 60 日新高新低、漲停 / 跌停、成交量擴散率。
- Sector Rotation：產業相對強度、5 / 20 日變化、產業內擴散率與背離。
- Relative Strength 與 Liquidity Ranking。
- Watchlist Trigger：新進候選、移除候選、強度提升 / 下降、量能 / 籌碼 / 風險條件。
- Portfolio Alert 初版：把價格、策略條件與籌碼警示整理到每日摘要。

### Track D：資料擴充與保守基本面

目的：建立能支援基本面與估值研究的資料底座，但不做過度自信的自動財報修正。

交付物：

- 月營收資料表：MoM、YoY、累計營收、資料公告日。
- 基本面資料表：EPS、ROE、毛利率、營益率、負債比、現金流、股本。
- 估值資料表或視圖：P/E、P/B、P/S、殖利率、產業相對估值分位。
- AbnormalFundamentalFlag：標記營收與獲利背離、業外損益異常、匯兌或投資收益影響。
- 後續三大法人資料可接入為籌碼因子，但必須保留資料品質、單位與可得日。

### Track E：Portfolio 回饋與策略生命週期

目的：讓實際交易 / 模擬持倉能反饋研究，而不只是持倉監控。

交付物：

- 持倉原因與現況差異歸因：Regime、Score、Factor、籌碼、估值。
- 實際交易 vs 回測預期落差：進場價差、滑價、出場原因、持有天數、最大不利走勢。
- Promote / demote / retire 規則：以 OOS、持倉後驗、風險與資料品質決定策略生命週期。
- Portfolio Review Dashboard。

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

> 2026-06-15 狀態：Factor Contract / Registry / Look-ahead Gate / v1 adapters / FactorService snapshot/contribution serialization 已進入實作；`ResearchRunService.save_run()` 可在實際寫入流程保存 factor snapshot 與 contribution summary。推薦組合回放已供給 `technical.total_score` 與 `volume.volume_ratio` metadata；單股回測與批次回測已由 signal score 序列供給 `technical.total_score` factor records。v1 不接營收、法人或估值新資料源，也不改 `ScoringEngine` 核心。

目標：

- 完成 Factor Layer v1 的保存覆蓋。
- 補強推薦組合與固定組合回放可信度，避免後續策略生命週期建立在不完整績效上。

交付物：

- 固定組合與更多 Research Lab 路徑的 factor records 供給。
- Factor Gate / adapters focused regression 與 no-look-ahead tests。
- 推薦組合回放的現金帳、權重、再平衡與未成交處理規格。
- Liquidity / Gap 風險在回放結果摘要中可追溯。
- PDF 報告輸出可保留為研究輸出 backlog，不阻塞 Month 3。

驗收標準：

- 缺少某因子資料時回傳 `missing`、`neutral` 或 `skip`，不讓流程中斷且留下 diagnostics。
- factor `available_date` 晚於決策日時必須 fail-closed、neutralize 或 skip，依 factor policy 處理且留下 diagnostics。
- `ScoringEngine` 不直接依賴新資料表。
- 推薦組合 / 固定組合回放結果能揭露現金、權重、再平衡、成交限制與風險標記。

### Month 4：Market Intelligence 與 Daily Decision Desk

目標：

- 讓系統每天打開就能回答「今天市場怎麼了、我該研究誰、我的持倉有沒有問題」。

交付物：

- Daily Decision Desk 首頁或等價頂層工作區。
- `DecisionDeskSnapshot` / `DecisionDeskSnapshotBuilder` 或等價 DTO / service。
- Market Breadth service。
- Sector Rotation service。
- Relative Strength / Liquidity Ranking。
- Watchlist Trigger service。
- Portfolio Alert 初版。
- Manual 與 UI docs 完整描述新首頁入口、參數、結果判讀與限制。

驗收標準：

- Daily Decision Desk 不重算 UI 各頁資料；它透過 service snapshot 聚合已治理的結果。
- 所有市場寬度、產業輪動與 watchlist trigger 都有資料日期與品質標示。
- Liquidity Gate 結果能進入 Why Not 或風險提示，不只是回測內部限制。
- 持倉警示能回到原始來源與目前狀態差異。

### Month 5：Fundamental Layer 初版

目標：

- 加入基本面觀察，但採取保守、可追溯、先標記後清洗的方式。

交付物：

- 月營收資料與公告日欄位。
- Revenue YoY / MoM / 3M trend / revenue new high factor。
- 第一版估值視圖：P/E、P/B、P/S、產業相對分位。
- AbnormalFundamentalFlag。
- Fundamental factor adapters 與 available_date gate。

驗收標準：

- 回測使用營收與估值因子時只讀 `available_date <= decision_date` 的資料。
- 估值先以相對分位與區間呈現，不輸出未驗證的單點目標價。
- 異常基本面只標記、降權或提示風險，不自動扣除業外或改寫財報。

### Month 6：Strategy Lifecycle 與 Portfolio Feedback

目標：

- 讓策略與持倉進入可監控、可降級、可淘汰的生命週期。

交付物：

- Promote / demote / retire 規則。
- StrategyDriftDetector。
- Portfolio post-trade attribution。
- Regime compatibility。
- Live vs research gap report。
- Portfolio Review Dashboard。
- 6 個月成果回顧與下一版 roadmap 草案。

驗收標準：

- 策略不能只靠單次高報酬被升級；必須通過 OOS、風險、交易次數與資料品質門檻。
- 被淘汰策略保留原因與證據，不刪除歷史。
- Portfolio 能回答「這筆交易原始假設是否仍成立」與「落差來自訊號、執行、資料或市場」。

---

## 5. 立即待辦清單

1. 延伸固定組合與更多 Research Lab 路徑的 factor records 供給，讓更多 run 自動產生 `factor_snapshot` / `factor_contributions`。
2. 設計 Portfolio Replay 可信度補強：現金帳、權重、再平衡、未成交、Liquidity / Gap 標記。
3. 保持 Factor Contract / Registry / Gate / adapters focused regression 與量化防禦檢查。
4. 維持 Month 2 Registry governance gate 的回歸驗證：immutable save、Cross-run comparison、registry-based promote gate、hash integrity 與 reconciliation。
5. 為 Month 4 Daily Decision Desk 預先定義 snapshot DTO、資料品質欄位與不重算現有頁面資料的 service 邊界。
6. PDF 報告輸出仍在研究輸出 backlog，不阻塞 Month 3 / Month 4。

---

## 6. 驗證規則

- UI 修改：依專案規範執行 Update Tab pytest、QA script、mypy 與 py_compile。
- 策略 / 回測 / 推薦 / factor 修改：必須先寫 Look-ahead 自查，並新增 no-look-ahead 測試。
- 金融核心數值：必須通過 `scripts/check_financial_float_boundaries.py` 與對應 pytest gate。
- 資料 schema：必須提供 migration / fallback / 資料品質驗證，且不得破壞正式資料。
- Daily Decision Desk：必須以 service snapshot 聚合，不得在 UI 層複製 scoring、screening、portfolio 或 broker flow 計算。

---

## 7. 更新記錄

- 2026-06-15：依 IDS 最終樣貌重排 Month 3 至 Month 6；Month 3 聚焦 Factor Layer 與 Portfolio Replay 可信度，Month 4 改為 Market Intelligence / Daily Decision Desk，Month 5 改為 Fundamental Layer 初版，Month 6 聚焦 Strategy Lifecycle 與 Portfolio Feedback。
- 2026-06-14：完成 Phase 5 Month 1 的 SQLite 檢視器分頁與規格化 Excel 報告匯出，並更新 6M Roadmap、Snapshot 及 Architecture。
- 2026-06-13：建立 6 個月可執行工程路線，作為未來方向的 scoped authority。
- 2026-06-13：加入 Legacy Carryover Gate，明確承接指標參數治理、推薦權重治理、Phase 5 輸出與穩定性驗證。

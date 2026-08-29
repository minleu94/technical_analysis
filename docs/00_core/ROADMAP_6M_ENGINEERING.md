# baldr 未來六個月工程 Roadmap

> **2026-07-12 engineering package update**：Gate 2–7 的純工程 deliverables 已依獨立 slices 落地並由 `scripts/verify_gate_2_to_7_closeout.py` 驗證；external human/time/license/evidence/ML gates 尚未因此完成。後續執行重心轉為 [Gate 2–7 External Validation Register](../06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)，不得重做工程模擬來折抵真實時間或人工決議。

> **2026-07-14 evidence rehearsal update**：replay / P0 source shadow / ML shadow / lineage 的唯讀工程預演底座狀態為 `engineering_rehearsal_complete`；coverage、quality、missingness 與 blocker 可重跑，但不折抵任何 Gate 2–7 external human/time/license/evidence/ML 需求。詳見 [Evidence Rehearsal Engineering Closeout](../06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md)。

> **工程終態**：15 capability、canonical lineage 與 operations handoff 已收口為 `V3.3 Engineering Complete`；後續屬 `V4.0 Evidence Accumulation Track`，不是正式 V4.0。見 [V3.3 Engineering Closeout](../06_qa/V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)。

> **2026-07-13 系統整合校正**：跨流 contracts、唯讀正式資料 smoke、Dashboard／Broker latency 與 pure closeout verifier 已完成工程驗證。Gate 2 真實 forward evidence、Gate 3 source／license acceptance、Gate 7 formal OOS、shadow-day 累積與 promotion review 均仍是 external pending，不能由本次工程測試折抵。
>
> **最後更新**：2026-08-28
> **定位**：本文件是未來六個月工程執行的 scoped authority，將 [PRODUCT_ROADMAP_POST_REFACTOR.md](PRODUCT_ROADMAP_POST_REFACTOR.md) 轉成可交付、可測試、可回滾的 Gate。
> **現況**：目前完成狀態以 [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) 為準。既有 V3.0 engineering candidate、read-only Workbench、candidate source readiness 或 simulated phase progress 不自動折抵本 Roadmap 的產品 Gate。
> **版本 companion**：產品成熟度版號見 [VERSION_ROADMAP_V2_1_TO_V4_0.md](VERSION_ROADMAP_V2_1_TO_V4_0.md)。

---

## 1. 六個月成果定義

六個月內不追求完成所有長期能力，而要完成一條可日常使用、可驗證、可拒絕輸出的主線：

```text
Gate 0 Safe Refactor Closeout
→ Gate 1 Daily Usable Advice
→ Gate 2 Real Evidence Operating Loop
→ Gate 3 P0 Data Acceptance
→ Gate 4 Portfolio Coach v1
→ Gate 5 Signal Effectiveness & Pruning
→ Gate 6 Position Health & Exit v1
```

Gate 7 ML Shadow Layer 只作條件式後續：若 Gate 5 在第六個月以前具備可判讀 baseline，才可建立 shadow experiment；它不是六個月必須上 production 的承諾。

## 2. 已有工程底座與不得誤讀的邊界

| 已有底座 | 可承接工作 | 不代表 |
|---|---|---|
| SQLite-first、data quality、available-date policies | P0 source governance | P0 sources 已正式接受 |
| Recommendation、Profile、screening matrix、Why / Why Not | Advice Contract | 已有可直接採信的投資建議 |
| Backtest、Replay、Walk-forward、Registry | Experiment / Promotion Gate | historical replay 是 forward evidence |
| Evidence Event / Outcome、weekly review、read-only dashboards | Evidence operating loop | production evidence write-mode 已批准 |
| Workbench read-only operating loop | Advice UI shell / drill-down | Guided Mode 或 Portfolio Advice 已完成 |
| Portfolio tracking / Condition / Chip / sandbox | Portfolio Coach / Health 的基礎 | 已有 target/current/gap 或 thesis-based Exit |
| Score effectiveness / ML readiness engineering candidate | Gate 5/7 read models | signal 有效或 ML production ready |
| Data update / evidence dry-run scheduled tasks | operations scaffold | 自動交易或 production evidence scheduler |

## 3. 時間配置

| 月份 | 主要 Gate | 交付結果 |
|---|---|---|
| Month 1 | Gate 0 + Gate 1 Contract | 關閉安全重構；凍結 Advice / Portfolio Advice / Mode 契約與 golden baseline。 |
| Month 2 | Gate 1 + Gate 2 | 建立每日 Advice read model 與真實 evidence review / action-item 節奏。 |
| Month 3 | Gate 2 + Gate 3 | 受批准的 evidence write-mode 與 P0 source diagnostics / shadow acceptance。 |
| Month 4 | Gate 4 | Portfolio Coach v1、Equal Weight benchmark、paper portfolio、execution feasibility。 |
| Month 5 | Gate 5 | Score / signal / gate / alert effectiveness、ablation、pruning / retirement 決議。 |
| Month 6 | Gate 6；Gate 7 conditional | Position Health / Exit v1；只有 Gate 5 可判讀時才開 ML shadow。 |

跨月 Gate 可重疊研究與設計，但前一 Gate 的正式 Exit Criteria 未通過時，不得把後一 Gate 能力接進 Guided Mode 或 formal decision layer。

## 4. Gate 0：Safe Refactor Closeout

### Investment Question

現有產品行為是否已被安全鎖定，能停止無止盡重構並回到產品主線？

### Dependencies

- [SAFE_REFACTORING_MASTER_REPORT_2026_07_12.md](../09_archive/SAFE_REFACTORING_MASTER_REPORT_2026_07_12.md)（Gate 0 已完成的歷史執行與 rollback companion）。
- 現行 Recommendation、Backtest、Portfolio、Scheduler、DTO / schema、UI navigation 測試。
- 完整 rollback point 與 known residual list。

### Engineering Deliverables

1. Golden baseline：固定代表性輸入、輸出、排序、warnings、DTO serialization 與主要 UI contract。
2. Recommendation diff：Profile / ranking / screening matrix / Why / Why Not 無非預期差異。
3. Backtest diff：交易、timeline、成本、績效與 OOS contract 無非預期差異。
4. Portfolio diff：持倉、平均成本、PnL、alert 與 source trace 無非預期差異。
5. Scheduler contract diff：market data write、evidence dry-run、production evidence write-mode 三者權限不混淆。
6. DTO / schema diff：向後相容、migration / fallback 清楚。
7. 完整 rollback point、closeout report 與後續不再主動擴張重構的停止規則。

### Verification

- Protected contract / characterization suite。
- Focused pytest、適用 UI QA、mypy、py_compile、quant guard。
- `git diff --check`、工作樹與 rollback artifact 檢查。
- 人工 MainWindow / core flow smoke 依風險執行。

### Exit Criteria

- 所有 protected diff 經確認，未解釋差異為 0。
- 主要 God nodes 已薄化或有保留理由；未完成 residual 有明確 owner / non-blocking 判定。
- 建立可回滾 commit / tag / SHA 紀錄，不修改正式資料或 production scheduler。
- Tech Lead 正式宣告 Gate 0 closeout 後，重構進入 maintenance，不再是產品主線。

### Prohibited

- 不以 LOC 最小化替代行為等價。
- 不在 closeout 同時新增 Advice、資料源或模型功能。
- 不因重構測試通過宣稱投資有效。

## 5. Gate 1：Daily Usable Advice Product

### Investment Question

今天應研究哪些股票、是否能建立新部位、建議配置多少；現有持倉應 Add / Hold / Reduce / Exit 嗎？

### Dependencies

- Gate 0 closeout。
- 既有 Recommendation / screening / Workbench / Portfolio source trace。
- Product Roadmap 的 Advice / Portfolio Advice Contract。

### Engineering Deliverables

1. Advice action enum：`RESEARCH`、`ADD_CANDIDATE`、`HOLD`、`REDUCE_CANDIDATE`、`EXIT_CANDIDATE`、`AVOID`、`NO_NEW_POSITION`。
2. Recommendation Advice Contract：Why、Why Not、Risk、Evidence tier、confidence tier、thesis、invalidation、horizon、liquidity、execution feasibility、strategy/data date。
3. Portfolio Advice Contract：`target_weight_bp`、`current_weight_bp`、`weight_gap_bp`、review date。
4. Guided Mode policy：只允許 promoted / locked / disclosure-complete strategy。
5. Professional Mode policy：candidate experiments 與 formal Advice 嚴格分離。
6. 共核驗證：兩種 Mode 使用相同 Recommendation / Portfolio / Evidence engine 與相同 DTO schema。
7. Advice refusal policy：資料不足、risk budget 滿、不可成交或市場風險過高時輸出 `RESEARCH` / `AVOID` / `NO_NEW_POSITION`。
8. Workbench read model / UI slice：先呈現建議、風險、證據與權重差距；不直接在 UI 計算。

### Testing

- Contract / JSON round-trip / legacy compatibility。
- Guided Mode 不可載入 candidate / shadow 策略。
- Professional result 未經 Promotion 不得出現在 Guided Mode。
- Missing / degraded / stale / execution unavailable 的 fail-closed matrix。
- `NO_NEW_POSITION` 可被正常輸出且 UI 不視為錯誤。
- Integer bp / Decimal / Look-ahead guard。
- UI 只讀 DTO / application façade 靜態 contract。

### Evidence Gate

- Advice completeness：正式樣本 100% 含必要欄位與 source trace。
- Deterministic replay：相同 frozen data / strategy / policy 產生相同 Advice。
- Human review：Why / Why Not / Risk / Evidence 不暗示保證獲利或自動交易。
- Paper dry-run：Advice 可轉成 paper allocation，但不建立 broker order。

### Exit Criteria

- 每日流程能回答「研究誰、能否新增、配置多少、持倉動作候選」。
- Advice 可拒絕輸出、可回溯、可重算、可版本化。
- Guided / Professional 共核，沒有第二套 calculation path。
- 目前仍可只在 read-only / paper mode closeout；不要求 production evidence scheduler 或真實交易。

### Prohibited

- 不把 TotalScore 直接映射為買入或權重。
- 不串 broker、不自動下單、不自動平倉。
- 不把 confidence tier 寫成勝率。

## 6. Gate 2：Real Evidence Operating Loop

### Investment Question

Recommendation、Portfolio Advice、Alert 與 Exit 是否被持續、可比較、可回滾地驗證？

### Dependencies

- Gate 1 Advice artifact。
- durable snapshots、Evidence Event / Outcome、weekly review、Decision Quality / lifecycle repositories。
- Production scheduler approval checklist、backup / rollback / recovery 設計。

### Engineering Deliverables

1. 真實 weekly review cadence：固定期間、owner、輸入、結論與 action item。
2. Action Item rhythm：open → reviewed / dismissed → follow-up；append-only history。
3. Manual review note：引用 source trace、quality、blocking / accepted residual，不含買賣命令。
4. Appendix-only Evidence write-mode：只新增 evidence / review artifact，不改策略、Portfolio 或交易。
5. Backup / rollback / recovery：run id、last-good、supersede / archive policy、disable-first recovery。
6. Production Evidence Scheduler approval package：job version、approval id、dry-run result、idempotency、recovery test。
7. Workbench / Evidence Review 顯示 historical replay、dry-run、forward、paper、live evidence tier。

### Testing

- Dry-run zero write、working-copy repeat idempotency、approved write append-only。
- Backup / restore rehearsal 與 scheduler disable-first。
- Duplicate / partial failure / stale input / source outage matrix。
- `production_scheduler_allowed` 只有 explicit approval artifact 才能為 true。
- Scheduler 不能 import broker execution 或 lifecycle mutation command。

### Evidence Gate

- 至少 3 個真實 weekly review period 與 3 個真實操作日 evidence record；historical replay 不計入。
- Action items 有真實 reviewed / dismissed / follow-up 節奏，不是 fixture。
- Approval owner 檢查 diagnostics、backup、rollback、recovery 與安全旗標。

### Exit Criteria

- Evidence loop 可在無 UI 手動補資料下重複運行並接受人工 review。
- Production evidence write-mode 如獲批准，只保存 evidence；不自動交易、不套 lifecycle action。
- Historical / replay / dry-run 不被標成 forward / live。

### Prohibited

- 不把 scheduled dry-run `Last Result=0` 當 production approval。
- 不用 replay 補 weekly / forward gate。
- 不讓 scheduler 自動 Promote / Demote / Retire。

## 7. Gate 3：P0 Data Integration

### Investment Question

回測、Advice、Portfolio 與 Exit 是否使用決策當時可得、可授權、可降級的關鍵資料？

### Dependencies

- Gate 2 可保存 diagnostics / evidence。
- Source Registry / corporate action / candidate readiness 現有底座。
- 官方或授權來源研究、license / rate-limit 決策。

### P0 Scope

1. Corporate Action：除權息、減資、分割、面額變更。
2. 停牌 / 復牌、處置、分盤、全額交割、漲跌停鎖死。
3. 三大法人。
4. 信用交易。
5. TDCC / 集保持股分散。
6. PIT 月營收與季度財報公告日。

### Engineering Deliverables

1. 統一 Source Contract：source id/version、as-of、available-date、quality、missing、license、rate limit、look-ahead、ingestion stage、downstream eligibility。
2. Data Source Control Center read model：freshness、coverage、schema、quarantine、retry、eligibility。2026-08-26 已先落地 `app_module/p0_source_control_center.py` 與 `scripts/inspect_p0_source_control_center.py` 的 13-source 唯讀 composition；它只投影 contract／audit／decision evidence，沒有 auto-accept 或 downstream grant，後續仍需逐來源補齊真實 evidence。
3. Adapter + raw evidence + manifest；不得由 UI 或 domain 直接呼叫 vendor。
4. Diagnostics → Shadow → Evidence Review → Accepted Feature 的逐來源狀態機。
5. Corporate action / restriction 對 execution、Why Not、Health 的 candidate impact report。
6. source outage / stale / revision / duplicate / future-data quarantine。

### Testing

- `available_date <= decision_date`、修訂 / late arrival、timezone / market-day boundary。
- Missing / stale / rate-limit / schema drift / duplicate / future-data fail-closed。
- Source adapter contract、raw manifest、idempotency、license / version disclosure。
- Candidate source 不可被 `ScoringEngine` / formal Portfolio Advice import 的靜態 boundary test。

### Evidence Gate

每個來源獨立形成：

- Decision use case 與可接受 quality。
- coverage / history / missing / look-ahead report。
- diagnostics / shadow outcome。
- 接受、限制、拒絕或延後決議。
- 正式 downstream eligibility 由人工核准。

### Exit Criteria

- 每個 P0 source 有可稽核狀態，不再只有「planned / ready」模糊語彙。
- Accepted Feature 才能供 formal decision layer；未接受來源維持 `research_candidate`。
- Corporate action / restriction 至少能影響可信度、execution feasibility 或 risk，不靜默忽略。

### Prohibited

- 不捏造 API、歷史 coverage 或 license。
- 不直接把三大法人、信用、TDCC 單點訊號加進 score。
- 不把 retroactive baseline 當官方 PIT history。

## 8. Gate 4：Portfolio Coach v1

### Investment Question

在資金、風險、流動性與成本限制下，應如何配置與再平衡？

### Dependencies

- Gate 1 Portfolio Advice Contract。
- Gate 3 accepted / explicitly limited data。
- current positions / cash / prices / liquidity / execution assumptions。

### Engineering Deliverables

1. Versioned Portfolio Policy：total exposure、cash reserve、single / sector / concept / correlation / small-cap / liquidity caps、target volatility、drawdown、turnover、cost。
2. Equal Weight benchmark。
3. Candidate sizing：Score Weight、Inverse Volatility、Risk Budgeting、Confidence-adjusted；全部 opt-in、可比較。
4. Rebalance bands：lower / target / upper、minimum trade、turnover budget、cooldown。
5. Portfolio Advice：target/current/gap、action、reason、evidence、feasibility。
6. Paper Portfolio 與 Trade Import / Decision Journal foundation：fill、partial fill、override、reason、execution gap。
7. Scenario & Stress Lab v1：快速下跌、跳空跌停、流動性消失、相關股同跌、集中、source outage。

2026-08-27 進度：Portfolio UI 已接上最小唯讀 Scenario & Stress Lab v1、受控手動 Trade Import、Paper Portfolio readiness、Paper weekly evidence read model 與獨立 Paper Trade Ledger v1 contract；另有預覽／明確確認分離的 `append_paper_trade_ledger.py` JSON producer、完整 execution contract 的 `append_paper_trade_csv.py`／UI Paper fills 匯入，以及從 baseline／既有 snapshots／T-1 市場資料建立 frozen-constituent Equal Weight preview 的 `build_paper_equal_weight_benchmark.py`。正式輸出重新檢查到 21 筆 raw paper snapshots，其中最新 `2026-08-28` 超過台北今日 `2026-08-27`；readiness 會將狀態降為 `degraded` 並把 future row 排除於 current projection，weekly evidence 與 Equal Weight builder 遇到 future period／snapshot 則 fail-closed。Equal Weight ledger／Paper Trade Ledger 尚未配置，故 weekly evidence 仍 `not_computable`；固定情境缺價只顯示 partial，輪動失敗／來源中斷維持 `not_computable`。本輪再加入 Stress history v1：明確確認後才可保存 hash-idempotent 研究快照，Portfolio UI 與 `append_portfolio_stress_history.py` 均提供唯讀歷史揭露。這些是可見的工程入口，不代表 Gate 4 的 OOS / forward / paper 成本後 evidence 已完成；producer 的實際來源資料、成本 fill、壓力結果與 forward outcome 關聯及 review 仍待後續輸入。

2026-08-28 進度：Equal Weight builder 已抽至 `app_module/paper_equal_weight_benchmark_builder.py`，CLI 與 Portfolio UI 共用 preview／確認／輸入重驗證／新檔拒絕覆寫流程；Paper readiness／weekly evidence 預設讀取 `<OUTPUT_ROOT>/paper_portfolio/paper_equal_weight_benchmark.sqlite`（仍可由 `PAPER_EQUAL_WEIGHT_BENCHMARK_PATH` 覆寫）。Portfolio UI 新增「預覽／建立 Equal Weight」入口，建立後只補 benchmark observation；Paper Trade Ledger、真實 fill／partial-fill／reject／override、成本與 execution gap 仍不可由 snapshot 或手動交易推導。
- 2026-08-28 進度：新增 `scripts/inspect_paper_trade_reconciliation.py` 的 query-only fills preflight；外部 CSV 先通過完整 execution contract，再以期初／期末 snapshot 逐股票核對 filled quantity delta，並檢查既有 ledger fill-id collision。缺 context 或對帳不符會停在 `needs_review`／`rejected`，只有 `ready` 才能交給既有明確 confirm append；此工具不從 snapshot 猜成交、不建立或修改 ledger。

2026-08-28 台北日期刷新：`taiwan_market_today()` 已進入 `2026-08-28`，上述 raw snapshot 不再是 future row；Paper readiness 目前為 `partial`。已在 QA output 以 3 檔 frozen constituents 產生 21 筆 Equal Weight staging preview（最新 `472302.39`），並於受控確認後建立正式 Paper output ledger `<OUTPUT_ROOT>/paper_portfolio/paper_equal_weight_benchmark.sqlite`；真正缺口縮小為 Paper Trade Ledger 與可計算的成本後週報／forward outcome。future-date guard 仍保留，下一筆超過台北市場日的資料仍必須 fail-closed。

### Testing

- Integer bp 總和 / cap / residual cash / lot size / Decimal 金額。
- Equal Weight、candidate methods deterministic golden tests。
- Constraint conflict、infeasible allocation、all candidates rejected、cash-only / `NO_NEW_POSITION`。
- Bands / minimum trade / cooldown / turnover tests。
- Paper fill / partial / reject / gap / cost / restriction scenarios。

### Evidence Gate

- 所有 sizing 與 Equal Weight 使用相同 universe / period / cost / constraints 比較。
- OOS / forward / paper 層評估成本後 return、drawdown、CVaR、turnover、concentration、exposure stability。
- 若 candidate method 無穩定增益，正式 policy 保持 Equal Weight 或更簡單方法。

### Exit Criteria

- 每次 Advice 有 target/current/gap 與可成交性。
- `ADD_CANDIDATE` 不會突破任何 risk budget；不可行時降級為 HOLD / RESEARCH / NO_NEW_POSITION。
- Paper Portfolio 可重現；仍不串 broker。

### Prohibited

- 不以 unconstrained mean-variance 作早期正式方法。
- 不因 optimizer 有解就視為可交易。
- 不接 production broker API。

## 9. Gate 5：Signal Effectiveness & Pruning

### Investment Question

TotalScore、component、gate、alert 與 Profile 中，哪些真正有貢獻，哪些應限制、降權或退休？

### Dependencies

- Gate 2 真實 evidence cadence。
- Gate 4 paper / Portfolio outcomes。
- frozen Experiment Contract、metric definitions、minimum samples。

### Engineering Deliverables

1. Recommendation metrics：forward / benchmark / industry / concept excess、MAE / MFE、hit、payoff、monotonicity、Precision@K、regime、liquidity、execution。
2. Portfolio metrics：cost-adjusted / excess、Sharpe、Sortino、MDD / duration、CVaR、turnover、cash、concentration、diversification、exposure、research gap。
3. Alert / Exit metrics：lead time、post-alert MAE、false rates、avoided / opportunity loss、early exit、post-exit、Add / Reduce outcome。
4. Model metrics scaffold：ranking、calibration、stability、regime、feature / label drift、OOS decay、live degradation。
5. Score bucket monotonicity、fixed threshold robustness、component ablation 與 factor attribution。
6. Experiment Manager：hypothesis、primary metric、benchmark、success / failure、split、search budget、horizon、execution、fingerprint。
7. Pruning review：每項 feature / signal / gate / alert / Profile 的 retain / restrict / downweight / retire 決議。

### Testing

- Metric formula / window / grouping / sample disclosure golden tests。
- Same-day universe、PIT feature、purged / embargo、benchmark alignment、cost consistency。
- Multiple comparison / search budget / frozen hypothesis guard。
- Missing component payload 不回補舊結論。
- Retirement 不刪歷史 artifact，改用 inactive / superseded / effective date。

### Evidence Gate

- 指標不只報值，必須對應產品決策。
- 任何保留或 promotion 至少有 OOS + forward / paper 可比較證據。
- 任何 pruning 決議保留 evidence、影響範圍、fallback 與 rollback。
- 樣本不足標示 inconclusive，不得硬選 winner。

### Exit Criteria

- 回答 TotalScore 是否有排序能力、bucket 是否單調、component / gate / alert / Profile 的真實貢獻。
- 產生第一批 retain / restrict / downweight / retire 決議。
- Gate 7 是否可啟動有明確 yes / no；readiness scaffold 本身不算 yes。

### Prohibited

- 不以單次最佳參數或 dashboard 視覺判斷有效。
- 不只新增 feature；必須允許刪除與退休。
- 不把 ML 作為規則 baseline 不可判讀時的逃生口。

## 10. Gate 6：Position Health & Exit Engine v1

### Investment Question

持倉何時維持、加碼、減碼或退出，且原因是否能回到 entry thesis 與 Portfolio 風險？

### Dependencies

- Gate 1 Advice / thesis / invalidation contract。
- Gate 4 Portfolio Policy / paper portfolio。
- Gate 5 alert / signal effectiveness baseline。
- Gate 3 restriction / corporate action / quality inputs。

### Engineering Deliverables

1. State machine：HEALTHY、WATCH、REDUCE_CANDIDATE、EXIT_CANDIDATE、CLOSED。
2. 判斷分類：Hard Risk、Thesis Invalidated、Relative Deterioration、Time Stop、Portfolio Rebalance、Data Quality、Trading Restriction。
3. Entry thesis / invalidation / expected horizon / review date persistence。
4. Add / Hold / Reduce / Exit Advice Contract 與 transition evidence。
5. Position Health read model、Workbench drill-down、Decision Journal linkage。
6. Portfolio-driven trim 與 Hard Risk 的優先順序、人工 override / reason。

### Testing

- 完整 state transition matrix、recovery / override、invalid transition。
- Hard Risk / restriction / missing data / market / relative / time / portfolio cases。
- Fixed stop、RSI、TotalScore 不得單獨壟斷狀態的 contract test。
- Exit advice 不得呼叫 broker、delete position 或 mutate lifecycle。
- Advice / journal / evidence round-trip 與 effective-date tests。

### Evidence Gate

- Alert lead time、post-alert MAE、false rates、avoided / opportunity loss。
- Early exit rate、post-exit performance、Add / Reduce outcomes。
- 按 regime、liquidity、reason category 與 data quality 分層。

### Exit Criteria

- 每個 active position 有 thesis / invalidation / review state 或明確 legacy-degraded 標示。
- 每次 state transition 可解釋、可追溯、可人工 override。
- Exit 不再只依 fixed SL / TP 或單一 score。
- 仍是 advice candidate，不自動平倉。

### Prohibited

- 不把資料缺失直接解讀為正常。
- 不自動賣出、不自動改 Portfolio。
- 不用 hindsight 填補 entry thesis。

## 11. Gate 7：ML Shadow Layer（條件式）

### 2026-08-19 Prospective restart execution lock

- 舊 `clock:prospective:20260819:v1` 已錯過且不得重建、沿用或回填；歷史 `2014–2026` artifacts 不取得 prospective Formal credit。
- 下一個執行 clock 依執行當下的官方 TWSE／TPEX 共同交易日與至少一個完整準備日另建新 identity；選日方法、責任與 DoD 見 [Prospective Formal Restart Direction](../06_qa/PROSPECTIVE_FORMAL_RESTART_DIRECTION_2026_08_19.md)。
- Rule Champion 由 Codex 從現有可重播、版本化、正式 Rule path 提出單一首選；Owner 只對具體 Champion identity 做一次接受，不需要自行設計策略。
- Prospective PIT sector 固定採 TWSE `t187ap03_L` 與 TPEX `t187ap03_O` 官方公司基本資料，保存 source／license／publication／available／hash lineage；不得用 current `companies.csv` 回填歷史。
- 本執行軌持續 `formal_oos_allowed=false`、alpha 0、Broker disabled；strict readiness 不等於 Formal OOS、promotion 或下單授權。

### 2026-08-25 activation-day pre-open status

- `clock:prospective:20260825:v1` 已建立，activation=`2026-08-25`、preparation=`2026-08-24`；官方 TWSE／TPEX source bytes 已在 create-only staging，尚未寫入正式 PIT manifest。
- Rule Champion identity 已接受，但三份 clock-bound formal inputs 仍為 `0/3`，controlled path 缺件與 T-1 `2026-08-24` market rows 使 strict readiness fail-closed；不得 partial start、回填或把 staging／fixture 當成 Formal evidence。
- 本週狀態、source hashes、測試與未通過 gates 見 [Prospective Formal Restart Weekly Update](../06_qa/PROSPECTIVE_FORMAL_RESTART_WEEKLY_UPDATE_2026_08_25.md)；本段不代表 Formal OOS、promotion、broker 或 weekly gate credit。

### 2026-08-28 owner handoff preparation

- Formal candidate inventory 實際解析 `511` 份 manifest、略過 `1` 份並因 bounded 上限保留 `truncated=true`；candidate input counts 為 causal=`3`、PIT sector=`1`、formal Rule=`0`，沒有任何一項可直接消費為正式 input。
- 新增 `scripts/build_formal_input_owner_packet.py` 與 `formal-input-owner-review.v1` 只讀 packet，為三項 expected input 建立具名 owner／reviewer review slot，保留 bounded manifest identity／原因；packet 不選 candidate、不寫 controlled path、不把 research／prospective artifact 改名成 Formal。
- 實際 packet status=`needs_named_owner_reviewer`、formal ready=`0/3`、`formal_oos_allowed=false`、`candidate_only=true`；下一步是 owner-controlled publisher 產出三份 expected schema manifest，再重跑正式 readiness。這是可持續的 handoff 工程化，不折抵 Formal OOS、promotion 或 broker gate。

### Entry Conditions

- Gate 5 對 rule score、bucket、component、label 與 metric 已可判讀。
- Feature / Label / Dataset Registry、purged / embargo split 與 leakage checks 完整。
- Champion baseline、shadow storage、rollback owner 已定義。

### Engineering Deliverables

- Gradient Boosting / learning-to-rank / meta-label / calibration / downside risk 的最小 challenger。
- Model Registry、Calibration Report、Feature Importance、Drift Monitor、Shadow Prediction Store。
- Champion / Challenger comparison 與 Promotion Review package。

### Testing / Evidence

- Purged walk-forward、OOS ranking、calibration、net utility、regime / liquidity stability。
- Feature / label drift、missing feature、model unavailable、rollback to champion。
- Shadow output 不得進 formal Recommendation / Portfolio / lifecycle / scheduler。

### Exit Criteria

- 只能提出「繼續 shadow、拒絕、或建議人工 promotion review」。
- 即使 promotion review 通過，也需另立 formal adapter 計畫與 rollback Gate；不自動上線。

## 12. 跨 Gate 驗證規則

1. **No-look-ahead**：所有 signal、feature、standardization、universe、benchmark、execution、stop / exit 只用 decision-time data。
2. **金融數值**：核心金額、權重、成本、PnL、風險使用 Decimal / 整數；float 只在隔離 analytics / visualization boundary。
3. **狀態誠實**：candidate / dry-run / replay / shadow / paper / live / production 必須是不同狀態。
4. **文件同步**：使用者可見功能實作時才同步 Manual；Target-only 規劃不得提前寫成已可操作。
5. **資料安全**：raw source 不破壞；migration / apply 有 backup / confirm / restore。
6. **Pruning**：任何新增 signal / gate / feature 同時定義 evidence metric 與 retirement path。
7. **自動化**：Production evidence scheduler 與 broker execution 是不同權限；本 Roadmap 不建立 broker execution。

## 13. 六個月 Closeout Definition

六個月 closeout 至少要求：

- Gate 0 關閉，產品主線不再被安全重構佔用。
- Gate 1 Advice Contract 可日常回答投資問題並安全拒絕輸出。
- Gate 2 真實 evidence operating loop 成立；scheduler 狀態無矛盾。
- P0 sources 有逐一接受／限制／拒絕決議，不以 candidate 冒充 formal。
- Portfolio Coach 以 Equal Weight benchmark、paper portfolio 與 target/current/gap 成立。
- Signal effectiveness 產生第一批 pruning / retirement 決議。
- Position Health / Exit 使用 thesis-based state machine。
- ML 如未符合 Gate，明確維持 shadow-disabled / readiness-only，不視為延期失敗。

---

## Gate 狀態校正（2026-07-12）

- Gate 0 已由 `ae83740` 與歸檔的 `SAFE_REFACTORING_MASTER_REPORT_2026_07_12.md` closeout；後續重構只作 maintenance，不再阻塞產品主線。
- Gate 1 已由 Advice DTO、fail-closed policy、read-only composer 與 Workbench DTO-to-view slice closeout。驗證見 `docs/06_qa/GATE_1_ADVICE_CLOSEOUT_2026_07_12.md`。Gate 1 的完成不折抵 Gate 2 的真實 weekly evidence、Gate 3 的 P0 source acceptance，亦不代表 broker execution 或投資有效性。
- 因此工程順序更新為 Gate 2 → Gate 3 → Gate 4；已完成 Gate 1 的 bounded Advice 仍維持 read-only / paper boundary。

## 更新記錄

- 2026-08-28：新增唯讀 `scripts/qa_technical_indicator_latency.py`、full-batch／isolated writer、real calculator staging process-pool、worker crash recovery／queued cancellation、parent single-writer integration staging 與 broker 離線 bounded-fetch acceptance probes；Broker CSV writer 加上 process-local single-writer lock。technical／broker pool 目前只在 protected-root 外 staging 以 bounded in-flight、retry、parent single writer 與 fail-closed checks 證明形狀；technical batch 的 production feature flag／scheduler lifecycle 已接上且預設關閉，真實 broker／Selenium 平行抓取仍未啟用；後續須補 owner-approved backup／rollback、technical canary 與真實 broker canary／rate-limit evidence。
- 2026-08-28：新增 `build_formal_input_owner_packet.py` 唯讀 owner handoff；從 bounded Formal candidate inventory 產生 `formal-input-owner-review.v1`，固定三項 expected input 的 owner／reviewer review slot 與 candidate metadata，輸出只能位於候選根目錄外，且固定 `formal_ready_input_count=0`、`formal_oos_allowed=false`、`candidate_only=true`、`write_performed=false`。這把候選盤點轉成可交接清單，但不選 candidate、不發布正式 manifest、不授予 Formal／promotion／broker credit。
- 2026-08-28：Data Update quick runner 新增 `data-update-status-history.v1` append-only JSONL（`--history-path`，預設與 latest status 同目錄），UpdateView 時間軸新增最近執行歷史表；只保存真實 runner 的 running／terminal status 摘要，既有 latest 不回填，未改資料、Evidence、Formal、scheduler 或 broker 邊界。
- 2026-08-27：新增 `scripts/append_source_acceptance_decision.py` 的 preview／明確確認 append foundation；applying decision 必須綁定 `ready_for_owner_review` intake 與 evidence ids，registry 只能位於 `DATA_ROOT` 之外，且 append 不改變 downstream／formal／scheduler／broker fail-closed 邊界。
- 2026-08-27：Update 大型每日合併與 SQLite CSV 匯出改用 `ProgressTaskWorker` 與批次進度回報；合併回報檔案／讀取批次／整合檔 chunk，匯出先以 query-only count 建立預估筆數並回報已處理筆數。取消仍維持檔案／資料批次安全邊界，不改變原子提交與既有資料保留規則；合併新增單檔內讀取批次取消檢查，仍不做逐列中斷。
- 2026-08-27：Update 增量合併在沒有新 CSV 時改回傳結構化 `no_op=true` 與既有筆數／最新日期，UI 明確顯示「資料已是最新」且不先建立備份，避免把 no-op 誤報成一般重新合併或產生不必要副作用。
- 2026-08-28：Runtime staging write probe 改用正式 `ResearchRunRepository` schema，於非正式暫存 DB 驗證 insert／讀回／rollback／清理並輸出 `registry_transaction_succeeded`；仍禁止指向正式 `DATA_ROOT`／`OUTPUT_ROOT`，不授予 scheduler／formal credit，也不宣稱正式 Registry ACL 已通過。
- 2026-08-28：`inspect_program_readiness.py` 新增唯讀 `--ml-direct-chain-status` 輸入；Direct/OOC `blocked_insufficient_storage`／已觀察的 `No space left on device` 會進入 performance lane 與 execution order，明確提示容量／保留策略，不啟動 worker、不刪除 immutable run。
- 2026-08-28：`inspect_program_readiness.py` 新增唯讀 `--runtime-readiness-json`；可載入允許 host context 產生的 `runtime-environment-readiness.v1`，避免 sandbox token 的正式檔案 handle `PermissionError` 覆蓋已核實的 host readiness；schema 不符即 fail-closed，仍不進行正式 Registry transaction。
- 2026-08-28：新增 `scripts/inspect_ml_storage_retention.py` 唯讀容量／retention inventory；只掃描明確根目錄的 metadata，輸出大目錄、manifest status 與可逆 owner review 候選，固定 `automatic_delete_allowed=false`，不刪除／搬移 immutable run。這讓 Direct/OOC 的 20 GiB headroom blocker 有可審核的容量證據，而不是直接重跑或猜測清理。
- 2026-08-28：Evidence scheduler readiness evaluator 新增 `evidence-production-scheduler-approval.v1` fail-closed gate；即使 source coverage 與 working-copy smoke 通過，仍需具名 owner、有效期限與 source／dry-run／backup／rollback／recovery checks 全部通過的 approval artifact，才可能回報 `operational_production`，避免 read-only readiness 自動放行 production write-mode。
- 2026-08-28：Formal readiness 對缺失的 `formal_prospective/clock-YYYYMMDD` path 新增 configured clock／training cutoff stale hint；只改善 owner handoff 診斷，不掃描或自動改接其他 clock，也不把 prospective bytes 升格成正式 input。
- 2026-08-27：Runtime formal path readiness 補上既有 logger／Research Registry 的不寫入 write-handle probe；`os.access` 與實際開啟權限不一致時，狀態固定降級為 `attention`，保留 formal ACL／鎖定 blocker。
- 2026-08-27：Runtime／MainWindow 窄版 UX 補強：長路徑診斷與 status strip 不再貢獻過大的水平 minimum hint；主視窗明確保留 320px compact 下限，Runtime 小於 720px 改用垂直治理欄並提供內容捲動。此為 presentation／可觀測性改善，不解除任何 formal、scheduler 或資料權限 blocker。
- 2026-08-27：Data Update 窄版 UX 補強：更新工作區加入垂直捲動，來源導覽移到上方，核心狀態卡改雙欄、候選卡單欄、操作按鈕直列；只修正 presentation，不改 update worker、SQLite sync 或資料來源 gate。
- 2026-08-27：Paper Portfolio readiness／weekly evidence／Equal Weight builder 新增台北交易日 future-date look-ahead guard；raw future snapshot 只保留診斷，current projection 改用最後一筆安全 snapshot，週報／benchmark builder 遇到 future period 直接降級或拒絕。Equal Weight builder CLI 也統一 UTF-8 stdout／stderr，Windows CP1252 可正常顯示 `--help` 與拒絕診斷。
- 2026-08-27：修正每日 Paper／Decision Desk 排程的 cutoff 選擇；排程入口改用最近已到達的台北 08:30，Paper writer 對明確未到達的 `--decision-at` 在開啟資料庫前回報 `skipped_future_decision`，避免重複產生 future／look-ahead row。既有正式 raw row 不刪除、不回填，仍需 owner 稽核。
- 2026-08-27：新增 `scripts/inspect_p0_intake_readiness.py` 唯讀 P0 source intake validator 與 13 列候選範本；它驗證 dossier schema／型別／分母／secret-like 欄位／安全旗標，將 `deferred`、`ready_for_owner_review`、`invalid_input` 分開投影，並固定不建立 decision registry、不授予 downstream eligibility。這是外部輸入的可重跑接入口，不是 source acceptance closeout。
- 2026-08-28：新增 `scripts/build_p0_intake_from_audit.py`，將既有 `p0-source-evidence-audit.v1` 的 machine row counts／payload hash／status 安全轉成 13 列 candidate intake，所有 owner／license／publication／PIT 欄位仍 fail-closed 為 `unverified`／`requires_review`；輸出限定 OS TEMP，不建立 registry、不改正式資料，也不授予 downstream eligibility。
- 2026-08-28：P0 source-evidence audit 的 MOPS verified-artifact 分支補上 validated artifact 的 raw／accepted／quarantine／blocked counts，讓 candidate intake 保留真實 coverage／row-conservation denominator（不再把已驗證 artifact 誤顯示為 `0/0`）；此修正不改 source acceptance、license、PIT authority 或 downstream eligibility。
- 2026-08-28：以允許 HTTPS 的 host context 重跑 P0 bounded live probe；12/13 官方路徑實際 observed、13/13 payload hash 存在，raw=`91,127`、accepted=`89,750`、blocked=`1,377`，再轉成 candidate intake／owner packet。這證明替代 acquisition route 可取得 machine evidence；publication timestamp、decision-time、license 與 owner acceptance 仍維持 fail-closed。
- 2026-08-28：MOPS EZSearch 季報 availability candidate 改支援 1–31 天 query window 與最多 3 次 error-only retry，manifest 保留每段 query window／attempt lineage；host context 以 40 個 7 天窗口重抓 2026-05 雙市場 F26–F29，取得 `7,473/7,473` events／projections，validator `accepted=7,473`、diagnostics=`0`。既有 raw 財報仍缺全量 explicit available-date，backfill dry-run `normalized=0`，所以此 evidence 仍只供 research candidate，未寫正式 mapping／SQLite 或解除 P0 source acceptance／Formal gate。
- 2026-08-28：將上述 chunked MOPS candidate 接回 P0 source-evidence audit；13/13 source rows 有 machine evidence，MOPS verified-artifact row conservation=`7,473/7,473`，並產生 13 列 candidate intake 與 Owner packet。validator 維持 `deferred`、owner-review-ready=`0`，所有 artifact 只在 TEMP；此步驟只增加可追溯 machine evidence，不把部分公告 availability 當成全量 raw available-date、source acceptance 或 Formal credit。
- 2026-08-28：補齊既有 performance／runtime／scheduler／freshness artifact 後，以 chunked MOPS audit 重算 unified readiness；新報告仍為 `action_required`，但 performance 不再因漏帶 baseline 而產生假性缺口，準確保留 Direct storage 與 technical production single-writer canary blockers。這是 read-model 更新，不改任何正式資料或 gate。
- 2026-08-28：歷史 MOPS EZSearch `2024-Q1` query 以 40 個 7 天窗口取得 `6,933` valid availability events／projections；8 筆缺 `CTIME` 的歷史列改為逐列 quarantine，artifact 以 `degraded` 保留有效資料與錯誤計數。對現有 raw 財報做 backfill dry-run 得到 `normalized=496`、`missing_available_date=1,645,059`；CLI 改為 bounded diagnostics，完整計數仍保留在 plan，`ready_for_apply=false` 與正式 mapping／SQLite 寫入邊界不變。這讓後續可按歷史窗口繼續擴充 coverage，而非把 schema drift 誤判成整批失敗。
- 2026-08-28：backfill 讀取器新增多份 `--availability-file` 累積能力；相同完整 candidate row 去重，同一 natural key 的不一致 provenance 經 revision validator fail-closed。2024-03／04／05 三份 MOPS candidate 合併唯讀盤點得到 `35,735` normalized rows，剩餘 `1,609,820` rows 缺 explicit available-date；這把「多來源補資料」變成可重跑、可稽核的 bounded path，仍不代表 mapping／SQLite 可直接 apply。
- 2026-08-28：以 retroactive baseline 加三份 MOPS candidate 做 hybrid planner dry-run，raw／normalized=`1,645,555 / 1,645,555`、diagnostics=`0`；records quality 分布為 official MOPS `observed=35,735`、baseline `degraded=1,609,820`。這提供完整 schema coverage 的安全 fallback，但 roadmap 仍要求逐段提高 official announcement／PIT coverage，不能把 baseline rows 升格成 Formal evidence。
- 2026-08-28：backfill plan／CLI 新增 `quality_counts`，讓完整 schema coverage、records quality 與正式 source acceptance 在同一份 dry-run 輸出中分開呈現；`ready_for_apply` 不再被解讀為 PIT／Formal gate 已通過。
- 2026-08-28：MOPS availability candidate 由 2024-Q1 繼續回溯至 2022-Q3（2023-05／08／11、2023-03、2022-11），hybrid planner 的 official observed raw records 提升至 `225,643`，degraded baseline 降至 `1,419,912`。官方 `status=fail` 空回應與 network／parser error 維持分流，未因部分月份成功而宣稱全期間 coverage 或解除 gate。
- 2026-08-28：再加入 2022-Q1／Q2 公告窗口（2022-05／08）；hybrid planner official observed raw records 提升至 `301,489`、degraded baseline 降至 `1,344,066`，全量 normalized／diagnostics=`1,645,555 / 0`。下一段按同一流程回溯 2021-Q4，仍維持 candidate-only 與正式 apply confirmation 邊界。
- 2026-08-28：2022-03 公告窗口（主要對應 2021-Q4）再取得 `5,966` valid events，hybrid planner official observed raw records 提升至 `335,620`、degraded baseline 降至 `1,309,935`；下一段按同一流程回溯 2021-Q3，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2021-11 公告窗口（主要對應 2021-Q3）再取得 `6,461` valid events，hybrid planner official observed raw records 提升至 `373,361`、degraded baseline 降至 `1,272,194`；下一段按同一流程回溯 2021-Q2，仍維持 candidate-only 與正式 apply confirmation 邊界。
- 2026-08-28：2021-08 公告窗口（主要對應 2021-Q2）再取得 `6,929` valid events，hybrid planner official observed raw records 提升至 `412,613`、degraded baseline 降至 `1,232,942`；下一段按同一流程回溯 2021-Q1，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2021-05 公告窗口（主要對應 2021-Q1）再取得 `6,349` valid events，36 個 query 有資料、4 個官方無資料；hybrid planner official observed raw records 提升至 `449,464`、degraded baseline 降至 `1,196,091`；下一段按同一流程回溯 2020-Q4，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2021-03 公告窗口（主要對應 2020-Q4）再取得 `5,989` valid events；hybrid planner official observed raw records 提升至 `484,302`、degraded baseline 降至 `1,161,253`；下一段按同一流程回溯 2020-Q3，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2020-11 公告窗口（主要對應 2020-Q3）再取得 `6,373` valid events；hybrid planner official observed raw records 提升至 `521,411`、degraded baseline 降至 `1,124,144`；下一段按同一流程回溯 2020-Q2，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2020-08 公告窗口（主要對應 2020-Q2）再取得 `6,610` valid events；hybrid planner official observed raw records 提升至 `559,082`、degraded baseline 降至 `1,086,473`；下一段按同一流程回溯 2020-Q1，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2020-05 公告窗口（主要對應 2020-Q1）再取得 `6,094` valid events；hybrid planner official observed raw records 提升至 `594,642`、degraded baseline 降至 `1,050,913`；下一段按同一流程回溯 2019-Q4，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2020-03 公告窗口（主要對應 2019-Q4）再取得 `5,864` valid events；hybrid planner official observed raw records 提升至 `630,985`、degraded baseline 降至 `1,014,570`；下一段按同一流程回溯 2019-Q3，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：2019-11 公告窗口（主要對應 2019-Q3）再取得 `6,444` valid events；hybrid planner official observed raw records 提升至 `670,943`、degraded baseline 降至 `974,612`；先重跑 unified readiness，再決定是否回溯 2019-Q2，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：歷史 MOPS coverage 回溯至 2019-Q3 後，以正確 real process-pool／broker canary baseline 重算 unified readiness；報告仍為 `action_required`，但只保留 P0 外部治理、Evidence pending review、Paper cost/fills、Formal inputs、Direct storage 與正式 technical canary blockers，仍不改正式 mapping／SQLite 或 Formal gate。
- 2026-08-28：Evidence weekly sidecar 新增唯讀 `scripts/build_evidence_weekly_approval_input.py`，把 8 筆 `pending_human_review` collection 轉成獨立 `evidence-weekly-approval-input.v1` owner／reviewer 交接包；packet 會驗證 source path／SHA-256、payload 與錯誤欄位，並固定 candidate-only、無寫入、無 Formal credit。這讓下一步從「找不到資料」收斂成外部具名 owner／reviewer 逐期決策；尚未產生 approved projection，不能直接餵入 Formal 或 scheduler。
- 2026-08-27：Pre-V2 readiness 的 Workbench、`inspect_pre_v2_readiness.py` 與 `inspect_simulated_phase_progress.py` 統一讀取 `WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH`（亦支援明確 projection path）；projection 只供 UI／readiness 揭露，不授予 formal credit，避免不同入口顯示不同 weekly Gate 數字。
- 2026-08-27：Decision Desk／Pre-V2／Workbench／Evidence source coverage 的 current snapshot 查詢加入台灣市場今日上限；future row 只留 raw 診斷並阻擋 current evidence。Evidence source coverage 與 snapshot inspector 改用 query-only 讀取，避免正式唯讀 DB 被 writer repository 初始化 schema。
- 2026-08-27：UpdateView 日期控件統一以台灣市場日期服務初始化；localized `不可用` 狀態改判異常；全域狀態檢查失敗時，六個核心與三個候選來源 inline 摘要同步清除舊內容並保留共同錯誤原因，候選來源分頁也會投影自己的檢查結果。補上 UI regression 與全量 pytest 證據，未改資料更新／SQLite 寫入契約。
- 2026-08-27：Recommendation Explain 補上 PatternScore rolling confirmation evidence；結果列保存 `PatternNames`／`Pattern_Signal`／`PatternAgeDays`，ReasonEngine 只消費已確認資料，無具體名稱時不從分數臆測型態。此為可追溯性修補，不改 score、交易訊號或任何 formal Gate。
- 2026-08-27：Recommendation 與四個策略 executor 移除未使用的全歷史 PatternAnalyzer 預掃描，避免和 ScoringEngine rolling path 重複計算；策略訊號與 score contract 維持不變。
- 2026-08-27：Data Update SQLite sync 修正欄位別名與重複條件處理；日期／股票代號／股票名稱的受治理 aliases 會先在副本上映射至 canonical schema，日期與四碼代號格式一致，raw CSV 不被改寫，缺必要欄位仍 fail-closed。
- 2026-08-26：Gate 3 先完成 13-source P0 Data Source Control Center 唯讀 read model、CLI 與 Evidence/Research Console 可見投影；只收斂 contract／audit／decision evidence，仍維持 auto-accept、downstream eligibility、formal OOS 與 production scheduler 關閉。
- 2026-08-19：新增 Gate 7 prospective restart execution lock；定案新未來 clock、Codex Rule Champion proposal、TWSE／TPEX 官方產業來源與 Broker 關閉邊界。
- 2026-07-12：校正 Gate 0 / Gate 1 closeout；下一工程 Gate 為真實 Evidence Operating Loop，不將 Advice 契約完成誤寫為 evidence、scheduler 或投資有效性完成。
- 2026-07-11：依 Post-Refactor 產品主線重寫為六個月 Gate；納入 Safe Refactor Closeout、Daily Usable Advice、Real Evidence Loop、P0 Data、Portfolio Coach、Signal Pruning、Position Health / Exit 與 conditional ML Shadow。

# baldr 未來六個月工程 Roadmap

> **2026-07-12 engineering package update**：Gate 2–7 的純工程 deliverables 已依獨立 slices 落地並由 `scripts/verify_gate_2_to_7_closeout.py` 驗證；external human/time/license/evidence/ML gates 尚未因此完成。後續執行重心轉為 [Gate 2–7 External Validation Register](../06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)，不得重做工程模擬來折抵真實時間或人工決議。

> **2026-07-14 evidence rehearsal update**：replay / P0 source shadow / ML shadow / lineage 的唯讀工程預演底座狀態為 `engineering_rehearsal_complete`；coverage、quality、missingness 與 blocker 可重跑，但不折抵任何 Gate 2–7 external human/time/license/evidence/ML 需求。詳見 [Evidence Rehearsal Engineering Closeout](../06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md)。

> **工程終態**：15 capability、canonical lineage 與 operations handoff 已收口為 `V3.3 Engineering Complete`；後續屬 `V4.0 Evidence Accumulation Track`，不是正式 V4.0。見 [V3.3 Engineering Closeout](../06_qa/V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)。

> **2026-07-13 系統整合校正**：跨流 contracts、唯讀正式資料 smoke、Dashboard／Broker latency 與 pure closeout verifier 已完成工程驗證。Gate 2 真實 forward evidence、Gate 3 source／license acceptance、Gate 7 formal OOS、shadow-day 累積與 promotion review 均仍是 external pending，不能由本次工程測試折抵。
>
> **最後更新**：2026-07-13
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
2. Data Source Control Center read model：freshness、coverage、schema、quarantine、retry、eligibility。
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

- 2026-07-12：校正 Gate 0 / Gate 1 closeout；下一工程 Gate 為真實 Evidence Operating Loop，不將 Advice 契約完成誤寫為 evidence、scheduler 或投資有效性完成。
- 2026-07-11：依 Post-Refactor 產品主線重寫為六個月 Gate；納入 Safe Refactor Closeout、Daily Usable Advice、Real Evidence Loop、P0 Data、Portfolio Coach、Signal Pruning、Position Health / Exit 與 conditional ML Shadow。

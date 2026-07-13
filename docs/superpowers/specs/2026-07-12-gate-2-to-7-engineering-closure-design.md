# Gate 2–7 工程閉環設計

> 日期：2026-07-12
> 狀態：已獲使用者批准
> 範圍：完成 Gate 2–7 目前可工程化的能力；真實時間、投資判斷、資料授權與 production approval 維持人工 Gate。

## 1. 目標

把現有 engineering readiness、單次 paper baseline、read-only health scaffold 與 V3 manual-validation 起點，演進成可每日／每週重複運行、可追溯、可回滾的研究閉環：

```text
Governed source observations
→ Evidence classification / maturity
→ Paper Portfolio snapshots
→ Position Health transitions
→ V3 effectiveness metrics / pruning package
→ Frozen ML dataset
→ Purged OOS challenger
→ Calibration / drift / registry
→ Shadow-only comparison
```

工程完成不等於任何 Gate 的投資有效性 closeout。沒有真實成熟 evidence 時，系統必須輸出 `waiting_for_time`、`requires_human_input`、`insufficient_sample` 或 `defer`。

## 2. 執行與提交策略

採依賴優先的垂直切片。每個切片必須：

1. 先有會因缺少該能力而失敗的測試。
2. 只修改完成該切片所需的最小範圍。
3. 同步對應 QA / Manual / authority 文件。
4. 通過 focused verification 後獨立 commit。
5. 不夾帶其他切片、工具輸出、正式資料或本機暫存檔。

跨工程包邊界執行完整 pytest、mypy、financial-float guard、look-ahead guard、py_compile 與 `git diff --check`。

## 3. Evidence 與 V3 資料品質

### 3.1 Event applicability

建立 event-family metric applicability contract，區分：

- `score_required`：Recommendation ranking 類事件應有 `score_bp`。
- `score_optional`：可帶 score，但不作缺失阻塞。
- `score_not_applicable`：risk prompt、純資料品質與部分 alert 不應被列為 missing score。

V3 報告只把 `score_required` 的缺值列為資料品質缺口，不得為不適用事件回填 score。

### 3.2 Event-price 與 maturity

- event price 必須使用 event decision 當下可得的最近合法交易日資料。
- 假日／週末 decision date 可對齊前一交易日，但必須保存 fallback reason。
- 不得使用 decision date 之後的價格作 event price。
- 每個 5 / 10 / 20 / 60 trading-day outcome 顯示 expected maturity date、ready / pending / missing 與缺失原因。

### 3.3 Effectiveness metrics

完整支持：forward / benchmark / industry / concept excess、MAE / MFE、hit、payoff、bucket monotonicity、Precision@K、regime、liquidity、execution feasibility、threshold robustness、component ablation。

每項輸出必須有 minimum sample、quality、limitations 與 `retain / restrict / downweight / retire / defer` 候選；只有人工 review 可以改正式狀態。

## 4. V2.3 P0 Source Control

### 4.1 統一 Source Contract

每個 P0 source 保存：

- source id、provider、endpoint、schema/version hash；
- observation date、as-of、實際 fetched-at、available-date；
- license / use scope / redistribution status；
- rate limit、freshness、coverage、missing / outage；
- retry、quarantine、stale policy；
- ingestion stage 與 downstream eligibility。

### 4.2 Adapter 群組

依可獨立驗收的來源群組拆分：

1. TWSE / TPEx corporate action 與 trading restriction。
2. TWSE / TPEx 三大法人。
3. TWSE / TPEx 信用交易。
4. TDCC 集保股權分散。
5. PIT 月營收公告日。
6. PIT 季度財報公告／更正日。

所有 adapter 先進 diagnostics / shadow store。未經人工接受時 `downstream eligibility=none`，不得接 ScoringEngine、formal Advice 或 Portfolio policy。

## 5. V2.4 Paper Portfolio 閉環

### 5.1 Durable paper state

建立 append-only paper snapshot repository，保存：

- policy version、source advice id、decision date；
- target / current / gap bp；
- shares、cash、NAV、price / available-date；
- commission、tax、slippage、partial fill、rejection；
- turnover、cooldown、rebalance band 與 diagnostics。

### 5.2 Daily mark 與 rebalance

每日 runner 只讀受治理價格與前一 snapshot，產生新的 paper snapshot。缺價格、stale、限制狀態或來源追溯時 fail-closed，不建立推測成交。

### 5.3 Benchmark 與 reporting

同一候選集合建立 Equal Weight baseline，按日／週輸出成本後 return、excess、drawdown、turnover、cash utilization、concentration 與 research-to-paper gap。

不串 broker、不改正式 Portfolio、不把 paper fill 寫成實際成交。

## 6. V2.5 Position Health / Exit

### 6.1 Thesis contract

每個 active paper / tracked position 支持 entry thesis、invalidation、holding horizon、review date、source trace 與人工 override。缺欄位時維持 `WATCH` 或 `legacy_degraded`。

### 6.2 State machine

狀態固定為：

```text
HEALTHY → WATCH → REDUCE_CANDIDATE → EXIT_CANDIDATE → CLOSED
```

允許在新證據下回復到較低風險狀態，但每次 transition 必須 append-only 保存 previous/new state、reason、quality、available-date 與人工覆核狀態。

### 6.3 Effectiveness

計算 alert lead time、alert 後 MAE、false positive / negative、avoided loss、opportunity loss、early-exit rate，以及 Add / Reduce 後續結果。任何 state 都不直接下單或平倉。

## 7. Gate 7 結構化傳統 ML Challenger

### 7.1 Dataset registry

建立 frozen dataset manifest，保存 feature schema、label schema、universe、decision dates、available-date policy、source versions、missing policy、purge / embargo、hash 與 row counts。

不允許 current mutable tables 在訓練時被隱式重讀；訓練必須引用 frozen dataset id。

### 7.2 Feature / label boundary

- features 只能使用 `available_date <= decision_date` 的 observation。
- labels 只由 decision date 之後的 outcome window 建立，不能回流成同日 feature。
- 支持 ranking label、calibrated success label 與 downside-risk label。
- 缺 benchmark、成本或 outcome maturity 時該 row 不得冒充 ready label。

### 7.3 模型範圍

第一版完整 challenger 包含：

- gradient-boosted ranking / regression challenger；
- downside-risk classifier；
- probability / confidence calibration；
- rule baseline 與 Equal Weight / existing score comparison。

優先使用現有環境中可重現的結構化 ML library；若新增依賴，必須固定版本並記錄 license。不得加入深度時序模型。

### 7.4 Purged OOS 與 registry

- 使用 purged walk-forward / embargo，避免相鄰 label window 洩漏。
- 保存每個 fold 的 train/test date、dataset hash、model config、seed、metrics 與 artifact hash。
- Model Registry 支持 `draft / shadow / rejected / promotion_review_candidate / retired`。
- champion 保持 rule baseline；challenger 不得自行 promotion。

### 7.5 Calibration、drift 與 rollback

支持 calibration curve / error、ranking metrics、net utility、downside capture、feature / label / prediction drift、regime stability 與 research-to-paper degradation。

每個 model version 必須有 rollback owner、previous champion、停用理由與可重跑命令。資料或 drift 不合格時輸出 `reject` 或 `continue_shadow`。

### 7.6 Shadow boundary

ML output 只能進 shadow store / report，不得被 formal Recommendation、Portfolio、Position Health、lifecycle 或 production scheduler import。靜態 dependency tests 必須防止反向接線。

## 8. Workbench 與 Closeout Verifier

Workbench 只讀呈現：

- Evidence maturity 與下一個 maturity date；
- P0 source acceptance / quarantine；
- Paper Portfolio NAV / benchmark / gap；
- Position Health transition queue；
- V3 pruning decision package；
- ML dataset / model / drift / shadow status。

Closeout verifier 依 Gate 檢查 required artifacts、hash、minimum sample、quality、人工 approval 與安全旗標。未完成項目必須列出，不得只回 pass / fail。

## 9. 人工與時間型 Gate 控制中心

最終建立一個可持續更新的 SSOT artifact，並由 CLI / Workbench 唯讀呈現。每個待辦包含：

- gate / capability / item id；
- 類型：`human_input`、`human_approval`、`waiting_for_time`、`data_license`、`evidence_maturity`、`ml_revalidation`；
- 目前狀態與阻塞原因；
- 需要補交的欄位或證據；
- owner 與 approval role；
- earliest validation date / required periods / current progress；
- artifact / source trace；
- 可直接執行的驗證命令；
- completion rule 與禁止事項。

### 9.1 ML 更新與再驗證 Runbook

控制中心必須明確列出：

1. 何時需要重新 freeze dataset。
2. 如何產生新 dataset version 與比較 schema drift。
3. 如何重跑 purged OOS。
4. 如何校準與檢查 calibration degradation。
5. 如何執行 feature / label / prediction drift。
6. 如何比較 rule champion 與 challenger。
7. 哪些結果只能 continue shadow / reject。
8. 何時可以建立人工 promotion review package。
9. 如何 rollback 到先前 model version。

任何 runbook 命令都不得直接啟用 formal model 或自動交易。

## 10. 錯誤處理與安全原則

- 核心金額、權重、成本、績效與風險使用 `Decimal` 或整數 bp；ML library 邊界的 float 必須隔離在明確 adapter。
- 所有日期型特徵先做 look-ahead / available-date 自查。
- missing / stale / schema drift / license unknown 一律 fail-closed。
- 不刪除或重建正式資料。
- 不啟用 production evidence scheduler、不串 broker、不自動 lifecycle。
- 工作樹既有使用者變更不得被覆寫。

## 11. 驗收標準

工程 closeout 必須同時具備：

1. 每個切片一個可回滾 commit，commit map 可追溯到 Gate 與測試。
2. Gate 2–6 的 runner / repository / read model / verifier 可在 sample 與受控 working-copy 重複運行。
3. Gate 7 frozen dataset、purged OOS、model registry、calibration、drift、rollback 與 shadow report 全部可重跑。
4. 靜態與動態測試證明 ML、Paper、Health 不會越權接 production decision path。
5. 人工與時間型 Gate 控制中心完整列出所有剩餘補件與驗證方法。
6. 完整 pytest、mypy、financial / look-ahead guard、py_compile 與 diff check 通過。
7. Snapshot、Roadmap companion、Architecture、QA 與 Application Manual 一致，且不把 engineering readiness 寫成投資有效性。


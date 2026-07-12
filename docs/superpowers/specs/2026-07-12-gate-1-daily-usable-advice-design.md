# Gate 1 Daily Usable Advice 設計規格

> 日期：2026-07-12  
> 狀態：已確認設計，待實作  
> 範圍：Gate 0 治理收口與 Gate 1 / V2.1 Daily Usable Advice

## 目標

在不修改既有推薦分數、回測、策略門檻、正式資料庫或排程器的前提下，將既有 Recommendation、Portfolio 與 Evidence 資料組合為可重算、可追溯且可拒絕的結構化 Advice。

## 非目標

- 不串接 broker、不自動下單、不自動平倉。
- 不修改 `ScoringEngine`、Recommendation ranking、Profile 權重或回測計算。
- 不將 candidate、shadow、replay 或 dry-run 冒充為正式投資有效性。
- 不啟用 production evidence scheduler 或寫入 production evidence DB。

## 產品政策

### 模式

- Guided Mode：只接受 promoted、參數鎖定且 disclosure 完整的策略；不可載入 candidate 或 ML shadow。
- Professional Mode：可呈現 candidate 研究結果，但與正式 Advice 明確隔離；共用同一 Advice Policy、DTO 與資料品質規則。

### 平衡風險檔

- 最低現金：`2000 bp`。
- 最大持倉數：8。
- 單一標的上限：`1500 bp`。
- 所有權重使用整數 bp；金額維持 `Decimal`。
- 資料不足、資料降級、策略狀態不符、市場風險過高、流動性或可成交性不足、風險預算已滿時，必須輸出 `RESEARCH`、`AVOID` 或 `NO_NEW_POSITION`，不得補值或硬湊候選。

## 架構與資料流

```text
既有 Recommendation / Portfolio / Evidence DTO
    -> AdviceComposer（application layer，唯讀）
    -> AdvicePolicy（mode、品質、可成交性、風險限制）
    -> RecommendationAdviceDTO / PortfolioAdviceDTO
    -> Workbench read-only presenter / view
```

`AdviceComposer` 不讀取 UI state、不直接查詢未受控資料、不寫 DB。UI 不計算 Advice；只渲染 DTO 與 source trace。Advice 的計算輸入必須保留 `decision_date` 與 `data_as_of_date`，並只採用決策當下可得資料。

## 契約

### Recommendation Advice

每筆結果至少包含：

- `advice_action`：`RESEARCH`、`ADD_CANDIDATE`、`HOLD`、`REDUCE_CANDIDATE`、`EXIT_CANDIDATE`、`AVOID` 或 `NO_NEW_POSITION`。
- Why、Why Not、Risk、Evidence tier、confidence tier、資料品質與 warnings。
- strategy / profile / version、`decision_date`、`data_as_of_date`、holding horizon、entry thesis、invalidation 與 execution feasibility。
- source trace、拒絕或降級原因。

### Portfolio Advice

每筆結果至少包含：

- `stock_code`、`advice_action`、`target_weight_bp`、`current_weight_bp`、`weight_gap_bp`。
- 平衡風險檔適用結果、可成交性、資料品質、理由、證據與 review date。
- 現金保留與持倉數限制的 diagnostics。

## 測試與驗收

先以測試鎖定下列行為：

1. Guided Mode 對 candidate / shadow fail-closed。
2. 缺資料、降級、不可成交與風險預算滿載時可產生拒絕輸出。
3. `NO_NEW_POSITION` 是有效結果，非例外。
4. 整數 bp、`Decimal` 金額、最大 8 檔、單檔 1500 bp、最低現金 2000 bp 不被突破。
5. DTO JSON round-trip、舊 payload compatibility 與 source trace 保留。
6. UI 僅渲染 Advice DTO，不直接呼叫核心計算或改寫資料。
7. 量化核心維持 no-look-ahead：所有輸入皆有決策日／資料截止日約束。

Gate 1 closeout 要求每日流程能回答「研究誰、能否新增、配置多少、持倉動作候選」，且 Advice 可拒絕、可回溯、可重算、可版本化；人工審查確認文案不暗示保證獲利或自動交易。

## Weekly Review History 操作契約

weekly review history 是 Gate 2 的真實時間證據，不是 Gate 1 完成的替代品。

每個真實週期由人工：

1. 檢查當週 data freshness、evidence dry-run、Evidence Review 與 Action Items。
2. 判讀資料缺口、warnings、需 follow-up 項目，決定 continue dry-run 或修正缺口。
3. 使用 `build_evidence_operations_weekly_review.py --save-history` 將覆盤快照保存至隔離 working-copy DB。
4. 使用 `--list-history` 驗證封存結果；累積至少三個不同真實週期。

人工不得直接編輯 SQLite history、以 replay 或 fixture 補週數，也不得使用 production DB 或 `--allow-production-like-db`。封存 history 不會啟用 scheduler、寫入正式 evidence DB 或套用 lifecycle action。

## 文件同步

- Gate 0 closeout 狀態以 `PROJECT_SNAPSHOT.md` 為準，並引用安全重構 closeout 證據。
- Gate 1 完成後同步 Snapshot、6M Roadmap、Roadmap Hub、system architecture、Manual、UI feature docs、navigation 與 index。
- V2.1 只在 Gate 1 exit criteria 全數通過後宣告 closeout；V3.0 engineering candidate 不因此變成正式 V3.0。

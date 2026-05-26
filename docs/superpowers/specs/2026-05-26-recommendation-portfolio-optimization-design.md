# 推薦組合優化設計規格

## 背景

目前 Recommendation tab 會依市場狀態與 Profile 產生當下推薦名單，並可一鍵送到 Backtest tab。現有流程主要把「現在推薦出的股票清單」轉成回測清單，再逐檔做單股或批次回測。這無法驗證「推薦系統本身」在歷史上的表現，也無法回答使用者實際操作時最重要的問題：若在每個歷史時間點依推薦邏輯買入一組股票，並照建議持有期間管理資金，整體組合績效如何。

本規格第一階段專注推薦組合優化。Sortino、Monte Carlo、VaR、CVaR 等穩健分析先保留為第二階段驗收層，不納入第一版必要範圍。

## 目標

1. 建立可回放的推薦流程：在歷史日期 t，只使用 t 以前資料產生推薦名單。
2. 建立推薦組合回測：用初始資金買入每期推薦組合，而不是逐檔獨立回測。
3. 支援推薦層參數優化：比較不同 top_n、權重、篩選條件、持有天數與資金分配方式。
4. 保留未來因子擴充空間：券商分點、營收、基本面、籌碼等資料應可作為新因子加入，不重寫回測核心。
5. 回測結果必須能追溯每一期買入、持有、出場的股票清單，用於判斷策略好壞來自哪些標的與哪些推薦條件。
6. Backtest tab 必須提升可讀性，讓使用者能先看懂組合層摘要，再下鑽到期間、股票、交易與推薦理由。

## 非目標

1. 第一版不實作 Monte Carlo、Sortino、VaR、CVaR、Ulcer Index。
2. 第一版不串接真實下單。
3. 第一版不強制改寫現有單股 BacktestService。
4. 第一版不移除現有 Profile 或一鍵送回測流程，只新增更正確的推薦組合驗證路徑。

## 核心概念

### Recommendation Snapshot

每個回測日期會產生一個推薦快照，至少包含：

- `as_of_date`
- `profile_id`
- `strategy_config`
- `regime`
- `recommendations`
- `factor_scores`
- `selection_reason`

快照必須可追溯，避免之後無法解釋為什麼某天買入某檔股票。

### Portfolio Audit Trail

推薦組合回測必須保留完整股票追溯資料。每一期至少包含：

- `rebalance_date`
- `selected_stock_codes`
- `selected_stock_names`
- `rank`
- `total_score`
- `factor_scores`
- `allocation_amount`
- `allocation_weight`
- `entry_date`
- `entry_price`
- `planned_exit_date`
- `actual_exit_date`
- `actual_exit_price`
- `exit_reason`
- `holding_days`
- `return_pct`

結果頁不能只顯示總報酬與勝率。使用者必須能回答：

- 哪些股票被這套推薦策略反覆選中。
- 哪些股票貢獻主要報酬。
- 哪些股票造成主要回撤。
- 哪些 rebalance date 推薦品質最差。
- 分數高的股票是否真的比低分股票表現好。

### Factor Slot

推薦分數不應寫死為技術指標、圖形、量能三類。第一版先保留現有三類，但資料結構預留：

- `technical`
- `pattern`
- `volume`
- `broker_flow`
- `revenue`
- `fundamental`
- `custom`

第一版只計算現有可用因子；未提供資料的因子回傳 neutral 或 missing，不阻斷流程。

### Portfolio Replay

推薦組合回測以「組合」為單位，不以單股排行榜為核心。每個 rebalance date：

1. 產生當日推薦名單。
2. 選擇 Top N。
3. 依資金分配方式配置部位。
4. 建立持倉。
5. 依持有期、停損停利或後續條件出場。
6. 更新組合 equity curve。

第一版出場規則先採 Profile 持有期為主：

- 暴衝策略：1 到 5 個交易日，預設 5 日。
- 穩健策略：5 到 20 個交易日，預設 20 日。
- 長期策略：20 到 60 個交易日，預設 60 日。

## 第一版模組

### RecommendationReplayService

職責：

- 讀取歷史資料。
- 在指定 `as_of_date` 截斷資料。
- 呼叫既有推薦邏輯產生推薦快照。
- 保證不使用未來資料。

預期介面：

```python
run_snapshot(as_of_date, profile_id, config, universe, top_n) -> RecommendationSnapshotDTO
```

### RecommendationPortfolioBacktestService

職責：

- 執行歷史推薦重播。
- 管理現金、持倉、出場。
- 產生組合 equity curve、trade list、snapshot list。
- 產生 `period_holdings` 與 `stock_contribution`，讓 UI 可顯示每期選股明細與個股貢獻。

預期介面：

```python
run_portfolio_backtest(
    start_date,
    end_date,
    profile_id,
    recommendation_config,
    initial_capital,
    rebalance_frequency,
    top_n,
    allocation_method,
    holding_days,
) -> RecommendationPortfolioBacktestResultDTO
```

`RecommendationPortfolioBacktestResultDTO` 至少包含：

- `summary`
- `equity_curve`
- `trades`
- `snapshots`
- `period_holdings`
- `stock_contribution`
- `selection_diagnostics`

第一版支援的 `allocation_method`：

- `equal_weight`
- `score_weight`

### RecommendationPortfolioOptimizerService

職責：

- 掃描推薦層參數組合。
- 對每組參數跑推薦組合回測。
- 依目標函數排序。

第一版優化參數：

- `top_n`
- `pattern_weight`
- `technical_weight`
- `volume_weight`
- `price_change_min`
- `volume_ratio_min`
- `rsi_max`
- `holding_days`
- `allocation_method`

第一版目標函數：

```text
score = total_return - abs(max_drawdown) * drawdown_penalty - invalid_sample_penalty
```

其中交易次數過少、推薦數量過少、資料不足都會產生 `invalid_sample_penalty`。

## UI 流程

第一版 UI 可先放在 Backtest tab 的新區塊或新子頁：

- 模式：單股回測 / 批次單股回測 / 推薦組合回測
- Profile 選擇
- 回測期間
- 初始資金
- Top N
- 持有天數
- 資金分配方式
- 是否執行參數優化

Backtest tab 的推薦組合結果要分成五個閱讀層次：

1. **總覽**：總報酬、最大回撤、勝率、交易次數、平均持有天數、資金使用率。
2. **期間明細**：每個 rebalance date 選了哪些股票、配置多少資金、後來報酬如何。
3. **個股貢獻**：依股票彙總總損益、平均報酬、被選次數、勝率、最大單筆虧損。
4. **交易紀錄**：每一筆買入與賣出，含進出場日期、價格、股數、費用與出場原因。
5. **推薦診斷**：推薦數量不足、資料不足、分數分布異常、因子缺失等警示。

Recommendation tab 的「一鍵送回測」後續應改成兩個選項：

- 送出目前名單做批次單股回測
- 送出目前 Profile/Config 做推薦組合回測

Recommendation tab 更新重點：

- 顯示目前 Profile/Config 是否可做推薦組合回測。
- 一鍵送回測時傳遞完整 Profile/Config，而不是只傳遞當下股票清單。
- 顯示「這次推薦若進入組合回測，將使用 Top N、持有天數、資金分配方式」的摘要。
- 保留現有送出股票清單流程，避免破壞既有批次單股回測使用方式。

第一版可以先實作服務與測試，再接 UI。

## 驗證策略

第一版測試重點：

1. 歷史推薦快照不使用 `as_of_date` 之後資料。
2. 等權資金分配總額不超過可用資金。
3. 持有期到期後會出場。
4. 多期推薦會產生可用 equity curve。
5. 優化結果依目標函數排序。
6. 缺少未來因子資料時流程不中斷。
7. 回測結果能列出每期選入股票與每檔股票的組合貢獻。
8. UI 結果資料模型能支援總覽、期間明細、個股貢獻、交易紀錄與推薦診斷五個視圖。

## 後續擴充

第二階段再加入穩健分析：

- Sortino Ratio
- Calmar / MAR
- VaR / CVaR
- Monte Carlo trade sequence simulation
- Walk-forward OOS 評估
- Rolling Sharpe / Rolling Sortino

第三階段加入新資料因子：

- 券商分點表現
- 營收 YoY / MoM
- 法人籌碼
- 財報與基本面
- 產業相對強弱

## 風險

1. 歷史推薦重播會重複計算多檔股票與多個日期，第一版需限制 universe 或日期頻率。
2. 現有 PatternScore 尚未真正接上 PatternAnalyzer，推薦組合回測會先暴露這個問題。
3. 現有批次回測是每檔獨立資金，不能直接重用為組合回測。
4. 若 Profile 設定與回測策略版本分離，後續需補 Strategy Version 掛載機制。

## 決策

第一版先做服務層與測試，不先大改 UI。完成後再把 Backtest tab 與 Recommendation tab 串到新服務。

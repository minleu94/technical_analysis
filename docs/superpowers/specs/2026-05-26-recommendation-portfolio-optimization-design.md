# 推薦組合優化設計規格

## 背景

目前 Recommendation tab 會依市場狀態與 Profile 產生當下推薦名單，並可一鍵送到 Backtest tab。現有流程主要把「現在推薦出的股票清單」轉成回測清單，再逐檔做單股或批次回測。這無法驗證「推薦系統本身」在歷史上的表現，也無法回答使用者實際操作時最重要的問題：若在每個歷史時間點依推薦邏輯買入一組股票，並照建議持有期間管理資金，整體組合績效如何。

本規格第一階段專注推薦組合優化。Sortino、Monte Carlo、VaR、CVaR 等穩健分析先保留為第二階段驗收層，不納入第一版必要範圍。

## 目標

1. 建立可回放的推薦流程：在歷史日期 t，只使用 t 以前資料產生推薦名單。
2. 建立推薦組合回測：用初始資金買入每期推薦組合，而不是逐檔獨立回測。
3. 支援推薦層參數優化：比較不同 top_n、權重、篩選條件、持有天數與資金分配方式。
4. 保留未來因子擴充空間：券商分點、營收、基本面、籌碼等資料應可作為新因子加入，不重寫回測核心。

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

Recommendation tab 的「一鍵送回測」後續應改成兩個選項：

- 送出目前名單做批次單股回測
- 送出目前 Profile/Config 做推薦組合回測

第一版可以先實作服務與測試，再接 UI。

## 驗證策略

第一版測試重點：

1. 歷史推薦快照不使用 `as_of_date` 之後資料。
2. 等權資金分配總額不超過可用資金。
3. 持有期到期後會出場。
4. 多期推薦會產生可用 equity curve。
5. 優化結果依目標函數排序。
6. 缺少未來因子資料時流程不中斷。

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

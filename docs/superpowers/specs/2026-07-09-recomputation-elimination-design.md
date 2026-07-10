# 重複計算消除與排程相容設計

## 目標

在不改變推薦、回測、每日決策與既有排程公開入口的前提下，消除三類重複工作：

1. 推薦流程重複計算最新一日 `漲幅%` 與 `成交量變化率%`。
2. 推薦與回測在技術指標已由 `UpdateService` 以相同參數算好時再次計算。
3. Daily Decision Desk 的 Market Breadth、Relative Strength / Liquidity 與 Smart Money 對相同交易日區間重複讀取 `daily_prices`。

本變更只減少重複工作，不改變分數、篩選門檻、推薦排序、回測撮合、績效、DTO、排程參數、資料寫入 gate 或 Look-ahead 契約。

## 非目標

- 不建立跨程序或跨日持久 cache。
- 不變更 `UpdateService.calculate_technical_indicators()` 的排程介面或執行順序。
- 不把 ATR、ADX 等目前未預存的指標假裝成可重用資料。
- 不修改策略參數、預設值、分數權重或篩選規則。
- 不修改 production scheduler、dry-run / confirm gate 或正式資料。
- 不進行與重複計算無關的大型 service / view 拆分。

## 方案選擇

採用「參數契約感知的重用 + 單次 snapshot 市場資料 frame」。

未採用「只要欄位存在就重用」，因為無法防止自訂參數誤用預設指標。未採用跨執行持久 cache，因為失效條件會增加 stale data 與排程風險。

## 架構設計

### 1. 推薦衍生市場特徵

新增純粹的市場特徵 helper，接收單一股票、已依日期排序的 DataFrame，回傳防禦性複製並只在最新一列寫入：

- `漲幅%`：最新收盤價相對前一筆有效觀測值的百分比變化。
- `成交量變化率%`：最新成交量相對前 20 筆歷史成交量平均；歷史不足 20 筆時沿用目前以前序全部資料平均的規則。

helper 必須保留目前的欄位別名、缺值、零分母與短歷史行為。金融運算使用 `Decimal`；若既有 pandas 篩選契約需要 numpy 數值，轉換只能發生在明確註記的 DataFrame 分析邊界。

`RecommendationService` 在每檔股票進入 `StrategyConfigurator` 前只呼叫一次 helper。後續三個消費者都讀取同一結果：

- `StrategyConfigurator` 的硬門檻篩選。
- 成功推薦的 DTO / reason 組裝。
- 空結果的 negative evidence 與 liquidity exclusion 判定。

`StrategyConfigurator` 保留對直接呼叫者的 fallback：只有輸入缺少衍生欄位時才呼叫同一 helper，不再保留另一份公式。

### 2. 技術指標參數契約重用

新增技術指標重用判定器，對每個已啟用指標執行以下順序：

1. 透過 `IndicatorParameterRegistry.validate_and_sanitize()` 正規化並驗證參數，保留 schema v1+ fail-closed 行為。
2. 比對正規化參數是否等於 `IndicatorParameterRegistry` 的標準預設值。
3. 檢查該指標所需的既存欄位是否存在，且不是整欄無效。
4. 只有第 2、3 點都成立才重用；自訂參數、缺欄位或無效資料一律重新計算。

預存欄位與現行分析欄位的相容別名由單一 mapping 處理，例如：

- `slowk` / `slowd` 對應 `SlowK` / `SlowD`。
- `upperband` / `middleband` / `lowerband` 對應 `BB_Upper` / `BB_Middle` / `BB_Lower`。

RSI、MACD、KD、Bollinger、SAR、TSF 與標準 MA 可在契約相符時重用。ATR、ADX 目前不由 `calculate_all_indicators()` 預存，因此仍依原流程計算。這不是重算，且不得為追求命中率而使用缺少來源契約的值。

重用判定整合於 `StrategyConfigurator.configure_technical_indicators()`，因此推薦、單股回測、批次回測與最佳化使用相同規則；既有方法簽名保持相容。

### 3. Decision Desk 單次 snapshot 市場資料 frame

新增唯讀 `DecisionMarketFrameLoader`，集中讀取指定 `as_of_date` 以前、足以支援現有 section 的交易日資料，至少包含：

- `日期`
- `證券代號`
- `收盤價`
- `漲跌價差`
- `成交股數`

loader 以 `as_of_date` 為 key，僅在同一次 `DecisionDeskSnapshotBuilder.build_snapshot()` 生命週期內重用。每次建立新 snapshot 前必須失效舊 frame，因此同日資料更新後再次建立 snapshot 仍會重新讀取 SQLite。

Market Breadth、Relative Strength / Liquidity 與 Smart Money 的 SQLite provider 接受可選的共享 loader：

- 有共享 loader 時從 frame 篩選所需交易日與股票。
- 未注入時保持原本獨立 SQL 路徑，確保既有測試、外部組裝與降級行為相容。

`decision_desk_builder_factory.py` 與 Qt composition root 會讓三個 provider 共用同一 loader。`DecisionDeskSnapshotBuilder` 僅負責在 snapshot 開始時失效該 loader，不改 section 建立順序、quality、warnings、fallback 或 dashboard composition。

共享 frame 必須維持 `日期 <= as_of_date`，不得讀取決策日之後資料。

## 排程相容性

下列公開入口與參數保持不變：

- `RecommendationService.run_recommendation()`
- `BacktestService.run_backtest()`
- `UpdateService.calculate_technical_indicators()`
- `DecisionDeskSnapshotBuilder.build_snapshot()`

排程腳本不需要改設定或命令列參數。`scheduled_recommendation_snapshot` 仍呼叫 RecommendationService；evidence / Decision Desk 排程仍透過既有 builder / service 組裝。共享市場 frame 是單次呼叫內的唯讀最佳化，不跨排程執行保存狀態。

## 錯誤與降級行為

- 指標參數無效：維持 `InvalidParameterError` fail-closed，不因 cache 降級吞掉錯誤。
- 預存指標缺欄位或全為無效值：重新計算，不宣稱 cache hit。
- Decision Market Frame 載入失敗：provider 沿用既有 SQL / section 降級路徑，維持 `MISSING` / `DEGRADED` warnings。
- 空推薦結果：negative evidence 使用本次已算好的成交量變化，不再另算，但 reason code 與 payload 格式不變。
- 不新增正式資料寫入、schema migration 或 cache 檔案。

## Look-ahead 與金融數值自查

- 衍生市場特徵只使用當前股票排序後的最後一筆與其之前的資料。
- 技術指標重用只接受已與價格以相同 `證券代號 + 日期` join 的欄位，不讀取決策日之後資料。
- Decision Market Frame SQL 與所有篩選固定使用 `日期 <= as_of_date`。
- 不改 benchmark、停損停利、訊號執行日或撮合時間軸。
- 新增百分比運算使用 `Decimal`；DataFrame 相容轉換明確隔離並測試等價輸出。

## 測試設計

採 TDD，先建立失敗測試，再實作最小修正：

1. 同一股票的價格與成交量特徵只計算一次，成功與空結果路徑取得相同值。
2. 缺值、零成交量、短歷史及欄位別名維持現有輸出。
3. 預設參數且欄位完整時不呼叫底層指標計算器。
4. 自訂參數、缺欄位、全無效欄位時必須呼叫底層計算器。
5. schema v1 缺必要參數仍 fail-closed，即使 DataFrame 已有同名欄位。
6. 同一次 Decision Desk snapshot 的三個 provider 共用一次市場 frame 載入。
7. 下一次 snapshot 必須重新載入；不同 `as_of_date` 不得共用。
8. Market Breadth、Relative Strength / Liquidity、Smart Money DTO、quality 與 warnings 與現況一致。
9. scheduled recommendation 與 scheduled evidence wrapper 的參數、結果狀態與 dry-run gate 不變。

驗證至少涵蓋推薦、回測、Decision Desk、排程 wrapper、語法與 mypy；不使用正式資料庫進行寫入測試。

## 預計變更邊界

預計新增或修改以下責任明確的檔案；實作計畫可依現有測試位置調整測試檔名，但不得擴張功能範圍：

- 新增 `decision_module/derived_market_features.py`
- 新增 `decision_module/indicator_reuse.py`
- 修改 `decision_module/strategy_configurator.py`
- 修改 `app_module/recommendation_service.py`
- 新增 `app_module/decision_market_frame.py`
- 修改 `app_module/market_breadth_service.py`
- 修改 `app_module/relative_strength_liquidity_service.py`
- 修改 `app_module/smart_money_semantic_service.py`
- 修改 `app_module/decision_desk_service.py`
- 修改 `app_module/decision_desk_builder_factory.py`
- 修改 `ui_qt/main.py`
- 新增或修改對應 `tests/` 測試
- 同步 `PROJECT_SNAPSHOT.md`、`system_architecture.md` 與 `APPLICATION_MANUAL.md` 中的行為邊界說明

## 驗收條件

- 公開 service 方法簽名與排程命令列介面不變。
- 推薦衍生特徵在單檔單次推薦中只計算一次。
- 預設且完整的預存技術指標不再重算，自訂或不可信資料仍重算。
- 單次 Decision Desk snapshot 不再對相同市場區間重複查詢 `daily_prices`。
- 推薦、回測、Decision Desk 與排程測試全部通過。
- mypy 與 Python 語法檢查通過。
- 無正式資料寫入、無 SQLite schema 變更、無跨執行 stale cache。

# Research Lab 工作流重整設計規格

## 背景

目前推薦、回測、觀察清單與持倉管理都已有功能，但使用者體驗呈現「各自長大」的狀態：

- 推薦頁可以快速產出名單，但下一步行動分散。
- 回測頁功能很多，策略回測、單股回測、批次回測、推薦組合回測、Promote、歷史比較等入口混在一起。
- 觀察清單像一般收藏夾，沒有清楚扮演「我要拿哪一批去測」的候選池角色。
- Portfolio 已有交易紀錄與持倉日誌雛形，但尚未清楚承接研究結果的來源脈絡。

本規格要解決的是產品與架構定位問題，不是新增另一個大型功能。核心目標是把既有能力整理成一個可理解的研究工作流，讓使用者知道自己正在做哪一種實驗、實驗輸入從哪來、結果要流向哪裡。

## 目標

1. 將 Backtest tab 明確定位為 **Research Lab（研究實驗室）**。
2. 將 Research Lab 拆成不同實驗模式，各自有清楚用途、輸入、輸出與下一步。
3. 將 Watchlist / 觀察清單重新定位為 **候選池 / 實驗 Universe**，回答「我要測哪一批」。
4. 定義 Strategy Center 雛形，承接策略模板、策略版本、回測紀錄與 Promote 流程。
5. 讓 Recommendation、Watchlist、Research Lab、Portfolio 之間的資料流有可追溯來源，不再只是 UI 按鈕互相丟資料。
6. 第一階段以流程整理、模式分層與最小 UI 降噪為主，不重寫回測核心。

## 非目標

1. 第一階段不新增自動交易、自動下單或自動調倉。
2. 第一階段不移除既有回測能力，只重新分層與整理入口。
3. 第一階段不把所有策略版本管理一次做成完整 Strategy Center；只建立清楚入口與資料 contract。
4. 第一階段不將固定股票組合回測與推薦系統歷史重播混為同一種模式。
5. 第一階段不改變 roadmap phase 定位；此重整服務 Phase 4.1 與後續 Strategy Center 發展。

## 核心模型

### Research Lab 模式

Research Lab 至少分成以下模式：

| 模式 | 主要問題 | 輸入 | 輸出 |
|---|---|---|---|
| 策略回測 | 這個策略模板或策略版本是否有效？ | strategy template / strategy version、參數、股票或 universe | 策略表現、優化結果、Promote 候選 |
| 單股回測 | 某檔股票套某策略是否合適？ | stock code、strategy、期間、風控參數 | 單股交易紀錄、績效、圖表 |
| 批次股票回測 | 一批股票各自套策略，誰比較適合？ | watchlist / universe、strategy、期間 | leaderboard、每檔 run、比較結果 |
| 固定組合回測 | 固定一批股票一起持有或輪動表現如何？ | watchlist / basket、配置方式、期間 | portfolio equity、個股貢獻 |
| 推薦系統回放 | 推薦邏輯在歷史日期會如何選股？ | profile/config、top N、rebalance、holding days | recommendation replay、selection diagnostics、策略改善線索 |

這些模式共享 Research Lab，但不應在同一個操作面板中全部展開。UI 應先讓使用者選擇「我要做哪種實驗」，再顯示該模式必要參數。

### Watchlist / Candidate Pool

觀察清單在研究工作流中的定位是 **候選池**，不是單純收藏夾。

每個候選池應至少保留：

- 清單名稱
- 股票清單
- 來源：推薦、強勢股、弱勢股、主力流向、手動、歷史研究
- 用途標籤：待觀察、待單股回測、待批次回測、固定組合回測
- 建立時間與備註
- 若來自 Recommendation，保存 profile/config/regime/result id 摘要

第一階段不要求重做 Watchlist 儲存格式，但 UI 與資料流要開始用「候選池」語言表達。

### Strategy Center 雛形

Strategy Center 是未來承接策略模板與策略版本的概念，不一定在第一階段新增頂層 tab。

它應負責：

- 管理既定策略模板。
- 管理從回測 Promote 出來的策略版本。
- 記錄策略版本的歷史回測狀況。
- 讓 Research Lab 可以選擇策略模板或策略版本進行實驗。
- 讓 Recommendation/Profile 後續可以套用已驗證策略版本。

第一階段只在 Research Lab 中建立清楚的 strategy source contract：

- `strategy_source_type`: `template` / `preset` / `version` / `recommendation_profile`
- `strategy_source_id`
- `strategy_source_name`
- `strategy_snapshot_hash`
- `strategy_snapshot_summary`

### Phase 3 到 Portfolio 的來源追溯

Portfolio 不應承接「推薦名單」本身，而應承接使用者明確決定記錄的交易或部位。

從 Recommendation / Backtest / Strategy Version 記錄到 Portfolio 時，應保存：

- `source_type`: `recommendation_result` / `backtest_run` / `strategy_version` / `manual`
- `source_id`
- `source_snapshot_hash`
- `source_summary`
- 使用者輸入的交易日期、價格、股數、費用與備註

Portfolio 仍以 append-only trades 作為唯一來源。Position 由 trade 重建，不啟用舊的獨立 Position JSON 儲存作為主路徑。

## 第一階段設計

### 1. Research Lab 入口降噪

BacktestView 第一階段應把既有功能重新分組：

- 模式選擇：單股、批次、固定組合、推薦回放、策略研究。
- 日常模式只顯示該模式必要參數。
- Grid Search、Promote、歷史比較、圖表切換等放入進階或結果區，不在初始畫面同時展開。

這是 UI 分層，不是回測核心重寫。

### 2. Recommendation 下一步動線

Recommendation 結果頁應把下一步分成清楚選項：

- 加入候選池：把目前推薦結果存成 Watchlist / Candidate Pool。
- 送 Research Lab 做批次股票回測：測當下名單中每檔股票。
- 送 Research Lab 做推薦系統回放：測目前 Profile/Config 的歷史表現。
- 記錄到 Portfolio：只針對使用者選定股票，打開交易紀錄對話框，並保存推薦來源脈絡。

第一階段可以保留既有按鈕，但文字與右鍵選單要對齊上述語意。

### 3. Watchlist 候選池重整

WatchlistView 第一階段不做大重寫，只先補三件事：

- 顯示清單來源與用途。
- 提供「送 Research Lab 批次回測」作為主行動。
- 避免把 watchlist 描述成雜亂管理器，統一稱為候選池或觀察候選池。

### 4. Portfolio 來源封裝

新增小型 adapter/service，用來從 Phase 3 產物建立 Portfolio trade metadata。

預期職責：

- 從 RecommendationDTO / RecommendationResultDTO 建立 source metadata。
- 從 Backtest run / trade row 建立 source metadata。
- 產生穩定 snapshot hash。
- 呼叫 `PortfolioService.record_trade()`，不直接寫 storage。

此 adapter 不做損益計算、不做交易決策、不改變 Portfolio domain。

## 資料流

### 推薦到批次回測

```text
Recommendation Result
→ Candidate Pool / Watchlist
→ Research Lab: Batch Stock Backtest
→ Backtest runs + leaderboard
→ 可選：Promote 策略版本或記錄研究筆記
```

### 推薦到推薦回放

```text
Recommendation Profile/Config
→ Research Lab: Recommendation Replay
→ Recommendation Portfolio Backtest Result
→ 改善建議 / Promote recommendation strategy version
```

### 回測到策略版本

```text
Strategy Template / Preset
→ Research Lab: Strategy Backtest
→ Backtest Run
→ PromotionService
→ Strategy Version
→ Future Strategy Center
```

### 研究到持倉

```text
Recommendation / Backtest / Strategy Version
→ User records explicit trade
→ PortfolioService.record_trade()
→ Derived Position
→ Journal / condition monitor
```

## UI 原則

1. 使用者先選「實驗模式」，再看參數。
2. 每個模式只顯示必要參數，其餘放進進階區。
3. Watchlist 主語是「候選池」，不是普通收藏。
4. Portfolio 主語是「已決定記錄的交易與持倉」，不是推薦名單。
5. 所有跨頁動作都要保存來源脈絡。
6. 不在 UI 中加入交易建議文字，只呈現研究與監控資訊。

## 驗證策略

第一階段測試重點：

1. Recommendation 選中股票記錄到 Portfolio 時，trade 會保存 recommendation source metadata。
2. Backtest trade row 記錄到 Portfolio 時，trade 會保存 backtest source metadata。
3. Portfolio 仍由 trades 重建 positions，不使用舊 Position JSON 作為主路徑。
4. Watchlist / Candidate Pool 可作為批次回測輸入。
5. Research Lab 模式切換不破壞既有單股回測與推薦組合回測。
6. 新增跨頁 metadata 不引入裸金融核心計算。

## 風險

1. BacktestView 已經很大，若直接在同一檔案加更多 UI，會讓維護性更差。第一階段應優先抽小元件或先做低風險分組。
2. Watchlist 目前既是候選池又是管理器，文案與資料模型存在不同步風險。第一階段先改入口與顯示，不急著重寫儲存。
3. Portfolio 現有 DTO 使用 float，第一階段若新增 trade metadata，應避免擴大金融計算邊界；後續需另開合規化任務處理 Decimal / integer unit。
4. Strategy Center 概念若一次做太大，會偏離目前痛點。第一階段只建立 strategy source contract。

## 第一階段交付範圍

1. Research Lab 模式分層設計落地到 Backtest UI 的最小可見改動。
2. Recommendation 下一步動線重新命名與整理。
3. Watchlist 候選池定位的最小 UI/文案調整。
4. Phase 3 → Portfolio source metadata adapter。
5. 對應測試與文檔同步。

## 後續階段

第二階段：

- 正式 Strategy Center UI。
- 策略模板與策略版本列表。
- 策略版本回測歷史與 Promote lineage。

第三階段：

- Watchlist / Candidate Pool 資料模型補強。
- 固定組合回測與推薦回放的 UI 完整分離。
- Portfolio 條件監控接入 strategy version / recommendation snapshot 對照。

# 策略回測實驗室功能說明

## 概述

「策略回測」標籤已升級為完整的「實驗室/策略工作台」，支援反覆研究、知識累積、快速迭代。

## 已實作功能（優先級 1-4）

### 參數與評分治理

- 新版指標配置採 Fail-Closed：未知欄位、錯誤型態、越界值與跨欄位衝突會拒絕執行。
- disabled 指標不驗證、不計算、不產生空欄位。
- 推薦打分權重採三鍵整數 bp 契約，總和固定為 `10000 bp`；Regime 重分配後仍重新驗證。
- `TotalScore` / `FinalScore` 使用 Decimal 計算並量化至 `0.01` 分，供 fixed / quantile 門檻與重播使用。

### 推薦組合回測

推薦組合回測會在歷史日期重播推薦邏輯，形成一組股票持倉，並以同一筆初始資金計算組合績效。結果包含總覽、期間明細、個股貢獻、交易紀錄與推薦診斷，用於判斷策略好壞來自哪些股票與哪些推薦條件。

這個功能與既有「一鍵送回測」不同：
- 既有一鍵送回測：把目前推薦結果中的股票清單送去做單檔或批次回測。
- 推薦組合回測：把 Profile/Config 送去回測頁，在每個歷史再平衡日重新跑一次推薦，依持有天數建立整組投資組合。

**使用方式**：
1. 在推薦頁執行推薦分析。
2. 點擊「送推薦組合回測」，把 Profile/Config 載入回測頁。
3. 在回測頁左側「推薦組合回測」區設定每次推薦檔數、每期候選上限、持有天數、重播頻率與資金配置。
4. 使用回測頁既有開始日期、結束日期與初始資金欄位。
5. 點擊「執行推薦組合回測」。
6. 在右側「推薦組合」結果頁查看期間明細、個股貢獻與交易紀錄。

**目前限制與建議**：
- 第一次驗證建議先用最近 1 個月、每期候選上限 20，確認有結果後再放大到 6 個月與候選 50/100。
- 已驗證 6 個月 / 每週重播 / Top 10 / 候選 50 可產生結果，但正式資料量大時仍需要等待約數分鐘。
- 目前已顯示整組報酬、最大回撤、交易檔數、平均持有天數、資金使用，並完整包含 Sharpe Ratio、Sortino Ratio 與 Monte Carlo P05/P50/P95 模擬報酬等組合層穩健性指標。
- 券商表現、營收資料與更多基本面/籌碼因子尚未接入，未來應以 factor/metric layer 擴充。

### ✅ 1. 策略預設 (Strategy Preset)

**使用者價值**：
- 一鍵重跑同策略同參數
- 建立策略庫（暴衝/穩健/長期看漲等）
- 與 Regime 切換策略配置接軌

**UI 位置**：
- 左側配置面板上方
- Preset 下拉選單：選擇已存的策略設定
- 儲存/載入/刪除按鈕

**後端實作**：
- `app_module/preset_service.py` - PresetService
- 儲存格式：JSON（含版本號、名稱、策略ID、參數、標籤、時間戳）
- 儲存位置：`{output_root}/backtest/presets/`

**使用方式**：
1. 配置策略參數
2. 點擊「儲存」→ 輸入預設名稱
3. 之後從下拉選單選擇預設 → 點擊「載入」

---

### ✅ 2. 選股清單 (Universe/Watchlist)

**使用者價值**：
- 回測不再只驗證單一股票，可驗證策略是否「可泛化」
- 支援：強勢股清單、本週產業清單、口袋名單
- 可做「同策略跑多檔」出總結

**UI 位置**：
- 左側「股票代號」區域
- 模式切換：單一股票 / 選股清單
- 清單來源：從下拉選單選擇已保存的 Watchlist

**後端實作**：
- `app_module/universe_service.py` - UniverseService
- 儲存格式：JSON（含名稱、代號列表、來源、篩選條件）
- 儲存位置：`{output_root}/backtest/watchlists/`
- 支援匯入/匯出 CSV

**使用方式**：
1. 切換模式為「選股清單」
2. 從下拉選單選擇已保存的清單
3. 視工作量勾選「並行執行」；小型清單會依門檻自動採循序執行
4. 執行回測；執行期間可按「取消」停止提交新工作，系統會等待已開始的工作安全結束

**並行與保存安全**：
- 批次回測使用 `ProcessPoolExecutor`，並限制同時送入的工作數量，避免大量清單造成記憶體暴增
- SQLite / Parquet 僅由主行程集中保存，子行程不直接寫入儲存層
- 循序與並行路徑皆使用 UUID 唯一 `run_id`，避免同秒執行時互相覆寫
- Windows spawn 子行程會顯式載入策略註冊模組，確保策略 Registry 完整

---

### ✅ 3. 回測結果保存 (Backtest Run Archive)

**使用者價值**：
- 每次回測都是一次實驗（run），可保存、標記、對照
- 累積「哪些參數組合真的有效」的知識庫
- 可追溯歷史結果

**UI 位置**：
- 執行按鈕旁「保存結果」按鈕（回測完成後啟用）
- 右側「比較」Tab → 回測歷史列表

**後端實作**：
- `app_module/backtest_repository.py` - BacktestRunRepository
- 儲存方式：SQLite 資料庫 + Parquet 檔案
- 資料庫：`{output_root}/backtest/runs/backtest_runs.db`
- 檔案：`{output_root}/backtest/runs/{run_id}_equity_curve.parquet`
- 檔案：`{output_root}/backtest/runs/{run_id}_trades.parquet`

**儲存內容**：
- 基本資訊：執行名稱、股票代號、日期範圍、策略ID、參數
- 成本設定：初始資金、手續費、滑價、停損/停利
- 績效指標：總報酬、年化報酬、夏普比率、最大回撤、勝率、交易次數等
- 完整資料：權益曲線、交易明細（Parquet格式）

**使用方式**：
1. 執行回測
2. 回測完成後，點擊「保存結果」
3. 輸入執行名稱和備註
4. 在「比較」Tab 查看歷史列表

---

### ✅ 4. 多次結果比較 (Compare View)

**使用者價值**：
- 直接比較不同參數、期間、策略的結果
- 解決「不知道這次變好是因為參數、期間、或只是運氣」的問題

**UI 位置**：
- 右側「比較」Tab
- 回測歷史列表（支援多選）
- 比較結果表格

**比較指標**：
- 總報酬率、年化報酬率、夏普比率
- 最大回撤、勝率、交易次數
- 期望值、獲利因子

**使用方式**：
1. 切換到「比較」Tab
2. 在歷史列表中選擇多個結果（Ctrl+點擊多選）
3. 點擊「比較選中」
4. 查看比較表格

---

## 資料結構

### 策略預設格式
```json
{
  "version": 1,
  "preset_id": "preset_20241201_120000",
  "name": "Baseline_60_40_confirm2_cd3",
  "strategy_id": "baseline_score_threshold",
  "params": {
    "buy_score": 60,
    "sell_score": 40,
    "buy_confirm_days": 2,
    "sell_confirm_days": 2,
    "cooldown_days": 3
  },
  "meta": {},
  "tags": ["穩健", "日線"],
  "created_at": "2024-12-01T12:00:00",
  "updated_at": "2024-12-01T12:00:00"
}
```

### 選股清單格式
```json
{
  "version": 1,
  "watchlist_id": "watchlist_20241201_120000",
  "name": "本週強勢股 Top 20",
  "codes": ["2330", "2317", "2454", ...],
  "source": "screening",
  "filters": {},
  "description": "從市場觀察篩選的強勢股",
  "created_at": "2024-12-01T12:00:00",
  "updated_at": "2024-12-01T12:00:00"
}
```

### 回測結果資料庫結構
- **runs 表**：儲存基本資訊和績效摘要
- **索引**：created_at, strategy_id, stock_code
- **檔案**：equity_curve 和 trade_list 以 Parquet 格式儲存

---

## 已實作功能（優先級 5-6）

### ✅ 5. 參數掃描/最佳化 (Grid Search)

**使用者價值**：
- 不用手動一直改 buy_score / confirm days
- 直接輸出 Top 20 組合，並且能一鍵把某組套用回主面板再跑一次（驗證）

**UI 位置**：
- 左側策略配置下方「參數最佳化」折疊區塊
- 每個參數可選：固定值 or 範圍
- 目標指標選擇：夏普比率 / 年化報酬率 / CAGR-MDD權衡
- 右側「最佳化」Tab 顯示結果表格

**後端實作**：
- `app_module/optimizer_service.py` - OptimizerService
- 支援參數範圍掃描（整數/浮點數）
- 自動生成參數網格並批量回測
- 按目標指標排序，返回 Top N 結果

**使用方式**：
1. 展開「參數最佳化」區塊
2. 為要掃描的參數設定範圍（例如 buy_score: 50~80 step 5）
3. 選擇目標指標
4. 點擊「執行參數掃描」
5. 在「最佳化」Tab 查看結果
6. 雙擊或選擇行後點擊「套用選中參數」將最佳參數套用到主表單

---

### ✅ 6. 防止過擬合 (Walk-forward)

**使用者價值**：
- 參數掃描如果只看同一段期間，很容易挑到"剛好適合那段"的參數
- Walk-forward 可以驗證策略在不同時期的穩定性

**UI 位置**：
- 左側「Walk-forward 驗證」折疊區塊
- 模式選擇：Train-Test Split / Walk-forward
- Train-Test Split：設定訓練/測試比例（預設 70/30）
- Walk-forward：設定訓練期/測試期/步進（月）

**後端實作**：
- `app_module/walkforward_service.py` - WalkForwardService
- Train-Test Split：單次切分驗證
- Walk-forward：滾動窗口驗證（多個 Fold）
- 計算退化程度和一致性指標

**使用方式**：
1. 展開「Walk-forward 驗證」區塊
2. 選擇驗證模式
3. 設定參數（比例或月份）
4. 點擊「執行驗證」
5. 查看結果摘要和退化分析

**結果解讀**：
- **退化 < 20%**：策略穩定性良好
- **退化 20-50%**：策略穩定性一般
- **退化 > 50%**：策略可能過擬合

---

## 已實作功能（視覺化與圖表）

### ✅ 7. 回測視覺化
- Equity curve（權益曲線）：使用 QtWebEngine + HTML5 Canvas fast renderer，支援策略權益、normalized benchmark、買賣點 marker、hover crosshair。
- Drawdown curve（回撤曲線）：使用 Canvas area chart，顯示 zero baseline、最大回撤點與 peak-to-trough 區間。
- Trade return distribution（報酬分佈）：使用 zero-centered histogram，紅色代表虧損、綠色代表獲利，並顯示每個 bin 的交易數。
- Holding period distribution（持有天數）：使用實務區間桶 `1-5d`、`6-20d`、`21-60d`、`61d+`，避免細碎天數柱狀圖難以閱讀。
- Rendering fallback：QtWebEngine 不可用時，factory 會退回既有 Matplotlib widgets。
- 技術說明：`docs/08_technical/UI_QT_CHART_RENDERING.md`

### ✅ 8. 規格化 Excel 報告匯出

**使用者價值**：
- 將回測結果、交易明細、權益曲線，以及批次回測排行榜與推薦重播歷史，以高度規格化且易讀的 Excel 檔案保存。
- 支援單股回測、批次回測、推薦回放的 Excel 報告匯出。
- 提供完整的可追溯元數據與資料完整性宣告。

**UI 位置**：
- 實驗摘要、批次結果、推薦回放等標籤頁右側或底部，設有「匯出 Excel 報告 / 匯出批次 Excel / 匯出回放 Excel」等按鈕（回測完成後啟用）。

**後端實作**：
- `app_module/report_export_dtos.py`：定義不可變 payload DTO 快照，防範 UI 計算與資料漂移。
- `app_module/report_export_service.py`：負責 Excel 工作表格式化、邊界數值寫入、臨時檔儲存與原子替換，並提供缺失元數據標示為 `N/A` 的資料完整性追溯。

**安全防護設計**：
- **背景執行**：使用 `TaskWorker` 於背景執行 I/O 與檔案寫入，確保 UI 介面流暢不卡死。
- **原子替換**：在寫入時先建立臨時檔，成功寫入後再以原子替換方式寫入目標路徑，避免目標檔案損壞。
- **唯讀序列化**：匯出服務僅序列化已提供的 payload 資料，不進行策略、績效或金融指標的二次計算。

## 待實作功能（優先級 8）

### ⬆️ 8. 回測引擎升級
- 持倉 sizing 模式（全倉/固定金額/風險百分比）
- 市場限制（漲跌停、成交量限制）
- 成本模型可切換

---

## 技術架構

### 服務層
- `PresetService`：策略預設管理
- `UniverseService`：選股清單管理
- `BacktestRunRepository`：回測結果儲存庫（SQLite）
- `OptimizerService`：參數最佳化服務（Grid Search）
- `WalkForwardService`：Walk-forward 驗證服務
- `RecommendationReplayService`：歷史日期重播推薦邏輯
- `RecommendationPortfolioBacktestService`：推薦組合持有期、資金配置與績效彙整
- `RecommendationDataFrameProvider`：推薦 replay 的資料提供與候選集 prefilter

### UI 層
- `BacktestView`：擴展的回測視圖
  - 策略預設區塊
  - 選股模式切換
  - 結果保存
  - 比較視圖

### 資料儲存
- JSON：預設和清單（人類可讀）
- SQLite：回測結果（查詢效率）
- Parquet：大型資料（equity curve, trade list）

---

## 使用流程範例

### 場景 1：測試新策略參數

1. **載入策略預設**
   - 選擇「Baseline_60_40_confirm2_cd3」
   - 點擊「載入」

2. **調整參數**
   - 修改 buy_score 從 60 到 70
   - 其他參數保持不變

3. **執行回測**
   - 輸入股票代號：2330
   - 設定日期範圍
   - 點擊「執行回測」

4. **保存結果**
   - 回測完成後，點擊「保存結果」
   - 輸入名稱：「Baseline_70_40_confirm2_cd3」
   - 輸入備註：「測試提高買入閾值」

5. **比較結果**
   - 切換到「比較」Tab
   - 選擇舊的「Baseline_60_40_confirm2_cd3」和新的「Baseline_70_40_confirm2_cd3」
   - 點擊「比較選中」
   - 查看哪組參數表現更好

6. **儲存最佳參數**
   - 如果新參數更好，點擊「儲存」建立新的預設

---

### 場景 2：參數最佳化

1. **設定參數範圍**
   - 展開「參數最佳化」區塊
   - 將 buy_score 設為「範圍」：50~80，步長 5
   - 將 sell_score 設為「範圍」：20~50，步長 5
   - 其他參數保持「固定值」

2. **執行參數掃描**
   - 選擇目標指標：「夏普比率」
   - 點擊「執行參數掃描」
   - 等待掃描完成（會自動測試所有組合）

3. **查看最佳結果**
   - 切換到「最佳化」Tab
   - 查看排名表格（按夏普比率排序）
   - 選擇排名第一的組合

4. **套用並驗證**
   - 雙擊或點擊「套用選中參數」
   - 參數自動填入主表單
   - 執行回測驗證

---

### 場景 3：驗證策略穩定性

1. **設定 Walk-forward 驗證**
   - 展開「Walk-forward 驗證」區塊
   - 選擇模式：「Walk-forward」
   - 設定：訓練期 6 個月，測試期 3 個月，步進 3 個月

2. **執行驗證**
   - 點擊「執行驗證」
   - 系統會自動進行多個 Fold 的驗證

3. **分析結果**
   - 查看摘要：平均退化、一致性
   - 查看詳細表格：每個 Fold 的表現
   - 如果退化 < 20%，策略穩定性良好

---

## 注意事項

1. **資料路徑**：所有資料儲存在 `{output_root}/backtest/` 下
2. **向後兼容**：現有回測功能完全保留，新功能為可選
3. **效能**：SQLite 適合中小型資料，未來可升級為 PostgreSQL
4. **取消語意**：取消為合作式軟取消；已開始的單檔回測會安全收尾，尚未開始的工作不再提交

---

## 未來擴展

- 策略組合回測
- 與推薦分析模組整合
- 匯出報告（PDF 格式）

 
## 2026-05-27 推薦組合穩健性指標

推薦組合回測總覽已納入 Sharpe Ratio、Sortino Ratio 與 Monte Carlo P05/P50/P95 模擬報酬，用於組合層穩健性判讀。

## 2026-05-27 推薦組合 Portfolio Value 圖表

推薦組合回測的 equity curve 已改為每日 mark-to-market：每個交易日以持倉股票當日或最近可用收盤價重估未實現損益，並加回已實現損益，形成 portfolio value。Backtest 的「推薦組合」結果頁新增 Portfolio Value 與 Drawdown 圖表；Portfolio Value 會嘗試透過既有 `ChartDataService` 載入大盤基準線，方便比較推薦 Profile/Config 相對大盤是否有效。

## 2026-05-27 推薦組合停損停利與失敗診斷

推薦組合回測已接入 Backtest 頁既有的停損 (%) / 停利 (%) 設定。每檔推薦持倉會逐交易日檢查是否先觸發 stop_loss 或 take_profit；若都未觸發，才以 holding_period 出場。結果總覽同步顯示停損、停利、持有到期次數、虧損交易占比與最拖累股票，作為第一版策略失敗診斷。

## 2026-05-27 推薦組合 Research Run 保存

推薦組合回測新增獨立保存機制 `RecommendationPortfolioRunRepository`，使用 SQLite metadata 搭配 JSON 詳情檔案保存 profile/config、回測參數、summary、equity curve、期間持倉、個股貢獻與改善建議。此資料模型與單股回測 run 分離，避免混淆單股策略回測與推薦組合研究紀錄。

## 2026-05-28 推薦組合 Research Run Promote

已保存的推薦組合 research run 可透過 Backtest「推薦組合回測」區塊升級為策略版本。升級流程會讀取保存的 portfolio config、第一期推薦設定、回測 summary、Regime 與改善建議，建立 `recommendation_portfolio:<profile_id>` 策略版本，並在原 run metadata / JSON detail 回寫 `promoted_version_id`，保留「推薦組合回測 → 策略版本」的來源追溯。

---

## 交易撮合、SOP 驗證與未來函數防禦機制 (Phase 3.5)

為了確保回測與真實台股交易環境相符，並提高策略的統計穩健性，系統引入了以下核心約束與安全防禦機制：

### 1. 台股交易撮合與 0 股拒絕交易限制
- **整股交易限制**：台股撮合模擬器（`BrokerSimulator`）嚴格執行台股交易規則，買入與賣出股數均必須是 **1000 股（一張）的整數倍**。
- **高價股 0 股拒絕交易現象**：
  - 當買進高價股（如台積電 2330，價格在 600~1000 元以上）時，單張起步資金需要 60 萬至 100 萬元以上。
  - 若使用者設定的**初始資金**或**固定金額（Sizing Amount）**低於買進一張所需的金額，模擬器在進行股數取整時，會將股數 `/ 1000 * 1000` 直接取整為 **0 股**，進而導致買入被拒絕而產生 **0 交易次數**。
- **解決方案**：
  - 調大初始資金（例如從 100 萬調高至 500 萬或 1000 萬）。
  - 若使用固定金額 Sizing，需將固定金額調高至大於標的股價 * 1000 元（例如 120 萬元以上），或直接切換回「全倉」模式。

### 2. SOP 驗證機制與 Promote 晉升限制
- **樣本數限制 (交易次數 >= 10)**：
  - 為了防止過擬合或偶發的運氣成分，策略回測在完成時會執行 **Phase 3.5 SOP 驗證**。
  - 若總交易次數**低於 10 次**，SOP 驗證狀態會顯示為 **❌ FAIL**，提示「樣本不足，無法可靠判斷策略有效性」。
  - 當驗證狀態為 FAIL 時，系統會**自動禁用「Promote」按鈕**，禁止使用者將此策略參數晉升為正式版 Profile。
  - **解決方案**：拉長回測日期區間、調高 `sell_score` 以提高資金周轉、或是適度降低 `buy_score` 進場門檻。
- **Walk-forward 穩健性提醒**：
  - 若回測未經過滾動窗口（Walk-forward）驗證，系統會標註「尚未執行 Walk-forward 驗證，無法評估穩健性」的黃色警告，提示潛在的過擬合風險。
- **單筆交易記錄保留**：
  - 即使 SOP 驗證 FAIL 導致無法 Promote，使用者依然可以**右鍵點擊下方的交易明細表**，手動將個別交易「記錄到持倉管理 (Portfolio)」。

### 3. 圖形模式無未來函數 (Look-ahead bias) 防禦
打分引擎與圖形分析器實施了物理級的歷史切片與確認點觸發機制，確保回測的絕對嚴謹性：
- **滾動歷史切片 (Historic Slicing)**：
  打分引擎（`ScoringEngine`）在計算每個歷史日 `t` 的分數時，僅會傳入截至當日的子集 `df.iloc[:t+1]` 給 `PatternAnalyzer`。圖形算法完全看不到未來的任何價格走勢，達成嚴格的物理隔離。
- **突破確認觸發 (Breakthrough Confirmation)**：
  對於 W底、雙底等突破型圖形，系統絕不在波谷最低點（`end_idx`）直接計分。算法會沿著歷史進程尋找「突破中間峰值的突破確認日 `confirm_idx`」，並且**僅在確認日剛好等於當日 (`confirm_idx == t`) 時，才在當日觸發圖形分數貢獻**，往後 20 天線性衰減，徹底杜絕超前交易。
- **安全延遲 (Safety Delay)**：
  對於無明確突破參考點的非突破型圖形，若 `confirm_idx` 為空，則強制採用安全延遲 `end_idx + 2` 當作確認點。

### 4. 強制平倉 Portfolio 記錄與追溯標記
- **強制平倉允許記錄**：
  - 由於回測期末結算或風控平倉通常是真實的回溯清盤交易，並非虛假數據，因此系統**允許將其記錄至持倉**。
- **來源追溯與標記**：
  - 當使用者在交易明細表右鍵將強制平倉記錄至 Portfolio 時，系統會自動在備註中寫入「`來自回測 (強制平倉)`」。
  - 儲存時，會自動在 `source_summary` 字典中寫入 `exit_reason="強制平倉"` 的元數據，保留完整的「回測強制平倉」歷史追溯鏈。


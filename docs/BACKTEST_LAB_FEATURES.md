# 策略回測實驗室功能說明

## 概述

「策略回測」標籤已升級為完整的「實驗室/策略工作台」，支援反覆研究、知識累積、快速迭代。

## 已實作功能（優先級 1-4）

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
3. 執行回測（目前支援單一股票模式，多標的批次回測待實作）

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

## 待實作功能（優先級 7-8）

### ⬆️ 7. 回測視覺化
- Equity curve（權益曲線）
- Drawdown curve（回撤曲線）
- Signal/Trade markers（K 線上標記買賣點）

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
4. **批次回測**：目前選股清單功能已實作，但批次執行待後續開發

---

## 未來擴展

- 批次回測多檔股票
- 參數最佳化自動化
- 策略組合回測
- 與推薦分析模組整合
- 匯出報告（PDF/Excel）


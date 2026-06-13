# DEVELOPMENT_ROADMAP

## 系統定位（System Vision）

**這不是一個「每天吐股票的工具」，而是一個「可驗證、可回溯、可演化」的投資決策系統。**

系統成長順序：

```
看懂市場 → 嘗試策略 → 驗證策略 → 管理持倉 → 管理自己
```

最終要回答的四個問題：

```
市場在幹嘛？
→ 我現在該用哪一種方式參與？
→ 這個方式過去表現如何？
→ 我現在的部位還合理嗎？
```

---

## UI / Tab 架構（Information Architecture）

目前系統具備 **7 個頂層 Tab**：

1. **數據更新 (Update)**：資料來源日常維護工作台，支援安全更新、SQLite 同步與檢視。
2. **市場觀察 (Market Watch)**：包含大盤指數、強勢個股、弱勢個股、強勢產業、弱勢產業，以及 **主力流向 (Smart Money Flow)** 子 Tab（原籌碼分析終端）。
3. **策略回測 (Backtest)**：產品語意為 **Research Lab**，提供單股回測、選股清單批次回測、固定組合回測、推薦系統回放、策略研究與優化/驗證。
4. **推薦分析 (Recommendation)**：執行策略打分模型與 Regime 適配分析，產出推薦名單。
5. **觀察清單 (Watchlist)**：跨 Tab 共用的候選池 (Candidate Pool)。
6. **持倉管理 (Portfolio)**：提供交易庫存部位追蹤、條件監控 (PortfolioConditionMonitor) 與交易覆盤日記 (Journal) 管理。
7. **運行監控 (Runtime Observatory)**：AI Runtime 子系統的 Observable Layer，監控狀態機狀態流轉。

---

## 跨 Tab 共用核心模組（Single Source of Truth）

* **Watchlist（候選池）**：跨 Market / Recommendation / Backtest 共用
* **StrategyRegistry**：策略定義與 meta（適用 Regime、風險屬性）
* **PresetService**：策略版本、參數預設、Profiles
* **BacktestResultStore**：回測結果（SQLite + Parquet/CSV）
* **DTO 規範**：Recommendation / Backtest 統一輸出格式

---

## Phase 1：市場觀察儀 ✅ 已完成

### 目標

成為「市場觀察儀」，校正交易直覺，而不是賺錢機器。

### 已完成核心功能

* 數據更新流程（股票 / 大盤 / 產業）
* 強勢股 / 強勢產業（本日 / 本週）
* 市場 Regime 判斷（Trend / Reversion / Breakout）
* 統一打分模型（技術 / 量能 / 結構）
* 推薦理由生成（Why，不是 Buy/Sell）

### Phase 1 Exit Criteria（已達成）

* 系統可完整運行
* 使用者能「看懂市場在偏好什麼行為」

---

## Phase 2：策略資料庫 ✅ 已完成

### 目標

讓策略成為「可被描述、被比較、被淘汰」的研究對象。

### Phase 2 核心精神

> 不是找聖杯，而是找「什麼時候不要用什麼策略」。

---

### Phase 2 Checklist（唯一真相來源）

#### Phase2-A：跨 Tab 共用 Watchlist ✅ 已完成

* [x] WatchlistService（JSON / SQLite metadata）
* [x] Watchlist 資料模型（來源 / 標籤 / 備註）
* [x] Market Watch → 加入候選池
* [x] Recommendation → 加入候選池
* [x] Backtest → 從候選池建立 stock list
* [x] UI 管理入口（非獨立頂層 Tab）

#### Phase2-D：Backtest 研究體驗補強 ✅ 已完成

* [x] Grid Search 進度回調（完成 x / y）
* [x] 最佳化結果雙擊套用參數

#### Phase2-B：Market Watch 弱勢分析 ✅ 已完成

* [x] 弱勢股（與強勢股同架構，反向排名）
* [x] 弱勢產業（與強勢產業同架構，反向排名）

#### Phase2-C：Recommendation DTO 統一 ✅ 已完成

* [x] RecommendationResultDTO（固定欄位）
* [x] 推薦結果可保存、可追溯

#### Phase2-E：預設策略庫（最小可用） ✅ 已完成

* [x] StrategyMeta（適用 / 不適用 Regime、風險屬性）
* [x] 實作 2 個最小策略（暴衝 / 穩健）
* [x] 每策略一頁策略說明（Why，不是 How）
* [x] 單一策略回測可跑、可保存

---

### Phase 2 Exit Criteria（驗收標準）✅ 已達成

到 Phase 2 結尾，系統必須能完成以下閉環：

1. ✅ Update：更新資料
2. ✅ Market Watch：產生強 / 弱勢候選
3. ✅ Recommendation：輸出固定 DTO 的推薦名單
4. ✅ Watchlist：集中管理候選池
5. ✅ Backtest：從候選池回測、顯示進度、套用最佳參數

**Phase 2 已完成，系統已具備完整的策略研究能力。**

---

## Phase 2.5：參數設計優化 ✅ 核心部分已完成

### 目標

解決參數「單位不一致」與「可比較性」問題，確保所有參數可被解釋、可被縮放、可跨股票比較、可做 walk-forward。

### 核心問題

1. **單位不一致**：百分比、點數、倍數、window 天數、prominence 混在一起
2. **可比較性差**：同一個參數在不同股票/不同波動下意義不同
3. **過擬合風險**：Grid Search 容易挑到「剛好貼資料」的參數

### Phase 2.5 Checklist

#### 優先級 1：立即修改 ✅ 已完成（3/3）
* [x] 強勢/弱勢分數改成標準化或壓縮（z-score 或 log 壓縮）
  * ✅ 實現位置：`ui_app/stock_screener.py`（使用 z-score 標準化）
* [x] Pattern threshold/prominence 改成 ATR-based
  * ✅ 實現位置：`analysis_module/pattern_analysis/pattern_analyzer.py`（prominence_atr_mult 參數）
* [x] Scoring contract 統一（所有子分數 0~100，Regime 用權重切換）
  * ✅ 實現位置：`decision_module/scoring_engine.py`（所有子分數使用 `.clip(0, 100)`，Regime 權重切換）

#### 優先級 2：短期 ✅ 已完成（3/3）
* [x] 回測 execution_price 明確定義（next_open/close）
  * ✅ 實現位置：`ui_qt/views/backtest_view.py`（UI 選擇器）、`backtest_module/broker_simulator.py`（執行邏輯）
* [x] 停損停利加入 ATR 倍數模式
  * ✅ 實現位置：`ui_qt/views/backtest_view.py`（UI 選擇器和輸入框）、`backtest_module/broker_simulator.py`（ATR-based 停損停利）
* [x] 加入 max_positions / position_sizing
  * ✅ 實現位置：`ui_qt/views/backtest_view.py`（UI 輸入框和選擇器）、`backtest_module/broker_simulator.py`（配置參數）

#### 優先級 3：中期 ⚠️ 未完成（0/3，移至 Phase 3）
* [ ] 指標參數改進（RSI/MACD/KD/ADX/MA/ATR/BBANDS）
* [ ] buy_score/sell_score 改為分位數
* [ ] 推薦系統參數改進

**說明**：這些項目屬於後續改進，不影響 Phase 2.5 核心目標，建議移至 Phase 3 或後續階段。

#### 優先級 4：長期 ⚠️ 部分完成（1/2，後續持續驗證）
* [x] Walk-forward 暖機期參數（已於 Phase 3.3b MVP-1 完成）
* [ ] 完整測試與驗證（優先級 1 和 2 已驗證通過，後續仍需對策略穩定性持續驗證）

**說明**：Walk-forward warmup_days 已於 Phase 3.3b 完成並納入 UI / service；完整穩定性驗證屬於持續研究流程，不再阻塞 Phase 2.5 核心完成。

### Phase 2.5 Exit Criteria

**核心部分（優先級 1 和 2）Exit Criteria：**
* ✅ 所有參數單位一致、可跨股票比較（強勢/弱勢分數、Pattern ATR-based、Scoring contract）
* ✅ 回測參數明確定義（execution_price、停損停利 ATR 模式、部位管理）
* ✅ 參數設計文檔完整

**整體 Exit Criteria（含優先級 3 和 4）：**
* ⚠️ 所有參數單位一致、可跨股票比較（核心部分已達成，指標參數未改進）
* ⚠️ Grid Search 結果在 walk-forward 驗證中穩定（Walk-forward 已實現，穩定性驗證未完成）
* ✅ 參數設計文檔完整

**詳細改進計劃**：請參考 [PARAMETER_DESIGN_IMPROVEMENTS.md](../08_technical/PARAMETER_DESIGN_IMPROVEMENTS.md)  
**完成狀態檢查報告**：請參考 [PHASE2_5_COMPLETION_STATUS.md](../05_phases/PHASE2_5_COMPLETION_STATUS.md)

---

## Phase 3：推薦產品化 + 研究閉環（你每天會開始「真正在用」的版本）

這一個 Phase 會重切成 3.1 / 3.2 / 3.3，每一段結束都能當作「可用版本」。

---

### Phase 3.1：推薦可用化（Daily Usable Recommendation）✅ 已完成

#### 目標

讓你每天 1 分鐘內完成：選一種風格 → 出名單 → 看懂理由 → 丟到候選池

#### 你每天怎麼用（日常流程）

1. **Update** 更新數據
2. **Market Watch** 看今天市場狀態（Regime + 強弱）
3. **Recommendation**：選「新手模式」Profile → 一鍵推薦
4. 把名單加入 **Watchlist**（候選池）

#### 必做功能（MVP）

* [x] **推薦分析 Tab UI 可理解性優化** ✅ 已完成（Phase 3.1 基礎工作）
  * [x] 說明資料集中管理
  * [x] 策略傾向引導
  * [x] Tooltip 明確說明系統角色
  * [x] 推薦結果可反推線索
  * [x] 配置面板滾動優化

* [x] **Recommendation 新手 / 進階模式切換** ✅ 已完成
  * [x] 新手：只看 Profiles + 少量關鍵參數 + 解釋
  * [x] 進階：完整參數面板（不改引擎，只改 UI 顯示）

* [x] **Why Not（反向解釋）v1** ✅ 已完成
  * [x] 顯示：缺哪個門檻、差多少（用既有中間分數/標籤，不新增引擎邏輯）

* [x] **Recommendation 結果「可保存」** ✅ 已完成：保存到 ResultStore（已有 DTO，已補齊 UI 入口 + meta）

#### Phase 3.1 驗收標準（Exit Criteria）✅ 已達成

* ✅ 新手模式下：30 秒完成一次推薦（選 Profile → 執行 → 看懂 Why/WhyNot）
* ✅ 每檔推薦股票都有 Why + Why Not
* ✅ 名單能一鍵丟進 Watchlist，並保留來源（Profile/時間/Regime）

**Phase 3.1 已完成，系統已具備完整的推薦可用化功能。**

---

### Phase 3.2：Profiles 正式化（Profiles-as-Product）✅ 已完成

#### 目標

把你說的「短線 / 中線 / 長線」落地成真正可用的 Profiles（不是一堆勾勾）。

#### 你每天怎麼用（日常流程）

1. **Market Watch** 看 Regime
2. **Recommendation** 顯示：Regime → 建議 Profile
3. 你可以一鍵套用 / 或覆蓋
4. 出名單 → 放入 **Watchlist**

#### 必做功能

* [x] **Profiles v1：暴衝 / 穩健 / 長期** ✅ 已完成
  * [x] 每個 Profile 定義：
    * [x] 指標/圖形勾選集合（UI preset）
    * [x] 參數範圍（尤其 ATR 類）
    * [x] 風險提示（最大回撤預期、適用/不適用狀態）

* [x] **Regime → Profile 建議** ✅ 已完成
  * [x] Market Watch 偵測 Regime 後，Recommendation 顯示建議
  * [x] 一鍵套用只改 UI preset，不改引擎

* [x] **Profile meta 可追溯** ✅ 已完成
  * [x] 推薦結果必須帶：profile_id / profile_version / regime_snapshot

#### Phase 3.2 驗收標準 ✅ 已達成

* ✅ 你可以在不調參的情況下，用 3 個 Profile 日更產出名單
* ✅ 系統會提示「目前市場狀態 → 建議用什麼 Profile」
* ✅ 推薦結果可回溯：當時 Regime + Profile 版本 + 參數

**Phase 3.2 已完成，系統已具備完整的 Profiles 正式化功能。**

---

### Phase 3.3a：研究閉環核心功能 ✅ 已完成

#### 目標

建立從推薦到回測的無縫銜接，形成研究流程的基礎閉環。

#### 已完成功能

* [x] **Explain 面板 v1** ✅ 已完成
  * [x] 顯示：IndicatorScore / PatternScore / VolumeScore 等拆解
  * [x] 顯示風險點提示（分數偏低、Regime 不匹配、價格變化風險等）

* [x] **一鍵送回測（Profile → Backtest）** ✅ 已完成
  * [x] 自動載入：股票清單 + 對應策略參數 + execution_price/風控模式
  * [x] 根據 Profile 風險等級自動設置執行價格（暴衝用 next_open，穩健用 close）
  * [x] 自動創建選股清單並載入到回測視圖

#### Phase 3.3a 驗收標準（已達成）

* ✅ 從推薦到回測不需要手動重設一堆參數（已完成：一鍵送回測）
* ✅ Explain 面板提供完整的分數拆解和風險點提示

---

### Phase 3.3b：研究閉環完整化 ✅ 已完成

#### 狀態

- ✅ **Research Design**：已完成（見 `docs/PHASE3_3B_RESEARCH_DESIGN.md`）
- ✅ **Implementation Planning**：已完成（見 `docs/PHASE_3_3B_IMPLEMENTATION_PLAN.md`）
- ✅ **實作順序**：Epic 2 → Epic 3 → Epic 1（已完成）

#### 目標

完成真正的閉環：**推薦 → 回測 → 最佳化 → Promote 成策略版本 → 回到推薦**

讓回測成果可以「升級」為可用策略版本，並提供視覺驗證機制。

#### Implementation Epics

**Epic 1：Promote 機制** ✅ 已完成（2026-01-02）
- **目標**：實作回測結果升級為策略版本的功能
- **範圍**：升級條件檢查、策略版本生成、Profile 整合
- **MVP-1**：✅ 保存為 Preset 功能（已完成）
- **完整版**：✅ Promote 機制完整版（已完成，2026-01-02）
  - ✅ PromotionService：管理回測結果升級流程
  - ✅ StrategyVersionService：管理策略版本生命週期
  - ✅ BacktestRepository：新增 promoted_version_id 欄位
  - ✅ PresetService：支援從回測結果保存
  - ✅ RecommendationService：支援從 Preset 或 Version 載入
  - ✅ BacktestView：新增 Promote 按鈕和 UI

**Epic 2：回測穩健性驗證** 🎯 優先實作
- **目標**：實作 Walk-Forward 暖機期、Baseline 對比、過擬合風險提示
- **範圍**：穩健性驗證機制、風險評估、驗證報告
- **MVP-1**：✅ 已完成（2025-12-30）
  - Walk-forward warmup_days（預設 0，向後兼容）
  - Baseline 對比（Buy & Hold）
  - 驗證狀態：29/29 測試案例通過（100% 通過率）
  - 驗證報告：`output/qa/epic2_mvp1_validation/VALIDATION_REPORT.md`
- **MVP-2**：過擬合風險提示 ✅ 已完成（2026-01-02）
  - ✅ 階段 1：核心計算方法實作（已完成，2025-12-30）
    - `calculate_walkforward_degradation()` 方法
    - `calculate_consistency()` 方法
    - `calculate_overfitting_risk()` 整合方法
  - ✅ 階段 2：DTO 與服務整合（已完成，2025-12-30）
    - `BacktestReportDTO` 新增 `overfitting_risk` 欄位
    - `BacktestService.run_backtest()` 整合過擬合風險計算
  - ✅ 階段 3：測試與驗證（已完成，2026-01-02）
    - 單元測試：20/20 通過（100% 通過率）
    - 驗證腳本：11/11 通過（100% 通過率）
    - 驗證報告：`output/qa/epic2_mvp2_validation/VALIDATION_REPORT.md`

**Epic 3：視覺驗證**
- **目標**：實作 K 線圖標記買賣點功能
- **範圍**：K 線圖顯示、買賣點標記、理由標籤顯示
- **MVP-1**：基本 K 線圖顯示 + 買賣點標記

#### MVP 切割策略

**Epic 2 MVP-1**（最低風險版本）✅ 已完成（2025-12-30）：
- ✅ Walk-forward warmup_days 參數（預設 0，向後兼容）
- ✅ Baseline 對比（至少 Buy & Hold）
- ✅ 驗證：29/29 測試案例通過（100% 通過率）
- ❌ 不做：過擬合風險提示、多 baseline、可調 warmup 長度（移至 MVP-2）

**Epic 3 MVP-1**：
- ✅ 基本 K 線圖顯示（使用 mplfinance）
- ✅ 買賣點標記（綠色向上箭頭、紅色向下箭頭）
- ❌ 不做：理由標籤 hover tooltip、技術指標疊加

**Epic 1 MVP-1**：
- ✅ 保存為 Preset 功能（使用現有 PresetService）
- ❌ 不做：完整版本管理、Profile 整合

#### Feature Flags

**ENABLE_CANDLESTICK_CHART**（預設：True）
- **用途**：控制 K 線圖功能開關
- **影響範圍**：`BacktestView` 的圖表切換
- **Fallback**：如果 K 線圖渲染有性能問題，可以切換回權益曲線

**ENABLE_PROMOTE_MECHANISM**（預設：True）
- **用途**：控制 Promote 功能開關
- **影響範圍**：`PromotionService`、`BacktestView` 的 Promote 按鈕
- **Fallback**：如果 Promote 功能有問題，可以快速關閉

#### Phase 3.3b 驗收標準 ✅ 已達成

* ✅ 回測結果可 Promote 成版本，並可回到推薦使用（Epic 1 完整版已完成）
* ✅ 能用圖（買賣點 + 理由）視覺驗證策略行為（Epic 3 MVP-1 已完成）
* ✅ 回測穩健性驗證機制完整（Walk-Forward、Baseline 對比、過擬合風險提示）（Epic 2 MVP-1 和 MVP-2 已完成）
* ✅ **完整功能驗證與修復**：已完成（2026-01-02）
  - ✅ 驗證通過率：100% (10/10)
  - ✅ 失效功能修復：WatchlistService.get_watchlist() 方法、BacktestReportDTO 引用錯誤
  - ✅ 功能確認：過擬合風險計算、推薦理由生成均正常運作
  - ✅ 驗證報告：`output/qa/phase3_3b_validation/VALIDATION_REPORT.md`
  - ✅ 修復總結：`output/qa/phase3_3b_validation/修復總結報告.md`

**Phase 3.3b 已完成，系統已具備完整的研究閉環功能，並通過完整功能驗證。**

#### 風險與 Fallback

**主要風險**：
- Promote 功能可能涉及複雜的版本管理邏輯
- K 線標記需要整合現有圖表組件，可能有技術挑戰

**Fallback 方案**：
- 如果 Promote 功能複雜度過高，可先實作簡化版本（僅保存策略參數，不建立完整版本管理）
- 如果 K 線標記技術難度大，可先提供文字列表形式的買賣點說明，後續再升級為視覺標記

---

### Phase 3 整體驗收標準

* ✅ 每個子階段（3.1、3.2、3.3）結束時系統都可完整使用
* ✅ 形成「推薦 → 回測 → 優化 → 再推薦」的完整閉環
* ✅ 使用者能理解自己在做什麼決策，並能追溯決策脈絡

---

## Phase 4：持倉管理與交易日誌（Portfolio & Journal）✅ Phase 4.1 已深化完成

**前置條件**：Phase 3.3b（Promote 功能、K 線標記買賣點）已完成。Phase 4.1 已深化實作：包含策略版本與推薦來源追蹤視圖、目前價格對照、未實現損益計算、停損停利監控與持倉層複合風險提示。

**目標**：你開始每天回答「這筆還對嗎」

**Phase 4 是你系統「從研究工具 → 日常決策系統」的轉折點**  
但仍維持：**非自動交易、你做決定**

---

### Phase 4.1：最小可用持倉（Portfolio MVP）

#### 你每天怎麼用

1. 手動記錄一筆交易（買/賣/加碼/減碼）
2. 系統顯示：該筆交易綁定的策略版本 + 當時 Regime
3. 每天打開看：是否仍符合當初條件（Condition Monitor）

#### 必做功能

* [x] **新增 Portfolio Tab**（最小版本）

* [x] **交易紀錄**（保留 recommendation / backtest source metadata；策略版本追蹤視圖已實作）

* [x] **條件監控（Monitor）**：已用 `PortfolioConditionMonitor` 對照來源快照與目前快照的 Regime / TotalScore，UI 顯示來源脈絡、進場分數、目前分數與監控原因；Price 對照與停損停利已實作

* [x] **非強制提示**（提醒/警示，不做自動操作）

#### Phase 4.1 已深化完成

* [x] **策略版本追蹤視圖**：讓持倉可回溯到策略版本歷史
* [x] **Price 對照**：進場價 vs 目前價 vs 停損停利區間對比
* [x] **持倉層風險提示**：結合 Regime 變化、Score 退化與 Price 偏離的複合提醒

#### Phase 4.1 驗收標準

* ✅ 你可以在 Portfolio 看到每筆交易的「策略脈絡」與「目前是否仍成立」
* ✅ 每天能用它做持倉檢查（不需要靠記憶）

---

### Phase 4.2：券商買賣超/籌碼面 v1（已完成）✅

* [x] **券商買賣超匯入 + 查詢 + 下鑽**（先做 v1：Top N + 連續性）
* [x] 用於「觀察」與「風險提示」，不直接當買賣訊號


---

### Phase 4 整體驗收標準

* ✅ 推薦 → 回測 → 持倉 → 回顧形成完整閉環
* ✅ 每筆持倉都有完整的策略脈絡和監控機制

---

## Phase 5：效能與研究輸出（Scale & Reporting）🚧 部分已完成

---

### Phase 5.1：效能

* [ ] **大表格分頁**
* [x] **圖表渲染優化**（QtWebEngine + HTML5 Canvas fast renderer，Matplotlib fallback）
* [x] **批次回測並行化**（可取消、可進度）

---

### Phase 5.2：研究報告輸出

* [ ] **匯出研究報告**（Excel / PDF）
* [ ] **回測結果摘要模板**（版本比較、參數、適用 Regime、風險指標）

---

### Phase 5 驗收標準

* ✅ 大量 batch / chart / table 不影響使用體驗
* ✅ 你可以把某個策略版本輸出成「可分享的研究結果」

---

## 📍 Living Section 定義（重要：所有 Agent 必讀）

### 什麼是 Living Section

**Living Section** 是 `DEVELOPMENT_ROADMAP.md` 中「當前狀態（Living Section）」段落及其所有子段落，代表專案的**當前事實狀態**（Single Source of Truth）。

### Living Section 包含的內容

Living Section 包含以下段落（從「## 當前狀態（Living Section）」標題開始，到「## 開發原則（不可違反）」標題之前）：

1. **現況（Baseline）** - 當前 Phase 完成狀態、系統運行狀態、已驗證功能
2. **本週 Done** - 本週完成的工作項目清單
3. **修復記錄** - 近期修復的問題與改進
4. **下一步 Next** - 下一步計劃與優先事項
5. **Blockers / Risks** - 當前阻礙與風險

### 哪些段落屬於 Living Section，哪些不是

**屬於 Living Section（必須與其他文件一致）：**
- `## 當前狀態（Living Section）` 及其所有子段落
  - `### 現況（Baseline）`
  - `### 本週 Done`
  - `### 修復記錄`
  - `### 下一步 Next`
  - `### Blockers / Risks`

**不屬於 Living Section（歷史記錄，不需同步）：**
- 各 Phase 的詳細描述（Phase 1、Phase 2、Phase 2.5、Phase 3 等）
- Phase 的 Checklist 和 Exit Criteria（已完成項目的歷史記錄）
- 「開發原則（不可違反）」段落（這是固定原則，不是狀態）

### 為什麼 Living Section 是其他文件的事實來源（SSOT）

1. **唯一真相來源**：Living Section 是專案當前狀態的唯一事實來源
2. **必須優先更新**：任何 Phase 狀態變更、優先事項變更、風險變更，都必須先更新 Living Section
3. **其他文件必須同步**：
   - `docs/00_core/PROJECT_SNAPSHOT.md` 必須與 Living Section 的「現況」和「下一步」一致
   - `docs/00_core/DOCUMENTATION_INDEX.md` 的進度描述必須與 Living Section 一致
   - 所有其他文件描述 Phase 狀態時，必須以 Living Section 為準

### 如何識別 Living Section

**識別方式：**
- 在 `DEVELOPMENT_ROADMAP.md` 中搜尋標題 `## 當前狀態（Living Section）`
- Living Section 從該標題開始，到 `## 開發原則（不可違反）` 標題之前結束
- 包含所有以 `###` 開頭的子段落（現況、本週 Done、修復記錄、下一步 Next、Blockers / Risks）

**維護規則：**
- 任何 Phase 狀態變更 → 必須更新 Living Section 的「現況」
- 任何優先事項變更 → 必須更新 Living Section 的「下一步 Next」
- 任何風險變更 → 必須更新 Living Section 的「Blockers / Risks」
- 更新 Living Section 後 → 必須同步更新 `docs/00_core/PROJECT_SNAPSHOT.md` 和 `docs/00_core/DOCUMENTATION_INDEX.md`

---

## 當前狀態（Living Section）

### 現況（Baseline）

專案已超出早期線性 Phase 規劃，實際產品主線已形成三個閉環：

**閉環 1：資料與市場狀態閉環** ✅ 基礎已建立

Update → SQLite 狀態 → Market Watch / Smart Money（市場觀察子 Tab）→ 候選池。

* Phase 1（市場觀察儀）✅、Phase 2（策略資料庫）✅、Phase 2.5（參數標準化）核心 ✅
* Phase 2.5 數據更新流程分流 (⚡快速更新 vs 🛡️安全更新) 與券商分點長碼解密與總公司判定 ✅
* Phase 2A/2B/2C（SQLite DB-first 讀取改造與視覺化 Table 檢視）✅
* Phase 3（CSV 手動匯出與更新流程優化）✅
* 數據更新工作台（Dashboard + 維運工作台布局 + 安全更新所有數據分流）✅
* SQLite 儲存升級與全量遷移（322 倍回測載入加速 + SQL 化秒開）✅
* Smart Money Terminal MVP（左右分欄 + 玻璃擬態卡片 + Sparklines + 排序修復）✅
* 券商分點資料更新與解析修復 ✅

**閉環 2：研究驗證閉環** ✅ 基礎已建立

Recommendation Profile → Research Lab（策略回測頁的產品語意）/ Backtest / Replay / Walk-forward → Promote。

* Phase 3.1（推薦可用化）✅ / Phase 3.2（Profiles 正式化）✅ / Phase 3.3a（研究閉環核心）✅ / Phase 3.3b（研究閉環完整化 + Promote + 過擬合風險 + K 線視覺驗證）✅
* Research Lab 工作流重整：Backtest 頁已整理為多模式實驗室（單股、批次、固定組合、推薦回放）✅
* Recommendation Portfolio Backtest MVP（歷史日期重播推薦 + Sharpe / Sortino / Monte Carlo + 停損停利 + 診斷 + Research Run 保存/Promote）✅
* UI Qt Backtest chart fast renderer（QtWebEngine + HTML5 Canvas，Matplotlib fallback）✅
* AI Runtime Subsystem MVP（Governance-aware 狀態機監控站）✅
* Codex / Antigravity / Agent 指引對齊 ✅

**閉環 3：持倉檢查閉環** ✅ 基礎與深化已完成

Recommendation / Backtest → Portfolio → Condition Monitor → Journal → 回到研究。

* Phase 4.1 Portfolio MVP 與深化 ✅：
  * ✅ `portfolio_module/` domain logic（append-only trades → positions projection）
  * ✅ `PortfolioService` / `JournalService`（交易紀錄、持倉投影、Journal entry）
  * ✅ `ui_qt/views/portfolio_view.py`（Portfolio Tab + trade entry path）
  * ✅ Recommendation / Backtest → Portfolio 來源追溯 metadata
  * ✅ `PortfolioConditionMonitor`（來源快照 vs 目前快照 Regime/TotalScore 對照 MVP，2026-06-09）
  * ✅ 策略版本追蹤視圖、Price 對照、持倉層風險提示已深化實作，且已修正 float 邊界合規漏洞與三層防禦策略版本串接 (2026-06-11)
* Phase 4.2 Portfolio 籌碼監控與下鑽 ✅：
  * ✅ `app_module/portfolio_chip_service.py`（SQLite/CSV 雙軌分點籌碼流向統計與風險規則評估）
  * ✅ `ui_qt/views/portfolio_view.py`（籌碼監控 Tab、追蹤分點買賣明細表格與主力籌碼風險警示）
  * ✅ `ui_qt/main.py` 與 `ui_qt/views/smart_money/smart_money_flow_view.py`（🔍 下鑽詳細主力流向按鈕，程式化切換 Tab 並自動高亮/載入分點詳情）

**效能與研究輸出（Phase 5）** 🚧 部分已完成

* ✅ 圖表渲染優化（QtWebEngine + HTML5 Canvas fast renderer，Matplotlib fallback）
* ✅ 批次回測並行化（合作式軟取消、進度回調、UnboundLocalError 與 BrokenProcessPool 優雅處理、並行測試）
* ⏳ 大表格分頁、Excel / PDF 研究報告輸出仍在後續

**Backlog**

* Strategy & Scoring Governance 的功能實作已完成；真實股票池 fixed / quantile walk-forward 績效比較仍待執行，quantile 維持 opt-in。
* Phase 5 中的大表格分頁、Excel/PDF 報告輸出仍在後續。

---

### 本週 Done（Strategy & Scoring Governance (增量 A：回測雙模式門檻 & 增量 B：推薦橫斷面排名) + 批次回測並行化與安全軟取消 + 券商分點擴充、長碼解密與總公司判定 + 數據更新流程快速/安全分流 + Phase 4.2 持倉層籌碼面風險提示與下鑽整合 + Phase 4.1 持倉管理深化 BUG 修正與 Gap 補全 + Research Lab 工作流重整與說明文檔同步）

* ✅ **Strategy & Scoring Governance (增量 B：推薦橫斷面排名)** (2026-06-13)：
  - **橫斷面百分位排名元件實作**：實作 `calculate_score_percentiles` 函式，採用 empirical CDF 計算公式，並以 `bisect_right` 保證同分時取得相同百分位，徹底鎖定排名演算法之統計一致性與輸入順序無涉。
  - **策略推薦服務與 metadata 追溯**：整合 `RecommendationService`，在合格母體大小不足時拋出 `RecommendationUniverseTooSmallError` 且拒絕降級；在符合百分位門檻下注入 `score_percentile_bp` 等元數據，並使用 total_score 降序與 stock_code 升序進行穩定化排序。
  - **DTO 與儲存庫 round-trip 還原**：於 `RecommendationDTO` 擴充 metadata 欄位，實作相容英文、中文 key 且向後相容歷史 JSON 數據的 `from_dict` 方法，並經 `RecommendationResultDTO` 還原驗證。JSON 檔案自動落盤，不破壞 SQLite schemas。
  - **推薦 UI 欄位與控制項整合**：重構 `RecommendationView` 於進階模式下提供門檻模式、最低百分位、最小母體數及排名方法控制項，且隨 fixed/quantile 動態隱藏與顯示；在結果表格中顯示百分位與母體，並於母體不足時發出友善警示與調整建議。
  - **測試驗證**：新增單元測試 `tests/test_recommendation_percentile_ranker.py`、`tests/test_recommendation_ranking_service.py` 與 `tests/test_recommendation_dto_roundtrip.py`，並納入 UI workflow 與推薦組合回測重播驗證。

* ✅ **Strategy & Scoring Governance (增量 A：回測雙模式門檻)** (2026-06-13)：
  - **純門檻評估元件實作**：實作 `ScoreThresholdPolicy`，支援 `fixed` 與 `quantile` 雙門檻模式。在 `fixed` 下完全向後相容舊策略；在 `quantile` 下，基點範圍採 0-10000 整數以符合量化防禦條款，並實作單股 Expanding 歷史分位數計算（暖機期 60 天），徹底排除未來函數 (Look-ahead bias)。
  - **策略執行器與回測整合**：將 `ScoreThresholdPolicy` 成功接入 `BaselineScoreExecutor`、`MomentumAggressiveExecutor` 與 `StableConservativeExecutor`。升級 `BacktestService` 診斷，在 quantile 模式下從訊號中安全提取動態門檻、暖機狀態與命中天數等指標。
  - **UI 與最佳化表單對齊**：
    - 更新正常參數表單，支援 `threshold_mode` 等 choice 下拉選單（`QComboBox`），並在模式切換時動態隱藏/顯示對應欄位。
    - 重構最佳化參數表單 `_update_optimization_params_form`，將每一行包裹在 `row_widget` 中以支援最佳化面板的行動態顯示/隱藏。Choice 參數不再生成數值範圍，僅能作為固定值進行參數掃描。
  - **無交易診斷與 Preset 存取**：更新無交易診斷文案，若採用 quantile 模式，會動態顯示暖機進度與命中次數，不再建議降低 `buy_score`；完成 5 個新參數在 Preset & StrategyVersion 的 100% round-trip 一致性驗證。
  - **測試驗證**：新增單元測試 `tests/test_score_threshold_policy.py`、`tests/test_strategy_threshold_modes.py`，並在 `tests/test_ui_qt_research_workflow.py` 新增下拉選單載入、顯示切換及無交易診斷測試。

* ✅ **批次回測並行化與安全軟取消實作** (2026-06-12)：
  - **批次回測並行化**：實作 ProcessPoolExecutor 並行處理機制，當回測個股數大於 threshold 時自動並行，並支援 `max_workers=None` 自適應調整 CPU 核心數。
  - **合作式軟取消**：實作非暴力 cooperative 取消機制，取消時停止向進程池提交新任務，且 Worker 等待 active 子行程清空後才發送 `cancelled` 信號並恢復 UI 按鈕，避免 UI 提前解鎖造成新舊任務重疊。
  - **唯一性 run_id 寫入**：在循序與並行路徑皆引入 UUID 來生成唯一 `run_id`，避免 SQLite 與 parquet 同秒覆寫衝突。
  - **TaskWorker 軟取消回歸防護**：保留 `TaskWorker` 取消時的 legacy `terminate()` 行為，並將新合作式軟取消限制在回測專用 Worker，維持 Update、Recommendation 與 SQLite Inspector 等既有頁面的行為相容；legacy 強制終止風險列為後續技術債。
  - **完整測試與驗證**：新增 `tests/test_backtest/test_parallel_safety.py`，完整覆蓋 UUID 唯一性、軟取消、自適應循序分流、非法股票處理、真實 `BrokenProcessPool` 異常重現及 `max_workers=None` 測試。所有 tests 順利 passed。

* ✅ **券商分點擴充與數據更新流程分流** (2026-06-11)：
  - **券商分點擴充、長碼解密與總公司判定**：在 `BrokerBranchUpdateService` 中實作 Unicode 長碼解密 `_decode_unicode_hex` 與總公司判定邏輯，自動在載入 registry 時將 16 進位 Unicode hex 長碼（如 `003800380038004b`）解密為真實短碼（如 `888K`），並在 display_name 符合規則且無分公司分行後綴時動態判定為總部。
  - **資料更新流程分流 (⚡ 快速更新 vs 🛡️ 安全更新)**：將 `UpdateView` 一鍵更新按鈕重構分拆為「⚡ 快速更新 (僅 SQLite)」與「🛡️ 安全更新 (完整 CSV + SQLite)」。實作 `_run_update_all` mode 分流，當 SQLite 啟用時快速更新直接走直查同步而略過大 CSV 合併重寫以實現數十倍提速，而安全更新仍強制執行 CSV 合併。
  - **測試與驗證**：新增 `tests/test_broker_branch_decode.py` 驗證解密與總部判定。更新 `test_ui_qt_update_view_workbench.py` 確保對應按鈕與文字正確並保持向後相容。mypy 零型態錯誤、py_compile 成功，UI QA 驗證腳本全綠通過。

* ✅ **Phase 4.2 持倉層籌碼面風險提示與下鑽整合** (2026-06-11)：
  * **籌碼監控服務**：實作 `PortfolioChipService`（[portfolio_chip_service.py](file:///c:/Projects/PythonProjects/technical_analysis/app_module/portfolio_chip_service.py)），在 SQLite 啟用時使用 SQL 直查（`broker_flows`）提供毫秒級統計，並支援 CSV 備用降級。計算主力近 5/20 日累計淨買賣、主力集中度與連續天數，依結構化風險規則評估風險級別（`bullish`/`neutral`/`bearish`）。
  * **持倉監控 UI 面板**：在右側面板新增「籌碼監控」分頁，呈現風險評估、連續天數警示與追蹤分點近 5 日買賣明細表格。
  * **雙向下鑽連動**：新增「🔍 下鑽詳細主力流向」按鈕，觸發時切換 MainWindow 至「市場觀察 -> 主力流向」Tab；且在主力流向 View 中實作 `select_stock` 函數，自動定位高亮個股並載入其詳情。
  * **測試與驗證**：新增 `tests/test_portfolio_chip_monitor.py` 完整覆蓋空值處理、買賣超判定、連續出貨判定與雙軌降級，mypy、編譯及 QA 驗證均順利綠燈通過。

* ✅ **Phase 4.1 持倉管理深化 BUG 修正與 Gap 補全** (2026-06-11)：
  * **金融數值治理合規**：修復了 `portfolio_service.py` 缺失的 `# numeric-boundary: dto`，並將 `portfolio_condition_monitor.py` 納入金融數值治理白名單檔案清單（補齊所有 `float()` 呼叫的邊界標註），安全通過 `check_financial_float_boundaries.py` 檢查與 `test_financial_float_boundary_checker.py` 測試。
  * **策略版本與回測深度串接**：為 `build_backtest_trade_source` 與匯入交易機制增加 `promoted_version_id` 欄位傳遞。在 `portfolio_view.py` 的「策略與價格監控」分頁實作**三層防禦策略版本查找**（`source_summary` ➔ `BacktestRunRepository` ➔ `StrategyVersionService`），保證所有匯入的 `backtest_run` 持倉在點選時皆能精準還原其正式策略版本資訊；同時為未升級的 `backtest_run` 提供專屬的回饋資訊 Fallback 呈現。
  * **測試覆蓋與驗證**：新增 `tests/test_portfolio_deepening.py` 測試以完整驗證三層防禦的運作。mypy 零新增錯誤，`qa_validate_update_tab.py` 21 項全部 passed！

* ✅ **Research Lab 工作流重整與說明文檔同步** (2026-06-06)：
  * **UI Info 說明對話框優化**：優化了 `tab_info_config.py`，移除 `how_to_use` 清單項目的手動數字標題，防禦 `InfoDialog` 在 list 格式化時出現數字雙重重疊現象。
  * **回測實驗室說明文檔同步**：在 `BACKTEST_LAB_FEATURES.md` 補齊台股整股（1000 股）撮合與 0 股拒絕交易、SOP 驗證門檻限制（總交易 >= 10 時 Promote 啟用）、圖形模式無未來函數防禦（滾動切片、突破確認日 confirm_idx、安全延遲）、強制平倉記錄至 Portfolio 追溯標記等說明，與實體代碼邏輯 100% 同步。


* ✅ **數據更新工作台 (UpdateView) 視覺重構與架構優化** (2026-06-03)：
  * **主看板與 StatusCard**：升級為極簡看板 Dashboard，移去所有手動控制與雜亂按鈕，改以精美 `StatusCard`（繼承自 `QGroupBox`、相容於 `QTextEdit`）與四色指示燈（🟢/🟡/🔴/⚪）展示數據概覽。
  * **進階手動操作歸位**：將下載日期、天數設定、手動下載/合併、指標計算配置分拆歸位至個別專屬分頁（每日股價、大盤、產業、券商分點、技術指標），並在每日股價分頁以紅框 Danger Zone 包裹強制重新合併按鈕。
  * **日誌控制台與進度共享**：進度條與 Terminal 日誌框移至全域佈局最下方，實作切換分頁時進度與日誌的全域共享。日誌框採用深色背景、Consolas 11px 等寬字型與「🧹 清除日誌」工具按鈕。
  * **日期聯動與委派**：透過 `blockSignals` 與 `_sync_dates()` 實作全分頁日期聯動同步；手動更新按鈕經 `_dispatch_update()` 自適應設定隱藏的對應 RadioButton 狀態，實現對原 Service 業務代碼的 100% 相容。
  * **自動與 QA 測試 100% 綠燈**：通過 mypy 無新增錯誤，`tests/test_ui_qt_update_view_workbench.py` (9 passed) 與 `scripts/qa_validate_update_tab.py` (21 passed, 0 failed) 順利通過。

* ✅ **主力流向 (Smart Money Flow) 視覺重構與排版優化** (2026-06-03)：
  * **UI 左右分欄**：重構為左右分欄布局（左側主表 65%，右側詳情 35%），並新增選中股雷達摘要卡片與 `explainable_reasons` 原因解析。
  * **小卡片中文化與放大**：頂部玻璃擬態卡片（市場趨勢、熱度、多空個股數、異常警示）完全繁體中文化，調大字體以優化視覺層次。
  * **Sparklines 漸層與 ToolTip 觸發**：採用 `QLinearGradient` 渲染漸層 Sparklines，固定顯示最新 5 筆交易明細，並實作跨 Cell 的 ToolTip 懸浮提示。
  * **Bug 修復與排序**：在 `TerminalTableModel` 與 `BranchTrackerTableModel` 中實作 `sort()` 方法解決點擊 Header 排序無反應問題；修復多空家數統計偏差（偏空股為0）與熱度恆定 100% 的 Bug。

* ✅ **Phase 3：CSV 手動匯出與更新流程優化** (2026-06-03)：
  * **停止日常更新大型 CSV 重寫**：當啟用 SQLite 時，日常安全更新流程直接將新下載的單日 CSV 同步寫入 SQLite 表（價格與分點），跳過 `stock_data_whole.csv` 與主力分點大合併 CSV 的合併重寫，解除日常磁碟 I/O 重擔。
  * **技術指標增量同步優化**：增量更新時略過保存 `all_stocks_data.csv`，寫入 SQLite `technical_indicators` 表時，改為只針對有更新的 `(證券代號, 日期)` 組合進行舊記錄刪除後追加寫入，不再清空並重新寫入 280 萬筆資料。
  * **各 subtab 加入「匯出 CSV」**：在數據更新工作台的每日股價、大盤、產業、分點與指標 subtab 中新增「匯出 CSV」按鈕，支援非同步匯出指定範圍或全量 SQLite 記錄至 CSV 備案，檔名與日期格式（`YYYY-MM-DD`）符合人工檢查需求，且使用 UTF-8 with BOM 避免 Excel 亂碼。
  * **測試與驗證**：單元測試與 QA 驗證腳本 100% 綠燈通過，mypy 零新增錯誤。

### 歷史 Done（Phase 2.5 完成 + 全功能驗證通過 + UI 穩定性修復 + 回測功能優化 + Broker Branch Data Update + 修復與測試文檔 + Epic 2 MVP-2 完成 + AI Runtime MVP + Smart Money Terminal + SQLite 儲存升級研究、遷移、指標全重算與 UI 秒開優化）

* ✅ **SQLite DB-first 讀取改造與視覺化 Table 檢視 (Phase 2A, 2B & 2C) 成果** (2026-06-03)：
  * **SQLite 視覺查詢資料表 (Phase 2C)**：新增了 `SqliteInspectorService` 與 `SqliteInspectorWidget`，並在 `UpdateView` 的左側導覽中整合「SQLite 資料檢視」分頁。支援 Preview 表格、PRAGMA table_info Schema 檢視與自訂 SELECT SQL 執行，並提供 Limit 限額與唯讀指令安全過濾。
  * 重構了強勢股篩選 ([stock_screener.py](file:///c:/Projects/PythonProjects/technical_analysis/decision_module/stock_screener.py))、市場狀態偵測 ([market_regime_detector.py](file:///c:/Projects/PythonProjects/technical_analysis/decision_module/market_regime_detector.py))、產業映射器 ([industry_mapper.py](file:///c:/Projects/PythonProjects/technical_analysis/decision_module/industry_mapper.py)) 及推薦服務 ([recommendation_service.py](file:///c:/Projects/PythonProjects/technical_analysis/app_module/recommendation_service.py)) 的 SQLite 優先讀取改造，全數實現 SQLite 優先與 CSV 備用降級，徹底消除遍歷磁碟小 CSV 的 I/O 毒瘤。
  * **一鍵安全更新效能 Hotfix**：修復並優化了 `_date_key` 日期格式解析，避免逐行呼叫 `pd.to_datetime`。產業指數日期 map 轉換耗時由 13.19 秒降至 **0.136 秒** (提速 100 倍)，286 萬筆每日股價同步寫入 SQLite 僅需 **59.35 秒**。
  * 驗證：單元測試 `test_ui_qt_update_view_workbench.py` (7 passed) 與更新頁 QA `qa_validate_update_tab.py` (通過 21，失敗 0) 100% 通過。

* ✅ **SQLite 儲存相容重構與數據遷移 (research/sqlite-storage)**：
  * 建立 `sqlite/` 獨立目錄、`db_manager.py` 動態寬表資料庫管理模組。
  * 完成 269.9 萬筆個股價格、17.9 萬筆產業指數、3,008 筆大盤指數、7.7 萬筆分點的遷移。
  * **民國年日期解析 Bug 修復**：重構 `standardize_date` 函數，解決無補零西元日期（長度為 7）被誤判為民國年加 1911 的大 Bug。產業指數結束日期修正為 `2026-05-29`。
  * **大盤指數 KeyError 修復**：修正大盤指數 columns 映射 KeyError，成功導入 3,008 筆加權指數記錄（覆蓋 `2014-01-02` 至 `2026-05-29`）。
  * **技術指標全量重新計算與高速批量寫入**：重構指標計算腳本與 UI 服務層，成功執行一鍵全量指標重新計算（1,157 檔個股，僅耗時 1 分 51 秒），成功將 **2,802,159 筆技術指標資料** 同步批次寫入 SQLite `technical_indicators` 表，數據對比 100% 精準。
  * **回測載入性能飆升 322.9 倍**：重構 `DataLoader` 與 `BacktestService` 載入核心。台積電 (2330) 載入時間從 8.37 秒降至 25 毫秒。
  * **UI 狀態加載毫秒級秒開優化**：重構 `check_data_status` 等數據狀態統計方法，當 SQLite 啟用時 100% 改由 SQL 極速聚合統計，徹底避開大 CSV 的硬碟掃描。
  * 通過 `pytest tests/test_ui_qt_update_view_workbench.py` (7/7 passed) 與 `qa_validate_update_tab.py` (21 passed, 0 failed)。

* ✅ **推薦組合回測 MVP** ✅ 已完成（2026-05-27）
  * ✅ 新增 Recommendation replay / portfolio backtest / portfolio optimizer service，保留未來接券商表現、營收數據、更多因子與穩健分析的擴充空間
  * ✅ BacktestView 新增「推薦組合回測」控制區與「推薦組合」結果頁，讓使用者看得出回測期間選了哪些股票、各自貢獻與實際交易紀錄
  * ✅ Pattern polyfit underconstrained 案例改為安全跳過，降低 `DLASCLS` / `RankWarning` 噪音；正式 replay 加入硬篩選 prefilter 與候選上限避免全市場掃描過慢
  * ✅ 驗證：`tests/test_recommendation_portfolio_backtest.py`、`tests/test_recommendation_portfolio_optimizer.py`、`tests/test_pattern_analysis/test_flag_pattern_robustness.py` 通過；6 個月正式資料 smoke 有產生結果

* ✅ **數據更新工作台重整與 Agent 指引更新** ✅ 已完成（2026-05-20）
  * ✅ `UpdateView` 由單頁控制面板整理為維運工作台式布局：左側導覽、上方狀態摘要、右側資料來源頁、底部共享日誌與進度
  * ✅ 新增「安全更新所有數據」流程，提供日常保守更新入口
  * ✅ 新增 Codex 根目錄 `AGENTS.md`，並修正 `docs/agents/` 中資料路徑、PySide6 / `ui_qt` 與 coverage 文件路徑
  * ✅ 驗證：`tests/test_ui_qt_update_view_workbench.py` 4/4 通過；更新頁 QA 17/17 通過
  * ⚠️ 全量 `pytest tests` 仍受既有 collection/import 問題阻擋，與本次工作台重整無直接關聯

* ✅ **UI Qt Backtest 圖表渲染優化** ✅ 已完成
  * ✅ 新增 `ui_qt/widgets/chart_payloads.py`，集中處理圖表資料正規化、benchmark normalization、drawdown metadata、報酬分佈 bins、持有天數 buckets。
  * ✅ 新增 `ui_qt/widgets/fast_chart_widget.py`，使用 QtWebEngine + HTML5 Canvas 顯示回測圖表。
  * ✅ `BacktestView` 改用 factory 建立圖表；QtWebEngine 不可用時 fallback 到既有 Matplotlib widgets。
  * ✅ 報酬分佈改為 zero-centered histogram；持有天數改為 `1-5d`、`6-20d`、`21-60d`、`61d+` 區間桶。
  * 📚 技術文檔：`docs/08_technical/UI_QT_CHART_RENDERING.md`

* ✅ **籌碼分析終端 (Smart Money Terminal) MVP** ✅ 已完成
  * ✅ 建立 `smart_money_flow_view.py`
  * ✅ 實作 Qt Delegate (`terminal_delegate.py`) 達成資料與呈現的高效分離
  * ✅ 實作 Row Intensity 與 Signal Badges

* ✅ **AI Runtime Subsystem MVP** ✅ 已完成
  * ✅ Phase A: Architecture Skeleton & Contracts
    * 建立 `IRuntimeStore` 與 `LocalFileStore`
    * 實作純 Python 解耦的 `EventBus`
    * 實作 `RuntimeSnapshotService` 與具備趨勢分析的 `RuntimeHealthService`
    * 確立架構治理規範與 Forbidden Dependencies
  * ✅ Phase B: RuntimeView UI Implementation
    * 建立 Pure Render 的 `RuntimeView`
    * 透過 `QtRuntimeBridge` 將 EventBus 與 Qt Signals 解耦
    * 利用 `QTimer` 與 `RuntimeController` 模擬資料串流，完成狀態機的 Observatory

* ✅ **Phase 2.5：參數設計優化** ✅ 已完成並驗證通過
  * ✅ 優先級 1：強勢/弱勢分數標準化、Pattern ATR-based、Scoring Contract 統一
  * ✅ 優先級 2：回測參數改進、停損停利 ATR 模式、部位管理
  * ✅ **功能驗證**：18/18 功能通過（100% 通過率）
    * 驗證報告：[output/qa/phase2_5_validation/VALIDATION_REPORT.md](../../output/qa/phase2_5_validation/VALIDATION_REPORT.md)
    * 驗證腳本：`scripts/qa_validate_phase2_5.py`
  * 詳細計劃：[docs/08_technical/PARAMETER_DESIGN_IMPROVEMENTS.md](../08_technical/PARAMETER_DESIGN_IMPROVEMENTS.md)

* ✅ **Phase 2 完整功能**：所有子任務已完成
  * ✅ Phase2-A：跨 Tab 共用 Watchlist
  * ✅ Phase2-D：Backtest 研究體驗補強（進度回調、參數套用）
  * ✅ Phase2-B：Market Watch 弱勢分析（弱勢股/產業）
  * ✅ Phase2-C：Recommendation DTO 統一（可保存、可追溯）
  * ✅ Phase2-E：預設策略庫（暴衝/穩健策略、策略說明文檔）

* ✅ **推薦分析 Tab QA 驗證** ✅ 已完成
  * ✅ 建立 QA 驗證腳本：`scripts/qa_validate_recommendation_tab.py`
  * ✅ 修復類型轉換錯誤（價格/成交量數據）
  * ✅ 修復缺失方法（`_get_regime_weights`）
  * ✅ 修復日期解析問題
  * ✅ 驗證報告：`output/qa/recommendation_tab/VALIDATION_REPORT.md`

* ✅ **數據更新 Tab QA 驗證與修復** ✅ 已完成
  * ✅ 建立 QA 驗證腳本：`scripts/qa_validate_update_tab.py`
  * ✅ 驗證結果：17 項通過，0 項失敗
  * ✅ 修復合併數據閃退問題（Worker 線程管理、異常處理）
  * ✅ 修復產業/大盤數據更新問題（實現實際更新邏輯，不再返回 stub）
  * ✅ 修復 I/O 錯誤（`print()` → `logging`，避免標準輸出已關閉時崩潰）
  * ✅ 改進 Worker 線程管理（取消舊 Worker、等待完成、正確清理）
  * ✅ 驗證報告：`output/qa/update_tab/VALIDATION_REPORT.md`

### 修復記錄（Phase 2.5 驗證修復）

* ✅ **編碼問題修復**：將所有 `print()` 改為 `logging`，解決 Windows charmap codec 問題
  * 修復文件：`ui_app/stock_screener.py`、`app_module/backtest_service.py`、`ui_app/industry_mapper.py`
* ✅ **Watchlist API 統一**：統一 `add_stocks` 參數格式，添加 `remove_stock` 和 `clear_watchlist` 方法
  * 修復文件：`app_module/watchlist_service.py`、`scripts/qa_validate_phase2_5.py`
* ✅ **StrategySpec 構造函數**：統一參數名稱（使用 `default_params` 和 `strategy_version`）
  * 修復文件：`scripts/qa_validate_phase2_5.py`
* ✅ **Recommendation 篩選邏輯**：修復篩選參數轉換（min_return_pct → price_change_min，min_volume_ratio → volume_ratio_min）
  * 修復文件：`ui_app/strategy_configurator.py`、`app_module/recommendation_service.py`
* ✅ **Backtest 屬性名稱**：修復 `annualized_return` → `annual_return` 屬性名稱問題
  * 修復文件：`scripts/qa_validate_phase2_5.py`

### 修復記錄（UI 穩定性修復）

* ✅ **推薦分析 Tab 修復**：
  * ✅ 修復類型轉換錯誤（`TypeError: '>' not supported between instances of 'str' and 'int'`）
  * ✅ 修復缺失方法（`AttributeError: 'ScoringEngine' object has no attribute '_get_regime_weights'`）
  * ✅ 修復日期解析問題（`1970-01-01` 日期）
  * ✅ 修復 `FutureWarning`（`fillna(method='ffill')` → `ffill().bfill()`）
  * ✅ 修復文件：`app_module/recommendation_service.py`、`ui_app/strategy_configurator.py`、`ui_app/scoring_engine.py`、`analysis_module/pattern_analysis/pattern_analyzer.py`

* ✅ **數據更新 Tab 修復**：
  * ✅ 修復合併數據閃退（Worker 線程管理、異常處理）
  * ✅ 修復產業/大盤數據更新（實現實際更新邏輯）
  * ✅ 修復 I/O 錯誤（`ValueError: I/O operation on closed file`）
  * ✅ 修復 Worker 線程問題（`QThread: Destroyed while thread is still running`）
  * ✅ 改進錯誤處理和日誌記錄
  * ✅ 修復文件：`app_module/update_service.py`、`scripts/merge_daily_data.py`、`scripts/batch_update_market_and_industry_index.py`、`ui_qt/views/update_view.py`、`ui_qt/workers/task_worker.py`、`data_module/config.py`

* ✅ **2025-12-20 修復與改進**：
  * ✅ **數據合併功能修復**：改進日期格式處理（支持 int/float/string），統一轉換為 YYYYMMDD 格式，確保所有數據正確合併
    * 修復文件：`scripts/merge_daily_data.py`、`app_module/update_service.py`
  * ✅ **PandasTableModel 錯誤修復**：修復列表/數組類型處理的布爾判斷錯誤（`The truth value of an empty array is ambiguous`）
    * 修復文件：`ui_qt/models/pandas_table_model.py`、`ui_qt/views/watchlist_view.py`
  * ✅ **觀察清單管理器功能增強**：整合選股清單管理（保存、載入、CRUD），實現觀察清單與回測清單之間的轉換
    * 修改文件：`ui_qt/views/watchlist_view.py`、`ui_qt/main.py`
  * ✅ **觀察清單管理器布局重新設計**：上下分割設計（主要工作區 70%，管理操作區 30%），符合「主資訊在上、輔助操作在下」的視覺結構
    * 修改文件：`ui_qt/views/watchlist_view.py`

* ✅ **推薦分析 Tab UI 可理解性優化** ✅ 已完成
  * ✅ **說明資料集中管理**：將所有技術指標/圖形模式的說明資料集中到單一資料結構，UI 建構時只讀取，不硬編碼文字
    * 資料結構包含：short_label、category、system_role、tags、tooltip_lines
    * 未來新增指標/圖形只需在資料結構中添加，無需修改 UI 代碼
  * ✅ **策略傾向引導**：在配置面板頂部新增策略傾向提示區，根據使用者勾選的指標/圖形動態顯示策略傾向
    * 支援顯示：趨勢追蹤策略、反轉策略、盤整/區間策略、趨勢延續策略、混合策略
    * 即時更新：勾選/取消任何指標或圖形時自動更新
  * ✅ **Tooltip 明確說明系統角色**：每個指標/圖形的 tooltip 明確標示系統角色（📊 分數加權依據 / 🧭 市場狀態輔助判斷）
    * 讓使用者能清楚知道每個指標是「加分依據」還是「觸發條件」
  * ✅ **推薦結果可反推線索**：在推薦理由中顯示觸發來源（技術指標、圖形訊號），使用 tags 識別關鍵詞
    * 使用者可從推薦理由反推出使用了哪些指標/圖形
  * ✅ **配置面板滾動優化**：使用 QScrollArea 包裹配置面板，解決未全螢幕時無法看到底部按鈕的問題
  * 修改文件：`ui_qt/views/recommendation_view.py`
  * **目標達成**：使用者在不懂技術分析的情況下，也能透過 UI 明確知道：
    - 自己現在選的是哪一類策略（趨勢 / 盤整 / 反轉）
    - 每個指標/圖形在系統中是「加分依據」還是「觸發條件」
    - 為什麼某檔股票被推薦（可從結果反推）

* ✅ **策略回測功能優化** ✅ 已完成（2025-12-22）
  * ✅ **日期範圍自動調整**：當選擇的日期範圍超過實際數據時，自動調整為可用範圍並顯示提示
    * 修改文件：`app_module/backtest_service.py`、`ui_qt/views/backtest_view.py`
  * ✅ **技術指標數據載入修復**：修復 YYYYMMDD 格式日期解析問題
    * 修改文件：`app_module/backtest_service.py`
  * ✅ **參數最佳化性能優化**：預載入數據、多線程並行執行
    * 性能提升：數據載入從 N 次減少到 1 次，執行速度提升 6-8 倍
    * 修改文件：`app_module/optimizer_service.py`、`app_module/backtest_service.py`
  * ✅ **技術指標計算腳本修復**：修復增量更新時覆蓋舊數據的問題
    * 修改文件：`analysis_module/technical_analysis/technical_indicators.py`、`scripts/calculate_technical_indicators.py`

* ✅ **券商分點資料更新功能** ✅ 已完成（2025-12-27，修復 2025-12-29）
  * ✅ **BrokerBranchUpdateService 模組**：實現券商分點資料抓取、標準化、合併功能
    * 新增文件：`app_module/broker_branch_update_service.py`
    * 功能：從 MoneyDJ 抓取 6 個追蹤分點的每日買賣資料
    * 資料存儲：每個分點獨立目錄 `data/broker_flow/{branch_system_key}/daily/{YYYY-MM-DD}.csv`
    * 合併功能：每個分點獨立合併檔案 `data/broker_flow/{branch_system_key}/meta/merged.csv`
  * ✅ **Registry 管理**：建立分點註冊表
    * 新增文件：`{meta_data_dir}/broker_branch_registry.csv`
    * 包含 6 個追蹤分點的完整資訊（branch_system_key、branch_broker_code、branch_code、branch_display_name、url_param_a、url_param_b）
    * 支援 UTF-8 with BOM 編碼，自動修復 mojibake 問題
  * ✅ **UI 整合**：整合到數據更新頁面
    * 修改文件：`ui_qt/views/update_view.py`
    * 新增「券商分點資料」更新類型選項
    * 新增「券商分點數據」狀態顯示區塊
    * 新增「合併券商分點資料」按鈕
  * ✅ **UpdateService 整合**：新增 broker branch 相關方法
    * 修改文件：`app_module/update_service.py`
    * 新增 `update_broker_branch()`、`merge_broker_branch_data()`、`check_broker_branch_data_status()` 方法
    * 修改 `check_data_status()` 方法，加入券商分點資料狀態檢查
  * ✅ **穩定性改進**：
    * ChromeDriver 自動恢復機制（檢測崩潰並自動重建）
    * 重試機制（每個日期最多重試 3 次）
    * 改進的錯誤處理和日誌記錄
    * 增強 Chrome 選項以提高穩定性
  * ✅ **編碼修復**：修復中文 mojibake 問題
    * 所有讀寫操作使用 UTF-8 with BOM 編碼
    * 自動檢測和修復 mojibake
    * 創建修復腳本：`scripts/fix_broker_branch_registry.py`
  * ✅ **2025-12-29 修復記錄**：
    * ✅ **URL 參數修復**：`c` 參數從 `E` 改為 `B`，日期範圍從 `e=當天&f=當天` 改為 `e=前一天&f=當天`
    * ✅ **Registry 前導零修復**：修復 `url_param_b` 前導零丟失問題（讀取時強制為字串類型）
    * ✅ **Selenium 穩定性增強**：改進超時處理、錯誤檢測、driver 重建機制
    * ✅ **datetime 導入修復**：移除函數內重複導入
    * ✅ **測試驗證**：所有 6 個分點成功下載，每個分點 100 筆記錄，總記錄數 600 筆
  * 📚 **相關文檔**：
    * 設計文檔：`docs/BROKER_BRANCH_DATA_MODULE_DESIGN_V2.md`
    * 實作總結：`docs/BROKER_BRANCH_IMPLEMENTATION_SUMMARY.md`（含修復記錄）
    * **測試與故障排除指南**：`docs/BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md` ⭐ **測試必讀**
  * 🧪 **測試腳本**：
    * `scripts/test_broker_branch_single.py`：快速測試單一分點
    * `scripts/test_all_branches_one_day.py`：測試所有分點（一天）
    * `scripts/test_broker_branch_10days.py`：測試多天資料（10 天）
    * `scripts/check_branch_files.py`：檢查下載的檔案
    * `scripts/verify_branch_data.py`：驗證資料格式

### 下一步 Next（Strategy & Scoring Governance → Phase 5 研究輸出）

1. 🎯 **P0：Fixed / Quantile 實證 Walk-forward 比較**
   - Strategy & Scoring Governance 增量 A、B 的功能與機制回歸已完成。
   - 固定股票池、資料版本、訓練/驗證/測試窗口、交易成本與成交假設。
   - 比較報酬、最大回撤、Sharpe、交易次數、暖機後有效日數、推薦通過率與換手。
   - 實證完成前 quantile 維持 opt-in，不宣稱改善績效或穩健度。

2. 🎯 **P1：大表格分頁與研究報告匯出（Phase 5.1 & 5.2）**
   - 針對 SQLite 資料檢視與大資料表導入分頁（Pagination）或虛擬滾動機制，徹底防範大數據量載入時的 UI 假死。
   - 實作回測 run 與推薦組合結果匯出為 Excel/PDF 規格化報告的模板與服務。

3. 🎯 **P2：Nice-to-have 舊文件清理**
   - 整理更新 `app_module/README.md`、`ui_qt/README.md` 等與 SQLite-first 讀取、產品三閉環架構描述不一致的歷史說明文件。

**歷史 Next 記錄**（以下為已完成項，保留作為追溯）

* **Strategy & Scoring Governance 增量 A、B**（2026-06-13）
  * ✅ 完成回測 fixed / quantile、Expanding T-1、60 個有效觀測暖機與整數 nearest-rank。
  * ✅ 完成推薦 eligible universe empirical CDF、最小母體防禦、DTO metadata 與 UI。
  * ✅ 完成機制回歸 Gate；真實 walk-forward 績效比較保留為 P0。
* **批次回測並行化與安全軟取消實作**（2026-06-12）
  * ✅ 實作 ProcessPoolExecutor 並行化，支援 max_workers=None，實作背景 cooperative cancellation 且還原 legacy `terminate()` 暴力取消防範回歸，通過測試與文檔更新。
* **Research Lab 工作流重整啟動**（2026-06-04）
  * ✅ Backtest / Research Lab 第一階段開始整理為多模式實驗室：策略研究、單股回測、批次股票回測、固定組合回測與推薦系統回放。
  * ✅ Watchlist / 觀察清單在研究流程中明確定位為候選池，後續會承接推薦、強弱勢、主力流向與手動挑選來源。
  * ✅ Phase 3 → Portfolio handoff 會以 append-only trade 為唯一主路徑，並保存 recommendation / backtest source metadata。

* **文件與進度整理**（2026-05-20）
  * ✅ 數據更新工作台與 Agent 指引已同步至主要入口文件

* ✅ **Phase 3.3b：研究閉環完整化** ✅ **已完成**（2026-01-02）
  * ✅ Epic 1 Promote 功能：已完成
  * ✅ Epic 2 回測穩健性驗證：已完成（MVP-1 + MVP-2）
    * ✅ MVP-2 過擬合風險提示：單元測試 20/20 通過，驗證腳本 11/11 通過
  * ✅ Epic 3 視覺驗證：已完成
  * ✅ **完整功能驗證與修復**：已完成（2026-01-02）
    * ✅ 驗證通過率：100% (10/10)
    * ✅ 修復失效功能：WatchlistService.get_watchlist()、BacktestReportDTO 引用錯誤
    * ✅ 功能確認：過擬合風險計算、推薦理由生成均正常運作
    * ✅ 驗證報告：`output/qa/phase3_3b_validation/VALIDATION_REPORT.md`
    * ✅ 修復總結：`output/qa/phase3_3b_validation/修復總結報告.md`

* **券商分點資料品質問題排查** ✅ **已完成**（2026-01-02）
  * ✅ 改進 `_parse_counterparty_broker_name` 解析邏輯，驗證修復後資料完整性（18/18 測試通過）

* ✅ **Phase 3.3b Epic 2 MVP-2：過擬合風險提示** ✅ 已完成（2026-01-02）

* **Phase 3.1 / 3.2 / 3.3a / 3.3b**：全部 ✅ 已完成（見上方歷史 Phase 段落）

* **Phase 4：持倉管理與交易日誌**（✅ Phase 4.1 已深化完成）
  * ✅ Phase 4.1：最小可用持倉與深化功能
    * ✅ service/domain/test 骨架已建立
    * ✅ 新增 `PortfolioView` 與 Portfolio 頂層 Tab
    * ✅ 串接 Recommendation / Backtest 來源追溯 metadata
    * ✅ `PortfolioConditionMonitor` 條件監控 MVP（2026-06-09）
    * ✅ 策略版本追蹤視圖、Price 對照、持倉層風險提示已深化實作（2026-06-11）
  * ✅ Phase 4.2 前置：券商分點資料與 Smart Money Terminal MVP 已完成
  * ✅ Phase 4.2 完整：持倉層的籌碼風險提示與下鑽整合（2026-06-11）

### Blockers / Risks

* ~~**回測時間軸未定義**~~：✅ 已建立初版 contract（2026-06-10），`next_open` 帳務錯位已修正；推薦組合回測同日收盤假設已明確警告與 metadata 揭露。
* ⚠️ **金融核心裸 float**：核心金額、交易成本、Portfolio domain、績效交易損益與推薦組合 PnL 已建立 Decimal 邊界；後續風險轉為「analytics / visualization float 邊界需持續標示與審查」，避免新功能把 float 重新帶回核心計算。
* ⚠️ **分位數 Look-ahead 與母體漂移**：回測不得使用完整期間分布或 T 日自身分數計算 T 日門檻；推薦必須先固定當日 eligible universe，再進行橫斷面排名。
* ⚠️ **策略版本相容性**：缺少 `threshold_mode` 的舊策略必須維持 fixed 行為；不得自動轉換歷史 Preset / StrategyVersion。
* ⚠️ **文檔歷史路徑與狀態**：部分歷史文件仍引用已遷移的 `ui_app` 路徑；Active 權威文件需使用 `decision_module`，歷史 QA 記錄保留追溯語意。
* ~~**參數設計問題**~~：✅ 已解決（Phase 2.5 完成）
* ~~**過擬合風險**~~：✅ 已解決（ATR-based 標準化完成）
* ~~**系統穩定性**~~：✅ 已解決（所有功能驗證通過，UI 穩定性問題已修復）

## 2026-06-13 Strategy & Scoring Governance 規格核准

- 核准 fixed / quantile 雙模式漸進遷移，舊策略缺少 `threshold_mode` 時維持 fixed。
- 回測 quantile 採單股 Expanding、T-1 資料邊界與 60 個有效觀測值暖機。
- 分位數決策參數採整數基點；第一版不支援 rolling window，也不自動轉換歷史策略版本。
- 推薦採當日 eligible universe 橫斷面百分位，與回測時間序列門檻分開實作。
- 正式設計：`docs/superpowers/specs/2026-06-13-strategy-scoring-governance-design.md`。

---

## 開發原則（不可違反）

* UI 層只做：收參數 / 呼叫 service / 顯示 DTO
* UI 不讀寫 CSV、不算指標、不寫推薦理由
* 所有耗時操作必須走 Worker（可取消 / 可顯示進度）
* 每個 Phase 結尾系統必須「完整可運行」

---

**這份文件是唯一的開發事實來源（Single Source of Truth），並且永遠都用繁體中文回答或做註解。**
 
## 2026-05-27 推薦組合穩健性更新

- Recommendation Portfolio Backtest 已補入第一版穩健性指標：Sharpe Ratio、Sortino Ratio 與 Monte Carlo P05/P50/P95 模擬報酬。
- 指標以獨立 metric layer 接入推薦組合回測 summary，避免把後續券商分點、營收、基本面或籌碼因子硬塞進 UI 或現有 scoring 函式。
- 後續可延伸 rolling Sharpe / rolling Sortino、VaR / CVaR 與更完整 factor/metric layer。

## 2026-05-27 推薦組合 Portfolio Value 圖表更新

- Recommendation Portfolio Backtest equity curve 已從「出場日 realized PnL 階梯線」改為每日 mark-to-market portfolio value。
- Backtest「推薦組合」結果頁新增 Portfolio Value 與 Drawdown 圖表，Portfolio Value 會嘗試疊加大盤基準線。
- 目前推薦組合路徑仍以持有天數出場為主，停損/停利、失敗診斷與策略版本學習閉環仍是下一段工作。

## 2026-05-27 推薦組合出場與診斷更新

- Recommendation Portfolio Backtest 已接入停損 (%) / 停利 (%) 提前出場，持倉會逐交易日檢查 stop_loss / take_profit，未觸發時才以 holding_period 出場。
- 推薦組合結果總覽新增出場原因統計、虧損交易占比與最拖累股票，提供第一版策略失敗診斷。
- 尚未完成：推薦組合結果保存為策略版本、依診斷推薦參數調整、以及更完整的 factor/failure attribution。

## 2026-05-27 推薦組合 Research Run 更新

- 新增 `RecommendationPortfolioRunRepository`，以 SQLite metadata + JSON detail 保存推薦組合 research run。
- Backtest「推薦組合回測」區塊新增保存、刪除與歷史記錄下拉選單，可重新載入完整 DTO 並重畫圖表/表格。
- 新增 deterministic improvement hints，依停損比例、持有到期虧損、最差個股、交易次數與整體虧損產生第一版策略改善建議。
- 已完成：推薦組合 research run 可 promote 成策略版本，並回寫 `promoted_version_id` 以保留來源追溯；尚未完成跨 run 比較視圖與更完整的 benchmark-relative attribution。

## 2026-06-03 主力流向 (Smart Money Flow) 視覺重構與排版優化成果

- **UI 分欄與雷達卡片**：重構為左右分欄佈局（65% 主表，35% 詳情），並加入選中股雷達摘要卡片與 `explainable_reasons` 解析。
- **玻璃擬態卡片中文化**：調整頂部小卡片標題（市場趨勢、熱度、多空個股數、異常警示）並調大字體。
- **Sparkline 與 ToolTip 優化**：使用 `QLinearGradient` 渲染漸層 Sparklines，固定抽取最近 5 筆交易記錄，並實作跨 Cell 的 ToolTip 懸浮提示。
- **Bug 修復與排序**：修復 Header 點擊排序無反應問題；修復偏空個股數為 0 與熱度 100% 的 Bug。

## 2026-06-03 數據更新工作台 (UpdateView) 視覺重構與架構優化成果

- **主看板與 StatusCard**：將「全部資料」頁面重構為極簡數據看板，移除了所有手動配置與雜亂按鈕。設計了 StatusCard 元件（圓角、Hover 漸變與陰影效果），整合四色狀態指示燈（🟢/🟡/🔴/⚪）顯示最新日期與筆數，與原 `QTextEdit` 介面相容度 100%。
- **進階與手動操作配置歸位**：解耦原有界面，將下載日期範圍、手動下載與合併按鈕搬移至個別專屬分頁（每日股價、大盤、產業、券商分點、技術指標）。每日股價分頁中，以紅色警示邊框封裝了 **Danger Zone (高風險區)** 存放強制重新合併按鈕。
- **全域底部日誌 Console 與進度條共享**：將 QProgressBar、進度 Label 以及 Terminal 日誌輸出框移至最外層佈局的最下方，實作分頁切換時日誌與進度的全域共享。Console 採用深色背景、Consolas 等寬 11px 字型與微型清除按鈕。
- **日期聯動同步與委派更新**：在 `UpdateView` 中實作了日期聯動邏輯，任何分頁修改日期皆會透過 blockSignals 同步更新其他分頁元件。手動更新按鈕透過 `_dispatch_update()` 自適應設定隱藏的對應 RadioButton 狀態，實現 UI 與原 Service 業務代碼的無縫相容。
- **自動與 QA 測試 100% 綠燈**：通過 mypy 無新增錯誤，`tests/test_ui_qt_update_view_workbench.py` (9 passed) 與 `scripts/qa_validate_update_tab.py` (21 passed, 0 failed) 順利通過。

## 2026-06-11 Phase 4.2 資料契約修正

- MoneyDJ `c=E` 定義為張數，`c=B` 定義為仟元金額。
- Phase 4.2 籌碼風險規則只讀 E 張數；B 金額另欄保存。
- 舊版 B-only CSV/SQLite 不刪除，也不以乘除 1000 偽造張數；缺少雙指標的日期會重新抓取。

## 2026-06-12 券商分點 Ranked Metric 治理成果

- MoneyDJ E/B 確認為獨立買超/賣超 Top 50，合併契約改為 union，榜外欄位保存 `NULL`。
- 新增 `trade_type`、observed 與 rank metadata；歷史缺 rank 的衍生資料依方向與淨值排序補回。
- Smart Money 與 Portfolio Chip Monitor 完成 observed / estimated / unavailable 三態、覆蓋率折舊與非毒性聚合。
- 正式 merged/SQLite 已無破壞重建與稽核完成，原始 daily CSV 未修改。



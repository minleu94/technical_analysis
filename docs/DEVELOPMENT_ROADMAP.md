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

### Phase 1 ～ Phase 3（固定 4 個 Tab）

1. **數據更新（Update）**
2. **市場觀察（Market Watch）**
3. **推薦分析（Recommendation）**
4. **策略回測（Research Lab / Backtest）**

> 原則：Phase 1～3 **不新增頂層 Tab**，所有功能擴張僅使用 sub-tab、區塊或 side panel。

### Phase 4 起（新增第 5 個 Tab）

5. **持倉 / Portfolio（Positions & Journal）**

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
  * ✅ 實現位置：`ui_app/scoring_engine.py`（所有子分數使用 `.clip(0, 100)`，Regime 權重切換）

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

#### 優先級 4：長期 ⚠️ 未完成（0/2，移至 Phase 3）
* [ ] Walk-forward 暖機期參數
* [ ] 完整測試與驗證（優先級 1 和 2 已驗證通過）

**說明**：Walk-forward 服務已實現，但暖機期參數未實現。優先級 1 和 2 已通過驗證（18/18 功能通過）。

### Phase 2.5 Exit Criteria

**核心部分（優先級 1 和 2）Exit Criteria：**
* ✅ 所有參數單位一致、可跨股票比較（強勢/弱勢分數、Pattern ATR-based、Scoring contract）
* ✅ 回測參數明確定義（execution_price、停損停利 ATR 模式、部位管理）
* ✅ 參數設計文檔完整

**整體 Exit Criteria（含優先級 3 和 4）：**
* ⚠️ 所有參數單位一致、可跨股票比較（核心部分已達成，指標參數未改進）
* ⚠️ Grid Search 結果在 walk-forward 驗證中穩定（Walk-forward 已實現，穩定性驗證未完成）
* ✅ 參數設計文檔完整

**詳細改進計劃**：請參考 [docs/PARAMETER_DESIGN_IMPROVEMENTS.md](docs/PARAMETER_DESIGN_IMPROVEMENTS.md)  
**完成狀態檢查報告**：請參考 [docs/PHASE2_5_COMPLETION_STATUS.md](docs/PHASE2_5_COMPLETION_STATUS.md)

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

- ✅ **Research Design**：已完成（見 `docs/PHASE_3_3B_RESEARCH_DESIGN.md`）
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

## Phase 4：持倉管理與交易日誌（Portfolio & Journal）⏸️ 依賴 Phase 3.3b

**前置條件**：需先完成 Phase 3.3b（Promote 功能、K 線標記買賣點），確保研究閉環完整後再進入持倉管理階段。

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

* [ ] **新增 Portfolio Tab**（最小版本）

* [ ] **交易紀錄**（必綁 strategy_version + regime_snapshot）

* [ ] **條件監控（Monitor）**：用「推薦引擎的判斷結果」去檢查是否還成立

* [ ] **非強制提示**（提醒/警示，不做自動操作）

#### Phase 4.1 驗收標準

* ✅ 你可以在 Portfolio 看到每筆交易的「策略脈絡」與「目前是否仍成立」
* ✅ 每天能用它做持倉檢查（不需要靠記憶）

---

### Phase 4.2：券商買賣超/籌碼面 v1（可選但建議）

* [ ] **券商買賣超匯入 + 查詢 + 下鑽**（先做 v1：Top N + 連續性）
* [ ] 用於「觀察」與「風險提示」，不直接當買賣訊號

---

### Phase 4 整體驗收標準

* ✅ 推薦 → 回測 → 持倉 → 回顧形成完整閉環
* ✅ 每筆持倉都有完整的策略脈絡和監控機制

---

## Phase 5：效能與研究輸出（Scale & Reporting）✅ 大規模仍流暢、能產出成果

---

### Phase 5.1：效能

* [ ] **大表格分頁**
* [ ] **圖表渲染優化**（PyQtGraph 或等效）
* [ ] **批次回測並行化**（可取消、可進度）

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
   - `docs/PROJECT_SNAPSHOT.md` 必須與 Living Section 的「現況」和「下一步」一致
   - `docs/DOCUMENTATION_INDEX.md` 的進度描述必須與 Living Section 一致
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
- 更新 Living Section 後 → 必須同步更新 `PROJECT_SNAPSHOT.md` 和 `DOCUMENTATION_INDEX.md`

---

## 當前狀態（Living Section）

### 現況（Baseline）

* ✅ **Phase 1、Phase 2、Phase 2.5 核心部分**：已完成且驗證通過
* ✅ **系統可運行、UI 穩定、回測/最佳化效能已大幅改善**
* ✅ **Phase 3.1、3.2、3.3a 核心功能**：已完成（推薦可用化、Profiles 正式化、研究閉環核心功能）
* ✅ **券商分點資料更新功能**：已完成（2025-12-27，修復 2025-12-29）
  * ✅ 所有 6 個分點成功下載測試通過（每個分點 100 筆記錄，總記錄數 600 筆）
  * ✅ URL 參數和日期範圍修復完成（`c=B`，日期範圍：`e=前一天&f=當天`）
  * ✅ Registry 前導零問題修復完成
  * ✅ Selenium 穩定性增強完成
  * 📚 測試文檔：`docs/BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md` ⭐ **測試必讀**
* ✅ **Phase 3.3b Epic 2 MVP-2：過擬合風險提示**：已完成（2026-01-02）
  * ✅ 單元測試：20/20 通過（100% 通過率）
  * ✅ 驗證腳本：11/11 通過（100% 通過率）
  * ✅ 驗證報告：`output/qa/epic2_mvp2_validation/VALIDATION_REPORT.md`
* ✅ **Phase 3.3b：研究閉環完整化**：已完成（2026-01-02）
  * ✅ Epic 1 Promote 功能：已完成
  * ✅ Epic 2 回測穩健性驗證：已完成（MVP-1 + MVP-2）
  * ✅ Epic 3 視覺驗證：已完成
  * ✅ **完整功能驗證與修復**：已完成（2026-01-02）
    - ✅ 驗證通過率：100% (10/10)
    - ✅ 修復失效功能：WatchlistService、BacktestReportDTO 引用
    - ✅ 驗證報告：`output/qa/phase3_3b_validation/VALIDATION_REPORT.md`

---

### 本週 Done（Phase 2.5 完成 + 全功能驗證通過 + UI 穩定性修復 + 回測功能優化 + Broker Branch Data Update + 修復與測試文檔 + Epic 2 MVP-2 完成）

* ✅ **Phase 2.5：參數設計優化** ✅ 已完成並驗證通過
  * ✅ 優先級 1：強勢/弱勢分數標準化、Pattern ATR-based、Scoring Contract 統一
  * ✅ 優先級 2：回測參數改進、停損停利 ATR 模式、部位管理
  * ✅ **功能驗證**：18/18 功能通過（100% 通過率）
    * 驗證報告：[output/qa/phase2_5_validation/VALIDATION_REPORT.md](../output/qa/phase2_5_validation/VALIDATION_REPORT.md)
    * 驗證腳本：`scripts/qa_validate_phase2_5.py`
  * 詳細計劃：[docs/PARAMETER_DESIGN_IMPROVEMENTS.md](docs/PARAMETER_DESIGN_IMPROVEMENTS.md)

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

### 下一步 Next（Phase 4 準備）

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
  * ✅ **問題**：部分券商或股票代號無法正確解析
    * 觀察到的問題：
      * ETF 名稱無法解析（例如：`元大台灣50`、`元大高股息`、`富邦科技`）
      * 特殊格式代號無法解析（例如：`6643M31`、`7722LINEPAY`）
    * 影響：`counterparty_broker_code` 被標記為 `UNKNOWN`，可能影響後續分析
    * 測試日期：2025-12-29（10 天測試）
    * 測試結果：成功下載 7000 筆記錄，但有多筆 `UNKNOWN` 對手券商
  * ✅ **解決方案**：
    * [x] 檢查 MoneyDJ 頁面原始資料格式
    * [x] 分析無法解析的名稱模式（ETF、特殊格式）
    * [x] 改進 `_parse_counterparty_broker_name` 解析邏輯
      * ✅ 支援標準券商格式（`1234元大證券`）
      * ✅ 支援 ETF 名稱（`元大台灣50` → `code='ETF'`）
      * ✅ 支援特殊格式（`6643M31` → `code='6643'`）
      * ✅ 支援純中文股票名稱（`台積電` → `code='STOCK'`）
      * ✅ 支援純數字股票代號（`2330` → `code='2330'`）
    * [x] 驗證修復後資料完整性（18/18 測試通過，100% 通過率）
  * 📚 **相關文檔**：
    * 改進說明：`docs/BROKER_BRANCH_PARSING_IMPROVEMENT.md` ⭐ **新增**
    * 測試與故障排除指南：`docs/BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md`
    * 實作總結：`docs/BROKER_BRANCH_IMPLEMENTATION_SUMMARY.md`
  * 🧪 **測試腳本**：
    * `scripts/test_counterparty_parsing.py`：解析邏輯測試（18/18 通過）
    * `scripts/analyze_unknown_counterparties.py`：分析現有資料中的 UNKNOWN 模式

* ✅ **Phase 3.3b Epic 2 MVP-2：過擬合風險提示** ✅ 已完成（2026-01-02）
  * ✅ **階段 3：測試與驗證**：已完成
    * ✅ 單元測試：20/20 通過（100% 通過率）
      * 測試文件：`tests/test_backtest/test_overfitting_risk.py`
      * 測試範圍：`calculate_walkforward_degradation()`、`calculate_consistency()`、`calculate_overfitting_risk()`、風險等級判斷
    * ✅ 驗證腳本：11/11 通過（100% 通過率）
      * 驗證腳本：`scripts/qa_validate_epic2_mvp2.py`
      * 驗證範圍：核心計算方法、DTO 整合、服務整合、向後兼容性
    * ✅ 驗證報告：`output/qa/epic2_mvp2_validation/VALIDATION_REPORT.md`
  * ✅ **修復記錄**：
    * ✅ 修復驗證腳本中的 `StrategyRegistry.get_strategy()` 方法調用錯誤
    * ✅ 改進策略獲取邏輯，支援動態查找可用策略
  * 📚 **相關文檔**：
    * 架構設計：`docs/EPIC2_MVP2_ARCHITECTURE_DESIGN.md`
    * 實作檢查清單：`docs/EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md`
    * 驗證報告：`output/qa/epic2_mvp2_validation/VALIDATION_REPORT.md`

* **Phase 3.1：推薦可用化** ✅ 已完成
  * ✅ 推薦分析 Tab UI 可理解性優化
  * ✅ 新手 / 進階模式切換
  * ✅ Why Not（反向解釋）v1
  * ✅ Recommendation 結果可保存
  * ✅ Profiles v1（暴衝/穩健/長期）

* **Phase 3.2：Profiles 正式化** ✅ 已完成
  * ✅ Profiles v1（暴衝 / 穩健 / 長期）
  * ✅ Regime → Profile 建議
  * ✅ Profile meta 可追溯

* **Phase 3.3a：研究閉環核心功能**（✅ 已完成）
* **Phase 3.3b：研究閉環完整化** ✅ 已完成（2026-01-02）
  * ✅ Explain 面板 v1（分數拆解、風險點提示）
  * ✅ 一鍵送回測（Profile → Backtest）
  * ✅ **Epic 2 MVP-2：過擬合風險提示**（已完成，2026-01-02）
    * ✅ 單元測試：20/20 通過
    * ✅ 驗證腳本：11/11 通過
  * ✅ **Epic 3 MVP-1：K 線標記買賣點**（已完成）
    * ✅ 基本 K 線圖顯示（使用 mplfinance）
    * ✅ 買賣點標記（綠色向上箭頭、紅色向下箭頭）
  * ✅ **Epic 1 MVP-1：保存為 Preset 功能**（已完成）
  * ✅ **Epic 1：Promote 機制完整版**（已完成，2026-01-02）
    * ✅ PromotionService：管理回測結果升級流程
    * ✅ StrategyVersionService：管理策略版本生命週期
    * ✅ BacktestRepository：新增 promoted_version_id 欄位
    * ✅ PresetService：支援從回測結果保存
    * ✅ RecommendationService：支援從 Preset 或 Version 載入
  * ✅ **完整功能驗證與修復**（已完成，2026-01-02）
    * ✅ 驗證通過率：100% (10/10)
    * ✅ 修復失效功能：WatchlistService.get_watchlist()、BacktestReportDTO 引用錯誤
    * ✅ 功能確認：過擬合風險計算、推薦理由生成均正常運作
    * ✅ 驗證報告：`output/qa/phase3_3b_validation/VALIDATION_REPORT.md`
    * ✅ 修復總結：`output/qa/phase3_3b_validation/修復總結報告.md`
    * ✅ BacktestView：新增 Promote 按鈕和 UI

* **Phase 4：持倉管理與交易日誌**（⏸️ 依賴 Phase 3.3b）
  * ⏸️ Phase 4.1：最小可用持倉（Portfolio MVP）
  * ⏸️ Phase 4.2：券商買賣超/籌碼面 v1（可選但建議）

### Blockers / Risks

* ~~**參數設計問題**~~：✅ 已解決（Phase 2.5 完成）
* ~~**過擬合風險**~~：✅ 已解決（ATR-based 標準化完成）
* ~~**系統穩定性**~~：✅ 已解決（所有功能驗證通過，UI 穩定性問題已修復）
  * Phase 2.5 驗證：18/18 功能通過
  * 推薦分析 Tab 驗證：所有測試通過
  * 數據更新 Tab 驗證：17/17 測試通過

---

## 開發原則（不可違反）

* UI 層只做：收參數 / 呼叫 service / 顯示 DTO
* UI 不讀寫 CSV、不算指標、不寫推薦理由
* 所有耗時操作必須走 Worker（可取消 / 可顯示進度）
* 每個 Phase 結尾系統必須「完整可運行」

---

**這份文件是唯一的開發事實來源（Single Source of Truth），並且永遠都用繁體中文回答或做註解。**

# 當前開發狀態

**更新日期**：2025-01-XX

## 系統定位

**這不是一個「每天吐股票的工具」，而是一個「會隨著你交易理解一起成長的投資決策系統」。**

## 當前位置：Phase 2.5 完成 ✅ → Phase 3 準備

### Phase 1：市場觀察儀 ✅ 已完成

#### 核心功能
1. **數據更新系統**
   - ✅ 每日股票數據更新
   - ✅ 大盤指數更新
   - ✅ 產業指數更新
   - ✅ 技術指標計算

2. **強勢股/產業識別**
   - ✅ 本日/本週強勢股查詢
   - ✅ 強勢股推薦理由生成（價格動能、成交量動能、趨勢結構、產業一致性）
   - ✅ 本日/本週強勢產業查詢

3. **市場 Regime 判斷**
   - ✅ Trend（趨勢追蹤）
   - ✅ Reversion（均值回歸）
   - ✅ Breakout（突破準備）
   - ✅ 自動策略切換

4. **統一打分模型**
   - ✅ 技術指標分數（0-100）
   - ✅ 圖形模式分數（0-100）
   - ✅ 成交量分數（0-100）
   - ✅ Regime Match Factor（匹配市場狀態加分）

5. **推薦理由引擎**
   - ✅ 市場狀態理由
   - ✅ 技術指標理由
   - ✅ 圖形模式理由
   - ✅ 成交量理由
   - ✅ 產業表現理由

6. **產業映射系統**
   - ✅ 股票到產業的映射（companies.csv）
   - ✅ 產業指數表現查詢（industry_index.csv）
   - ✅ 產業篩選功能

### Phase 2：策略資料庫 ✅ 已完成

#### 已完成
1. **應用服務層（app_module/）** ✅
   - ✅ 推薦服務（RecommendationService）
   - ✅ 強勢股/產業篩選服務（ScreeningService）
   - ✅ 市場狀態檢測服務（RegimeService）
   - ✅ 數據更新服務（UpdateService）
   - ✅ 回測服務（BacktestService）
   - ✅ 批次回測服務（BatchBacktestService）
   - ✅ 策略預設服務（PresetService）
   - ✅ 觀察清單服務（WatchlistService）
   - ✅ 推薦結果儲存（RecommendationRepository）
   - ✅ 數據傳輸對象（DTOs）

2. **Qt UI（ui_qt/）** ✅
   - ✅ 數據更新標籤（數據狀態檢查、更新、合併）
   - ✅ 市場觀察標籤（大盤指數、強勢個股、弱勢個股、強勢產業、弱勢產業）
   - ✅ 推薦分析標籤（策略配置、執行、結果顯示、產業篩選、加入觀察清單）
   - ✅ 回測實驗室（單檔/批次回測、參數最佳化、Walk-forward、策略預設）
   - ✅ 觀察清單管理器（跨 Tab 共用、新增/移除/清空、選股清單管理、布局優化）
   - ✅ 非阻塞任務執行（TaskWorker、ProgressTaskWorker）
   - ✅ 表格數據顯示（PandasTableModel，支持列表/數組類型）

3. **策略配置界面** ✅
   - ✅ 6 個配置標籤頁
   - ✅ 技術指標配置
   - ✅ 圖形模式選擇
   - ✅ 信號組合配置
   - ✅ 篩選條件設置

4. **策略框架** ✅
   - ✅ 統一打分模型（0-100 分制）
   - ✅ Regime 自動切換（權重切換，非倍率）
   - ✅ 策略配置保存/載入
   - ✅ 策略註冊系統（StrategyRegistry）
   - ✅ 策略元數據（StrategyMeta）

5. **預設策略庫** ✅
   - ✅ 基礎策略（baseline_score_threshold）
   - ✅ 暴衝策略（momentum_aggressive_v1）
   - ✅ 穩健策略（stable_conservative_v1）
   - ✅ 策略說明文檔（docs/strategies/）

6. **回測系統** ✅
   - ✅ 單檔回測
   - ✅ 批次回測
   - ✅ 參數最佳化（Grid Search）
   - ✅ Walk-forward 驗證
   - ✅ 回測結果保存（SQLite + Parquet/CSV）
   - ✅ 回測歷史管理
   - ✅ 圖表輸出（權益曲線、回撤、分佈、持有天數）

### Phase 2.5：參數設計優化 ✅ 已完成並驗證通過

#### 已完成
1. **強勢/弱勢分數標準化** ✅
   - ✅ z-score 標準化（價格變動、成交量變動）
   - ✅ log 壓縮（成交量變動）
   - ✅ 新增參數：volume_lookback、min_price、min_liquidity

2. **Pattern ATR-based 參數** ✅
   - ✅ threshold_atr_mult（所有 pattern）
   - ✅ prominence_atr_mult（peak/trough 識別）
   - ✅ 保留百分比模式作為 fallback

3. **Scoring Contract 統一** ✅
   - ✅ 所有子分數：0-100 分制
   - ✅ Regime 權重切換（非倍率）
   - ✅ Trend/Reversion/Breakout 不同權重

4. **回測參數改進** ✅
   - ✅ execution_price（next_open/close）
   - ✅ stop_loss_atr_mult / take_profit_atr_mult（ATR 模式）
   - ✅ max_positions（持有上限）
   - ✅ position_sizing（等權/分數加權/波動調整）
   - ✅ allow_pyramid、allow_reentry、reentry_cooldown_days

5. **功能驗證** ✅
   - ✅ 18/18 功能通過（100% 通過率）
   - ✅ 驗證報告：`output/qa/phase2_5_validation/VALIDATION_REPORT.md`
   - ✅ 驗證腳本：`scripts/qa_validate_phase2_5.py`

---

## 系統架構

### 核心模組

#### 1. 數據模組 (`data_module/`)
- ✅ `config.py` - 配置管理
- ✅ `data_loader.py` - 數據加載和更新
- ✅ 數據更新流程完整

#### 2. 分析模組 (`analysis_module/`)
- ✅ `technical_analysis/` - 技術指標計算
- ✅ `pattern_analysis/` - 圖形模式識別
- ✅ `signal_analysis/` - 信號組合分析

#### 3. 應用服務層 (`app_module/`)
- ✅ `recommendation_service.py` - 推薦服務
- ✅ `universe_service.py` - 選股清單服務（用於回測）
- ✅ `screening_service.py` - 強勢股/產業篩選服務
- ✅ `regime_service.py` - 市場狀態檢測服務
- ✅ `update_service.py` - 數據更新服務
- ✅ `backtest_service.py` - 回測服務（骨架完成）
- ✅ `dtos.py` - 數據傳輸對象（DTOs）

#### 4. UI 應用
- **Tkinter UI (`ui_app/`)** ✅ 已完成
  - ✅ `main.py` - 主應用程式
  - ✅ `stock_screener.py` - 強勢股/產業篩選
  - ✅ `strategy_configurator.py` - 策略配置
  - ✅ `scoring_engine.py` - 統一打分模型
  - ✅ `reason_engine.py` - 推薦理由引擎
  - ✅ `market_regime_detector.py` - 市場狀態判斷
  - ✅ `industry_mapper.py` - 產業映射

- **Qt UI (`ui_qt/`)** ✅ 已完成（推薦使用）
  - ✅ `main.py` - 主應用程式（PySide6）
  - ✅ `views/update_view.py` - 數據更新視圖
  - ✅ `views/strong_stocks_view.py` - 強勢個股視圖
  - ✅ `views/market_regime_view.py` - 大盤指數視圖
  - ✅ `views/strong_industries_view.py` - 強勢產業視圖
  - ✅ `views/recommendation_view.py` - 推薦分析視圖
  - ✅ `models/pandas_table_model.py` - 表格數據模型
  - ✅ `workers/task_worker.py` - 非阻塞任務執行

#### 4. 回測模組 (`backtest_module/`)
- ✅ `strategy_tester.py` - 策略測試器
- ✅ `performance_analyzer.py` - 績效分析器
- 🚧 單一策略回測（待整合）

---

## 功能清單

### ✅ 已完成功能

#### 數據更新
- [x] 每日股票數據更新
- [x] 大盤指數更新
- [x] 產業指數更新
- [x] 技術指標計算
- [x] 批量更新功能

#### 市場觀察
- [x] 強勢股查詢（本日/本週）
- [x] 強勢產業查詢（本日/本週）
- [x] 強勢股推薦理由生成
- [x] 市場 Regime 判斷
- [x] Regime 自動策略切換

#### 策略配置
- [x] 技術指標配置（RSI、MACD、KD、ADX、均線、布林通道、ATR）
- [x] 圖形模式選擇（11種模式）
- [x] 信號組合配置
- [x] 篩選條件設置
- [x] 權重配置
- [x] 產業篩選

#### 推薦系統
- [x] 統一打分模型（0-100分）
- [x] Regime Match Factor
- [x] 推薦理由生成
- [x] 分數詳情顯示（總分、指標分、圖形分、成交量分）

### 🚧 進行中功能

#### 策略資料庫
- [ ] 預設策略庫設計
- [ ] 策略說明文檔
- [ ] 單一策略回測
- [ ] 策略在不同 Regime 下的表現分析

### ❌ 未來功能（Phase 3-4）

#### Phase 3（6-12 個月）
- [ ] 多策略組合回測
- [ ] 策略權重優化
- [ ] 回撤分析
- [ ] 穩定性分析

#### Phase 4（12-24 個月）
- [ ] 持倉紀錄
- [ ] 持倉監控
- [ ] 策略條件檢查
- [ ] 系統提示（非強制賣出）

---

## 技術架構

### UI 架構
- **框架**：tkinter + ttk
- **組織方式**：Notebook（標籤頁）
- **執行方式**：多線程（避免 UI 卡頓）

### 數據架構
- **數據源**：TWSE API（MI_INDEX、FMTQIK）
- **存儲位置**：`D:\Min\Python\Project\FA_Data\`
- **數據格式**：CSV（UTF-8-sig）

### 分析架構
- **打分模型**：統一 0-100 分制
- **Regime 判斷**：基於大盤指數（MA20、MA60、ADX）
- **理由生成**：基於已計算數據，不預測未來

---

## 下一步行動

### 立即要做（Phase 3 啟動）

1. **推薦產品化**
   - 推薦 Profiles（暴衝 / 穩健 / 長期）
   - Explain 面板（分數拆解 / 風險點）
   - 一鍵送回測（Profile → Backtest）

2. **策略驗證**
   - 策略版本 Promote（回測成果 → 可被推薦使用）
   - 策略表現追蹤
   - 策略優化建議

### 短期目標（1-2 個月）
- 完成推薦 Profiles
- 完成 Explain 面板
- 完成策略版本 Promote
- 開始收集策略表現數據

---

## 開發原則

### ✅ 現在該做
- 強勢股/產業理由（已完成 ✅）
- Regime 判斷穩定化（已完成 ✅）
- 預設策略「說明書」（進行中 🚧）
- 單一策略回測（待實作）

### ❌ 現在不要急
- ML（機器學習）
- 即時交易
- 太多參數
- 預測未來報酬
- 多策略組合（Phase 3）
- 持倉管理（Phase 4）

---

## 相關文檔

- [開發演進地圖](DEVELOPMENT_ROADMAP.md) - 完整的系統演進計劃
- [開發進度記錄](note.txt) - 詳細的開發日誌
- [系統架構文檔](system_architecture.md) - 系統架構說明


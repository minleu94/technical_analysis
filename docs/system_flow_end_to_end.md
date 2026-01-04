# 台股技術分析系統｜端到端流程藍圖

## 0) 環境與設定初始化

**輸入**：.env（API Token、路徑）、`data_module/config.py`、requirements.txt

**處理**：載入設定、建立資料夾結構

**輸出**：已初始化的資料夾（data/, output/, logs/）

**位置**：technical_analysis/ 根目錄；Windows 既有預設（見第 2 段）

**QC**：檢查必要環境變數是否存在、資料夾是否可寫

**對應**：`data_module/config.py`

---

## 1) 市場日曆與標的清單準備（可選，但強烈建議）

**輸入**：交易日曆（台股開市日）、標的名單（如全市場/0050 成份/自選 18 檔）

**處理**：產生 trading_calendar.csv、universe.csv

**輸出**：data/meta_data/trading_calendar.csv、data/meta_data/universe.csv

**位置**：data/meta_data/

**QC**：日期連續性、去除例假日、標的代碼格式（四碼）

**對應**：data_module/（之後加 meta.py 讀取）

---

## 2) 資料蒐集（Raw Ingestion）

**輸入**：外部來源（TWSE API）、標的清單、日期範圍/增量模式

**處理**：抓取個股/指數/產業指數日 OHLCV，附原始欄位

**輸出**：原始 CSV

- 個股整合：D:/Min/Python/Project/FA_Data/meta_data/stock_data_whole.csv
- 每日快照：D:/Min/Python/Project/FA_Data/daily_price/YYYYMMDD.csv
- 大盤指數：D:/Min/Python/Project/FA_Data/meta_data/market_index.csv
- 產業指數：D:/Min/Python/Project/FA_Data/meta_data/industry_index.csv

**位置**：data/raw/（專案相對）與你現存 Windows 路徑

**QC**：缺值/負值/日期重複、欄位完整性（date, open, high, low, close, volume）

**對應腳本**：
- `scripts/batch_update_daily_data.py` - 批量更新個股數據
- `scripts/batch_update_market_and_industry_index.py` - 更新大盤和產業指數
- `scripts/update_daily_stock_data.py` - 更新單日數據
- `ui_app/main.py` - UI 應用程式（整合所有更新功能）

**對應模組**：`data_module/data_loader.py`

---

## 3) 資料修復與清理（Raw → Processed）

**輸入**：第 2 步輸出的原始 CSV

**處理**：填補/修正/對齊——例如：
- 修復市場/產業指數缺口（`scripts/fix_market_index.py`、`scripts/fix_industry_index.py`）
- 合併相同日期多筆（`scripts/merge_daily_data.py`）
- 調整欄位命名與型別（日期轉 datetime、volume → int）

**輸出**：規範化的日線表（Processed）

- data/processed/daily_price/{stock_id}.csv（建議一檔一檔）
- data/processed/market_index/^TWII.csv 等

**位置**：data/processed/

**QC**：Schema 驗證（欄位完整、型別正確）、一檔一行唯一鍵（date, stock_id）唯一

**對應腳本**：
- `scripts/fix_market_index.py` - 修復市場指數
- `scripts/fix_industry_index.py` - 修復產業指數
- `scripts/merge_daily_data.py` - 合併每日數據

**對應模組**：`data_module/data_processor.py`

---

## 4) 技術指標計算（Processed → Technical Features）

**輸入**：data/processed/daily_price/*.csv 或 stock_data_whole.csv

**處理**：以統一介面計算 RSI/MACD/KD/布林等；命名規則如 rsi_14、macd_hist_12_26_9

**輸出**：特徵檔

- 單檔：D:/Min/Python/Project/FA_Data/technical_analysis/stocks/{stock_id}_indicators.csv
- 或集中：data/technical_analysis/{stock_id}.parquet

**位置**：data/technical_analysis/

**QC**：指標計算期數造成的前期 NaN 處理策略、欄位重名檢查、對齊（date）

**對應腳本**：
- `scripts/calculate_technical_indicators.py` - 批量計算技術指標
- `scripts/simple_technical_calc.py` - 簡化技術指標計算
- `scripts/date_specific_indicator_calc.py` - 特定日期指標計算

**對應模組**：
- `analysis_module/technical_analysis/technical_indicators.py`
- `analysis_module/technical_analysis/talib_compatibility.py`（TA-Lib 兼容性）

---

## 5) 特徵整併與快取（Feature Store）

**輸入**：第 4 步產出的多個指標檔 +（可選）市場/產業特徵

**處理**：依 [date, stock_id] 合併成單一特徵表；可轉 Parquet 以提升 IO

**輸出**：data/technical_analysis/features_{universe}_{yyyymmdd}.parquet

**位置**：data/technical_analysis/

**QC**：多檔合併鍵一致、欄位命名一致、Null 比例監控

**對應模組**：analysis_module/feature_pipeline.py（建議新增）

---

## 6) 訊號/策略產生（Signals & Strategy）

**輸入**：daily_price（收盤）+ features（指標）

**處理**：規則（Rule-based）或模型（Model-based）產生 signal ∈ {-1,0,1}，再轉 target_weight

**輸出**：output/results/signals/{strategy}/{run_id}/signals.parquet

**位置**：output/results/signals/

**QC**：未來資料洩漏檢查（lookahead=0）、交易日對齊、漲跌停邏輯（若需）

**對應模組**：
- `analysis_module/` - 技術分析
- `recommendation_module/` - 推薦引擎
- `ui_app/strategies.py` - 策略定義（UI 使用）

---

## 7) 回測（Backtest）

**輸入**：
- bars（價格）：從 `stock_data_whole.csv` 載入
- 技術指標：從 `technical_analysis/{stock_id}_indicators.csv` 載入
- signals/weights：策略信號
- 交易成本參數（fee bps、slippage）
- 策略參數（buy_score、sell_score、cooldown_days 等）
- 風險管理參數（停損停利、部位管理）

**處理**：
1. **數據載入**：
   - 載入價格數據和技術指標數據
   - 自動調整日期範圍（如果請求日期超出實際數據範圍）
   - 合併價格和技術指標數據
2. **信號生成**：
   - 使用策略執行器生成交易信號
   - 根據策略參數過濾信號
3. **交易模擬**：
   - BrokerSimulator 執行撮合
   - 支援多種執行價格模式（next_open、close）
   - 支援 ATR-based 停損停利
   - 支援部位管理（max_positions、position_sizing、allow_pyramid、allow_reentry）
4. **績效計算**：
   - PerformanceAnalyzer 計算績效指標
   - 生成權益曲線和交易列表

**輸出**：
- `BacktestReportDTO`：回測報告（包含績效指標、交易列表、權益曲線）
- 日期調整訊息（如果日期範圍被自動調整）

**位置**：`app_module/backtest_service.py`、`backtest_module/`

**QC**：
- 資產負債表恆等式
- 成交金額與費用計算
- 股數取整與現金為正
- 日期範圍驗證（自動調整超出範圍的日期）
- 技術指標數據完整性檢查

**對應腳本/模組**：
- `app_module/backtest_service.py` - 回測服務（✅ 已完成）
- `app_module/optimizer_service.py` - 參數最佳化服務（✅ 已完成）
- `backtest_module/strategy_tester.py` - 策略測試器
- `backtest_module/performance_analyzer.py` - 績效分析器
- `backtest_module/broker_simulator.py` - 交易模擬器
- `ui_qt/views/backtest_view.py` - Qt UI 回測視圖（✅ 已完成）

**最新優化（2025-12-22）**：
- ✅ 日期範圍自動調整：當請求日期超出實際數據範圍時，自動調整為可用範圍
- ✅ 參數最佳化性能優化：預載入數據一次，所有參數組合共用，多線程並行執行
- ✅ 技術指標數據載入修復：正確解析 YYYYMMDD 格式日期

---

## 8) UI 應用程式（新增）

**功能**：
- 數據更新（每日/大盤/產業）
- 策略選擇
- 回測（日期範圍選擇）

**位置**：`ui_app/main.py`

**使用方式**：
```bash
python ui_app/main.py
```


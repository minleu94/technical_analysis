# 推薦分析數據流程邏輯說明

## 📊 當前系統邏輯

### 1. 產業篩選階段

**數據來源**：`meta_data/companies.csv`

**流程**：
1. 用戶在 UI 中選擇產業（例如：「半導體業」）
2. `IndustryMapper.filter_stocks_by_industry()` 從 `companies.csv` 讀取股票與產業的對應關係
3. 返回屬於該產業的股票代號列表（例如：`['2330', '2303', ...]`）

**代碼位置**：
- `ui_app/industry_mapper.py` - `filter_stocks_by_industry()`
- `app_module/recommendation_service.py` - 第 104-109 行

---

### 2. 股票數據讀取階段

**數據來源**：`meta_data/stock_data_whole.csv`（**不是** `technical_analysis/*_indicators.csv`）

**流程**：
1. `RecommendationService.run_recommendation()` 讀取 `stock_data_whole.csv`
2. 這是一個**整合的 CSV 文件**，包含所有股票的價格數據（開盤、最高、最低、收盤、成交量等）
3. 根據產業篩選結果，只處理屬於該產業的股票

**代碼位置**：
- `app_module/recommendation_service.py` - 第 57-78 行

**重要**：系統**不是**從 `technical_analysis/*_indicators.csv` 讀取數據！

---

### 3. 技術指標計算階段

**計算方式**：**即時計算**（On-the-fly Calculation）

**流程**：
1. 對每支股票，從 `stock_data_whole.csv` 中提取該股票的歷史價格數據
2. 調用 `StrategyConfigurator.configure_technical_indicators()` 
3. 使用 `TechnicalAnalyzer` 即時計算技術指標（RSI、MACD、KD、ADX、MA 等）
4. 指標計算結果直接添加到 DataFrame 中，**不保存到文件**

**代碼位置**：
- `ui_app/strategy_configurator.py` - `configure_technical_indicators()`
- `analysis_module/technical_analysis/technical_analyzer.py` - `add_momentum_indicators()`, `add_trend_indicators()`, etc.

---

### 4. 技術指標文件的作用

**文件位置**：`technical_analysis/{stock_id}_indicators.csv`

**用途**：
- ✅ **回測服務**（`BacktestService`）會讀取這些預先計算好的技術指標文件
- ❌ **推薦分析服務**（`RecommendationService`）**不使用**這些文件

**原因**：
- 推薦分析需要根據用戶選擇的指標配置**動態計算**指標
- 預先計算的文件可能不包含用戶需要的所有指標組合
- 即時計算可以確保指標參數與用戶配置一致

**代碼位置**：
- `app_module/backtest_service.py` - `_load_indicator_data()` 第 328-377 行

---

## 🔄 完整數據流程圖

```
用戶選擇產業（例如：「半導體業」）
    ↓
IndustryMapper.filter_stocks_by_industry()
    ↓
從 companies.csv 讀取產業對應關係
    ↓
返回股票代號列表：['2330', '2303', ...]
    ↓
RecommendationService.run_recommendation()
    ↓
從 stock_data_whole.csv 讀取所有股票數據
    ↓
篩選出屬於該產業的股票數據
    ↓
對每支股票：
    ├─ 提取該股票的歷史價格數據
    ├─ StrategyConfigurator.generate_recommendations()
    │   ├─ configure_technical_indicators() ← 即時計算技術指標
    │   ├─ identify_patterns() ← 識別圖形模式
    │   ├─ calculate_total_score() ← 計算總分
    │   └─ screen_stocks() ← 應用篩選條件
    └─ 返回推薦結果
```

---

## ⚠️ 重要說明

### 為什麼推薦分析不使用預先計算的技術指標文件？

1. **靈活性**：用戶可以選擇不同的指標組合（例如：只選 RSI + MA，不選 MACD）
2. **參數一致性**：確保指標參數與用戶配置完全一致
3. **實時性**：使用最新的價格數據計算，不受預先計算文件的更新頻率限制

### 技術指標文件何時使用？

- **回測服務**：回測需要完整的歷史技術指標數據，使用預先計算的文件可以提高效率
- **批量分析**：如果需要對大量股票進行相同指標的分析，預先計算可以節省時間

---

## 📝 總結

**推薦分析的數據流程**：
1. ✅ 從 `companies.csv` 獲取產業對應關係
2. ✅ 從 `stock_data_whole.csv` 讀取價格數據
3. ✅ **即時計算**技術指標（不使用 `technical_analysis/*_indicators.csv`）
4. ✅ 計算分數並篩選

**技術指標文件的作用**：
- 主要用於**回測服務**
- 推薦分析服務**不使用**這些文件


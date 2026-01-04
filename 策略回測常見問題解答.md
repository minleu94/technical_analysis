# 策略回測常見問題解答

## 1. 選股清單存儲位置和格式

### 存儲位置
- **路徑**：`{output_dir}/backtest/watchlists/`
- **完整路徑示例**：`D:\Min\Python\Project\FA_Data\output\backtest\watchlists\`
- 其中 `output_dir` 由 `config.resolve_output_path('backtest/watchlists')` 決定

### 存儲格式
- **格式**：**JSON 檔案**
- **檔名格式**：`{watchlist_id}.json`
- **watchlist_id 格式**：`watchlist_YYYYMMDD_HHMMSS`（例如：`watchlist_20251216_165930`）

### JSON 檔案結構
```json
{
  "version": 1,
  "watchlist_id": "watchlist_20251216_165930",
  "name": "我的選股清單",
  "codes": ["2330", "2317", "2454"],
  "source": "manual",
  "filters": {},
  "description": "測試清單",
  "created_at": "2025-12-16T16:59:30.123456",
  "updated_at": "2025-12-16T16:59:30.123456"
}
```

### 相關代碼位置
- **服務類**：`app_module/universe_service.py` → `UniverseService`
- **儲存方法**：`UniverseService.save_watchlist()`
- **載入方法**：`UniverseService.load_watchlist()`

---

## 2. 數據來源：回測時讀取哪些數據？

### 數據載入流程

回測時會載入**兩種數據**並合併：

#### 2.1 價格數據（Price Data）
- **來源**：`stock_data_whole.csv`（meta_data 大檔案）
- **路徑**：由 `config.stock_data_file` 決定
- **欄位**：包含 `證券代號`、`日期`、`開盤`、`最高`、`最低`、`收盤`、`成交量` 等
- **載入方法**：`BacktestService._load_price_data()`

#### 2.2 技術指標數據（Technical Indicators）
- **來源**：`{technical_analysis_dir}/{stock_code}_indicators.csv`
- **路徑**：由 `config.get_technical_file(stock_code)` 決定
- **完整路徑示例**：`D:\Min\Python\Project\FA_Data\technical_analysis\2330_indicators.csv`
- **欄位**：包含各種技術指標（RSI、MACD、KD、MA 等）
- **載入方法**：`BacktestService._load_indicator_data()`

### 數據合併
- 兩種數據會根據**日期索引**進行 `left join` 合併
- 以價格數據為主，技術指標數據為輔
- 合併後的 DataFrame 用於策略信號生成和回測

### 相關代碼位置
- **主方法**：`app_module/backtest_service.py` → `BacktestService._load_stock_data()`
- **價格數據**：`BacktestService._load_price_data()`（第 204-295 行）
- **技術指標**：`BacktestService._load_indicator_data()`（第 297-346 行）

### 重要提示
- 如果技術指標檔案不存在，回測仍會繼續（只使用價格數據）
- 如果價格數據不存在或日期範圍內無數據，回測會失敗並返回空報告

---

## 3. 運行方式：選股清單 vs 單檔回測

### 判斷邏輯
系統會根據**股票代號數量**自動判斷模式：

```python
# 在 ui_qt/views/backtest_view.py 第 704 行
is_batch_mode = len(stock_codes) > 1
```

### 單檔模式（1 檔股票）
- **觸發條件**：選擇「單一股票」模式，或選股清單只有 1 檔
- **顯示位置**：**「結果」Tab**
- **顯示內容**：
  - 績效摘要（文字）
  - 交易明細（表格）
  - 圖表（4 張圖表）
- **保存方式**：需要**手動點擊「保存結果」按鈕**

### 批次模式（2 檔以上股票）
- **觸發條件**：選擇「選股清單」模式，且清單包含 2 檔以上股票
- **顯示位置**：**「批次結果」Tab**（自動切換）
- **顯示內容**：
  - 排行榜表格（所有股票的績效對比）
  - 整體統計（賺錢股票數、中位數等）
- **保存方式**：**自動保存**每個股票的結果（如果 `save_runs=True`）
- **互動功能**：雙擊排行榜中的行，可載入該股票的詳細結果到「結果」和「圖表」Tab

### 相關代碼位置
- **判斷邏輯**：`ui_qt/views/backtest_view.py` → `_execute_backtest()`（第 695-841 行）
- **批次回測**：`ui_qt/views/backtest_view.py` → `_execute_batch_backtest()`（第 2266-2309 行）
- **批次服務**：`app_module/batch_backtest_service.py` → `BatchBacktestService.run_batch_backtest()`

---

## 4. 保存結果功能的使用條件

### 啟用條件
「保存結果」按鈕會在以下**三個條件都滿足**時啟用：

1. ✅ **`run_repository` 已初始化**
   - 如果 `config` 存在，會在 `BacktestView.__init__()` 中自動創建
   - 如果為 `None`，按鈕會保持禁用

2. ✅ **`current_report` 不為空**
   - 在單檔回測完成後，`_on_backtest_finished()` 會設置 `self.current_report = report`
   - 如果回測失敗或沒有結果，此值為 `None`，按鈕會禁用

3. ✅ **`current_run_params` 不為空**
   - 在單檔回測開始時，`_execute_backtest()` 會設置此字典
   - 包含：股票代號、日期範圍、策略ID、參數、資金設定等
   - 批次回測**不會設置**此值，所以批次模式下按鈕會禁用

### 啟用時機
- **單檔回測完成後**：按鈕會自動啟用（如果上述條件都滿足）
- **批次回測完成後**：按鈕**不會啟用**（因為批次模式會自動保存）

### 保存內容
點擊「保存結果」後會保存：
- **SQLite 資料庫**：回測元數據（執行名稱、股票代號、策略、參數、績效指標等）
- **Parquet/CSV 檔案**：
  - Equity Curve（權益曲線）：`{run_id}_equity_curve.parquet`
  - Trade List（交易明細）：`{run_id}_trades.parquet`

### 相關代碼位置
- **啟用邏輯**：`ui_qt/views/backtest_view.py` → `_on_backtest_finished()`（第 879-892 行）
- **保存方法**：`ui_qt/views/backtest_view.py` → `_save_backtest_result()`（第 1416-1476 行）
- **儲存庫**：`app_module/backtest_repository.py` → `BacktestRunRepository.save_run()`

### 重要提示
- **批次回測不需要手動保存**：每個股票的結果會自動保存到資料庫
- **單檔回測需要手動保存**：回測完成後點擊「保存結果」按鈕
- 如果按鈕無法啟用，請檢查控制台輸出，會顯示具體缺少哪個條件

---

## 總結對照表

| 問題 | 答案 |
|------|------|
| **選股清單存哪裡？** | `{output_dir}/backtest/watchlists/` |
| **選股清單格式？** | JSON 檔案（`{watchlist_id}.json`） |
| **價格數據來源？** | `stock_data_whole.csv`（meta_data） |
| **技術指標來源？** | `{technical_analysis_dir}/{stock_code}_indicators.csv` |
| **選股清單會跑批次嗎？** | 是，如果清單有 2 檔以上股票 |
| **批次結果顯示在哪？** | 「批次結果」Tab |
| **單檔結果顯示在哪？** | 「結果」Tab |
| **保存結果何時可用？** | 單檔回測完成後，且三個條件都滿足 |
| **批次回測需要保存嗎？** | 不需要，會自動保存 |

---

## 5. 回測歷史管理

### 如何刪除回測結果？
1. 切換到「比較」Tab
2. 在「回測歷史」列表中選擇要刪除的結果（可多選）
3. 點擊「刪除選中」按鈕（紅色按鈕）
4. 確認刪除對話框
5. 刪除完成後列表會自動更新

### 刪除會刪除哪些內容？
- SQLite 資料庫中的記錄
- Parquet/CSV 檔案（equity curve 和 trade list）
- 刪除後無法恢復，請謹慎操作

### 可以批量刪除嗎？
- 可以，支援多選刪除
- 選擇多個結果後點擊「刪除選中」即可

---

**最後更新**：2025-12-16


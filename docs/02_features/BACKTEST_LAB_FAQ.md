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

## 5. 推薦組合回測為什麼可能沒有結果？

推薦組合回測會在歷史日期重新跑推薦邏輯，所以沒有結果通常不是 UI 壞掉，而是以下原因之一：

- 日期範圍太短，或資料在該區間沒有足夠交易日。
- 推薦條件太嚴格，例如漲幅、量增、RSI 或總分門檻讓候選股全部被過濾。
- 每期候選上限太低，剛好前段候選都不符合硬篩選。
- 正式資料量較大，仍在背景執行；第一次測試建議用最近 1 個月、候選 20。

已修復的已知問題：數字型 `YYYYMMDD` 日期曾可能被誤解析成 1970 年，導致 6 個月區間看起來完全沒有結果。後續 replay / backtest 日期處理應使用 `app_module/recommendation_portfolio_dates.py` 的解析工具。

---

## 6. 回測歷史管理

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

## 7. 為什麼回測結果交易次數為 0？（高價股與整股取整限制）

### 7.1 原因分析
台股撮合模擬器（`BrokerSimulator`）嚴格遵循台股交易規則，買入股數必須是 **1000 股（一張）的整數倍**。
如果買進一張高價股（如台積電 2330 價格 600~1000 元以上）所需的資金大於您設定的交易額度，經過 `/ 1000 * 1000` 的無情整除取整後，股數計算結果會直接變成 **0 股**，進而導致買入被拒絕。
* **全倉模式**：初始資金 100 萬，但買進 1000 股（1000元）需要 100 萬，再加上手續費與滑價後超出可用資金，取整後變成 0 股。
* **固定金額模式**：固定金額設定太小（例如預設 10 萬、50 萬），不足以購買高價股 1000 股。

### 7.2 解決方法
* **方案 A**：調大初始資金（例如從 100 萬調大到 500 萬或 1000 萬）。
* **方案 B**：如果使用固定金額 Sizing，請將固定金額調高至大於股票價格 * 1000 元的金額（如 120 萬），或直接改回「全倉」模式。
* **方案 C**：回測股價較低的股票（如股價低於 100 元的股票）進行功能驗證。

---

## 8. 為什麼 SOP 驗證失敗 (❌ FAIL)？如何處理？

### 8.1 樣本不足限制 (交易次數 < 10)
為確保策略具備統計學上的可靠性，避免過擬合或運氣成分，Phase 3.5 規範要求回測必須積累 **至少 10 次交易** 才能進行正式版策略晉升。
* **FAIL 的後果**：無法將此回測的策略參數一鍵晉升（Promote 按鈕將被自動禁用）。
* **保留功能**：您依然可以透過右鍵點擊下方的交易明細表，將個別交易「記錄到持倉管理（Portfolio）」中進行追蹤。

### 8.2 解決方法
* **降低進場門檻**：適度降低 `buy_score`（例如從 70 降到 60）或縮短連續確認天數 `buy_confirm_days`，以增加交易次數。
* **提高出場靈活度**：若賣出門檻 `sell_score` 設定太低（如 40.0），命中率極低（例如僅 1.6%），資金會長期被卡在持倉中。適度調高 `sell_score`（如至 50.0），可提高交易周轉率並增加交易次數。
* **拉長回測區間**：將回測日期從 1 年延伸至 2~3 年以上，涵蓋更多行情週期與波動。

---

## 9. 圖形模式是如何防禦未來函數 (Look-ahead bias) 的？

我們的打分引擎（`ScoringEngine`）與圖形分析器（`PatternAnalyzer`）具備極為嚴苛的多重 Look-ahead bias 防範機制：

1. **滾動歷史切片識別 (Strict Historic Slicing)**：
   打分引擎在每個歷史回測日 `t` 計算圖形分數時，**只**會將截至當日的子集 `df.iloc[:t+1]` 傳入 `PatternAnalyzer`。這使得圖形辨識算法在判斷波峰波谷、計算顯著性與 prominence 時，完全「看不見」未來的任何價格走勢，達成了物理隔離。
2. **突破確認觸發 (Breakthrough Confirmation)**：
   對於 W底、雙底、頭肩底、雙頂、頭肩頂等突破型圖形，引擎絕不會在谷底/山頂最低點（end_idx）直接計分（因為在極端點當天是無法知道這是否為谷底的，必須等到後市上漲）。引擎會沿著歷史進程尋找「突破頸線或中間峰值（`ref_val`）的突破確認日 `confirm_idx`」，並且**只在確認日剛好等於當日 (`confirm_idx == t`) 時，才在當天觸發該圖形的分數貢獻**，往後進行 20 天的線性衰減。
3. **安全延遲**：
   對於無明確突破參考點的圖形，若 `confirm_idx` 為空，則採用安全延遲 `end_idx + 2` 當作確認點，嚴防未卜先知的超前交易。

---

**最後更新**：2026-06-06


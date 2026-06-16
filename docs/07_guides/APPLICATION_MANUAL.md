# 台股投資決策系統完整操作手冊

> **最後更新**：2026-06-16
> **適用版本**：目前主要 PySide6 UI，入口為 `ui_qt/main.py`。
> **範圍**：本手冊涵蓋目前 8 個頂層工作區與跨工作區流程。開發中或 Roadmap 規劃功能不會描述成已可用。

## 1. 系統能做什麼

目前系統提供：

1. 更新每日股價、大盤、產業、券商分點與技術指標。
2. 用市場 Regime、強弱個股、強弱產業與 Smart Money 觀察市場。
3. 用 Profile 或進階參數產生推薦候選，查看 Why、Why Not 與分數拆解。
4. 建立候選池與可重用選股清單。
5. 執行單股、批次、固定組合、推薦回放與策略研究。
6. 保存研究結果、比較既有結果，並在符合目前 Gate 時升級策略版本。
7. 記錄交易、持倉、覆盤日誌、停損停利與籌碼監控。
8. 唯讀觀察 Runtime 狀態、治理健康與事件流。

目前不能保證：

- 推薦股票一定上漲或策略一定獲利。
- quantile 一定優於 fixed；2026-06-14 的 10 檔 OOS 實證未顯示 quantile 優於 fixed，因此仍為 opt-in。
- 推薦回放等同可成交的實盤績效。
- Daily Decision Desk 已接上主 UI「每日決策」頁籤（v1），可直接查看每日整合摘要；Market Breadth v1 已由 SQLite `daily_prices` 接線，Sector Rotation v1 已由 SQLite `industry_indices` 接線，Watchlist Trigger v1 已由 `WatchlistService` 與 SQLite `technical_indicators` 接線，Portfolio Alert v1 已由 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService` 接線，Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` 接線，Why Not / 風險提示 v1 已由 `DecisionDeskRiskPromptService` 對接，並可呈現 fundamental diagnostics 來源的基本面風險提示。缺口會以 MISSING / DEGRADED / ESTIMATED 顯示，並保留 warnings。
- Runtime Observatory 會自動修復問題或自動下單。
- 觀察清單等同實際投資組合。

## 2. 安裝與啟動

### 2.1 建立環境

在專案根目錄執行：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

若專案已經有可用的 `.venv`，不需要重新建立。

### 2.2 資料位置

預設正式資料根目錄：

```text
D:/Min/Python/Project/FA_Data
```

可在啟動前覆蓋：

```powershell
$env:DATA_ROOT = "D:\your\data\root"
$env:OUTPUT_ROOT = "D:\your\data\root\output"
```

SQLite 主資料庫位於：

```text
<DATA_ROOT>/sqlite/twstock.db
```

### 2.3 啟動主程式

推薦：

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

若目前 shell 已啟用正確虛擬環境：

```powershell
python ui_qt/main.py
```

`ui_app/main.py` 是 Legacy Tkinter UI，不是目前主要入口。

### 2.4 第一次啟動檢查

1. 開啟「數據更新」。
2. 點擊「檢查數據狀態」。
3. 確認每日股價、大盤、產業、券商分點與技術指標有日期與筆數。
4. 若顯示待更新，依需求執行快速或安全更新。
5. 完成後再進入市場觀察、推薦與回測。

## 3. 每日建議流程

### 快速研究流程

1. 數據更新：執行「快速更新（僅 SQLite）」。
2. 市場觀察：檢測 Regime，查看強弱與主力流向。
3. 推薦分析：選 Profile，執行推薦並閱讀 Why / Why Not。
4. 加入候選池：保存要研究的股票。
5. Research Lab：使用單股或批次回測驗證。
6. 保存結果；只有符合 Gate 的結果才升級策略版本。
7. 需要追蹤交易時記錄到持倉管理，後續寫覆盤日誌。

### 完整備份流程

定期或資料修復後使用「安全更新（完整 CSV + SQLite）」，保留 CSV 歷史備份與 SQLite 同步。

## 4. 數據更新

### 4.1 全部資料看板

狀態卡片包括：

- 每日股票數據
- 大盤指數數據
- 產業指數數據
- 券商分點數據
- 技術指標數據

狀態意義：

| 狀態 | 意義 |
|---|---|
| 正常 | 本地資料接近最新交易日且可讀。 |
| 待更新 | 資料庫可讀，但日期落後。 |
| 異常 | SQLite 或必要資料讀取失敗。 |
| 未檢查 | 本次啟動尚未執行狀態檢查。 |

### 4.2 快速更新與安全更新

| 模式 | 內容 | 適用情境 |
|---|---|---|
| 快速更新（僅 SQLite） | 下載近期缺失資料並直接同步 SQLite，略過大型 CSV 重寫。 | 日常更新。 |
| 安全更新（完整 CSV + SQLite） | 更新原始檔、重建或同步合併 CSV，再同步 SQLite。 | 定期備份、完整性檢查或修復後。 |

快速更新不代表資料品質較低，但不會同步重寫完整歷史 CSV 備案。

### 4.3 個別資料來源

左側可選：

- 每日股價
- 大盤指數
- 產業指數
- 券商分點
- 技術指標
- SQLite 資料檢視

每日股價、大盤、產業、券商分點操作：

1. 設定「結束日期」。
2. 設定「最近範圍」。
3. 先按「檢查此資料源狀態」。
4. 按「手動下載此資料源」只會下載原始資料。
5. 每日股價或券商分點下載後，還要執行對應的「合併」才會寫入分析資料庫。
6. 手動合併股價後，執行技術指標增量更新。

一鍵「快速更新」與「安全更新」的每日股價流程會同時處理 TWSE 與 TPEX：TWSE raw CSV 寫入 `DATA_ROOT/daily_price/YYYYMMDD.csv`，TPEX official daily close quotes 寫入 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`，SQLite 同步時一併 upsert 到 `daily_prices`。左側「每日股價」單一來源手動下載仍是 TWSE 操作；若要日常自動納入 TPEX，使用快速或安全更新。若 TPEX endpoint 發生 timeout 或暫時連線失敗，完成視窗會顯示警告，流程仍會繼續同步已成功取得的 TWSE 與其他資料。

券商分點同步會保存 `trade_type`，同一分點 / 股票 / 日期可同時有買超與賣超 rows。若舊 SQLite `broker_flows` 還是三欄主鍵，下一次同步券商分點時會先備份 DB，再把唯一鍵升級為 `(分點名稱, 證券代號, 日期, trade_type)`。

### 4.4 技術指標

- 「增量更新」：只處理新資料，日常首選。
- 「強制全量更新」：重算所有股票歷史資料，只在指標算法改動或資料損毀時使用。
- 股票代號留空代表處理全部；輸入例如 `2330` 代表只處理單一股票。

### 4.5 SQLite 資料檢視

1. **選擇與篩選**：選擇資料表，設定每頁限制筆數，填入股票代號、名稱、分點或日期篩選；單一日期預設為今天，日期區間預設為本月 1 日至今天，可用日曆選擇器點選調整，按「清除」可回到不套用日期條件。
2. **載入數據**：點擊「載入數據與結構」按鈕。
3. **資料分頁控制**：
   - 底部設有分頁控制列，包含「上一頁」、「下一頁」、「跳至第 X 頁碼（輸入頁碼並按跳頁按鈕）」、以及「當前頁數 / 總頁數」與「篩選後總記錄數」。
   - **防禦機制**：修改篩選條件並重新載入時，系統會自動重設為第一頁，並快取 schema 避免不必要的拉取。
   - **Stale 結果防護**：連續切換分頁或資料表時，舊有的非當前背景查詢結果會被自動忽略；執行中的背景查詢會安全保留到自然結束，防止 UI 資料錯亂或執行緒提前銷毀。
4. **欄位結構**：在「欄位結構」Tab 查看欄位 Schema 與型態描述。
5. **表頭排序**：在「資料預覽」點擊任一欄位表頭可切換升冪 / 降冪。排序由 SQLite 端以白名單欄位 `ORDER BY` 執行，並沿用目前篩選與分頁限制，避免 UI 端載入全表排序。
6. **漲跌欄位顯示**：`daily_prices` 若遇到舊 schema 的簡體 `涨跌`，畫面會顯示為繁體 `漲跌`；`漲跌價差` 會依 `漲跌(+/-)` 或 `漲跌` 方向顯示正負號，以利顏色與排序判讀。
7. **重複顯示欄名防護**：若 raw schema 與 alias 造成相同顯示欄名，表格仍以欄位位置取值，不應出現 `PandasTableModel.data` 的 Series ambiguity 錯誤。

此工具是受控唯讀檢視器，不應用來修改或刪除資料。

### 4.6 匯出 CSV 備案

個別資料頁可選：

- 最近範圍
- 全部歷史

輸出使用 UTF-8 with BOM，方便用 Excel 開啟。這是離線備份與人工研究功能，不影響系統日常運作。

### 4.7 高風險操作

「強制重新合併」與「強制全量更新」會長時間處理大量歷史資料。只有在資料損毀、schema 修復或算法變更後使用，不要作為日常更新方式。

### 4.8 Month 5 月營收候選資料抓取

月營收候選資料抓取目前只供 Month 5 available_date / 公告日 mapping 建立前的來源驗證與 raw evidence 保存使用，不會寫入正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`，也不會寫入 `fundamental_monthly_revenues`。

今晚建議先跑兩個檔案：

```powershell
.\.venv\Scripts\python.exe scripts\fetch_mops_monthly_revenue_snapshot.py --start-period 2014-04 --end-period 2026-05 --markets twse,tpex --output-dir D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots --fetch-date 2026-06-16 --sleep-seconds 0.5
.\.venv\Scripts\python.exe scripts\fetch_finmind_monthly_revenue_create_time.py --start-date 2014-04-01 --end-date 2026-05-31 --raw-dir D:\Min\Python\Project\FA_Data\financial_data --output-dir D:\Min\Python\Project\FA_Data\output\monthly_revenue_finmind_create_time --max-requests-per-hour 540 --resume --fetch-date 2026-06-16
```

第一個命令會保存 MOPS raw HTML 與完整市場月營收 snapshot CSV；它只代表營收內容快照，不得用 period 或查詢日推定 `available_date`。第二個命令會使用已加密保存於本機的 FinMind token 逐檔抓取 `TaiwanStockMonthRevenue.create_time`，輸出 create_time 分組檔；`create_time` 只代表 FinMind 觀測 / 入庫日期候選，不等同官方 MOPS 公告日。若 FinMind 流程中斷，用同一個 `--output-dir` 加 `--resume` 重跑即可接續。

毛利率不是月營收資料。MOPS `t163sb06` 是季度財務比率 / 毛利率彙總表，查詢維度是年度與季別；後續若要納入，應走季度財報 / 財務比率 pipeline，另建公告日與 `available_date` gate，不要混進今晚的月營收 snapshot 或 FinMind create_time 流程。

## 5. 市場觀察

### 5.1 大盤指數

1. 點擊「檢測市場狀態」。
2. 查看 Regime、信心度與判斷摘要。
3. 展開技術細節時，可查看價格與均線、趨勢、評分、其他指標與判斷條件。
4. 將策略建議作為 Profile 選擇參考，不要視為買賣訊號。

Regime 是對當下市場環境的分類，不是未來預測。

### 5.2 強勢與弱勢個股

1. 選擇「本日」或「本周」。
2. 第一次進入可按「載入數據」。
3. 需要重新計算時按「刷新」。
4. 選取股票後按「加入觀察清單」。

強勢排名不等於建議追價；弱勢排名也不等於做空或立即賣出。

### 5.3 強勢與弱勢產業

使用本日或本周排名判斷產業相對強弱，再回到個股頁或推薦頁研究產業內股票。

### 5.4 主力流向

「個股資金流向」操作：

1. 選擇日線、週線或月線。
2. 選擇直方、折線或面積趨勢圖。
3. 點擊「開始掃描」。
4. 點選主表股票，右側顯示分數、集中度、訊號原因與分點明細。
5. 表格標頭可排序。
6. 有 Watchlist service 時，可按「+ 觀察清單」。

「分點進出追蹤」操作：

1. 選擇券商分點。
2. 查看該分點近期操作股票、張數、標籤與趨勢。

資料品質：

| 品質 | 解讀 |
|---|---|
| observed | 原資料直接觀測到張數或金額。 |
| estimated | 由可用價格與金額估算，信心較低。 |
| unavailable | 無足夠資料，不應硬補成 0。 |

單一分點買超不等於真實主力意圖，應優先觀察多分點共振、價格行為與資料覆蓋率。

## 6. 推薦分析

### 6.1 新手模式

1. 查看系統偵測的市場狀態與 Profile 建議。
2. 可按「一鍵套用建議 Profile」。
3. 或自行選擇暴衝、穩健、長期等 Profile。
4. 點擊「執行推薦分析」。

### 6.2 進階模式

可設定：

- 技術指標
- 圖形模式
- 最小漲幅
- 最小成交量比率
- 產業
- 排名門檻

參數治理限制：

- 新版配置啟用的技術指標必須提供完整參數；字串代替整數、未知欄位、越界值或衝突組合會直接顯示失敗，不會靜默使用猜測值。
- 關閉的子指標不會計算，也不會產生空欄位。
- 評分權重使用 `pattern`、`technical`、`volume` 三項整數基點，總和必須為 `10000 bp`。
- 核心總分使用 Decimal 並固定至 `0.01` 分；設定錯誤屬治理例外，不會被轉成空結果。

### 6.3 固定門檻與百分位排名

| 模式 | 行為 |
|---|---|
| 固定門檻 | 使用既有絕對分數與篩選邏輯。 |
| 百分位排名 | 在當日 eligible universe 中計算橫斷面排名。 |

百分位模式參數：

- 最低百分位：例如 80% 代表保留當日母體中較高排名區間。
- 最小母體數：避免用太少股票產生不穩定百分位。
- 排名方法：目前為 Nearest Rank。

若出現 eligible universe too small：

1. 放寬前置篩選。
2. 增加最大掃描股票數。
3. 降低最小母體數。
4. 不要把錯誤改成自動退回 fixed；兩種模式應保持可辨識。

quantile 目前是 opt-in，不能宣稱比 fixed 更準。

### 6.4 結果判讀

- Why：為何入選。
- Why Not：哪些條件不足或限制排名。
- Explain：技術、圖形、量能等子分數與風險點。
- 百分位與母體：只在 quantile 模式有意義。

### 6.5 結果後續操作

- 「保存結果」：保存推薦配置、Profile、Regime 與推薦名單。
- 「加入候選池」：把選取股票加入 Watchlist。
- 「送 Research Lab 批次回測」：用推薦名單建立批次研究輸入。
- 「送 Research Lab 推薦回放」：使用推薦配置進行歷史回放。
- 表格右鍵「記錄到持倉管理」：建立帶推薦來源 metadata 的交易。
- 「匯出 Excel」：建立包含元數據、今日推薦配置、Regime 狀態以及推薦股票名單的 Excel 報告，並在背景執行原子寫入。

## 7. 觀察清單與選股清單

### 7.1 候選池操作

- 「新增股票」：手動輸入股票。
- 「移除選中」：刪除選取列。
- 「清空候選池」：刪除全部候選，無法復原。
- 「刷新」：重新載入資料。

候選池保存來源、加入時間與備註，用於研究，不是實際持倉。

### 7.2 選股清單

- 「保存為選股清單」：把目前候選池保存為可重用 Universe。
- 「載入到候選池」：把既有 Universe 載入目前候選池。
- 「新增 / 編輯 / 刪除」：管理 Universe 名稱、說明與股票內容。

目前「送 Research Lab 批次回測」按鈕仍停用。實際流程是：

1. 保存為選股清單。
2. 開啟「策略回測」。
3. 選擇「批次股票回測」。
4. 從選股清單下拉載入。

## 8. 每日決策（Daily Decision Desk）

### 8.1 進入與刷新

Daily Decision Desk 採用 Midnight Analyst 深色介面：深色背景、section header 狀態 badge、緊湊摘要卡片與分行代碼清單。強勢、弱勢與低流動性代碼每類預設顯示前 8 檔，其餘以剩餘檔數摘要；完整資料仍由 service snapshot 保留，不因 UI 摘要而改變計算結果。

1. 進入主視窗頂層 tab「每日決策」。
2. 點選「刷新」可重建 Snapshot。
3. 若初始化或刷新失敗，畫面會保留可閱讀狀態並顯示 fallback 提示，不會中斷整體 App。

### 8.2 結果解讀

每日決策摘要會顯示：

- `as_of_date`：資料對應日期
- `quality`：整體品質（`OBSERVED` / `ESTIMATED` / `DEGRADED` / `MISSING`）
- `warnings`：所有 section 的缺口與降級原因彙總
- 各區塊 section：如 Market Regime、Market Breadth、Sector Rotation、Watchlist Trigger、Portfolio Alert

Market Breadth v1 會從 SQLite `daily_prices` 唯讀推導：

- 多方 / 空方 / 持平家數
- 廣度比率 BP
- 20 / 60 日新高新低 metadata
- 漲跌停近似統計與成交量擴散 metadata

若指定日期不是交易日或該日尚無資料，本頁會使用最近可用交易日並在 warnings 顯示 fallback 日期，不會把缺資料補成當日觀測值。

Sector Rotation v1 會從 SQLite `industry_indices` 唯讀推導：

- 領先 / 落後產業
- 5 / 20 日變化
- 輪動強度 BP
- 產業排名 metadata

若指定日期不是交易日或該日尚無產業指數資料，本頁會使用最近可用交易日並在 warnings 顯示 fallback 日期。若某產業歷史不足 21 筆，該產業會被降級提示，不會強制補值。

Watchlist Trigger v1 會從 `WatchlistService` 與 SQLite `technical_indicators` 唯讀推導：

- 個股強度評分 `score_bp`（RSI * 100，值域 0~10000）
- 個股風險警示 `risk_alert`（偏離 RSI > 80 / < 20 或收盤價低於布林通道下軌 `Close < lowerband`）
- 新進候選、強度提升、強度下降等觸發統計

若指定日期不是交易日或該日無指標資料，本頁會採用最近可用交易日，並在 `warnings` 顯示 fallback 日期，且 quality 降級為 `DEGRADED`（在 warnings 中標註 `watchlist_trigger_as_of_fallback:<date>`）。

Portfolio Alert v1 會整合持倉條件監控與 `PortfolioChipService` 籌碼摘要。當持倉條件失效、警告，或個股籌碼風險為 bearish / extreme / risk 時，會列入持倉警示；若籌碼股數資料缺失、估算或部分事件不可用，會在 warnings 顯示 `portfolio_alerts_chip_*`，並將 quality 降級為 `ESTIMATED` 或 `DEGRADED`。Portfolio Alert 的來源歸因會顯示每檔警示持倉的來源標籤、condition 狀態、chip risk level 與原因 token。這用於解釋警示來源，不代表自動賣出或調倉。

Relative Strength / Liquidity Ranking v1 會從 SQLite `daily_prices` 唯讀推導 5 / 20 日相對強度與平均成交金額，顯示強勢代碼、弱勢代碼與低流動性代碼。
- **畫面呈現**：每日決策頁會把強勢、弱勢與低流動性代碼以單一 compact list 分行顯示，單類別只顯示前 8 檔並標示剩餘檔數，避免大量股票代碼撐寬主視窗；各 section 的品質狀態以 header badge 顯示。
- **流動性過濾**：當 20 日平均成交金額低於預設的 20,000,000 元時，該股將被列為低流動性代碼。
- **強弱勢判定**：股票的 20 日相對強度必須至少有 21 個有效交易觀測值（當日 + 前 20 日歷史）。若因歷史資料不足（如新上市股票或資料缺失）無法滿足 21 天，該股票將不參與強度排序，直接跳過；若整個模組無可用觀測歷史，quality 將降級為 `DEGRADED` 且在 warnings 中標註 `relative_strength_liquidity_insufficient_history`。

Why Not / 風險提示 v1 會從既有已計算的區塊 DTO 中，推導出可行動的風險提示（prompts），而不在 UI 或此服務內重新計算複雜邏輯：
- **市場風險提示（market_context）**：大盤為 risk-off 或 bear 等狀態時提示「市場風險偏高」，建議降低對個股強勢的解讀信心。
- **流動性提示（liquidity）**：個股被 Relative Strength / Liquidity 判定為低流動性時提示「低流動性」，提醒檢查部位大小。
- **相對弱勢提示（weakness）**：個股在 20 日相對弱勢清單時提示「相對弱勢」，提醒確認反轉條件再行考慮。
- **觀察清單風險觸發提示（watchlist_risk）**：個股觸發 Watchlist 的 risk_alert 時提示「觀察清單風險觸發」。
- **持倉警示提示（portfolio_alert）**：個股位於 Portfolio Alert 警示名單時提示「持倉警示」。
- **基本面診斷提示（fundamental_diagnostic）**：當 Research metadata 或 application service 提供 abnormal fundamental diagnostics 時，會以 `source=fundamental` 顯示營收與獲利背離、一次性收益風險或資料品質缺口。這只是研究風險提示，不代表財報已被重算、推薦分數已被扣分或系統產生買賣建議。
- **品質警告規則**：當來源區塊品質為非 OBSERVED 時，會產生 `risk_prompt_source_quality:...` 警告，並將 Why Not 區塊之 quality 降級為 `DEGRADED`。

#### quality 與 warnings 規則

- `OBSERVED`：當前節點資料完整且已驗證可用。
- `ESTIMATED`：有可補值但非直接觀測值。
- `DEGRADED`：有資料但需降級顯示，需注意風險。
- `MISSING`：節點缺資料，僅保留警示，不能視為可交易依據。

#### 限制與排錯

- 本頁是每日決策摘要，不是自動交易或下單介面。
- Market Breadth v1、Sector Rotation v1、Relative Strength / Liquidity Ranking v1、Watchlist Trigger v1 與 Portfolio Alert v1 已接線，但仍可能因 SQLite 缺資料、資料日期 fallback、歷史不足或籌碼資料缺失而降級顯示 `DEGRADED` 或 `ESTIMATED`。
- Portfolio Alert 僅為持倉摘要警示，未直接改變持倉。
- 基本面診斷提示僅使用已治理 metadata；不會直接讀 raw financial CSV、不會改寫財報、不會輸出目標價、合理價、上漲空間或交易建議。

#### 月營收 availability mapping 維護

月營收 raw CSV 不能自行推定公告日或可得日。若要建立候選 mapping，可先使用 TWSE/TPEX historical dry-run builder：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2020-01 --end-period 2026-05 --markets twse,tpex
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2020-01 --end-period 2026-05 --markets twse,tpex --stock-code 2330 --output <candidate-csv>
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2024-04 --end-period 2024-04 --markets twse --mops-html-dir <mops-html-dir> --output <candidate-csv>
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2024-04 --end-period 2024-04 --markets twse --stock-code 2330 --mops-static
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2020-01 --end-period 2024-04 --markets twse,tpex --pit-csv <authorized-pit-export.csv> --pit-source-version <export-version> --output <candidate-csv>
```

未提供 `--output` 時只輸出 summary，不寫檔；指定 `--output` 時只寫候選 CSV，不會改寫正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`。候選列使用官方 `出表日期` 作 `announced_date`，並以公告日隔天作保守 `available_date`，避免同日盤中可得性假設。`--mops-html-dir` 僅讀人工保存的官方 MOPS HTML，檔名規則為 `twse_YYYY-MM.html` / `tpex_YYYY-MM.html`；HTML 必須含頁面層級 `出表日期` 與 `公司代號` 表格，否則只輸出 diagnostics，不用 raw CSV 日期補值。`--mops-static` 會走新版 MOPS `/mops/api/redirectToOld` 取得 `mopsov.twse.com.tw/nas/t21/...` historical static report，只作來源驗證；目前該 report 的 `出表日期` 是查詢當日重新出表日，不是歷史原始公告日，因此會被 `as_of_date + 45 days` 合理揭露窗口擋下。

若取得授權 point-in-time 月營收公告日匯出檔，可使用 `--pit-csv`。匯出檔必須至少有股票代號、資料年月與公告日欄位；支援 `stock_code` / `公司代號`、`period` / `資料年月`、`announced_date` / `公告日` / `出表日期` 等欄名。`--pit-source-version` 必須非空，並會原樣寫入候選 mapping 的 `source_version`。PIT 匯入來源目前治理為 `tej.monthly_revenue_announcement_pit`；此路徑仍只產生 candidate CSV，不會寫正式 mapping，也不會回填 SQLite。

舊版 TWSE OpenAPI 候選產生器仍可用於單一最新月來源測試：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability.py --fetch-date 2026-06-16
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability.py --source-json <twse-json> --output <candidate-csv> --fetch-date 2026-06-16
```

寫入正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 前，必須先以 `scripts\validate_monthly_revenue_availability.py --path <candidate-csv>` 驗證，並取得人工確認；此工具不會自動改寫正式 mapping、raw CSV 或 SQLite。

截至 2026-06-16，TWSE 上市 endpoint `/opendata/t187ap05_L` 與 TPEX 上櫃 endpoint `/openapi/v1/mopsfin_t187ap05_O` 均可提供最新月 `出表日期`；樣本為 `2330` / `9935` 的 `2026-05` 公告日 `2026-06-15`，以及 `3207` 的 `2026-05` 公告日 `2026-06-16`。這些 OpenAPI 目前未提供歷史 period query；MOPS historical static report 可透過新版 API 取得，且可看到 `113/04` 的 `2330`、`9935`、`3207` rows，但其 `出表日期` 是查詢當日，不能視為歷史公告日。正式 raw 月營收目前只到 `2024-04`，與最新月來源無交集，因此 `2020-01..2026-05` dry-run 產生 0 candidate rows。歷史公告日仍需可追溯的原始公告日批次來源或受控人工 mapping。

#### 月營收 normalized backfill

正式 DB 已有 `fundamental_monthly_revenues` schema，但回填必須先通過 availability mapping。可先執行 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --dry-run
```

dry-run 只輸出 plan，不寫入 SQLite。若正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 不存在，結果會是 `ready_for_apply=false` 並輸出 `fundamental_availability.mapping_file_missing`，不會讀 raw 月營收 rows，也不會產生 normalized records。

正式回填必須在 mapping 通過驗證後，由人工確認再執行：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --apply --confirm apply-monthly-revenue-backfill
```

正式 apply 會先備份 DB；缺少 `--confirm apply-monthly-revenue-backfill` 時會拒絕執行。回填工具只寫入 `fundamental_monthly_revenues`，不會修改 raw CSV、availability mapping 或既有核心表。2026-06-16 正式路徑 dry-run 因 mapping 缺檔 fail-closed，尚未寫入任何 fundamental records。

#### 公司清單 / 產業 mapping 更新

`meta_data/companies.csv` 可用官方 TWSE/TPEX 公司基本資料更新。預設 dry-run 不寫檔：

```powershell
.\.venv\Scripts\python.exe scripts\update_company_registry.py --dry-run
```

正式寫入必須人工確認：

```powershell
.\.venv\Scripts\python.exe scripts\update_company_registry.py --apply --confirm apply-company-registry
```

正式 apply 會先備份既有 `companies.csv`，只更新公司 registry CSV，不修改 SQLite、daily price 或 raw financial CSV。2026-06-16 已以官方 TWSE/TPEX 來源正式更新：輸出 2,326 筆、0 diagnostics、無重複 `stock_id`，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/companies_company_registry_20260616_031111.csv`。抽查 `3207` 耀勝為 `電子零組件業 / tpex`，`9935` 慶豐富為 `居家生活 / twse`。

注意：`companies.csv` 是公司與產業 registry，不代表 `daily_prices` 已具備該股票行情。TPEX daily price 已納入日常市場日價管線；若歷史 TPEX 股票仍缺舊日價，需由市場日價資料層的 dry-run / 人工確認回補，不應用 company registry 或 fundamental layer 假造價格列。

#### TPEX daily price 日常更新與歷史 dry-run

日常快速 / 安全更新會在 TWSE 每日股價後抓取 TPEX official daily close quotes，保存到 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`，並在 SQLite 同步時寫入 `DATA_ROOT/sqlite/twstock.db` 的 `daily_prices`。這是市場資料層更新，不修改 `companies.csv`、raw financial CSV、fundamental tables、技術指標算法或推薦分數。

若上櫃股票存在於 `companies.csv` 但缺歷史 `daily_prices`，先使用歷史 dry-run plan：

```powershell
.\.venv\Scripts\python.exe scripts\plan_tpex_daily_price_history_backfill.py --start-date 2026-01-01 --end-date 2026-06-16
```

dry-run plan 只讀官方來源或指定 source JSON、SQLite 既有資料，輸出日期範圍、每日來源筆數、已存在筆數、新增候選筆數、失敗日期與估計耗時，不寫正式 DB。正式歷史回補需另行人工確認。

單日受控補寫工具仍保留給已確認日期使用。預設先 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --dry-run
```

dry-run 只讀官方 TPEX daily close quotes 與 SQLite，顯示 `ready_for_apply`、`insert_count`、`existing_count` 與 diagnostics，不寫入資料。正式寫入必須先取得人工確認，再執行：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --apply --confirm apply-tpex-daily-price-backfill
```

正式 apply 會先備份 DB；缺少 `--confirm apply-tpex-daily-price-backfill` 時會拒絕執行。此 workflow 只寫入 `daily_prices`，不會修改 `companies.csv`、raw financial CSV、fundamental tables、技術指標或推薦分數。批次模式只處理指定交易日、四碼普通股且收盤價為正數的 rows；債券、權證、ETF 或停牌無價 rows 會被跳過。

2026-06-16 已對正式 DB 執行一次：dry-run 顯示可新增 877 筆、0 diagnostics；正式 apply 後備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_tpex_daily_price_backfill_20260616_034627.db`。驗證結果：`daily_prices` 的 `20260616` 有 877 筆四碼上櫃日價、0 duplicate `(證券代號, 日期)` keys；`3207` 耀勝已有 `20260616` 日價，`9935` 慶豐富既有日價仍保留。

#### 估值 metrics backfill

正式 DB 已有 `fundamental_valuation_metrics` schema。P/E v1 可由 SQLite `daily_prices.本益比` 與 `meta_data/companies.csv` 產業 mapping 建立受治理 valuation records，並計算同產業整數基點分位。預設只執行 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --dry-run
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --as-of-date 2026-06-15 --dry-run
```

未指定 `--as-of-date` 時，工具會選擇 `daily_prices` 中最新有 P/E 的交易日。dry-run 只輸出 plan，不寫入 SQLite；P/E 非正數、無法解析或缺產業 mapping 的 rows 會列為 diagnostics 並跳過。同產業只有單一樣本時會保留 record，但 `industry_percentile_bp` 為空且 quality 降級，後續估值 adapter 只會輸出 diagnostics。

正式寫入必須先取得人工確認，再執行：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --apply --confirm apply-valuation-metrics-backfill
```

正式 apply 會先備份 DB；缺少 `--confirm apply-valuation-metrics-backfill` 時會拒絕執行。此 workflow 只寫入 `fundamental_valuation_metrics`，不會修改 raw CSV、`companies.csv` 或既有核心表。2026-06-16 更新官方 `companies.csv` 後再次執行正式 apply：最新 P/E 日為 `2026-06-15`，來源 1,090 筆，831 筆可正規化，259 筆 diagnostics；正式表 count 為 831，0 duplicate primary keys，quality 全為 `observed`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_valuation_metrics_backfill_20260616_031146.db`。

## 9. Research Lab / 策略回測

### 9.1 五種實驗模式

| 模式 | 主要用途 |
|---|---|
| 單股回測 | 驗證一檔股票套用策略後的交易表現。 |
| 批次股票回測 | 比較同一策略在多檔候選股票上的差異。 |
| 固定組合回測 | 研究固定股票清單的組合表現；目前 Registry 保存採 per-stock run，並以固定組合 metadata 區分來源。 |
| 推薦系統回放 | 回放推薦配置與名單。 |
| 策略研究 | 比較策略模板、參數、最佳化與驗證結果。 |

### 9.2 基本設定

1. 選擇策略來源或載入 Preset。
2. 選擇單股或選股清單。
3. 設定開始與結束日期。
4. 設定初始資金、手續費與滑價。
5. 執行價格建議使用 `next_open`；`close` 是同根 K 收盤成交假設，必須清楚揭露。

### 9.3 停損、停利與部位

- 百分比模式：使用固定停損停利百分比。
- ATR 倍數模式：依市場波動調整距離。
- 全倉：可用資金集中於目前部位。
- 固定金額：每次使用指定金額。
- 風險百分比：依風險比例與 ATR 決定部位。

部位管理包括最大持倉數、等權/分數加權/波動調整、加碼、重新進場與冷卻期。

台股整股模擬以 1000 股為單位。高價股若資金不足一張，可能產生 0 交易。

### 9.4 市場限制

- 漲跌停限制
- 成交量限制
- 最大參與率

如果訊號很多但交易為 0，先檢查資金、整股限制、成交量與參與率，不要直接判定策略沒有訊號。

### 9.5 fixed 與 quantile

- fixed 使用固定買賣分數。
- quantile 使用 T-1 以前的 expanding 歷史分布，暖機需要 60 個有效觀測值。
- 暖機完成前不應產生 quantile 交易訊號。
- 比較兩模式時必須使用相同資料、成本、成交假設與期間。

### 9.6 參數最佳化

1. 選擇目標：Sharpe、年化報酬或 CAGR-MDD。
2. 對要掃描的參數設定固定值或範圍。
3. 執行參數掃描。
4. 在「最佳化 / 驗證」查看結果。
5. 選取結果後按「套用選中參數」。

最佳化結果是 In-Sample 候選，不能直接視為可靠策略。

### 9.7 Walk-forward

- Train-Test Split：單次訓練/測試切分。
- Walk-forward：以訓練月數、測試月數與步進月份滾動驗證。

至少檢查：

- OOS 報酬是否穩定
- 最大回撤是否惡化
- 交易次數是否足夠
- 不同窗口是否只靠單一期間獲利
- fixed / quantile 是否用完全相同條件

本專案 2026-06-14 基準實證使用 10 檔股票、每檔 8 個 OOS fold；fixed 57 筆、quantile 79 筆交易均通過 20 筆最低樣本 Gate，Regime coverage 為 100%。結果未顯示 quantile 的平均 OOS Sharpe 優於 fixed，詳見 `docs/06_qa/WALK_FORWARD_COMPARISON_REPORT.md`。

### 9.8 執行、取消、保存與升級

- 「執行實驗」：開始目前模式。
- 「取消執行」：合作式取消；已開始的單檔工作可能安全收尾。
- 「保存結果」：將單股回測、批次回測單檔結果、固定組合 per-stock 結果或推薦回放結果保存到 Research Run Registry；系統會保存參數快照、資料 fingerprint、成本、成交假設、績效摘要、factor snapshot / contribution metadata、equity curve 與 trades。單股、批次與固定組合 per-stock 結果的 factor metadata 來自該次回測已產生的 score/factor records，不會在保存時重算分數或重新抓取資料。
- 「升級為策略版本」：新版 Gate 必須讀取 Research Run Registry，不得只靠單次 summary；run 需 committed / valid、未封存、未升級、具備可還原參數合約版本，且通過最低 validation gate。

目前最低樣本 Gate 為 10 筆交易。通過最低 Gate 不代表已完成充分 OOS 驗證。

保存安全限制：

- 只有目前成功完成且尚未被新一輪執行取代的結果可以保存。
- 開始新一輪回測或推薦回放後，舊 pending result 會被視為 stale，不可再保存。
- Registry 寫入採 SQLite metadata + Parquet 明細；若 hash 不符或檔案不完整，載入時會以完整性錯誤處理，不會靜默讀取部分結果。
- Legacy 單股回測 / 推薦組合保存庫仍可用於歷史資料與 backfill；新的「保存結果」入口以 Research Run Registry 為準。

### 9.9 結果分頁

- 實驗摘要：績效摘要與交易明細。
- 圖表：權益、回撤、報酬分布、持有天數。
- 最佳化 / 驗證：參數掃描與 Walk-forward。
- 歷史與比較：載入、刪除與比較 legacy 已保存結果。
- Registry 比較：列出 Research Run Registry 中的 run，可依 run type、strategy、tag 篩選並分頁瀏覽；選取 2 至 5 個 run 後顯示 comparability badge、參數差異、normalized equity、metrics、Regime 與已保存 benchmark 結果。
- 批次結果：排行榜與整體統計，雙擊股票可載入明細。
- 推薦回放：組合價值、回撤、期間持倉、股票貢獻與交易。

**報告匯出按鈕**：
- 在「實驗摘要」設有「匯出 Excel 報告」按鈕（僅在單股回測成功後啟用）。
- 在「批次結果」設有「匯出批次 Excel」按鈕（僅在批次回測成功後啟用）。
- 在「推薦回放」設有「匯出回放 Excel」按鈕（僅在推薦組合回測成功後啟用）。
- **安全設計**：所有匯出皆在背景線程（`TaskWorker`）執行，防止 UI 卡死，並採用臨時檔寫入後 `os.replace` 原子替換；替換失敗時既有報告保持不變。報告使用執行結果與參數快照，不重跑策略或摘要績效；equity curve 可接受 `日期`、`date` 或日期 index。若元數據缺失，會在「資料完整性」警示中標示 `N/A`，不以目前 UI 值或預設常數代填。

Registry 比較只使用已保存的 metadata、equity curve 與 benchmark_results，不重新抓取目前資料。資料 fingerprint、execution 或 sizing 不同時會標示為 Incompatible；期間、Universe 或成本不同時標示為 Caution，不應直接做優劣排名。Registry-based Promote 會先做 Registry Gate，通過後才建立策略版本。

固定組合目前的 Registry 保存粒度是每檔股票的 per-stock run，metadata 會標記為 `fixed_basket_stock` 以保留固定組合來源，並沿用該檔回測產生的 factor records 生成 `factor_snapshot` / `factor_contributions`。完整固定組合層級的現金帳、再平衡、未成交、Liquidity / Gap 風險揭露仍未建成，不應把 per-stock 保存結果解讀為完整可成交的固定組合績效；Month 3 v1 的完整 portfolio credibility 揭露集中在推薦組合回放。

### 9.10 推薦回放

建議從推薦頁按「送 Research Lab 推薦回放」載入配置。

可設定：

- 每次推薦檔數
- 每期候選上限
- 持有天數
- 每週重播或只跑一次
- 等權或分數加權

執行後可保存到 Research Run Registry。歷史載入、刪除與 legacy Promote 能力仍保留在舊 repository 邊界；新版 Cross-run Comparison 與 Registry-based Promote Gate 以 Registry run 為準。結果 details 會包含 `portfolio_credibility`、`unfilled_orders`、`cash_ledger`、`weight_exposure` 與 `gap_risk`：若推薦股票在回放視窗內沒有可用價格列，會以 `missing_price_rows` 記錄為未成交，而不是靜默跳過；若呼叫端提供 `max_participation_rate`，系統會用進場日成交股數與收盤價估算可參與金額，配置金額超過時以 `liquidity_limited` 記錄為未成交。回放現在會在建立 holding 前檢查可用現金，現金不足時以 `cash_limited` 記錄為未成交；`cash_ledger` 由這個現金 gate 流程產生買進、賣出與 `ending_cash`。若呼叫端提供 fee / tax / slippage bps，成本會套用到買賣現金流、ledger breakdown 與 `total_transaction_cost`；未提供時維持無成本回放。若呼叫端提供 `lot_size`，配置金額會依進場價向下取整為可成交整股股數，買不起最小交易單位時以 `lot_size_limited` 記錄為未成交。期間持倉的 `allocation_weight` 代表推薦配置的目標權重，`actual_allocation_weight` 代表整股 sizing 與 cash gate 後的實際可成交權重；`weight_exposure` 會依每個再平衡日彙總目標權重、實際權重、未成交權重與殘餘現金權重。若歷史資料含「開盤價」，`gap_risk.records` 會列出每筆 holding 的 `entry_close_price`、下一個可用交易日 `next_open_price`、`gap_pct`、`gap_direction` 與 `severity`，用來揭露同日收盤成交假設在隔日開盤可能遇到的跳空風險。`portfolio_credibility` 仍會揭露同日收盤成交、再平衡現金重用限制、成交量 / Liquidity 與 Gap 限制；目前仍未建零股、委託簿撮合、買賣價差或 gap 實際成交模型，`gap_risk` 只做風險標籤，不會改變 PnL、成交價、cash ledger 或 sizing。這些 warning 應先讀完，再判讀回放績效。結果仍依成交與推薦回放假設，不等同實盤。

## 10. 持倉管理

### 10.1 手動記錄交易

1. 點擊「手動記錄交易」。
2. 輸入股票、買賣別、價格、股數、日期、費用與稅金。
3. 可選擇策略來源並填寫備註。
4. 保存後系統重算持倉與平均成本。

賣出數量不得超過目前可用持倉。

### 10.2 從推薦或回測建立來源追溯

- 推薦結果表右鍵「記錄到持倉管理」。
- 回測交易明細右鍵記錄交易。

這些入口會保存推薦結果、回測 run 或策略版本來源。它們仍是手動記錄，不會送出券商委託。

### 10.3 持倉與交易歷史

選取持倉後，右側同步顯示：

- 交易歷史
- 覆盤日誌
- 策略與價格監控
- 籌碼監控

交易歷史可用右鍵刪除；刪除後持倉與成本會重新計算。

### 10.4 覆盤日誌

1. 選取持倉。
2. 點擊「新增日記」。
3. 記錄進場假設、風險、觀察結果與出場理由。

### 10.5 策略與價格監控

顯示：

- 目前價格
- 未實現損益
- 停損與停利門檻
- 監控狀態與原因
- 策略、推薦或回測來源

警示是輔助判讀，不會自動平倉。

### 10.6 籌碼監控

顯示籌碼風險、近期分點買賣明細與資料品質。按「下鑽詳細主力流向」會切換至市場觀察的 Smart Money 並定位目前股票。

### 10.7 清空全體數據

此操作會永久清空持倉交易與日誌，需要二次確認。執行前應先確認資料是否已備份。

## 11. Runtime Observatory

這是唯讀工程治理頁，不是選股工具。

欄位：

- Objective：目前 Runtime 任務目標。
- Task Workflow Status：FSM 狀態。
- Active Files：目前上下文檔案。
- Overall System State：整體治理狀態。
- Rejection Rate：治理拒絕率、趨勢與連續失敗數。
- Last Critical Violation：最近一次重大違規。
- Append-only Event Stream：時間、嚴重度、actor、事件類型與訊息。

當狀態為 ERROR 或 HALTED：

1. 查看 Last Critical Violation。
2. 查看事件流中最接近異常時間的訊息。
3. 記錄 actor 與 event type。
4. 回到對應功能頁或日誌排錯。

此頁不會修改資料、重新啟動服務或自動修復。

## 12. 常見問題

### UI 無法啟動

```powershell
.\.venv\Scripts\python.exe -c "import PySide6; print(PySide6.__version__)"
.\.venv\Scripts\python.exe ui_qt\main.py
```

確認目前目錄是 repo 根目錄，並檢查 `DATA_ROOT` 是否可存取。

### 圖表空白

確認 PySide6 QtWebEngine 可用；系統無法使用 fast renderer 時會嘗試 Matplotlib fallback。先查看 terminal 或應用日誌的匯入錯誤。

### 更新後推薦仍沒有最新日期

1. 檢查 SQLite 狀態日期。
2. 手動下載後確認已合併。
3. 確認技術指標已增量計算。
4. 在 SQLite Inspector 檢查 `daily_prices` 與 `technical_indicators`。

### Smart Money 沒有資料

確認券商分點已下載、合併並同步至 `broker_flows`。`unavailable` 不應解讀為 0 張。

若快速更新在「同步券商分點至 SQLite」遇到同一分點 / 股票 / 日期的買超與賣超唯一鍵衝突，代表 DB 仍是舊三欄主鍵；更新後的流程會在同步前先備份並升級為含 `trade_type` 的主鍵。

### TPEX 股票只有一筆日價

若在 SQLite Inspector 查 `3207` 只看到 `20260616`，這是目前正式資料狀態：TPEX 日常更新已接上，但歷史 TPEX 尚未正式大量回補。歷史回補需先跑 dry-run plan 並人工確認，不會由日常快速更新自動大量寫入。

### 回測 0 交易

依序檢查：

1. 資金是否足夠買一張。
2. 日期範圍是否涵蓋足夠訊號。
3. quantile 是否仍在暖機期。
4. 固定門檻是否過高。
5. 漲跌停、成交量與最大參與率是否拒絕成交。
6. 是否只有期末未平倉部位。

### Promote 按鈕不能使用

確認結果已保存，且驗證狀態不是 FAIL。樣本不足、無結果、未保存、run 已封存、run 已升級、資料完整性不是 valid、缺少參數合約版本，或最低 validation gate 未通過時，不允許升級。若策略版本 JSON 已寫入但 Registry 回填失敗，系統會執行補償刪除；刪除失敗時標記 reconciliation required，需進入受控修復流程。

## 13. Manual 覆蓋狀態

| 工作區 | 啟動/入口 | 操作 | 參數 | 結果解讀 | 安全/排錯 |
|---|---:|---:|---:|---:|---:|
| 數據更新 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 市場觀察 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 推薦分析 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 觀察清單 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 每日決策 | 完成（v1 首頁） | 完成 | 完成 | quality / warnings 判讀；Market Breadth v1 / Sector Rotation v1 / Relative Strength / Liquidity Ranking v1 / Watchlist Trigger v1 / Portfolio Alert v1 / Why Not v1 / fundamental diagnostics prompts 已接線 | 完成 |
| Research Lab | 完成 | 完成 | 完成 | 完成 | 完成 |
| 持倉管理 | 完成 | 完成 | 完成 | 完成 | 完成 |
| Runtime Observatory | 完成 | 完成 | 不適用 | 完成 | 完成 |

功能行為改動時，必須同步更新本表與對應章節。

完整主 UI 人工 smoke test 母檔維護於 [FULL_APP_HEALTHCHECK_2026_06_16.md](../06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md)。每次修改數據更新、SQLite 檢視、每日決策或跨工作區流程後，除自動化測試外，應依該 healthcheck 做 smoke test。

## 14. 更新記錄

- 2026-06-16：新增月營收 normalized backfill 操作說明，記錄 dry-run、正式 apply confirm、備份與缺 availability mapping 時 fail-closed 的行為。
- 2026-06-16：新增公司清單 / 產業 mapping 更新操作說明，記錄 TWSE/TPEX 官方 registry dry-run、正式 apply confirm、備份、`3207` TPEX daily price 缺口與 `9935` 產業修正。
- 2026-06-16：更新估值 metrics backfill 操作說明，記錄 P/E dry-run、產業 mapping、同產業分位、正式 apply confirm、備份與 831 筆正式寫入狀態。
- 2026-06-16：新增 TPEX daily price backfill 操作說明，記錄 TPEX official daily close quotes dry-run、正式 apply confirm、DB 備份、`3207` 日價補齊與 877 筆正式寫入驗證。
- 2026-06-16：新增月營收 availability mapping 維護說明，記錄 TWSE OpenAPI 候選產生器、validator 流程、正式資料寫入前人工確認要求，以及最新月端點與本機歷史 raw 期間暫無交集的限制。
- 2026-06-16：補充 TWSE/TPEX 月營收 historical dry-run builder，記錄最新月 OpenAPI 樣本、MOPS historical 自動化限制、`2020-01..2026-05` dry-run 0 candidate rows，以及正式 mapping / 月營收 backfill 的人工 gate。
- 2026-06-16：補充 MOPS HTML source-dir 操作方式，記錄 `--mops-html-dir` 檔名規則、`出表日期` requirement、`mops.monthly_revenue_announcement` source 與 fail-closed diagnostics。
- 2026-06-17：補充 `--mops-static` 操作方式，記錄新版 MOPS redirectToOld / mopsov historical static report 可驗證歷史 rows，但 `出表日期` 為查詢當日，會被 45 天合理揭露窗口 gate 擋下。
- 2026-06-16：補充授權 PIT 月營收公告日 CSV 匯入方式，記錄 `--pit-csv`、必填 `--pit-source-version`、支援欄位與 candidate-only / 人工 gate 限制。
- 2026-06-16：更新 SQLite 資料檢視操作說明，補充日期日曆選擇器、清除日期、資料庫端表頭排序、`daily_prices` 繁中欄位 alias 與 `漲跌價差` 正負號顯示規則。
- 2026-06-16：調整 SQLite 資料檢視日期控件說明，單一日期預設今天，日期區間預設本月 1 日至今天，清除後才不套用日期條件。
- 2026-06-16：更新每日股價操作說明，確認快速 / 安全更新已納入 TPEX official daily close quotes；TPEX CSV 寫入 `DATA_ROOT/daily_price_tpex/`，SQLite 寫入 `daily_prices`，TPEX endpoint timeout 會以警告呈現且不阻斷其他資料同步，歷史 TPEX 回補仍需 dry-run plan 與人工確認。
- 2026-06-16：補充 SQLite Inspector 重複欄名防護、券商分點 `broker_flows` 主鍵納入 `trade_type`、TPEX 歷史缺漏判讀，以及 Full App Healthcheck 人工驗證入口。
- 2026-06-16：新增 Month 5 月營收候選資料抓取操作段，記錄今晚要跑的 MOPS snapshot 與 FinMind create_time 兩個 candidate-only CLI、輸出位置、resume / rate limit 與毛利率季度資料邊界。
- 2026-06-15：整理 Daily Decision Desk 顯示密度，將強弱與流動性代碼改為分行摘要並限制單類別顯示數量，避免主視窗被長清單撐寬。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾說明，確認 section quality 以 header badge 顯示，強弱 / 流動性代碼採單一 compact list 呈現，UI 不重算 service snapshot 以外的 domain logic。
- 2026-06-15：補充 Portfolio Alert Attribution v1，說明每檔持倉警示的來源標籤、condition 狀態、chip risk level 與原因 token 歸因呈現，用於輔助警示來源之分析與判讀。
- 2026-06-15：補充 Why Not / 風險提示 v1 對接，說明如何由既有 section DTO 屬性與 quality/warnings 推導風險提示、各提示類別之解讀與 quality 降級規則。
- 2026-06-16：補充 Daily Decision Desk fundamental diagnostics 風險提示，說明異常基本面只作研究風險提示，不改財報、不扣分、不輸出交易建議。

- 2026-06-15：補充 Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` 接線，說明相對強度基點計算、20 日平均成交額流動性門檻過濾，以及歷史不足 21 天的 fallback 與 quality/warnings 降級判讀。
- 2026-06-15：補充 Portfolio Alert v1 已由 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService` 共同接線，說明如何整合條件與籌碼風險警示，以及籌碼缺資料、估算、unavailable 的 quality / warnings 判讀。
- 2026-06-15：補充 Watchlist Trigger v1 已由 `WatchlistService` 與 SQLite `technical_indicators` 接線，說明強度 `score_bp`、風險 `risk_alert`、觸發統計與非交易日 fallback warning。
- 2026-06-15：補充 Daily Decision Desk v1 已接上主 UI 頂層「每日決策」頁籤，並更新質量欄位（OBSERVED / ESTIMATED / DEGRADED / MISSING）與 warnings 的解讀方式。
- 2026-06-15：補充 Market Breadth v1 已由 SQLite `daily_prices` 接線，說明多方 / 空方 / 持平、廣度比率、新高新低 metadata、成交量擴散與非交易日 fallback warning。
- 2026-06-15：補充 Sector Rotation v1 已由 SQLite `industry_indices` 接線，說明領先 / 落後產業、5 / 20 日變化、輪動強度、產業排名 metadata 與非交易日 fallback warning。

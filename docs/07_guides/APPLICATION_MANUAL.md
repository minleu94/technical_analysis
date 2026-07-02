# baldr 完整操作手冊

> **最後更新**：2026-06-30
> **適用版本**：目前主要 PySide6 UI，入口為 `ui_qt/main.py`。
> **範圍**：本手冊涵蓋目前 8 個頂層工作區與跨工作區流程。開發中或 Roadmap 規劃功能不會描述成已可用。

## 1. 系統能做什麼

目前系統提供：

1. 更新每日股價、大盤、產業、券商分點與技術指標。
2. 用市場 Regime、強弱個股、強弱產業與 Smart Money 觀察市場。
3. 用 Profile 或進階參數產生推薦候選，查看 Why、Why Not 與分數拆解。
4. 建立觀察清單（候選池）與可重用選股清單。
5. 執行單股、批次、固定組合、推薦回放與策略研究。
6. 保存研究結果、比較既有結果，並在符合 Registry 與 Month 6 lifecycle Gate 時升級策略版本。
7. 記錄交易、持倉、覆盤日誌、停損停利、籌碼監控與生命週期回顧。
8. 唯讀觀察 Runtime 狀態、治理健康與事件流。

目前不能保證：

- 推薦股票一定上漲或策略一定獲利。
- quantile 一定優於 fixed；2026-06-14 的 10 檔 OOS 實證未顯示 quantile 優於 fixed，因此仍為 opt-in。
- 推薦回放等同可成交的實盤績效。
- Forward Evidence / Forward Performance 的 close-to-close forward return 等同實盤可執行績效，或能證明任一訊號有效。
- Daily Decision Desk 已接上主 UI「每日決策」頁籤，並新增 answer-first dashboard：先顯示今日主結論、研究模式註記、優先 / 風險產業與股票焦點，再保留各模組細節；股票焦點可下鑽至「市場觀察 > 主力流向」。Market Breadth v1 已由 SQLite `daily_prices` 接線，Sector Rotation v1 已由 SQLite `industry_indices` 接線，Watchlist Trigger v1 已由 `WatchlistService` 與 SQLite `technical_indicators` 接線，Portfolio Alert v1 已由 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService` 接線，Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` 接線，Why Not / 風險提示 v1 已由 `DecisionDeskRiskPromptService` 對接，並可呈現 fundamental diagnostics 來源的基本面風險提示。缺口會以 MISSING / DEGRADED / ESTIMATED 顯示，並保留 warnings。
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

1. 數據更新：先檢查資料狀態，必要時執行快速更新。
2. 市場觀察：檢測 Regime，查看強弱與主力流向。
3. 推薦分析：選 Profile，執行推薦並閱讀 Why / Why Not。
4. 加入觀察清單：保存要研究的股票。
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
- 月營收資料

月營收卡片會顯示 `fundamental_monthly_revenues` 的最新資料年月、筆數與狀態，用來確認正式 SQLite 基本面資料是否已進入目前資料庫。

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
| 快速更新（跳過大型合併） | TWSE / TPEX 每日股價與券商分點會依 UI 最近範圍補齊，預設為結束日前最近 10 個工作日，並直接增量同步 SQLite；會保留已下載的日檔 CSV，但跳過 `stock_data_whole.csv` 與券商分點 `merged.csv` 的大型重寫。 | 日常盤後更新、只需要讓 SQLite 查詢與技術指標追上最新資料。 |
| 安全更新（完整 CSV + SQLite） | 依 UI 最近範圍補齊 TWSE / TPEX / 大盤 / 產業 / 券商分點，預設為結束日前最近 10 個工作日；完成後重建每日股價大表與券商分點 `merged.csv`，再同步 SQLite。 | 資料修復、備份完整性檢查、需要確認 CSV 歷史資料庫也完整時。 |

快速更新仍會更新必要的日檔 CSV，因為 SQLite 同步以這些日檔作為可追溯來源；速度優勢主要來自跳過大型合併檔重寫。最近 10 個工作日可涵蓋使用者約兩週才開一次程式的常見情境；若間隔更久，請改用個別資料來源日期範圍或安全更新補齊。若近期資料已存在，系統會先用 CSV / SQLite 判斷並跳過網頁抓取。

### 4.3 個別資料來源

左側可選：

- 每日股價
- 大盤指數
- 產業指數
- 券商分點
- 技術指標
- 月營收
- SQLite 資料檢視

每日股價、大盤、產業、券商分點操作：

1. 設定「結束日期」；可用日曆選取，或按「今日」一鍵帶入今天。
2. 設定「最近範圍」；系統換算出的開始日期會納入下載與缺漏檢查範圍。
3. 先按「檢查此資料源狀態」。
4. 按「手動下載此資料源」會依資料源下載或補齊指定日期範圍的原始資料。
5. 每日股價手動下載會同時處理 TWSE 與 TPEX：TWSE raw CSV 寫入 `DATA_ROOT/daily_price/YYYYMMDD.csv`，TPEX official daily close quotes 寫入 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`，完成後同步 SQLite `daily_prices` 並觸發技術指標增量更新。執行「合併每日股價」時，`stock_data_whole.csv` 也會同時納入這兩個日檔目錄。
6. 券商分點下載後，還要執行對應的「合併」才會寫入分析資料庫。

每日股價與券商分點按「檢查此資料源狀態」後，結果會顯示在該資料源頁面內的摘要列，包含最新日期、筆數、SQLite / CSV 狀態與缺漏提示；下方日誌只保留細節，不是唯一判讀入口。

每日股價的「強制重新合併所有每日股價」屬高風險維護操作。系統會先顯示二次確認對話框，按「取消」不會執行，只有按「確認強制合併」才會重建衍生合併資料；此流程不應亦不會修改或刪除 `DATA_ROOT` 底下的 raw CSV 原始檔。

若 TPEX endpoint timeout 或部分日期失敗，UI 會以 warning 呈現並繼續已成功的 TWSE / SQLite / 技術指標流程；這代表需要重測或補跑缺漏日期，不代表 TWSE 資料也失敗。

每日股價分頁另有「背景補齊 TPEX + 技術指標」與「檢查背景任務狀態」。背景任務不會先強制跑 TWSE 全量，也不會強制全量重算技術指標；同步 SQLite 後會比對每日股價與技術指標最新日期，若技術指標已追上每日股價，狀態會顯示 skipped。狀態檔位於 `DATA_ROOT/meta_data/tpex_full_refresh_status.json`；若狀態顯示 `running`，請用狀態查詢確認進度，不要重複啟動第二個背景任務。

券商分點同步會保存 `trade_type`，同一分點 / 股票 / 日期可同時有買超與賣超 rows。若舊 SQLite `broker_flows` 還是三欄主鍵，下一次同步券商分點時會先備份 DB，再把唯一鍵升級為 `(分點名稱, 證券代號, 日期, trade_type)`。

券商分點下載在 `force_all=false` 時會先檢查日檔 CSV 與 SQLite `broker_flows`。SQLite 檢查會同時比對分點顯示名稱與系統 key，避免 DB 已有資料卻仍啟動 MoneyDJ / Selenium 重新抓取。

券商分點下載仍採保守序列流程，但進入 MoneyDJ 前會先用每日股價日檔或 SQLite `daily_prices` 檢查目標日期是否有行情證據；無行情證據的日期會整天跳過，不會讓每個分點各自重試。MoneyDJ 正常頁面會優先使用 HTTP fast path 直接抓取 Big5 HTML，只有 HTTP 失敗或解析不到資料時才退回 Selenium fallback。預設請求間隔為 0.5 秒；若一次更新約 40 個分點耗時較長，先確認是否已有 CSV / SQLite 既有資料可跳過。本版尚未支援 5 或 10 worker 並行，避免對 MoneyDJ 造成過高併發與站方阻擋風險。

### 4.4 技術指標

- 「增量更新」：只處理新資料，日常首選；若單股指標已到最新股價日期會直接跳過，只有落後時才回看 120 個交易日重算重疊區間。
- 「強制全量更新」：重算所有股票歷史資料，只在指標算法改動或資料損毀時使用。
- 股票代號留空代表處理全部；輸入例如 `2330` 代表只處理單一股票。
- 增量寫入單股指標 CSV 時，若舊檔或新結果缺少可辨識日期欄位，會避免直接疊加資料；必要時以新計算結果覆蓋該單股檔，防止同一股票歷史列倍增。
- 技術指標計算目前仍以既有單流程治理 SQLite / CSV 寫入；即使後續加入多核心，也必須拆成 compute-only 平行與單 writer 寫入，避免 SQLite lock 或 CSV 覆寫競爭。本版不提供技術指標 worker 數設定。

### 4.5 SQLite 資料檢視

1. **選擇與篩選**：選擇資料表，設定每頁限制筆數，填入股票代號、名稱、券商分點或日期篩選。券商分點可在 `broker_flows` 時由下拉選單選取，也可手動輸入關鍵字。日期預設空白，不會自動套用條件；打開日曆時會定位到今天。單一日期可按「今日」快速帶入今天，區間旁的「清除」會同時清掉單一日期與區間日期。
2. **載入數據**：點擊「載入數據與結構」按鈕。
3. **基本面資料表**：資料表下拉選單會列出 `fundamental_monthly_revenues`、`fundamental_statement_items`、`fundamental_valuation_metrics`。月營收表可用股票代號與日期篩選，日期對應 `as_of_date`，例如 `2026-05-31`。
4. **資料分頁控制**：
   - 底部設有分頁控制列，包含「上一頁」、「下一頁」、「跳至第 X 頁碼（輸入頁碼並按跳頁按鈕）」、以及「當前頁數 / 總頁數」與「篩選後總記錄數」。
   - **防禦機制**：修改篩選條件並重新載入時，系統會自動重設為第一頁，並快取 schema 避免不必要的拉取。
   - **Stale 結果防護**：連續切換分頁或資料表時，舊有的非當前背景查詢結果會被自動忽略；執行中的背景查詢會安全保留到自然結束，防止 UI 資料錯亂或執行緒提前銷毀。
5. **欄位結構**：在「欄位結構」Tab 查看欄位 Schema 與型態描述。
6. **表頭排序**：在「資料預覽」點擊任一欄位表頭可切換升冪 / 降冪。排序由 SQLite 端以白名單欄位 `ORDER BY` 執行，並沿用目前篩選與分頁限制，避免 UI 端載入全表排序。
7. **漲跌欄位顯示**：`daily_prices` 若遇到舊 schema 的簡體 `涨跌`，畫面會顯示為繁體 `漲跌`；`漲跌價差` 會依 `漲跌(+/-)` 或 `漲跌` 方向顯示正負號，以利顏色與排序判讀。
8. **重複顯示欄名防護**：若 raw schema 與 alias 造成相同顯示欄名，表格仍以欄位位置取值，不應出現 `PandasTableModel.data` 的 Series ambiguity 錯誤。

此工具是受控唯讀檢視器，不應用來修改或刪除資料。

### 4.6 匯出 CSV 備案

個別資料頁可選：

- 最近範圍
- 全部歷史

輸出使用 UTF-8 with BOM，方便用 Excel 開啟。這是離線備份與人工研究功能，不影響系統日常運作。

### 4.7 高風險操作

「強制重新合併」與「強制全量更新」會長時間處理大量歷史資料。只有在資料損毀、schema 修復或算法變更後使用，不要作為日常更新方式。

### 4.8 Month 5 月營收候選資料抓取

月營收候選資料抓取只負責來源驗證與 raw evidence 保存；抓取 CLI 本身不會寫入正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`，也不會寫入 `fundamental_monthly_revenues`。正式 mapping 與 SQLite 回填需另外走 validator / backfill 流程，並在高風險操作前由人工確認。

今晚建議先跑兩個檔案：

```powershell
.\.venv\Scripts\python.exe scripts\fetch_mops_monthly_revenue_snapshot.py --start-period 2014-04 --end-period 2026-05 --markets twse,tpex --output-dir D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots --fetch-date 2026-06-16 --sleep-seconds 0.5
.\.venv\Scripts\python.exe scripts\fetch_finmind_monthly_revenue_create_time.py --start-date 2014-04-01 --end-date 2026-05-31 --raw-dir D:\Min\Python\Project\FA_Data\financial_data --output-dir D:\Min\Python\Project\FA_Data\output\monthly_revenue_finmind_create_time --max-requests-per-hour 540 --resume --fetch-date 2026-06-16
```

第一個命令會保存 MOPS raw HTML 與完整市場月營收 snapshot CSV；它只代表營收內容快照，不得用 period 或歷史查詢日推定官方公告日。若從某天開始每日保存 MOPS snapshot，可把本機首次看見該月營收列的日期視為 first-seen observation candidate，搭配 `available_date=first_seen+1 calendar day` 作保守候選 mapping；這仍不是官方 MOPS 公告日，正式寫入前必須由人工確認。第二個命令會使用已加密保存於本機的 FinMind token 逐檔抓取 `TaiwanStockMonthRevenue.create_time`，輸出 create_time 分組檔；`create_time` 只作備用 / 交叉檢查與每月分批更新參考，不作主線 mapping。若 FinMind 流程中斷，用同一個 `--output-dir` 加 `--resume` 重跑即可接續。

毛利率不是月營收資料。MOPS `t163sb06` 是季度財務比率 / 毛利率彙總表，查詢維度是年度與季別；後續若要納入，應走季度財報 / 財務比率 pipeline，另建公告日與 `available_date` gate，不要混進今晚的月營收 snapshot 或 FinMind create_time 流程。

## 5. 市場觀察

### 5.1 大盤指數

1. 點擊「檢測市場狀態」。
2. 查看 Regime、規則匹配度與判斷摘要。
3. 展開技術細節時，可查看價格與均線、趨勢、評分、其他指標與判斷條件。
4. 將策略建議作為 Profile 選擇參考，不要視為買賣訊號。

Regime 是對當下市場環境的分類，不是未來預測。規則匹配度是 detector 對目前資料符合既有規則的程度；100% 代表達到目前規則上限，不代表未來勝率或成功機率。

### 5.2 強勢與弱勢個股

1. 選擇「本日」或「本周」。
2. 第一次進入可按「載入數據」。
3. 需要重新計算時按「刷新」。
4. 選取股票後按「加入觀察清單」。

強勢排名不等於建議追價；弱勢排名也不等於做空或立即賣出。

效能邊界：強 / 弱勢個股在 SQLite 啟用時會優先從 SQLite `daily_prices` 只讀近期交易日與必要欄位，不依賴全量 indicator CSV 掃描；產業共振理由會使用 `IndustryMapper` 最新產業表現快取，避免逐檔股票重掃產業指數 DataFrame；讀取失敗才降級為既有 CSV / 舊查詢路徑。若仍感到卡頓，應先量測 SQLite 查詢、DataFrame 分組與 UI thread 更新時間；不要把排名結果解讀成交易指令。

### 5.3 強勢與弱勢產業

使用本日或本周排名判斷產業相對強弱，再回到個股頁或推薦頁研究產業內股票。

強 / 弱勢產業同樣採 SQLite-first，從 SQLite `industry_indices` 只讀近期交易日與 `日期` / `指數名稱` / `收盤指數` 必要欄位；缺資料或讀取失敗才 fallback CSV。大型資料量下第一次載入仍可能需要等待，但不再需要先載入整張產業指數表。

### 5.4 主力流向

「個股資金流向」操作：

1. 選擇日線、週線或月線。
2. 選擇直方、折線或面積趨勢圖。
3. 選擇顯示範圍；預設為「Top / Bottom 50」，主表只顯示買超前 50 與賣超後 50，摘要統計仍使用全市場掃描結果。
4. 點擊「開始掃描」。
5. 點選主表股票，右側顯示分數、集中度、訊號原因與分點明細。
6. 主表新增「語意狀態」與「5/20/60 日診斷」欄；語意狀態包含 `初轉買`、`買超延續`、`初轉賣`、`賣超延續`、`高檔出貨疑慮`、`分點集中異常`。
7. 主表欄寬預設優先保留 5/20/60 日診斷與近期趨勢圖；集中度、語意狀態、5/20/60 日診斷與 Badges 欄都依目前資料最長內容加少量留白自動貼合，不吃掉所有剩餘空間。近期趨勢欄維持 compact 固定寬度，直方圖會在欄內以緊湊間距並保留左側 padding 繪製，右側分點 panel 會取得多餘空間；完整數字與品質細節保留在 tooltip。
8. 懸停列可查看 5 / 20 / 60 日 Top N quantity 集中度、observed / estimated / unavailable 筆數、5 / 20 / 60 日淨量與價格位置等診斷。
9. 表格標頭可排序。
10. 有 Watchlist service 時，可按「+ 觀察清單」。
11. 右側分點明細表會依 panel 寬度自動分配「分點名稱 / 買進張數 / 賣出張數 / 淨買賣超」四欄，優先完整顯示內容與淨買賣超 bar，不應需要水平捲動。
12. 在右側分點明細雙擊分點名稱，會切到「分點進出追蹤」並選中該分點。

「分點進出追蹤」操作：

1. 選擇券商分點。
2. 查看該分點近期操作股票、張數、標籤與趨勢。

資料品質：

| 品質 | 解讀 |
|---|---|
| observed | 原資料直接觀測到張數或金額。 |
| estimated | 由可用價格與金額估算，信心較低。 |
| unavailable | 無足夠資料，不應硬補成 0。 |

語意診斷限制：

- 5 / 20 / 60 日視窗只使用決策日以前可取得的分點事件，不使用未來資料補滿視窗。
- 分點集中度使用 quantity（張數 / 股數等價數量）計算，不使用千元金額直接當集中度。
- unavailable 事件不放進集中度分子或分母，會在 tooltip 揭露排除筆數與覆蓋率。
- `高檔出貨疑慮` 是價格位置與主力賣超聯動的風險提示，不等於賣出建議。
- `分點集中異常` 代表同方向淨量集中於少數分點，應搭配價格、成交量與資料品質判讀，不直接代表利多或利空。

單一分點買超不等於真實主力意圖，應優先觀察多分點共振、價格行為與資料覆蓋率。

## 6. 推薦分析

### 6.1 新手模式

1. 查看系統偵測的市場狀態與 Profile 建議。
2. 可按「一鍵套用建議 Profile」。
3. 或自行選擇 Profile。下拉會標示來源：
   - `內建｜...`：系統內建模板，例如暴衝、穩健、長期。
   - `自訂｜...`：使用者從目前推薦設定保存的 Profile，會標示「自訂，未經回測驗證」。
   - `策略版本｜...`：Research Lab / Strategy Registry 已通過 gate 的策略版本；停用或未通過 gate 的版本不顯示，但歷史策略版本資料不會被刪除。
4. 選擇 Profile 後，閱讀說明區的「對應進階設定」，確認權重、技術分類與型態數是否符合預期。
5. 若目前設定值得重用，可按「保存目前設定為自訂 Profile」；保存後會出現在 `自訂｜...` 清單。
6. 點擊「執行推薦分析」。

市場狀態卡會顯示 Regime 中文名、regime code、confidence / 規則匹配度、Regime score、資料日期與來源。confidence / 規則匹配度是當下資料符合分類規則的程度，不是未來走勢勝率。

Profile-Regime 說明：

- `match` / `bonus`：目前 Regime 落在 Profile 適用 Regime；既有 scoring 會以 regime 權重調整揭露加分語意。
- `mismatch` / `penalty`：目前 Regime 不在 Profile 適用範圍；結果不會被直接排除，只在排序、分數或原因中揭露不匹配。
- `neutral` / `no_bonus`：Regime 尚不可用或 Profile 未指定適用 Regime；不套用 Profile-Regime 加分。

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
- 排名方法：目前為「最近名次法」，使用排序後最接近的觀測值作為百分位門檻，方便追溯。

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
- Regime match / mismatch：顯示目前 market Regime 與 Profile 期望 Regime 是否一致；mismatch 是解釋與排序訊號，不是自動排除或交易指令。

「目前策略傾向摘要」只描述已勾選技術指標與圖形模式推導出的摘要，不是可調偏好控制。若需要改變偏短線、偏長線或盤整 / 趨勢取向，應回到 Profile 或進階設定調整實際條件。

推薦分析不會自動下單、不會自動調整持倉，也不會把自訂 Profile 視為已通過回測驗證。策略版本 Profile 只代表該版本通過既有 gate，可作推薦設定來源，仍需自行判讀資料品質、風險與研究證據。

### 6.5 結果後續操作

- 「保存結果」：保存推薦配置、Profile、Regime 與推薦名單；成功訊息會顯示保存 ID、保存範圍與下一步入口。
- 「加入觀察清單」：把選取股票加入 Watchlist。
- 「送 Research Lab 批次回測」：用推薦名單建立批次研究輸入。
- 「送 Research Lab 推薦回放」：使用推薦配置進行歷史回放。
- 表格右鍵「記錄到持倉管理」：建立帶推薦來源 metadata 的交易。
- 「匯出 Excel」：建立包含元數據、今日推薦配置、Regime 狀態以及推薦股票名單的 Excel 報告，並在背景執行原子寫入。

## 7. 觀察清單與選股清單

### 7.1 候選池操作

- 「新增股票」：手動輸入股票代號；系統會先用正式股票資料查找名稱，查不到的代號會被阻擋，不會混入正式觀察清單。
- 「移除選中」：刪除選取列。
- 「清空候選池」：刪除全部候選，無法復原。
- 「刷新」：重新載入資料。

候選池保存來源、加入時間與備註，用於研究，不是實際持倉。

### 7.2 選股清單

- 「保存為選股清單」：把目前候選池保存為可重用 Universe。
- 「載入到候選池」：把既有 Universe 載入目前候選池。
- 「新增 / 編輯 / 刪除」：管理 Universe 名稱、說明與股票內容。

「送 Research Lab 批次回測」可直接把目前觀察清單送到 Research Lab，並切到批次股票回測模式。若清單為空，按鈕會停用並在 tooltip 顯示原因；若要保存成可重用 Universe，仍可使用「保存為選股清單」。

## 8. 每日決策（Daily Decision Desk）

### 8.1 進入與刷新

Daily Decision Desk 採用 Midnight Analyst 深色介面：深色背景、section header 狀態 badge、緊湊摘要卡片與分行代碼清單。強勢、弱勢與低流動性代碼每類預設顯示前 8 檔，其餘以剩餘檔數摘要；完整資料仍由 service snapshot 保留，不因 UI 摘要而改變計算結果。

頁面最上方會先顯示 answer-first dashboard：

- `今日主結論`：以 `積極研究`、`正常研究`、`保守觀察`、`暫停新進場` 表示市場研究節奏。
- `研究模式註記`：提醒本頁是市場與籌碼輔助判讀，不是交易建議。
- `優先產業` / `避開產業 / 風險區`：由產業輪動摘要產生，幫助先決定研究方向。
- `優先研究股票` / `風險股票`：整合相對強弱、Watchlist、持倉警示與 Smart Money 語意摘要。
- 股票焦點按鈕可下鑽到「市場觀察 > 主力流向」並定位該股票。

Watchlist、持倉或單一股票風險不會直接降低整體市場行動等級；它們只影響股票焦點、風險清單與提示文字。整體行動等級主要由 Market Regime、Market Breadth 與資料品質決定。

warnings 在 UI 會以繁體中文說明主要原因與影響範圍；原始 token 保留在底層 snapshot / log 供除錯追溯，不直接作為一般畫面文字。看到 warnings 時先判斷是資料覆蓋率、歷史不足或服務降級，不應只看工程代碼做決策。

1. 進入主視窗頂層 tab「每日決策」。
2. 進入頁面時會先顯示「尚未載入 / 載入中」，Snapshot 會在背景執行緒建立，避免主 App 啟動被每日決策查詢阻塞。
3. 點選「刷新」可在背景重建 Snapshot；載入期間按鈕會暫時停用，完成後自動更新畫面。
4. 若初始化或刷新失敗，畫面會保留可閱讀狀態並顯示 fallback 提示，不會中斷整體 App。

### 8.2 結果解讀

每日決策摘要會顯示：

- 主結論與行動等級
- 優先 / 風險產業與股票焦點
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

若使用 MOPS snapshot 作為月營收值主來源，可在候選 mapping 通過 validator 後，用 `--mops-snapshot-file` 直接 dry-run，不需先轉成 `financial_data/*_monthly_revenue.csv`：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --dry-run --mops-snapshot-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots\mops_monthly_revenue_snapshot_2014-04_2026-05_2026-06-16.csv --availability-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_availability_candidates\mops_first_seen_monthly_revenue_availability_validator_ready_2026-06-16.csv --source-version mops-static-snapshot-monthly-revenue-2026-06-16
```

此路徑會把 normalized record 的 `source` 保留為 `mops.monthly_revenue_static_snapshot`。2026-06-16 對 MOPS first-seen candidate 執行 dry-run 時，validator accepted `1,848` 筆、backfill plan 為 `ready_for_apply=true`、`normalized_record_count=1,848`、`diagnostics=0`。同日依人工確認，正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 已寫入 1,848 筆 2026-05 MOPS first-seen mapping，並已用 MOPS snapshot 對正式 SQLite 回填 `fundamental_monthly_revenues` 1,848 筆；DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_mops_monthly_revenue_backfill_20260616_203031.db`。

正式回填必須在 mapping 通過驗證後，由人工確認再執行：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --apply --confirm apply-monthly-revenue-backfill
```

正式 apply 會先備份 DB；缺少 `--confirm apply-monthly-revenue-backfill` 時會拒絕執行。回填工具只寫入 `fundamental_monthly_revenues`，不會修改 raw CSV、availability mapping 或既有核心表。2026-06-16 正式回填後，`fundamental_monthly_revenues` 期間為 `2026-05`、股票數 1,848、0 duplicate primary keys；樣本 `2330`、`3207`、`9935` 均為 `quality=observed`、`source=mops.monthly_revenue_static_snapshot`、`source_version=mops-static-snapshot-monthly-revenue-2026-06-16`。

#### 更新頁月營收功能

主 UI 的「資料更新」頁新增「月營收」分頁。此分頁提供三個欄位：

- `MOPS 月營收快照檔`：從 MOPS snapshot CSV 讀取各公司每月營收值。
- `正式可得日對照檔`：指定 `monthly_revenue_availability.csv`，用來決定每筆月營收從哪一天起可被因子層讀取。
- `本次寫入版本名稱`：寫入資料表的版本名稱，用於日後追溯與比對。

此分頁提供兩個操作：

- `先檢查，不寫入`：只檢查可回填筆數與診斷結果，不寫入正式資料庫。
- `確認後寫入月營收`：先跳出確認視窗，再建立 DB 備份並寫入 `fundamental_monthly_revenues`。此按鈕不抓取新 MOPS HTML、不修改 raw CSV，也不更新 availability mapping。

#### 月營收因子檢視

若要確認正式 SQLite 月營收是否已進入基本面 factor layer，可使用唯讀檢視 CLI：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_fundamental_factors.py --all-monthly-revenue-stocks --decision-date 2026-06-30 --diagnostic-limit 8 --stock-summary-limit 12
```

此工具只讀取 `fundamental_monthly_revenues`、`fundamental_statement_items` 與 `fundamental_valuation_metrics`，透過 `FundamentalFactorService` 產生當下可見的 factor records / diagnostics，不寫 SQLite、不修改 CSV，也不接 `ScoringEngine`。2026-06-16 單月營收初版檢查結果為：股票數 1,848、factor records 4,464、diagnostics 3,696；其中月營收已產生 `fundamental.revenue_3m_trend` 1,848 筆與 `fundamental.revenue_new_high` 1,848 筆。2026-06-17 retroactive baseline 補齊後，Revenue Factor Pack 可產生 YoY 1,843 筆、MoM 1,842 筆、3M trend 1,848 筆與 new high 1,848 筆，剩餘 diagnostics 11 筆。這代表 Month 5 已能把 SQLite 月營收送到 Revenue Factor Pack；但 historical baseline 多數 quality 為 `degraded`，不可解讀為官方歷史 point-in-time 公告日，也不可直接接入 `ScoringEngine`。

#### 月營收歷史 baseline 候選

MOPS snapshot 可以用來補「從導入日之後才可使用」的歷史 baseline。此路徑不是官方歷史公告日 mapping；產出的 source 固定為 `manual.retroactive_baseline_mapping`，`announced_date` 留空，`available_date` 設為人工指定的導入可用日，品質會是 `degraded`。因此它可讓 2026-06-17 之後的決策日計算 YoY / MoM baseline，但不得用於 2026-06-17 以前的歷史回測。

建議先產生候選檔，不覆蓋正式 mapping：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_retroactive_baseline_mapping.py --snapshot-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots\mops_monthly_revenue_snapshot_2014-04_2026-05_2026-06-16.csv --start-period 2014-04 --end-period 2026-04 --available-date 2026-06-17 --source-version mops-retroactive-baseline-2014-04_2026-04-2026-06-17 --output D:\Min\Python\Project\FA_Data\output\monthly_revenue_availability_candidates\mops_retroactive_baseline_monthly_revenue_availability_2014-04_2026-04_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\validate_monthly_revenue_availability.py --path D:\Min\Python\Project\FA_Data\output\monthly_revenue_availability_candidates\mops_retroactive_baseline_monthly_revenue_availability_2014-04_2026-04_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --dry-run --mops-snapshot-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots\mops_monthly_revenue_snapshot_2014-04_2026-05_2026-06-16.csv --availability-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_availability_candidates\mops_retroactive_baseline_monthly_revenue_availability_2014-04_2026-04_2026-06-17.csv --source-version mops-static-snapshot-monthly-revenue-2026-06-16
```

2026-06-16 dry-run 結果：candidate 242,651 筆、validator accepted 242,651 筆、backfill normalized 242,651 筆、diagnostics 0。依人工確認正式 apply 後，`fundamental_monthly_revenues` 共有 244,499 筆，期間 `2014-04..2026-05`，股票數 1,848、period 數 146、0 duplicate；品質分布為 242,651 筆 `degraded` historical baseline 與 1,848 筆 `observed` 2026-05 records，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_mops_monthly_revenue_backfill_20260616_224147.db`。factor inspection 顯示 `fundamental.revenue_yoy` 1,843 筆、`fundamental.revenue_mom` 1,842 筆、`fundamental.revenue_3m_trend` 1,848 筆、`fundamental.revenue_new_high` 1,848 筆，剩餘 diagnostics 11 筆主要為 baseline missing / zero。

#### 季度財報 available date gate

季度財報 raw CSV 不能直接進入因子層；必須先有 `fundamental_statement_availability.csv` 作 `available_date` gate。正式預設路徑為 `DATA_ROOT/meta_data/fundamental_statement_availability.csv`，欄位為 `stock_code`、`statement_type`、`period`、`as_of_date`、`announced_date`、`available_date`、`source`、`source_version`。

若目前只要建立「導入日後可用」的歷史 baseline candidate，可先產生候選檔：

```powershell
.\.venv\Scripts\python.exe scripts\build_statement_retroactive_baseline_mapping.py --raw-dir D:\Min\Python\Project\FA_Data\financial_data --available-date 2026-06-17 --source-version statement-retroactive-baseline-2026-06-17 --output D:\Min\Python\Project\FA_Data\output\statement_availability_candidates\statement_retroactive_baseline_availability_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\validate_statement_availability.py --path D:\Min\Python\Project\FA_Data\output\statement_availability_candidates\statement_retroactive_baseline_availability_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\backfill_fundamental_statement_items.py --dry-run --raw-dir D:\Min\Python\Project\FA_Data\financial_data --availability-file D:\Min\Python\Project\FA_Data\output\statement_availability_candidates\statement_retroactive_baseline_availability_2026-06-17.csv --source-version financial-data-statements-2026-06-17
```

2026-06-16 dry-run 結果：statement availability candidate 170,425 筆、validator accepted 170,425 筆、diagnostics 0；statement item backfill normalized 1,645,555 筆、diagnostics 0。依人工確認正式 apply 後，`fundamental_statement_items` 期間為 `2014-Q2..2024-Q1`、股票數 1,567、period 數 40、0 duplicate，quality 全為 `degraded`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_statement_items_backfill_20260617_004912.db`。此資料已可作導入日後 EPS、毛利率、營益率、ROE、業外損益 factor 的 baseline foundation；factor layer 只輸出 records / diagnostics，不接 `ScoringEngine`。

季度財報 factor layer 已可用唯讀方式檢查：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_fundamental_factors.py --all-monthly-revenue-stocks --decision-date 2026-06-30 --diagnostic-limit 12 --stock-summary-limit 12
```

2026-06-17 正式 DB inspection 結果：總 factor records 14,840、diagnostics 812；statement factors 為 `fundamental.statement.eps` 1,411 筆、`fundamental.statement.gross_margin` 1,368 筆、`fundamental.statement.operating_margin` 1,374 筆、`fundamental.statement.roe` 1,277 筆、`fundamental.statement.non_operating_income_ratio` 1,261 筆。缺 statement rows、缺必要科目或分母為 0 時只輸出 diagnostics，不輸出中性訊號，不接 `ScoringEngine`。

PB / PS 目前只做來源政策檢查：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_valuation_source_policy.py
```

Month 5 後 P/E、P/B、P/S 都具備 presentation policy。P/B 與 P/S 只接受 governed external observations 或後續明確 backfill records；系統不會在內部用不完整財報推導 book value、share count、market cap 或 TTM sales，也不會把估值指標接進 `ScoringEngine`。

#### Month 5 closeout 判讀

Month 5 Fundamental Layer v1 的完成定義是「基本面資料已能以受治理、可診斷、可追溯的方式進入 factor records / diagnostics」，不是把基本面自動納入推薦分數。使用者在 Daily Decision Desk、Research metadata 或 factor inspection 看到 fundamental diagnostics 時，應將其視為研究風險提示與資料品質揭露；系統不會因此自動買賣、調倉、改寫財報或調整 `ScoringEngine` 分數。下一階段 Month 6 才會討論策略生命週期與 Portfolio feedback 如何使用這些 evidence。

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

注意：`companies.csv` 是公司與產業 registry，不代表 `daily_prices` 已具備該股票行情。TPEX daily price 已納入日常市場日價管線；若歷史 TPEX 股票缺舊日價，需由每日股價區間補齊、快速 / 安全更新或背景補齊流程處理，不應用 company registry 或 fundamental layer 假造價格列。

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

模式下方會用「適合 / 輸入來源」說明目前模式該用在哪種研究情境，以及主要輸入來自股票代號、候選池、固定清單、推薦結果或策略模板。

Research Lab 左側設定面板預設保留足夠寬度給長下拉選項與表單欄位，右側結果區吃剩餘空間；一般 1400px 預設主視窗不應需要手動左右拖動才看得到完整「執行價格」等設定列。

### 9.2 基本設定

1. 選擇策略來源或載入 Preset。
2. 選擇單股或選股清單。
3. 設定開始與結束日期。
4. 設定初始資金、手續費與滑價。
5. 執行價格建議使用 `next_open`；`close` 是同根 K 收盤成交假設，必須清楚揭露。

開始日期與結束日期可開啟日曆選取；開始日期預設為今天往前一年，結束日期預設為今天，日曆開啟時會定位在目前欄位日期。

### 9.3 停損、停利與部位

- 百分比模式：使用固定停損停利百分比。
- ATR 倍數模式：依市場波動調整距離。
- 全倉：可用資金集中於目前部位。
- 固定金額：每次使用指定金額。
- 風險百分比：依風險比例與 ATR 決定部位。

部位管理包括最大持倉數、等權/分數加權/波動調整、加碼、重新進場與冷卻期。

台股整股模擬以 1000 股為單位。高價股若資金不足一張，可能產生 0 交易。

最大持倉數設為 `0` 代表無限制；設為 `1` 代表最多同時只持有 1 檔。這是部位數量限制，不是買賣訊號來源。

### 9.4 市場限制

- 漲跌停限制
- 成交量限制
- 最大參與率

如果訊號很多但交易為 0，先檢查資金、整股限制、成交量與參與率，不要直接判定策略沒有訊號。

### 9.5 固定門檻與百分位排名

- 「固定門檻」使用固定買賣分數。
- 「百分位排名」使用 T-1 以前的 expanding 歷史分布，暖機需要 60 個有效觀測值。
- 暖機完成前不應產生 quantile 交易訊號。
- 比較兩模式時必須使用相同資料、成本、成交假設與期間。

### 9.6 參數最佳化

1. 選擇目標：Sharpe、年化報酬或 CAGR-MDD。
2. 設定工作線程數。範圍為 1 到 8，預設使用保守上限；目前是 ThreadPool，不是 ProcessPool 多進程。
3. 對要掃描的參數設定固定值或範圍。
4. 執行參數掃描。大型掃描會先顯示預估組合數、worker 數、資料來源與取消提示，確認後才開始。
5. 在「最佳化 / 驗證」查看結果。
6. 選取結果後按「套用選中參數」。

資料與效能邊界：單股最佳化會在執行前預載該股資料一次；`config.use_sqlite=True` 時優先讀 SQLite，缺資料或讀取失敗才 fallback CSV。Optimizer 會用 bounded in-flight futures 分批提交任務，避免一次把所有參數組合送進 ThreadPool。

取消流程：按取消後系統會停止提交新組合，並清理已啟動子任務；清理期間 UI 會顯示「已送出取消」。若組合數很大，已啟動的少量子任務仍需要安全結束才會完全解鎖。

最佳化結果是 In-Sample 候選，不能直接視為可靠策略。

### 9.7 Walk-forward

- Train-Test Split：單次訓練/測試切分。
- Walk-forward：以訓練月數、測試月數與步進月份滾動驗證。

結果摘要會顯示樣本可靠度提示。Train-Test 會列出訓練集交易數與 OOS 交易數；Walk-forward 會列出 Fold 數、OOS 交易數與測試期正向 Sharpe 覆蓋率。Fold 少於 3、OOS 交易數不足，或出現勝率 100% 但最大回撤偏大的不直覺組合時，系統會提示「樣本不足，不宜作正式策略判斷」。此提示只使用該次驗證已產生的結果 metadata，不重新抓取目前資料，也不改變績效計算。

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
- 「升級為策略版本」：新版 Gate 必須讀取 Research Run Registry，不得只靠單次 summary；run 需 committed / valid、未封存、未升級、具備可還原參數合約版本，且通過最低 validation gate 與 Month 6 lifecycle gate。Lifecycle gate 會檢查交易次數、總報酬、Sharpe、最大回撤、勝率、benchmark excess return、factor quality 與 regime compatibility。成功升級後，若 lifecycle evidence repository 已啟用，系統會保存 applied evidence，包含 decision snapshot、gate reasons 與 version id。

「保存結果」與「升級為策略版本」按鈕會依目前是否已有可保存結果、是否已保存、validation 是否允許而啟用；停用時 tooltip 會說明原因。保存成功訊息會顯示 Registry run ID 與下一步。

保存、刪除或升級成功後，Research Lab 會刷新歷史列表、圖表選單與 Registry 比較面板，並在進度文字顯示剛保存的 run ID 或升級後的策略版本 ID。

Month 6 lifecycle gate 的預設最低交易數為 20 筆，且缺 benchmark excess return 或 factor snapshot 時會保守降級，不允許只靠單次高報酬升級策略版本。通過 Gate 不代表已完成實盤驗證。Demote / retire 判斷會先以 proposed evidence 保存，供人工 review；系統不會自動刪除策略版本或改寫歷史 run。

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
- Registry 比較：列出 Research Run Registry 中的 run，可依類型、strategy、tag 篩選並分頁瀏覽；類型在 UI 顯示為「單股回測」或「推薦回放」，但存檔 metadata 仍保留原始 run type。選取 2 至 5 個 run 後顯示「可直接比較 / 需謹慎比較 / 不可直接比較」、參數差異、指標、市場 Regime、Benchmark 基準與標準化權益。標準化權益沒有共同日期時會顯示空狀態原因。
- 證據覆盤：唯讀檢查已保存 evidence / observation / review。子頁包含「前瞻證據」、「研究落差」、「訊號衰退」與「決策品質」。頁面上方會顯示目前實際讀取的 SQLite 資料庫路徑，並提供「複製路徑」按鈕，方便確認是否使用 working-copy DB。各子頁日期欄位使用日曆選擇器，未選日期時不套用日期篩選。
  - 前瞻證據：檢查已保存 evidence events / outcomes 的 forward summary。可依日期、event type / family、source type、股票、regime、sector、profile、strategy version、window days、group by 與最小樣本數篩選，並查看事件總數、已完成 / 等待中 / 缺失結果、樣本不足、benchmark / industry 缺口、quality 與 warnings。close-to-close forward return 是 research basis，不代表可執行績效。
  - 研究落差：檢查 portfolio source trace、Research Run / strategy version、evidence event / outcome link、portfolio mode、gap metrics、attribution categories、match confidence、quality 與 warnings。沒有真實交易與人工 override 記錄時，只能解讀為 research / simulated gap。
  - 訊號衰退：檢查 event_type、event_family、strategy_version、profile scope 的短窗 / 長窗樣本、decay score、status、lifecycle candidate、confidence、quality 與 warnings。`demote_candidate` / `retire_candidate` 只是人工覆盤候選，不會自動套用。
  - 決策品質：檢查週 / 月 / custom review item、process score、reason codes、review question、open / reviewed / dismissed 狀態、quality 與 warnings。score 只代表流程 evidence，不是投資能力、不是交易建議，也不是責備使用者。
  這個分頁只使用 dashboard service 與已保存 read model，不重算推薦、不重算策略、不讀 UI state、不寫 evidence，也不建立排程；樣本不足或資料降級時只能作資料品質檢查，不可作訊號有效性判斷。
- 批次結果：排行榜與整體統計，雙擊股票可載入明細；頁首會說明排行榜只用來找出同批次內值得複核的股票，整體統計用來看樣本分布與成功率，不代表正式策略判斷、交易建議或持倉調整。
- 推薦回放：摘要分為概況、交易假設與可信度、風險與情境指標、Monte Carlo 情境；下方以分頁呈現組合價值 / 回撤圖、期間持倉、股票貢獻與交易紀錄。

### 9.9.1 Evidence Pipeline Runner（手動 dry-run）

Evidence Pipeline Runner 是手動 CLI，用來模擬每日 evidence pipeline；它不是 Windows Task Scheduler、cron 或背景 job。預設只做 dry-run，不會寫入 evidence events / outcomes。正式 `--confirm` 只能對 explicit working-copy DB 執行，且仍需人工審核 diagnostics report。

常用命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --dry-run --sources recommendation,watchlist-trigger,portfolio-alert,risk-prompt --report-output output\evidence_pipeline\reports\evidence_pipeline_2026-06-30.md
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --confirm --db-path <working-copy-db>
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline_working_copy.py --source-db-path <source-db> --working-copy-db-path <working-copy-db> --decision-date 2026-06-30 --repeat 2 --json-output
.\.venv\Scripts\python.exe scripts\evaluate_evidence_scheduler_readiness.py --db-path <working-copy-db> --json-output
```

支援參數包含 `--decision-date`、`--start-date`、`--end-date`、`--db-path`、`--sources`、`--windows`、`--group-by`、`--window`、`--min-sample-size`、`--limit`、`--dry-run`、`--confirm`、`--skip-snapshot`、`--skip-capture`、`--skip-outcomes`、`--skip-summary`、`--json-output`、`--report-output`。`--dry-run` 與 `--confirm` 互斥；`--confirm` 必須指定 `--db-path`。若 DB path 看起來是正式 DB，還需要額外 `--allow-production-db-confirm`，但一般 QA 不應使用正式 DB。

Runner steps：

1. `source_coverage_check`
2. `capture_decision_desk_snapshot`
3. `capture_evidence_events`
4. `calculate_forward_outcomes`
5. `summarize_forward_performance`
6. `write_diagnostics_report`

輸出 summary 會包含 events_seen、events_inserted、events_skipped_duplicate、outcomes_attempted、outcomes_created、outcomes_updated、outcomes_pending、summary_groups、groups_ready、groups_insufficient_sample、groups_degraded、warnings_count、errors_count、blocking_gaps 與 scheduler_readiness。Readiness 最高只到 `ready_for_manual_confirm`，不代表 production scheduler 已批准。

Working-copy smoke 會先確認 source DB 與 working-copy DB 不是同一路徑；若 working-copy DB 不存在，會以 `shutil.copy2` 從 source DB 複製一份，再只對 working-copy DB 執行 confirm smoke。預設 repeat 至少 2 次，用 event / outcome counts 檢查 idempotency；source DB 應維持 read-only。readiness evaluator 只彙總 source coverage、smoke report 與 dashboard availability，輸出的 `production_scheduler_allowed` 固定為 `false`。正式排程前仍需人工 review `docs/06_qa/POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md` 的 source coverage、diagnostics report、backup path、rollback path 與 manual approval steps。

Live vs Research Gap linkage CLI 用來把 portfolio position source trace、Evidence Event / Outcome 與 saved source metadata 串成 gap observation。這是 evidence，不是 action；不修改持倉、不修改 Research Run、不做 lifecycle action，也不是完整實帳歸因。沒有真實交易與人工 override 記錄時，只能解讀為 research / simulated gap。Symbol / date fuzzy match 只會列為 low-confidence candidate，不會當作 confirmed evidence link。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_live_research_gap.py --observation-date 2026-07-08 --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-08 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-08 --confirm --db-path <working-copy-db> --json-output
```

Signal Decay Monitor CLI 用來檢查已保存 forward evidence 與 live gap observation 是否在近期相對長窗轉弱。v1 支援 `event_type`、`event_family`、`strategy_version`、`profile` scope；`factor_name` scope 尚未完成。Research Lab `Evidence Review` 已提供唯讀 Signal Decay 子頁。輸出的 `demote_candidate` / `retire_candidate` 只是 lifecycle proposed payload，不會自動修改策略狀態、策略版本或持倉。樣本不足時只會標示 `insufficient_sample`，不能解讀為策略失敗；缺 benchmark 或 live gap evidence 時會降低 confidence。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_signal_decay.py --observation-date 2026-07-09 --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-09 --scope event_type --scope-id recommendation_included --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-09 --scope all --confirm --db-path <working-copy-db> --json-output
```

`capture_signal_decay.py` 預設 dry-run；`--confirm` 必須指定 explicit `--db-path`，疑似正式 DB 仍需額外 `--allow-production-db-confirm`。一般 QA 與人工審核應使用 working-copy DB。

Decision Quality Review CLI 用來建立週 / 月 / custom 流程覆盤。它只檢查 source trace、journal linkage、manual override、portfolio alert、large live gap、signal decay candidate 與資料品質是否已有覆盤證據；輸出的 score 是 process quality bp，不是投資能力、不是交易建議，也不是責備使用者。Research Lab `Evidence Review` 已提供唯讀 Decision Quality 子頁；CLI 與 repository 仍是資料來源。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_decision_quality.py --start-date 2026-06-01 --end-date 2026-06-30 --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type weekly --start-date 2026-06-24 --end-date 2026-06-30 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type monthly --start-date 2026-06-01 --end-date 2026-06-30 --confirm --db-path <working-copy-db> --json-output
```

`capture_decision_quality_review.py` 預設 dry-run；`--confirm` 必須指定 explicit `--db-path`，疑似正式 DB 仍需額外 `--allow-production-like-db`。缺 journal、缺 source trace 或 sample size 不足都只代表 review gap / warning，需要人工判讀。

Report evidence boundary 固定為：This report is research evidence only. Close-to-close forward return is not executable live performance. No trading recommendation is produced.

### 9.9.2 Evidence Review Manual Smoke / Multi-day Dry-run

Evidence Review UI 完成後，正式 scheduler 前仍需要人工 closeout：

- `docs/06_qa/POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md`：人工檢查 Forward Evidence、Live vs Research Gap、Signal Decay、Decision Quality、boundary banner、empty / degraded / insufficient sample states、read-only guarantee 與無買賣建議語言。
- `docs/06_qa/POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`：記錄 3-5 個交易日的 data update status、source coverage、dry-run pipeline、working-copy confirm smoke、events / outcomes / summary / warnings / blocking gaps、dashboard review 與人工 decision。
- `docs/06_qa/POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md`：描述 Manual run → Multi-day dry-run → Working-copy confirm smoke → Dashboard review → Manual approval checklist → Production scheduler design → explicit approval 後才 implementation。

這些文件只是 QA scaffold；不會建立 production scheduler、Windows Task Scheduler、cron 或 background job。任何 production confirm 未來都需要 backup、rollback、diagnostics 與 explicit human approval；scheduler 不得自動 lifecycle action，也不得自動交易。

### 9.9.3 Evidence Scheduled Dry-run Wrappers

`scripts/scheduled/` 提供 safe scheduled wrappers，用於每日自動產生「可人工檢查」的 freshness 與 evidence dry-run 輸出：

```powershell
.\scripts\scheduled\register_baldr_scheduled_tasks.ps1 -Mode DryRun
.\scripts\scheduled\register_baldr_scheduled_tasks.ps1 -Mode Register
.\scripts\scheduled\unregister_baldr_scheduled_tasks.ps1 -Mode DryRun
.\scripts\scheduled\unregister_baldr_scheduled_tasks.ps1 -Mode Unregister
```

預設 task：

- `baldr-data-freshness-check-daily`：每日 07:30，唯讀檢查 SQLite / `DATA_ROOT` freshness，只寫 `<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json` 與 logs。
- `baldr-evidence-pipeline-dry-run-daily`：每日 07:45，只執行 evidence pipeline dry-run；若 freshness status 不是 `passed`，report status 會標為 degraded / failed。輸出位於 `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/`。
- `baldr-evidence-working-copy-smoke-manual`：預設 disabled / manual-only，只能人工指定 source DB 與 working-copy DB；不得寫 source DB 或 default `DATA_ROOT/sqlite/twstock.db`。

明早檢查步驟見 `docs/07_guides/EVIDENCE_SCHEDULED_MORNING_CHECK.md`。Scheduler QA 紀錄見 `docs/06_qa/POST_V1_EVIDENCE_SCHEDULED_DRY_RUN_QA_2026_07_12.md`。

這些 wrappers 不更新資料、不寫 production evidence DB、不跑 UI、不讀 UI state、不做 portfolio / lifecycle action，也不代表任何訊號或事件類型已被證明有效。

**報告匯出按鈕**：
- 在「實驗摘要」設有「匯出 Excel 報告」按鈕（僅在單股回測成功後啟用）。
- 在「批次結果」設有「匯出批次 Excel」按鈕（僅在批次回測成功後啟用）。
- 在「推薦回放」設有「匯出回放 Excel」按鈕（僅在推薦組合回測成功後啟用）。
- **安全設計**：所有匯出皆在背景線程（`TaskWorker`）執行，防止 UI 卡死，並採用臨時檔寫入後 `os.replace` 原子替換；替換失敗時既有報告保持不變。報告使用執行結果與參數快照，不重跑策略或摘要績效；equity curve 可接受 `日期`、`date` 或日期 index。若元數據缺失，會在「資料完整性」警示中顯示中文欄位名並保留原始代號，例如「資料截止日期（data_as_of_date）」；系統不以目前 UI 值或預設常數代填。

Registry 比較只使用已保存的 metadata、equity curve 與 benchmark_results，不重新抓取目前資料。資料 fingerprint、execution 或 sizing 不同時會標示為「不可直接比較」，並以中文原因顯示如「資料指紋不同」「成交假設不同」「部位 sizing 模式不同」；期間、Universe 或成本不同時會標示為「需謹慎比較」，並以「日期區間不同」「Universe 股票池不同」「交易成本模型不同」等原因提醒，不應直接做優劣排名。標準化權益只在共同日期交集上把每個 run 的第一筆淨值設為 10000；沒有共同日期時不補值、不推估，也不重新計算回測。Registry-based Promote 會先做 Registry Gate，通過後才建立策略版本。

固定組合目前的 Registry 保存粒度是每檔股票的 per-stock run，metadata 會標記為 `fixed_basket_stock` 以保留固定組合來源，並沿用該檔回測產生的 factor records 生成 `factor_snapshot` / `factor_contributions`。完整固定組合層級的現金帳、再平衡、未成交、Liquidity / Gap 風險揭露仍未建成，不應把 per-stock 保存結果解讀為完整可成交的固定組合績效；Month 3 v1 的完整 portfolio credibility 揭露集中在推薦組合回放。

### 9.10 推薦回放

建議從推薦頁按「送 Research Lab 推薦回放」載入配置。

可設定：

- 每次推薦檔數
- 每期候選上限
- 持有天數
- 每週重播或只跑一次：每週重播會在回放期間定期重新產生推薦名單，只跑一次則只用起始日名單。
- 等權或分數加權：等權配置平均分配資金，分數加權會讓高分股票取得較高權重。

執行後可保存到 Research Run Registry。結果頁摘要只顯示一次，並用段落解釋總報酬、最大回撤、交易檔數、資金使用、交易假設、虧損交易占比、最拖累股票、Sharpe / Sortino 與 Monte Carlo P05 / P50 / P95。資金使用代表期間投入金額，不等同最終淨值；Monte Carlo P05 / P50 / P95 分別是偏弱、中位與偏強情境，不是保證績效。期間明細、個股貢獻與交易紀錄在結果頁內部分頁查看，避免被底部區域吃掉。

歷史載入、刪除與 legacy Promote 能力仍保留在舊 repository 邊界；新版 Cross-run Comparison 與 Registry-based Promote Gate 以 Registry run 為準。結果 details 會包含 `portfolio_credibility`、`unfilled_orders`、`cash_ledger`、`weight_exposure` 與 `gap_risk`：若推薦股票在回放視窗內沒有可用價格列，會以 `missing_price_rows` 記錄為未成交，而不是靜默跳過；若呼叫端提供 `max_participation_rate`，系統會用進場日成交股數與收盤價估算可參與金額，配置金額超過時以 `liquidity_limited` 記錄為未成交。回放現在會在建立 holding 前檢查可用現金，現金不足時以 `cash_limited` 記錄為未成交；`cash_ledger` 由這個現金 gate 流程產生買進、賣出與 `ending_cash`。若呼叫端提供 fee / tax / slippage bps，成本會套用到買賣現金流、ledger breakdown 與 `total_transaction_cost`；未提供時維持無成本回放。若呼叫端提供 `lot_size`，配置金額會依進場價向下取整為可成交整股股數，買不起最小交易單位時以 `lot_size_limited` 記錄為未成交。期間持倉的 `allocation_weight` 代表推薦配置的目標權重，`actual_allocation_weight` 代表整股 sizing 與 cash gate 後的實際可成交權重；`weight_exposure` 會依每個再平衡日彙總目標權重、實際權重、未成交權重與殘餘現金權重。若歷史資料含「開盤價」，`gap_risk.records` 會列出每筆 holding 的 `entry_close_price`、下一個可用交易日 `next_open_price`、`gap_pct`、`gap_direction` 與 `severity`，用來揭露同日收盤成交假設在隔日開盤可能遇到的跳空風險。`portfolio_credibility` 仍會揭露同日收盤成交、再平衡現金重用限制、成交量 / Liquidity 與 Gap 限制；目前仍未建零股、委託簿撮合、買賣價差或 gap 實際成交模型，`gap_risk` 只做風險標籤，不會改變 PnL、成交價、cash ledger 或 sizing。這些 warning 應先讀完，再判讀回放績效。結果仍依成交與推薦回放假設，不等同實盤。

## 10. 持倉管理

### 10.1 手動記錄交易

1. 點擊「手動記錄交易」。
2. 輸入股票、買賣別、價格、股數、日期、費用與稅金。
3. 可選擇策略來源並填寫備註。
4. 保存後系統重算持倉與平均成本。

輸入股票代號後，系統會嘗試從 stock master / SQLite 自動補證券名稱；找不到正式代號時會提示。手續費與證交稅會依台股預設值自動估算，使用者仍可手動覆寫。

賣出數量不得超過目前可用持倉。

### 10.2 從推薦或回測建立來源追溯

- 推薦結果表右鍵「記錄到持倉管理」。
- 回測交易明細右鍵記錄交易。

這些入口會保存推薦結果、回測 run 或策略版本來源。它們仍是手動記錄，不會送出券商委託。

目前不要把批次回測排行榜理解成已提供直接加入持倉入口；可記錄到持倉的主要入口是推薦結果表與回測交易明細。

### 10.3 持倉與交易歷史

選取持倉後，右側同步顯示：

- 交易歷史
- 覆盤日誌
- 策略與價格監控
- 生命週期回顧
- 籌碼監控

交易歷史可用右鍵刪除；刪除後持倉與成本會重新計算。

從持倉篩選交易歷史時，交易歷史區會顯示目前篩選狀態，並提供「清除篩選」回到全部交易。

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

目前價格會一併顯示價格日期。手動建立持倉會顯示為「手動建立，無推薦 / 回測來源」，避免誤解為資料缺失。

警示是輔助判讀，不會自動平倉。

### 10.6 生命週期回顧

選取持倉後，右側「生命週期回顧」會顯示：

- Thesis 狀態：假設仍成立、證據降級 / 持續觀察、或假設失效 / 需要覆盤。
- 來源追溯：例如推薦結果、回測 run 或策略版本來源。
- 執行落差：進場平均成本相對來源快照價格的 basis points gap。
- 訊號落差：`PortfolioConditionMonitor` 的 valid / warning / invalid 狀態與原因。
- 市場體制：進場 regime 與目前 regime 是否一致。
- 資料品質：來源 hash、來源品質與 degraded / estimated flags。
- 摘要 tokens：source / execution / signal / market / data_quality 的狀態摘要。

此分頁只做 post-trade attribution 與 live-vs-research gap 判讀，不會自動下單、平倉、調整持倉、刪除策略版本或改寫回測結果。若顯示假設失效，使用者應回到 Research Lab、Registry 比較或覆盤日誌確認原因。

### 10.7 籌碼監控

顯示籌碼風險、近期分點買賣明細與資料品質。風險等級與品質狀態會以繁體中文顯示，原始 key 保留在 tooltip 供除錯。按「下鑽詳細主力流向」會切換至市場觀察的 Smart Money 並定位目前股票。

### 10.8 清空全體數據

此操作會永久清空持倉交易與日誌，需要二次確認。執行前應先確認資料是否已備份。

## 11. Runtime Observatory

這是唯讀工程治理頁，不是選股工具。

Runtime Observatory 只監控 Runtime / Governance 任務、agent workflow 或受治理流程，不監控資料更新、回測或推薦分析的背景任務。資料更新、回測與推薦的進度仍應回到各自功能頁查看。

欄位：

- Objective：目前 Runtime 任務目標；沒有任務時會顯示「尚未指派治理任務」。
- Task Workflow Status：任務流程狀態；IDLE 會顯示為「閒置」，平常閒置屬正常。
- Active Files：目前上下文檔案。
- Overall System State：整體治理狀態，例如「已暫停 / 治理暫停」。
- Rejection Rate：治理拒絕率、趨勢與連續失敗數。
- Last Critical Violation：最近一次重大違規，例如「治理規則違反」。
- Append-only Event Stream：時間、嚴重度、actor、繁中事件摘要與訊息；raw event type 與 payload 保留在 tooltip。

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

若主表有股票但「語意狀態」顯示未計算，先確認 `SmartMoneySemanticService` 是否初始化成功，以及 SQLite `daily_prices` 是否可提供決策日前價格；沒有價格時仍可顯示 5 / 20 / 60 日淨量，但高檔出貨疑慮可能不會產生。

若快速更新在「同步券商分點至 SQLite」遇到同一分點 / 股票 / 日期的買超與賣超唯一鍵衝突，代表 DB 仍是舊三欄主鍵；更新後的流程會在同步前先備份並升級為含 `trade_type` 的主鍵。

### TPEX 股票日價缺漏

若在 SQLite Inspector 查 `3207` 只看到近一兩日，代表 TPEX 歷史補齊或 SQLite 同步未完成。2026-06-17 排查後的正式狀態應可看到 `3207` 覆蓋 `20140102..20260617`、共 2,907 筆。請先檢查 `DATA_ROOT/daily_price_tpex/` 是否有對應日期 CSV，再使用每日股價手動下載、快速/安全更新，或「背景補齊 TPEX + 技術指標」補齊並同步。

### TWSE 股票日價缺漏

若 SQLite Inspector 查 TWSE 股票（例如 `2330`）缺少某個交易日，先檢查 `DATA_ROOT/daily_price/YYYYMMDD.csv` 是否存在；若日檔不存在，代表 TWSE 日檔未下載成功或曾被跳過，需用每日股價手動下載或安全更新補齊該日期範圍後再同步 SQLite。若缺少日期是交易所休市日則屬正常，例如 2026-06-19 為端午節休市。

### 回測 0 交易

依序檢查：

1. 資金是否足夠買一張。
2. 日期範圍是否涵蓋足夠訊號。
3. quantile 是否仍在暖機期。
4. 固定門檻是否過高。
5. 漲跌停、成交量與最大參與率是否拒絕成交。
6. 是否只有期末未平倉部位。

### Promote 按鈕不能使用

確認結果已保存，且驗證狀態不是 FAIL。樣本不足、無結果、未保存、run 已封存、run 已升級、資料完整性不是 valid、缺少參數合約版本、最低 validation gate 未通過、缺 benchmark excess return、factor snapshot 品質不足、regime compatibility 不足或 Month 6 lifecycle gate 未通過時，不允許升級。若策略版本 JSON 已寫入但 Registry 回填失敗，系統會執行補償刪除；刪除失敗時標記 reconciliation required，需進入受控修復流程。

## 13. Manual 覆蓋狀態

| 工作區 | 啟動/入口 | 操作 | 參數 | 結果解讀 | 安全/排錯 |
|---|---:|---:|---:|---:|---:|
| 數據更新 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 市場觀察 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 推薦分析 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 觀察清單 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 每日決策 | 完成（answer-first dashboard） | 完成 | 完成 | 主結論 / 行動等級、焦點卡、quality / warnings 判讀；Market Breadth v1 / Sector Rotation v1 / Relative Strength / Liquidity Ranking v1 / Watchlist Trigger v1 / Portfolio Alert v1 / Smart Money semantics / Why Not v1 / fundamental diagnostics prompts 已接線 | 完成 |
| Research Lab | 完成 | 完成 | 完成 | 完成 | 完成 |
| 持倉管理 | 完成 | 完成 | 完成 | 完成 | 完成 |
| Runtime Observatory | 完成 | 完成 | 不適用 | 完成 | 完成 |

功能行為改動時，必須同步更新本表與對應章節。

完整主 UI 人工 smoke test 母檔維護於 [FULL_APP_HEALTHCHECK_2026_06_16.md](../06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md)。每次修改數據更新、SQLite 檢視、每日決策或跨工作區流程後，除自動化測試外，應依該 healthcheck 做 smoke test。

非破壞式 Full App Healthcheck Runner 可用於開發期間的自動化輔助驗證：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab recommendation --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
```

`--tab` 可用於分頁驗證，目前支援 `update`、`market`、`decision`、`research`、`recommendation`、`watchlist`、`portfolio`、`runtime` 與 `cross-flow`。這些測試只代表已核准的非破壞 direct bridge / QA script 通過；真實資料寫入、刪除、匯出檔案、完整 MainWindow 啟動、視覺判讀與真人互動流程仍要依母檔人工確認。

若需要接近真人 UI 操作的 MainWindow smoke，可明確 opt-in：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
```

這會在隔離子程序啟動真實 PySide6 MainWindow、逐一切換 8 個頂層 tab、保存 startup / resize screenshots、記錄 requested / actual viewport size，並測試 UpdateView 強制重新合併 dialog 的取消路徑。`--ui-smoke-dialog-cancel` 只會按取消，不會按確認；若 destructive action 被呼叫，healthcheck 會失敗。窄 viewport 可能被主視窗最小寬度限制，report 會以 `constrained_by_minimum` 呈現，仍需人工開圖判讀視覺可讀性。

## 14. 更新記錄

- 2026-06-30：縮小 Research Lab 參數最佳化列的 label 留白；強 / 弱勢個股產業共振理由改用最新產業表現快取，正式資料路徑載入由約 13 秒降至約 0.6 秒；Smart Money 集中度、語意狀態、診斷與 Badges 欄改為依最長內容貼合寬度，近期趨勢欄維持 compact 固定寬度且直方圖以緊湊間距與左側 padding 繪製。
- 2026-06-30：Smart Money 右側分點明細表改為依 panel 寬度自適應四欄，移除固定欄寬，優先保留淨買賣超數值與 bar 的顯示空間，避免不必要水平捲動。
- 2026-06-30：每日決策總覽 warnings 與持倉警示來源歸因改為 UI 顯示中文化，底層 warning token 與 DTO 資料維持原樣供除錯追溯。
- 2026-06-30：調整 Research Lab 左側設定面板與 Smart Money 主表欄寬；策略回測長下拉欄位預設可完整顯示，主力流向以 compact 5D/20D/60D 診斷與固定欄寬保留近期趨勢圖。
- 2026-06-30：市場觀察的強 / 弱勢個股與強 / 弱勢產業改為 SQLite-first 快速載入，只讀近期交易日必要欄位；SQLite 不可用時才降級既有 CSV / 舊查詢路徑。
- 2026-06-30：快速更新與安全更新的預設補齊窗口改為結束日前最近 10 個工作日；快速更新仍跳過大型合併但不再只限最近 2 天，降低兩週才開啟程式時漏抓資料的風險。
- 2026-06-30：新增 executable opt-in MainWindow UI smoke 說明；可啟動真實 MainWindow、切換 tab、截圖、測 resize evidence 與 Update 強制合併 cancel dialog，且預設 healthcheck 不會啟動 MainWindow。
- 2026-06-29：補充 Full App Healthcheck Runner 分頁驗證方式；`--tab` 可分別驗證 Update、Market、Decision、Research、Recommendation、Watchlist、Portfolio、Runtime 與 cross-flow 的安全 direct bridge，完整真人 UI smoke test 仍以母檔人工確認為準。
- 2026-07-05：新增 Research Lab `Forward Evidence` 分頁操作說明，標示 Forward Performance Dashboard read-only UI v1 只檢查已保存 evidence summary，不重算策略、不寫 evidence、不建立 scheduler，且 close-to-close forward return 不是實盤可執行績效。
- 2026-07-06：新增 Evidence Pipeline Runner 手動 dry-run CLI 操作說明，標示 runner 預設 dry-run、confirm 只允許 working-copy DB、readiness 最高只到 `ready_for_manual_confirm`，production scheduler 仍未啟用。
- 2026-07-07：新增 working-copy DB smoke 與 scheduler readiness evaluator 操作說明，標示 source DB read-only、repeat confirm idempotency check、`production_scheduler_allowed=false` 與正式排程前人工核准 checklist。
- 2026-07-08：新增 Live vs Research Gap linkage CLI 操作說明，標示 gap observation 是 evidence，不是 action；沒有真實交易與人工 override 時只能解讀為 research / simulated gap。
- 2026-07-09：新增 Signal Decay Monitor CLI 操作說明，標示 decay observation 與 lifecycle proposed payload 只是人工審核 evidence，不自動套用策略生命週期動作。
- 2026-07-10：新增 Decision Quality Review CLI 操作說明，標示 review item 與 process quality score 只作流程覆盤，不是投資能力、交易建議或責備判斷。
- 2026-07-11：新增 Research Lab `Evidence Review` 分頁操作說明，標示 Forward Evidence、Live vs Research Gap、Signal Decay 與 Decision Quality dashboard 只讀已保存 evidence / observation / review，不寫 evidence、不建立 scheduler、不自動 lifecycle action。
- 2026-07-12：新增 Evidence Review manual smoke、multi-day dry-run record 與 scheduler approval SOP 操作說明，標示這些是 production scheduler 前的人工 QA scaffold，不代表 scheduler 已啟用。
- 2026-07-12：Evidence Review UI 介面中文化，Research Lab 結果分頁顯示為「證據覆盤」，四個子頁顯示為「前瞻證據 / 研究落差 / 訊號衰退 / 決策品質」，日期篩選改用日曆選擇器。
- 2026-07-12：證據覆盤頁新增「目前資料庫」資訊列與複製路徑按鈕，協助人工 smoke 時確認 UI 實際讀取的 SQLite DB。
- 2026-07-12：新增 safe scheduled wrappers 操作說明與 morning check guide；每日 task 僅做 read-only freshness check 與 evidence dry-run，working-copy smoke 預設 disabled / manual-only。
- 2026-06-23：完成 Healthcheck Batch 2 計畫範圍實作後的操作說明：Daily Decision Desk answer-first dashboard、Smart Money 5 / 20 / 60 日語意診斷、quantity concentration 與股票焦點下鑽。
- 2026-06-23：完成 Healthcheck Batch 4 Research Lab 結果頁操作說明：推薦回放結果頁重排、Registry 比較中文化與空狀態、批次結果比較目的、Train-Test / Walk-forward 樣本可靠度提示。
- 2026-06-23：同步 Full App Healthcheck 修正後的操作說明；新增全部資料月營收狀態卡、Smart Money Top / Bottom 50 預設與分點雙擊跳轉、推薦分析「加入觀察清單」文案、Watchlist 直接送 Research Lab、Daily Decision warnings 中文化、Research Lab 最大持倉 0=無限制、固定門檻 / 百分位排名 tooltip 與推薦回放保存 / 成交假設提醒。
- 2026-06-23：補充推薦分析 Profile / Regime lifecycle：內建、自訂、策略版本 Profile 來源標示，自訂 Profile 未回測驗證警示，Profile-Regime match / mismatch / bonus / penalty 判讀，以及 mismatch 不直接排除推薦結果的安全限制。
- 2026-06-23：補充 Healthcheck Batch 1 direct fixes：資料源檢查摘要與強制合併確認、Research Lab 模式 / 日期 / Registry 刷新 / 報告缺欄位診斷、持倉管理交易表單與監控中文化，以及 Runtime Observatory 監控範圍。
- 2026-06-23：修正每日股價手動下載 / 快速更新的日期邊界說明；開始日期會納入缺漏檢查，並補充 TWSE 股票日價缺漏排錯方式。
- 2026-06-17：完成 Month 5 Fundamental Layer v1 closeout 說明，確認月營收、季度財報與 P/E 估值已進 factor records / diagnostics；P/B、P/S 已補 guarded presentation policy，官方歷史 PIT 公告日保留為後續治理 residual，基本面仍不接 `ScoringEngine`。
- 2026-06-18：更新每日股價與 TPEX 操作說明，確認手動每日股價、快速更新與安全更新皆納入 TPEX 區間補齊、SQLite 同步與技術指標增量；新增背景補齊 TPEX + 技術指標狀態查詢說明，並修正 `3207` 歷史日價缺漏排錯判斷。
- 2026-06-18：更新每日股價日期選擇與 SQLite 資料檢視操作說明；日期預設空白、日曆定位今天、單一日期可一鍵今日、共用清除會清掉所有日期條件，券商分點篩選可使用下拉選單；背景 TPEX 補齊若技術指標已最新會跳過重算。
- 2026-06-18：修正每日股價大表合併說明與流程；`stock_data_whole.csv` 合併會同時納入 `daily_price/` 與 `daily_price_tpex/`，避免 TPEX 已有最新日檔但合併後大表最新日期落後。
- 2026-06-18：修正快速 / 安全更新模式說明亂碼；補充快速更新仍保留可追溯日檔 CSV、跳過大型合併重寫、券商分點會用 CSV / SQLite 先行跳過既有資料；補充技術指標增量合併缺日期時不直接疊加，避免單股指標檔倍增。
- 2026-06-18：更新 Daily Decision Desk 啟動行為說明，確認每日決策 Snapshot 改為背景載入，主 App 會先顯示工作台再更新每日摘要。
- 2026-06-17：完成 Month 6 Strategy Lifecycle / Portfolio Feedback v1 操作說明，補充 Registry-based Promote lifecycle gate、持倉管理「生命週期回顧」分頁、post-trade attribution 與 live-vs-research gap 判讀限制。
- 2026-06-17：補充 lifecycle evidence 持久化操作語意，說明 promotion applied evidence、demote / retire proposed evidence 與不自動刪除策略版本的安全限制。
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
- 2026-06-16：調整 SQLite 資料檢視日期控件說明，單一日期預設今天，日期區間預設本月 1 日至今天，清除後才不套用日期條件。2026-06-18 已改為預設空白，避免未注意到預填日期而誤套篩選。
- 2026-06-16：更新每日股價操作說明，確認快速 / 安全更新已納入 TPEX official daily close quotes；TPEX CSV 寫入 `DATA_ROOT/daily_price_tpex/`，SQLite 寫入 `daily_prices`，TPEX endpoint timeout 會以警告呈現且不阻斷其他資料同步。
- 2026-06-16：補充 SQLite Inspector 重複欄名防護、券商分點 `broker_flows` 主鍵納入 `trade_type`、TPEX 歷史缺漏判讀，以及 Full App Healthcheck 人工驗證入口。
- 2026-06-16：新增 Month 5 月營收候選資料抓取操作段，記錄今晚要跑的 MOPS snapshot 與 FinMind create_time 兩個 candidate-only CLI、輸出位置、resume / rate limit 與毛利率季度資料邊界。
- 2026-06-16：補充 MOPS first-seen 作為月營收主線候選來源、FinMind 退為備用 / 交叉檢查來源，並新增 `--mops-snapshot-file` 月營收 backfill dry-run 說明；正式 mapping 與 SQLite apply 仍需人工 gate。
- 2026-06-16：更新資料更新頁月營收分頁文案，將 MOPS 快照檔、正式可得日對照檔與版本名稱改為完整中文說明；SQLite 資料檢視白名單新增三張 fundamental tables，可直接檢視 `fundamental_monthly_revenues`。
- 2026-06-16：新增 `scripts/inspect_fundamental_factors.py` 唯讀檢視入口，可確認正式 SQLite 月營收已進 Revenue Factor Pack；目前 2026-05 單月資料可產生 3M trend / new high，YoY / MoM 仍因 baseline 不足只回 diagnostics。
- 2026-06-16：新增 `scripts/build_monthly_revenue_retroactive_baseline_mapping.py`，可從 MOPS snapshot 產生 retroactive baseline 候選 mapping；此來源只供導入日後決策使用，不作官方歷史公告日或導入日前回測。
- 2026-06-17：季度財報 baseline 已正式寫入 `fundamental_statement_items`，並新增 EPS、毛利率、營益率、ROE、業外損益 statement factor diagnostics；PB / PS 來源政策改為 guarded external-observation boundary。
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

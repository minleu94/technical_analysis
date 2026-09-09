# V4 個股研究報告交接

日期：2026-09-08

範圍：個股研究報告 DTO、唯讀 read service、PySide6 view、持倉／觀察清單下鑽與專屬驗收。

整合方式：本次沒有建立 branch/worktree，也沒有執行 repo commit；既有 dirty 檔案未以整檔覆寫。`APPLICATION_MANUAL.md` 已依本交付直接補入對應段落，供 root owner review。

## 交付結果

使用者可以從持倉管理或觀察清單以雙擊、按鈕或右鍵選單開啟同一個 `StockResearchReportDialog`。報告視窗支援代碼搜尋、來源清單上一檔／下一檔、重新載入及返回原頁；返回時透過既有 research context 重新選取原始列，清單本身的篩選／選取狀態不被報告頁改寫。

首屏只放身份、查詢日、最新可用價格、關注理由、主要風險、資料新鮮度、Advice 摘要與來源狀態。其餘資料按分頁延遲呈現，沒有資料時明確顯示原因與既有「數據更新」／保存研究結果入口，不以 0、空字串或假預測補值。

## 變更檔案

| 檔案 | 用途 |
|---|---|
| `app_module/stock_research_report_dtos.py` | `StockResearchReportDTO` 及來源、section、價格／技術、基本面、籌碼、事件／outcome、持倉、Advice、ML 子 DTO。 |
| `app_module/stock_research_report_service.py` | `StockResearchReportReadService.read_report()`；唯讀 SQLite、point-in-time 邊界、既有 freshness probe cadence receipt、每 section 失敗隔離、有限 row、合作式取消。 |
| `app_module/watchlist_analysis_service.py` | 新增公開 `load_result()`，讓 report read service 讀既有保存推薦，不在 UI 重算評分。 |
| `ui_qt/views/stock_research_report_view.py` | `StockResearchReportView`、`StockResearchReportDialog`、bounded Qt table model 與價格圖。 |
| `ui_qt/views/watchlist_view.py` | 觀察清單按鈕／雙擊／右鍵統一發出 `stockResearchRequested`，保留舊 signal 相容性。 |
| `ui_qt/views/portfolio_view.py` | 持倉按鈕／雙擊／右鍵統一發出 `stockResearchRequested`，返回可重新定位持倉。 |
| `ui_qt/main.py` | 建立共用 read service、連接兩個來源頁、管理非模態報告視窗及返回路徑。 |
| `tests/test_stock_research_report_service.py` | 真 SQLite read-back、PIT、空資料、過期、來源 cadence、future／損壞 freshness receipt、Advice 日期缺件與單一來源失敗隔離。 |
| `tests/test_ui_qt_stock_research_report.py` | 真 service UI、ML 不可用、來源 cadence 欄位、鍵盤、窄視窗、競態丟棄舊股票結果及 late-started guard。 |
| `tests/test_ui_qt_stock_research_navigation.py` | 持倉／觀察清單相同 context 入口及返回選股。 |

## 單一資料契約

`StockResearchReportDTO` 的 `schema_version` 為 `stock-research-report.v1`，核心欄位如下：

- 身份：`stock_code`、`stock_name`、`market`、`industry`、`as_of`、`generated_at`。
- 追溯：`sources`（`source_id`、資料日 `data_as_of`、可用時間 `available_at`、`freshness`、`quality`、版本、row count、`frequency`、`expected_period`、`freshness_reason`、限制）。
- 可用性：`sections`、`available_modules`、`attention_reasons`、`key_risks`、`limitations`。
- 內容：`price_points`、`technical`、`fundamentals`、`flows`、`institutional`、`credit`、`shareholding`、`events`／`outcomes`。
- 既有決策資料：`position`、`advice`、`rule_reasons`、`ml`、`research_context`。

金額／價格保留 `Decimal`；績效及曝險使用整數 bp；`to_dict()` 才將 Decimal 序列化為字串。圖表的像素座標也先用 Decimal 計算，僅在 Qt 視覺化邊界轉為整數座標。DTO 強制 `read_only=True`，報告不含下單或持倉修改命令。

### 時間與品質規則

`read_report(stock_code, as_of_date, context, cancel_callback)` 對每個來源套用 `available_at <= as_of`；沒有可得日的資料不會被猜測成可用。若存在明確的 `data_freshness_probe` receipt，報告依 receipt 的官方交易 session／公告 cadence、`expected_period`、本股實際 period 與 `freshness_status` 判讀；receipt 必須是同一查詢日、同一 `data_root`／SQLite 路徑且可重建的 bounded JSON。receipt 缺失、損壞、日期不符或資料根不符時保留來源日期但 freshness 為 `unknown`，不把它硬判成 fresh 或 stale。各 section 可以有自己的 `data_as_of`／`available_at`，整份報告的 `as_of` 只是查詢 cutoff，不代表所有來源同時更新。

- `fresh`：來源 receipt 依官方交易日／公告 cadence 判定為 current 或合法 expected wait，且本股的資料日／公告 period 與 receipt `expected_period` 相符。
- `stale`：來源 receipt 判定為 stale／partial，或 receipt 明確指出本股資料 period 落後 `expected_period`；UI 顯示「過期」與來源 reason。
- `unknown`：沒有合法 receipt、receipt 身分／日期不符、expected period 缺失或無法把本股資料 period 與 receipt 對齊；不能只用資料日早於 cutoff 推論過期。
- `missing`：沒有符合 PIT 邊界的 row；不補零。
- `error`：該來源 query 失敗；其他 section 照常顯示。
- `degraded`／`estimated`：來源存在但品質或欄位不足；保留限制文字。
- `unavailable`：optional owner provider 尚未提供合格結果。

來源表會顯示 cadence、expected period 與 reason，讓週末／假日的上一個官方 session、月營收公告期與季報發布期不被資料日直接比較誤報。`failed`／`unknown` receipt 對已有 row 會降為 partial／degraded；不會因檔案存在、單一旗標或 `MAX(date)` 就升成 current。

## 真實資料覆蓋矩陣

以下是使用 `TWStockConfig` 對正式唯讀 SQLite 的盤點（查詢日 2026-09-08，股票 2330；不修改資料）。Service 對長表只取最近有限 row，表內總筆數不是單次 UI 載入量。

| Report section／source | 可按代碼取得 | 盤點結果 | UI 行為／限制 |
|---|---:|---|---|
| 價格／`daily_prices` | 是 | 3,082 rows；2014-01-02～2026-09-08；最新收盤 2,470、成交股數 28,931,697、成交金額 71,769,230,740 | 報告最多讀 120 筆；最新可用價格與日期可追溯。 |
| 技術／`technical_indicators` | 是 | 3,091 rows；2014-01-02～2026-09-08 | 最多讀 120 筆價格上下文，技術快照按最新 PIT row；不在 UI 另算指標。 |
| 營收／`fundamental_monthly_revenues` | 是 | 147 rows；`available_at` 約 2026-06-17～2026-07-15 | 只顯示公告／可得日已到 cutoff 的觀察；每表 bounded 24 rows 先按報告 `as_of_date`（缺件才用 `period`）取最新期，再按 `available_at` 選版本；freshness 依月營收公告 cadence receipt 判定，未達 expected period 才標示過期。 |
| 財報／`fundamental_statement_items` | 是 | 1,209 rows；`available_at` 主要為 2026-06-17，品質多為 degraded；最新合法報告期為 2023-Q4（`as_of_date=2023-12-31`） | 顯示來源品質與限制，不把缺欄位當成完整財報；bounded 24-row 投影先按報告期／資料日排序，不讓晚取得的歷史 row 擠掉最新期。 |
| 估值／`fundamental_valuation_metrics` | 是 | 2 rows；可得日 2026-06-15～2026-08-06；含 PE 約 31.8、產業半導體業 | 只呈現實際欄位；不由 UI 推導目標價或勝率。 |
| 分點／`broker_flows` | 是 | 6,993 rows；2025-10-24～2026-09-08 | 最多讀 120 筆；買賣股數／千元金額可追溯；不在 UI 另寫主力評分。 |
| 法人／`institutional_flows` | schema 可查 | 2330 盤點 0 rows | 顯示缺資料；不以空白補 0，更新入口由數據更新 owner 維護。 |
| 信用／`credit_transactions` | schema 可查 | 2330 盤點 0 rows | 同上，section 不阻斷價格與基本面。 |
| 集保／`tdcc_shareholding` | schema 可查 | 2330 盤點 0 rows | 同上。 |
| 產業／事件／`evidence_events` | 是 | 28 events；`available_at` 約 2026-07-30～2026-08-18；正式 DB 對應 outcomes 盤點 0 | 事件顯示原因／風險；沒有 outcome 就明確說沒有後續結果，不製造績效。 |
| 持倉／PortfolioService | 依既有服務 | 本次正式盤點對 2330 未查到持倉 row | 無持倉時顯示「只對現有持倉提供判讀」；有持倉時才映射成本、損益、曝險與 Health。 |
| Advice／保存推薦結果 | 依 `result_id` | 只讀 `WatchlistAnalysisService.load_result()` 與既有 `AdviceComposer` | 無保存結果顯示缺資料；不另寫股票評分。Advice 仍受既有 policy／資料品質限制。 |
| ML | optional provider | 預設未接入合格個股 ML read provider | 顯示 unavailable 與限制；不顯示機率、目標價、勝率或假模型版本。 |

依 root 最新 canonical freshness receipt 的正式讀回，2330 的價格／技術／分點為 fresh，月營收／季報為 stale；法人／信用／集保、持倉、Advice、ML 依實際缺件維持 missing 或 unavailable。最新合法財報 period 為 2023-Q4（`as_of_date=2023-12-31`），不再被 2014 歷史 row 的較晚 available date 擠掉。`available_modules` 只列真的有資料的 `price`、`technical`、`fundamental`、`flows`、`industry_events`、`history`。

### 正式設定唯讀 read-back

以 `TWStockConfig()` 的正式設定執行 `StockResearchReportReadService.read_report("2330", as_of_date="2026-09-08")`，未呼叫任何更新／寫入入口。實際結果保存於 ignored QA artifact：
`output/v4_stock_research_report_ui_20260908/formal_readback_2330.json`。

最新修補後的同樣唯讀 read-back 為 `output/v4_stock_research_report_ui_20260908/formal_readback_2330_final.json`；前一份保留作變更前後對照，不作唯一證據。

先前 artifact `formal_readback_2330_final.json` 是 freshness receipt 尚未更新時的 fail-safe 只讀快照；其後 root 以最新唯讀 probe 重建 canonical receipt 並獨立讀回：source status 共 24 筆，7 current、2 stale、14 not_applicable、1 unknown；2330 的價格／技術／分點為 fresh，月營收／季報為 stale。排序修補後的隔離 read-back 保存於 `output/v4_stock_research_report_ui_20260908/formal_readback_2330_period_fix.json`，證明最新合法財報 period 為 2023-Q4（`as_of_date=2023-12-31`）；兩者均為 read-only，不改寫 D 原始資料，也不把缺少 receipt 或延後 probe 時間冒充歷史信用。

## UI 與操作路徑

### 從觀察清單

1. 在「觀察清單」保留原有搜尋／篩選，選取一列。
2. 按「查看選中個股研究報告」、雙擊列，或右鍵選「查看個股研究報告」。
3. 報告上方輸入代碼後按 Enter／「載入個股報告」可切股；若來自清單，上／下一檔只使用目前 model 中的代碼。
4. 按「返回原持倉或觀察清單」或關閉視窗，MainWindow 依 context 回到觀察清單並重新選取原列；既有清單篩選不由報告 view 修改。

### 從持倉管理

1. 在持倉表選取一列，按「查看個股研究報告」、雙擊列，或右鍵選「查看個股研究報告」。
2. 報告同樣進入上述單一視圖；持倉專屬資料在「持倉／Health／Exit」分頁出現。
3. 返回會回到持倉管理並重新選取該股票，保留既有交易歷史／日記篩選狀態；報告不修改持倉。

### 報告分頁

| 分頁 | 內容 |
|---|---|
| 摘要 | 身份、價格、注意／風險、Advice、來源與 freshness。 |
| 價格／技術 | 最近有限價格表、收盤價圖、技術快照。 |
| 基本面／營收財報 | 實際取得的營收、財報、估值與每筆資料日期。 |
| 籌碼／產業事件 | 分點、法人／信用／集保（有才顯示）、事件及可用 outcomes。 |
| 持倉／Health／Exit | 成本、損益、曝險、既有 Health；Exit 若 owner 未提供則 unavailable。 |
| Rule／ML／歷史 | 既有 Rule／Advice 理由、ML metadata／解釋（有合格結果才顯示）、歷史事件與後續結果。 |

載入由 `TaskWorker` 執行；每次請求都有 request id 與股票代碼 guard。切換 A→B 時，A 的晚到結果會被丟棄；關閉時合作式取消並等待 worker native thread finished，不使用 `terminate()`。

## 其他 owner 的介面需求

- Health：目前透過既有 `PortfolioConditionMonitor.evaluate()` 與 `PositionHealthService.evaluate(stock_code=..., condition_result=..., feedback_status=..., source_trace=...)` 讀取；若 owner 改契約，請保留可序列化的 status、label、reasons、source trace。
- Exit：本交付只保留 `exit_provider` optional read callback；provider 未接入時顯示 unavailable。請提供唯讀、按股票／持倉、帶 cutoff 的結果，並包含 status、reasons、source trace／時間，不要在 UI 補算。
- Formal／Direct：本交付不宣稱這些模組存在，也不把研究 Advice 轉成交易指令。若接入，請提供唯讀 snapshot、版本、決策日、資料日、品質與限制，並維持既有確認／記錄流程。
- 更新器：缺資料文字指向既有「數據更新」入口；更新器 owner 不需改 UI contract。若需精確跳轉，請提供穩定的 update action／route id，而不是讓 report service 直接啟動更新。
- ML：請提供 optional read provider，輸入至少為 `stock_code` + cutoff，輸出模型版本、dataset 版本、推論時間、研究／正式狀態、可解釋文字與品質；不提供合格結果時保持 unavailable。

本輪已盤點既有 Exit／ML read model：Exit 目前是 aggregate／observation builder，ML 需要 feature rows、frozen artifact 與 inference context，沒有可直接按股票及 cutoff 讀取的合格 provider。因此 MainWindow 只注入已有 Portfolio／Health／Watchlist read service；Exit／ML 維持 unavailable，不把 aggregate 或缺少 PIT 的結果投影成個股報告。

## 驗收與畫面驗證

已通過的專屬測試（本輪新增 cadence／receipt／race 覆蓋）：

```text
tests/test_stock_research_report_service.py
tests/test_ui_qt_stock_research_report.py
tests/test_ui_qt_stock_research_navigation.py
20 passed
```

可重跑命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_stock_research_report_service.py tests\test_ui_qt_stock_research_report.py tests\test_ui_qt_stock_research_navigation.py -q -o addopts= -p no:cacheprovider --tb=short
```

涵蓋真 SQLite read-back、PIT 排除未來價格／事件／outcome、空資料、過期資料、週末官方 session、月／季 cadence、future／損壞 freshness receipt、Advice data_date 缺件、單一來源失敗、Advice／ML 缺資料、有限 sample、context 不洩漏原股票身份、鍵盤 Enter、375px 窄視窗、同一 DTO context 入口與 A/B 切股競態。UI 測試使用實際 `StockResearchReportReadService`，不是只 mock widget。

指定整合驗證結果：

| 命令 | 結果 |
|---|---|
| `pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=` | 81 passed |
| `scripts/qa_validate_update_tab.py` | 25 passed、0 failed、4 skipped；報告只寫入 ignored `output/qa/` |
| `mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | Success；585 source files，只有既有 untyped-body notes |
| changed Python files `py_compile` | 通過 |

本次三個測試已加入 `qa/full_app_healthcheck/test_inventory.py`。整體 inventory audit 仍會回報 repo 在本任務前已存在的未註冊測試／舊文件數量基線：新增註冊後為 31 個 missing inventory paths、3 個 documentation count drift；這不是本功能的失敗，請 root owner 在清冊專案整合時一併重算，不要把本次三個測試移除以掩蓋基線。

Root 整合 read-back（2026-09-08）另回報最新全域驗收 `777/777`；其中本片報告 suite `20 passed` 加上更新頁 workbench `81 passed` 為 `101 passed`，全域 mypy 為 585 source files，`qa_validate_update_tab.py` 為 25 passed、0 failed、4 skipped。這些數字與本 handoff 的專屬命令分開記錄；早期 inventory audit 的 31 missing paths／3 documentation count drift 是修補前紀錄，已於 root 整合清冊消除。

畫面驗證項目：

- 375px 寬度仍可建立 view，搜尋／載入／返回 controls 有 accessible name 與 tooltip。
- 表格 cell 提供完整 tooltip，長限制文字可選取，圖表有文字替代與價格表；價格圖的 Qt painter 已使用明確 `QColor`／畫筆寬度並在 `finally` 結束，且測試實際觸發 `grab()` 重繪驗證。
- freshness／quality 同時用文字與狀態色呈現，不依賴顏色單獨傳意。
- 報告視窗最小寬度 360px；view `minimumSizeHint()` 為 320px，DPI／小視窗不要求載入完整歷史。

已由 deterministic SQLite fixture 讀回 2330 並產生首屏畫面：
`C:\Users\archi\.codex\visualizations\2026\09\08\01a07f42-fcba-7952-bc12-971ae2d0878e\stock_research_report_2330_final.png`。
畫面檢查確認身份、價格／資料日、freshness、缺資料／ML 限制、分頁與來源表可讀；這是 UI layout evidence，不宣稱 fixture 是正式資料覆蓋證據。
另以 375×280 logical view 截取窄版畫面，確認搜尋／導航列換行、分頁由 Qt tab overflow controls 保持可切換：
`C:\Users\archi\.codex\visualizations\2026\09\08\01a07f42-fcba-7952-bc12-971ae2d0878e\stock_research_report_2330_final_narrow.png`。

## Root 整合清單

1. Review 本交付新增／修改檔案與既有 dirty diff，確認只挑本任務內容；本次也新增了三筆 test inventory 分類。
2. 個股研究報告與 freshness 文字已直接整併到 `docs/07_guides/APPLICATION_MANUAL.md`：資料更新 `### 4.2` 後、觀察清單 `### 7.3`。不保留平行補丁檔，root review 時只需核對正式 Manual 與本 handoff。
3. 依 root 的資料更新、Health、Exit、Formal、Direct、ML owner 契約補 provider wiring；沒有 provider 時保留 unavailable 文案。
4. 執行下方完整驗證命令，確認本地 PySide6／SQLite 環境可用，再決定是否納入 release gate。`81 passed` 與 `25 passed／4 skipped` 是既有更新頁共同 gate；本交付自己的報告 suite 是上方明列的 `20 passed`，各測試集合維持分開記錄。

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe -m py_compile app_module\stock_research_report_dtos.py app_module\stock_research_report_service.py app_module\watchlist_analysis_service.py ui_qt\views\stock_research_report_view.py ui_qt\views\watchlist_view.py ui_qt\views\portfolio_view.py ui_qt\main.py tests\test_stock_research_report_service.py tests\test_ui_qt_stock_research_report.py tests\test_ui_qt_stock_research_navigation.py
```

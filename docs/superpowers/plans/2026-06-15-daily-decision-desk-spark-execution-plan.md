# Daily Decision Desk Spark Execution Plan

> **For agentic workers:** 本文件是交給 GPT-5.3-Codex-Spark 的受控執行計畫。Spark 必須逐一 Work Package 執行，不得跨包擴張 scope。任何架構邊界、資料流、量化安全或文件權威判斷，先交由 GPT-5.5 Tech Lead / Architect 審查。

**Goal:** 建立 Month 4「Daily Decision Desk」的最小可用前置架構，透過 application service / DTO 聚合既有市場狀態、Market Breadth、Sector Rotation、Watchlist Trigger 與 Portfolio Alert。

**Architecture:** Daily Decision Desk v1 必須以 service snapshot 聚合既有治理後結果，不在 UI 層重算 scoring、screening、portfolio 或 broker flow 邏輯。第一階段只做可測、可讀、可逐步接 UI 的 v1，不做資料 schema migration、不寫正式資料、不宣稱已完成完整每日決策閉環。

**Tech Stack:** Python、PySide6、pytest、既有 `app_module` service / DTO pattern、既有 `ui_qt` view pattern。

---

## Overall Goal

建立 Month 4「Daily Decision Desk」的最小可用前置架構：用新的 application service / DTO 聚合既有市場狀態、Market Breadth、Sector Rotation、Watchlist Trigger 與 Portfolio Alert，不在 UI 層重算 scoring / screening / portfolio / broker flow 邏輯，不改既有策略、回測、推薦核心，也不破壞 Scoped SSOT 文件導航。

本計畫假設第一階段只做「可測、可讀、可逐步接 UI」的 v1，不做資料 schema migration、不寫正式資料、不宣稱 Daily Decision Desk 已完全取代現有 7 個工作區。

## Work Packages

### WP-0：GPT-5.5 架構核准，不交給 Spark

**範圍：** 確認 Daily Decision Desk v1 的 DTO 欄位、服務邊界、資料品質欄位與不重算原則。

**可修改檔案：** 無。

**驗收標準：**

- 明確決定 `DecisionDeskSnapshot` 應包含哪些 sections。
- 明確標示哪些資料只能 read-only 聚合。
- 明確禁止改 `ScoringEngine`、`RecommendationService`、`backtest_module/`、正式資料 schema。

**建議測試：** 不需要。

**原因：** 這是架構決策與風險邊界，不應交給 Spark 自行推斷。

### WP-1：Decision Desk DTO 與空骨架 Builder

**可交給 Spark：** 是。

**允許修改檔案：**

- `app_module/decision_desk_dtos.py`
- `app_module/decision_desk_service.py`
- `tests/test_decision_desk_service.py`

**禁止修改：**

- `ui_qt/`
- `decision_module/`
- `backtest_module/`
- `app_module/recommendation_service.py`
- `app_module/backtest_service.py`

**工作內容：**

- 新增 frozen dataclass DTO：`DecisionDeskSnapshot`、`DecisionDeskSectionStatus`、`MarketRegimeSummary`、`MarketBreadthSummary`、`SectorRotationSummary`、`WatchlistTriggerSummary`、`PortfolioAlertSummary`。
- 新增 `DecisionDeskSnapshotBuilder`，先支援注入 fake provider，回傳完整但保守的 snapshot。
- 所有 section 必須有 `as_of_date`、`quality`、`warnings`。

**驗收標準：**

- 沒有任何 UI 依賴。
- builder 不直接讀寫正式資料。
- 缺資料時回傳 `quality="missing"` 或 `quality="degraded"`，不中斷整體 snapshot。

**建議測試：**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_dtos.py app_module\decision_desk_service.py
```

### WP-2：Market Breadth Read-only Service

**可交給 Spark：** 是。

**允許修改檔案：**

- `app_module/market_breadth_service.py`
- `tests/test_market_breadth_service.py`

**禁止修改：**

- `data_module/db_manager.py`
- SQLite schema
- 任何正式資料檔

**工作內容：**

- 新增 `MarketBreadthService`，以注入 DataFrame / provider 為主要測試入口。
- 計算上漲 / 下跌 / 平盤家數、20 / 60 日新高新低、成交量擴散率的 DTO-friendly dict 或 dataclass。
- 若資料不足，回傳 warning，不補假資料。

**驗收標準：**

- 單元測試不依賴真實 `DATA_ROOT`。
- 日期欄位不得用裸 `pd.to_datetime(series)` 誤解 `YYYYMMDD`，必要時用明確格式解析。
- 只讀資料，不建立或修改 SQLite 表。

**建議測試：**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_market_breadth_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\market_breadth_service.py
```

### WP-3：Sector Rotation Service

**可交給 Spark：** 是。

**允許修改檔案：**

- `app_module/sector_rotation_service.py`
- `tests/test_sector_rotation_service.py`

**禁止修改：**

- `decision_module/industry_mapper.py`
- `decision_module/stock_screener.py`
- `app_module/recommendation_service.py`
- `ui_qt/`

**工作內容：**

- 聚合既有產業指數資料，輸出產業相對強度、5 / 20 日變化、資料日期與品質。
- 不改 `IndustryMapper` 與 `StockScreener`。
- 不把 sector ranking 寫進 recommendation scoring。

**驗收標準：**

- 測試覆蓋正常資料、缺日期、資料不足。
- 結果排序穩定，同分時有 deterministic tie-breaker。
- 無裸金融核心 float 計算；展示 / analytics 邊界可接受，但需保持隔離。

**建議測試：**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_sector_rotation_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\sector_rotation_service.py
```

### WP-4：Watchlist Trigger Service

**可交給 Spark：** 是。

**允許修改檔案：**

- `app_module/watchlist_trigger_service.py`
- `tests/test_watchlist_trigger_service.py`

**工作內容：**

- 讀取 watchlist / universe 的股票清單，和注入的 ranking / breadth / price snapshot 比對。
- 輸出新進候選、強度提升 / 下降、資料不足、風險提示。
- 不自動新增 / 刪除 watchlist item。

**驗收標準：**

- 不修改 `app_module/watchlist_service.py` 的儲存行為。
- trigger 是 read-only summary，不做推薦分數重算。
- 缺 ranking provider 時可回傳 degraded snapshot。

**建議測試：**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_watchlist_trigger_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\watchlist_trigger_service.py
```

### WP-5：Portfolio Alert Aggregator

**可交給 Spark：** 是，但需 GPT-5.5 審查。

**允許修改檔案：**

- `app_module/portfolio_alert_service.py`
- `tests/test_portfolio_alert_service.py`

**工作內容：**

- 聚合 `PortfolioService.list_positions()`、`PortfolioConditionMonitor.evaluate()`、可注入 chip summary provider。
- 輸出 alert counts、最高風險持倉、來源追溯摘要。
- 不修改交易、持倉、日誌或清空流程。

**驗收標準：**

- 測試使用 fake services，不寫 portfolio store。
- 不新增裸 `float` 核心計算。
- alert 僅輔助判讀，不自動平倉或下單。

**建議測試：**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile app_module\portfolio_alert_service.py
```

### WP-6：DecisionDeskSnapshotBuilder 整合各聚合服務

**可交給 Spark：** 是。

**允許修改檔案：**

- `app_module/decision_desk_service.py`
- `tests/test_decision_desk_service.py`

**工作內容：**

- 將 WP-2 到 WP-5 的 services 以 dependency injection 接入 builder。
- 每個 section 失敗時只降級該 section，整體 snapshot 仍可回傳。
- 增加 `generated_at`、`overall_quality`、`warnings`。

**驗收標準：**

- 任一子服務丟例外時，snapshot 不崩潰。
- 不在 builder 內直接重算 scoring / portfolio domain 邏輯。
- 測試涵蓋全成功、部分失敗、全部缺資料。

**建議測試：**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py tests\test_market_breadth_service.py tests\test_sector_rotation_service.py tests\test_watchlist_trigger_service.py tests\test_portfolio_alert_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_service.py
```

### WP-7：Daily Decision Desk Qt View

**可交給 Spark：** 是，限 UI 接線，不做架構判斷。

**允許修改檔案：**

- `ui_qt/views/decision_desk_view.py`
- `tests/test_ui_qt_decision_desk_view.py`

**暫不允許修改：**

- `ui_qt/main.py`

**工作內容：**

- 新增 `DecisionDeskView`，接受 `DecisionDeskSnapshotBuilder` 或 fake builder。
- 顯示 market regime、breadth、sector、watchlist、portfolio alert 五個區塊。
- 加入刷新按鈕與錯誤 / 降級狀態文字。

**驗收標準：**

- offscreen Qt test 可建立 view 並刷新 fake snapshot。
- View 不直接呼叫 `RecommendationService`、`StockScreener`、`PortfolioService`。
- UI 文字使用繁體中文。

**建議測試：**

```powershell
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\decision_desk_view.py
```

### WP-8：主視窗掛載 Daily Decision Desk Tab

**可交給 Spark：** 是，但必須在 WP-7 通過後。

**允許修改檔案：**

- `ui_qt/main.py`
- `tests/test_ui_qt_decision_desk_main_integration.py` 或既有合適 UI 測試檔

**工作內容：**

- 在 `MainWindow` 初始化 services 後建立 builder。
- 新增頂層 Tab 名稱建議：「每日決策」。
- 不移除既有 7 個工作區；只新增入口。

**驗收標準：**

- MainWindow 可在 fake / offscreen 條件建立。
- 現有 tab 不被移除或重新命名。
- 失敗時不阻斷整個 app 啟動，可顯示降級。

**建議測試：**

```powershell
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_market_regime_view.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m py_compile ui_qt\main.py ui_qt\views\decision_desk_view.py
```

### WP-9：文件同步

**可交給 Spark：** 可做 Patch，但 Coverage 與最終審查由 GPT-5.5。

**允許修改檔案：**

- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/01_architecture/system_architecture.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
- `PROJECT_NAVIGATION.md`

**工作內容：**

- 將 Daily Decision Desk 從「尚未完成」更新為「v1 已有入口」的精準狀態，僅在 WP-8 完成後。
- Manual 補入口、操作、參數 / 資料品質、結果判讀、安全限制與排錯。
- Architecture 補 service snapshot 聚合邊界。

**驗收標準：**

- 不宣稱推薦更準、不宣稱實盤績效。
- 不把 Roadmap Hub 變回大型歷史文件。
- Index 只做導航，不作狀態權威。

**建議測試：**

```powershell
rg "Daily Decision Desk|每日決策|尚未完成|目前可用" docs PROJECT_NAVIGATION.md
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_dtos.py app_module\decision_desk_service.py ui_qt\views\decision_desk_view.py
```

## Dependency Order

1. WP-0：GPT-5.5 核准 DTO / service 邊界。
2. WP-1：DTO 與 builder 骨架。
3. WP-2、WP-3、WP-4、WP-5：可平行交給不同 Spark session。
4. WP-6：整合所有聚合服務。
5. WP-7：建立 Qt view。
6. WP-8：掛入 `ui_qt/main.py`。
7. WP-9：文件同步。
8. GPT-5.5 final review：架構、風險、測試、文件一致性、git exclusion。

## Risk Areas

- Daily Decision Desk 不得在 UI 層複製 scoring、screening、portfolio、broker flow 計算。
- 不得修改 `ScoringEngine`、`RecommendationService`、`backtest_module/` 來迎合首頁。
- SQLite 必須 read-only；不得新增 schema、migration 或重建資料。
- 日期解析要避免 `YYYYMMDD` 被誤判為 epoch。
- Portfolio alert 不得自動下單、平倉、刪交易或改日誌。
- 文件不得提前把 Daily Decision Desk 描述成完整閉環；只能描述實際完成程度。
- UI 修改後必跑 Update Tab 既有 QA，避免主視窗整合破壞既有頁。

## Spark Prompts

### Prompt for WP-1

```text
你是本專案 Execution Agent。只執行 WP-1。

請先閱讀 AGENTS.md 指定必讀文件，尤其 shared_context、PROJECT_SNAPSHOT、system_architecture、execution_agent。

任務：新增 Daily Decision Desk 的 DTO 與 snapshot builder 骨架。

允許修改：
- app_module/decision_desk_dtos.py
- app_module/decision_desk_service.py
- tests/test_decision_desk_service.py

禁止修改其他檔案。不得改 UI、不得改推薦/回測/策略核心、不得寫正式資料。

驗收：
- builder 可用 fake provider 建立完整 snapshot。
- 每個 section 有 as_of_date、quality、warnings。
- 缺資料不中斷整體 snapshot。

請先輸出標準回滾清單，再實作，最後執行：
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_dtos.py app_module\decision_desk_service.py
```

### Prompt for WP-2

```text
只執行 WP-2：Market Breadth read-only service。

允許修改：
- app_module/market_breadth_service.py
- tests/test_market_breadth_service.py

禁止修改 data_module、SQLite schema、正式資料、UI。

請用注入 DataFrame/provider 的方式測試，不依賴 DATA_ROOT。日期解析需明確處理 YYYYMMDD / YYYY-MM-DD。缺資料回傳 degraded/missing 與 warnings，不補假資料。

測試：
.\.venv\Scripts\python.exe -m pytest tests\test_market_breadth_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\market_breadth_service.py
```

### Prompt for WP-3

```text
只執行 WP-3：Sector Rotation service。

允許修改：
- app_module/sector_rotation_service.py
- tests/test_sector_rotation_service.py

禁止修改 IndustryMapper、StockScreener、RecommendationService、UI。

輸出產業相對強度、5/20 日變化、as_of_date、quality、warnings。排序需穩定，資料不足需降級。

測試：
.\.venv\Scripts\python.exe -m pytest tests\test_sector_rotation_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\sector_rotation_service.py
```

### Prompt for WP-4

```text
只執行 WP-4：Watchlist Trigger service。

允許修改：
- app_module/watchlist_trigger_service.py
- tests/test_watchlist_trigger_service.py

禁止修改 watchlist_service 的寫入行為，不可新增/刪除 watchlist item，不可重算推薦分數。

使用 fake watchlist/ranking provider 測試，輸出新進候選、強度提升/下降、資料不足與風險提示。

測試：
.\.venv\Scripts\python.exe -m pytest tests\test_watchlist_trigger_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\watchlist_trigger_service.py
```

### Prompt for WP-5

```text
只執行 WP-5：Portfolio Alert Aggregator。

允許修改：
- app_module/portfolio_alert_service.py
- tests/test_portfolio_alert_service.py

禁止修改 PortfolioService、PortfolioStore、JournalService、portfolio_module/core.py，不得寫入或刪除持倉資料。

使用 fake portfolio service、fake condition monitor、fake chip provider 測試。Alert 僅提供 summary，不自動交易。

測試：
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile app_module\portfolio_alert_service.py
```

### Prompt for WP-6

```text
只執行 WP-6：整合 DecisionDeskSnapshotBuilder。

允許修改：
- app_module/decision_desk_service.py
- tests/test_decision_desk_service.py

禁止修改各子 service 已通過的 public behavior。不得改 UI。

將 market breadth、sector rotation、watchlist trigger、portfolio alert 以 dependency injection 接入 builder。任一子服務失敗只降級該 section。

測試：
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py tests\test_market_breadth_service.py tests\test_sector_rotation_service.py tests\test_watchlist_trigger_service.py tests\test_portfolio_alert_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_service.py
```

### Prompt for WP-7

```text
只執行 WP-7：Daily Decision Desk Qt View。

允許修改：
- ui_qt/views/decision_desk_view.py
- tests/test_ui_qt_decision_desk_view.py

禁止修改 ui_qt/main.py。View 只能呼叫 DecisionDeskSnapshotBuilder 或 fake builder，不得直接呼叫推薦、回測、Portfolio domain service。

使用繁體中文 UI 文字。需支援刷新與 degraded/missing 狀態顯示。

測試：
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\decision_desk_view.py
```

### Prompt for WP-8

```text
只執行 WP-8：將 Daily Decision Desk 掛入主視窗。

允許修改：
- ui_qt/main.py
- tests/test_ui_qt_decision_desk_main_integration.py

禁止移除或重新命名既有工作區。新增頂層 Tab「每日決策」。初始化失敗時需降級，不可阻斷整個 app。

測試：
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_market_regime_view.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m py_compile ui_qt\main.py ui_qt\views\decision_desk_view.py
```

### Prompt for WP-9

```text
只執行 WP-9：文件同步 Patch Pass。

前提：WP-8 已完成且 GPT-5.5 已確認功能狀態。

允許修改：
- docs/07_guides/APPLICATION_MANUAL.md
- docs/01_architecture/system_architecture.md
- docs/00_core/PROJECT_SNAPSHOT.md
- docs/00_core/ROADMAP_6M_ENGINEERING.md
- docs/00_core/DEVELOPMENT_ROADMAP.md
- docs/00_core/DOCUMENTATION_INDEX.md
- docs/02_features/UI_FEATURES_DOCUMENTATION.md
- PROJECT_NAVIGATION.md

不得修改其他文件。不得宣稱推薦更準、不得宣稱實盤績效、不得把 Roadmap Hub 寫成大型歷史文件。請依 DOC_COVERAGE_MAP 更新使用者入口、操作、結果判讀、安全限制與排錯。
```

## Review Checklist

- Work package 是否只修改允許檔案。
- 是否未碰正式資料、SQLite schema、migration、資料重建。
- 是否未修改 `ScoringEngine`、`RecommendationService`、`backtest_module/`。
- DTO 是否有 `as_of_date`、`quality`、`warnings`。
- Builder 是否能 partial failure degraded，而不是整體崩潰。
- UI 是否只讀 snapshot，不直接重算 domain 邏輯。
- 是否無未標記的金融核心裸 `float`。
- 日期解析是否避開 `YYYYMMDD` epoch 誤判。
- UI 修改後是否跑 Update Tab pytest、QA script、py_compile，必要時跑 mypy。
- 文件是否遵守 Scoped SSOT：Snapshot 現況、6M Roadmap 未來、Architecture 邊界、Manual 操作、Index 導航。
- `git status --short` 是否只有本任務檔案；不可 stage `output/qa/update_tab/*` 這類易變 tracked QA output，除非任務明確要求。

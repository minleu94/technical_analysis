# TASK-LOOP-02 MARKET 交接

## 交接狀態

TASK-LOOP-02 的市場狀態、廣度、產業輪動、相對強弱與強弱排名閉環已完成隔離工程驗收。服務層現在能以指定決策日凍結可用資料，將實際有效日期、品質、警告、來源 ID 與排名包成應用層 DTO；既有 `tuple[DataFrame, int]` 與產業 `DataFrame` 回傳仍可透過相容邊界使用。本卡未執行網路來源、正式資料更新、Watchlist writer、ScoringEngine 或任何 promotion；本文件代表工程驗證完成，不代表正式市場資料已接受。

基線與目前工作樹仍以 `git rev-parse HEAD` 所見的既有 commit 為準；本卡未 stage、commit 或 push。工作樹同時包含其他任務的未提交變更，回滾必須依檔案 owner 分開處理。

## 變更邊界

| 檔案 | 變更 | 交接意義 |
|---|---|---|
| `app_module/dtos/market_loop_dtos.py` | 新增 | 定義 Regime、Breadth、Sector、Relative Strength 與 Screening DTO；保留決策日／有效日、品質、警告、來源與可序列化排名。 |
| `app_module/regime_service.py` | 修改 | 新增明確日期的 Regime DTO 入口與 `as_of_date` 相容參數；預設不持久化 regime history，避免市場觀測寫入正式輸出。 |
| `app_module/market_breadth_service.py` | 修改 | 新增 DTO wrapper；單筆歷史 fallback 必須小於等於決策日並標示 degraded／警告；未識別日期或未來單筆資料不再被猜成有效。 |
| `app_module/sector_rotation_service.py` | 修改 | 新增 Sector DTO wrapper，沿用既有 Decimal／整數基點排名與來源警告。 |
| `app_module/relative_strength_liquidity_service.py` | 修改 | 新增 Relative Strength DTO wrapper，沿用既有有效歷史窗口、流動性與跳過比例品質。 |
| `app_module/screening_service.py` | 修改 | 新增日期凍結的股票／產業 DTO 入口；在傳給既有 screener 前先裁切 `日期 <= decision_date`，並保留 tuple／DataFrame 相容 API。 |
| `ui_qt/views/market_regime_view.py` | 修改 | 優先使用 Regime DTO，僅在舊 fake service 沒有 DTO 入口時走測試相容路徑；UI 不查 DB。 |
| `ui_qt/views/strong_stocks_view.py`、`ui_qt/views/weak_stocks_view.py` | 修改 | 優先消費 Screening DTO 的相容投影；加入觀察清單流程維持既有 command port。 |
| `ui_qt/views/strong_industries_view.py`、`ui_qt/views/weak_industries_view.py` | 修改 | 優先消費產業 Screening DTO 的 DataFrame 投影；UI 不查 DB、不讀 CSV、不重算排名。 |
| `scripts/qa_validate_market_loop.py` | 新增 | 以記憶體 fixture 與 TemporaryDirectory 驗證 future append、缺資料、fallback、DTO roundtrip、Regime 邊界及 UI storage boundary。 |
| `tests/test_task_loop_02_contract.py` | 新增 | 驗證市場四類 DTO、排名與日期凍結、eligible universe、同日相容投影及失敗語意。 |
| `docs/06_qa/TASK_LOOP_02_HANDOFF.md` | 新增 | 本交接、驗收命令、限制與回滾說明。 |

未修改 TASK-LOOP-01 owner 檔案、資料 ingestion／schema、`decision_module/stock_screener.py`、Watchlist writer 或 ScoringEngine。所有 QA fixture 都是隔離記憶體資料，沒有連線正式資料庫或建立正式輸出。

## 凍結的市場契約

- DTO 同時保存 `decision_date` 與 `effective_date`。來源日期低於決策日時，品質為 degraded 並保留 `*_as_of_fallback:<date>` 警告；未來唯一資料、未知日期、零有效樣本或歷史窗口不足不會填零冒充 observed。
- `MarketBreadthDTO` 的廣度比例以整數基點傳遞；產業與相對強弱服務沿用既有 Decimal／整數基點計算。Regime 的 `match_score_bp` 是分類匹配度邊界值，DTO 與文件不把它命名或宣稱為勝率。
- `ScreeningService` 在呼叫既有篩選引擎前先固定 `日期 <= decision_date` 的 frame；因此追加未來列不會改寫已凍結日的 cross-sectional universe 或排名。股票結果的 eligible universe 來自既有 builder 的有效樣本數，產業結果保留有效日產業數。
- UI 只透過 app service DTO／相容投影交換資料；五個市場頁面沒有 `sqlite3`、`DBManager`、`read_csv` 或 `read_sql`。UI 不決定來源 fallback，也不在展示層重算排名。
- 舊的 `get_strong_stocks`／`get_weak_stocks`／產業 API 在沒有指定日期時維持舊行為；指定日期時可直接回傳相容的 tuple／DataFrame。新呼叫端應優先使用各 `_dto` 入口並保存來源與品質。

## 驗收命令與結果

所有命令使用 `C:\Projects\PythonProjects\technical_analysis\.venv\Scripts\python.exe`，pytest 加 `-o addopts=`；pytest cache 的既有 ACL 只產生 warning。

| 命令 | 結果 |
|---|---|
| `-m pytest tests\test_ui_qt_market_regime_view.py tests\test_market_breadth_service.py tests\test_sector_rotation_service.py tests\test_relative_strength_liquidity_service.py tests\test_market_regime_data_provider.py tests\test_task_loop_02_contract.py -q -o addopts=` | exit 0；35 passed，1 個既有 pytest cache warning。 |
| `scripts\qa_validate_market_loop.py` | exit 0；4 個隔離檢查全部 PASS，沒有正式資料或網路。 |
| `-m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=` | exit 0；81 passed，1 個既有 pytest cache warning。 |
| `scripts\qa_validate_update_tab.py` | exit 0；25 passed、0 failed、4 skipped；4 個 skip 為既有刻意略過真實下載／合併的介面案例。此命令只作共同 gate，沒有修改 TASK-01 檔案。 |
| `-m py_compile` 本卡 13 個 Python 檔 | exit 0。 |
| `scripts\check_financial_float_boundaries.py` | exit 0。 |
| `scripts\check_look_ahead_bias.py` | exit 0。 |
| `-m mypy --follow-imports=skip` 本卡 DTO／服務／QA 檔 | exit 0；7 source files 無型別錯誤。 |
| `-m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | exit 1；只剩其他 owner 的 `app_module/evidence_event_service.py:183,187`（`str` 沒有 `value`）及 `app_module/forward_performance_dashboard_service.py:92`（override signature 不相容）三項錯誤，本卡未越界修改。 |
| `scripts\run_full_app_healthcheck.py --mode quick` | exit 0；Healthcheck passed。專案上下文中的 `--quick` 參數目前不是此腳本有效 CLI，使用等價的 `--mode quick`。 |
| `git diff --check` | exit 0；僅有既有 CRLF 轉換提示。 |

## 回滾清單

回滾前先檢查 `git status --short` 與各並行 owner 的最新差異；不得整體 checkout、clean 或覆蓋其他任務變更。

| 路徑 | 回滾方式與風險 |
|---|---|
| `app_module/dtos/market_loop_dtos.py` | 確認沒有後續服務依賴後移除新增檔，再一併反向移除五個服務的 DTO import／入口；否則既有 UI DTO 路徑會失效。 |
| 五個 `app_module/*service.py` | 只反向套用本卡新增方法與日期裁切 hunk；不要整檔還原，避免覆蓋其他 agent 的並行變更。回退後需重跑原有市場 focused pytest。 |
| 五個市場 UI view | 只反向套用 DTO 入口 hunk；保留原本 fake service 的 legacy API。回退後需重跑市場 UI pytest 與 UI storage static check。 |
| `scripts/qa_validate_market_loop.py`、`tests/test_task_loop_02_contract.py` | 確認沒有 runner／inventory 依賴後移除新增檔；功能回退時應保留失敗證據，不得把測試刪除當成通過。 |
| 本文件 | 保留歷史交接紀錄；若功能回退，新增回退日期與原因，不覆寫既有驗收結果。 |

## 未完成與外部條件

- 真實 TWSE／TPEX／SQLite formal snapshot、正式 source acceptance、Watchlist 寫入與 ScoringEngine 串接不在本卡範圍；隔離 QA 通過不代表外部來源可用或投資證據成立。
- 集中式 Application Manual／架構／Roadmap 同步由文件 owner 依 scoped SSOT 處理；本卡遵守白名單，只留下可重跑 handoff，不越界修改集中文件。
- 全域 mypy 的三個錯誤屬其他任務 owner；TASK-02 變更檔 targeted mypy 已通過，不應以跨 owner 修改掩蓋該 gate。
- UI 的既有觀察清單按鈕仍只呼叫既有服務 command port；本卡沒有新增 writer 或宣稱即時訊號已達正式交易品質。

## Closeout

TASK-LOOP-02 工程交接完成：市場 focused pytest 35 passed、隔離 QA 4 項通過、py_compile／金融浮點／future-function／本卡 mypy／quick healthcheck 均通過；全域 mypy 的外部 owner 阻擋已保留。未 stage、commit 或 push，未觸碰正式資料。

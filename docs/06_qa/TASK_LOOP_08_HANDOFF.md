# TASK-LOOP-08-A Runtime 觀測與 QA 骨架交接

日期：2026-09-06。範圍只包含可平行的 08-A；全部上游 handoff、正式文件集中同步及最終跨閉環驗收屬於 08-B。

## 版本、來源與邊界

- Base SHA：`678db2bb260bb1de5cee4a0864f9f402db3660a7`；本卡沒有 stage、commit 或 push，current SHA 未改變。
- 接手時既有 dirty：`GPT6_ASTRA_CONTEXT_PACK.md` 與 `docs/07_guides/ASTRA_LUNA_COLLABORATION_SOP.md` 的刪除，以及未追蹤的 `MASTER_GOAL_PLAYBOOK_2026_09_06.md`；本卡未操作這些變更。TASK-01／04 同時修改中的檔案由各自 owner 管理。
- 執行依據：`docs/07_guides/MASTER_GOAL_PLAYBOOK_2026_09_06.md` 的共同契約及 TASK-08，另由根任務明確限縮為 08-A。
- 執行雙根：`output/master_goal/TASK-LOOP-08/data`、`output/master_goal/TASK-LOOP-08/artifacts`，`PROFILE=test` 時設定實際解析至各根下的 `_test`。Qt 使用 `QT_QPA_PLATFORM=offscreen`。
- 專用 QA 額外在系統 TEMP 建立自己的雙根，覆蓋並還原環境變數；不建立 `TWStockConfig`，故該專用 fixture 根不再追加 `_test`。
- 原始來源為合成 fixture，不是真實時間、正式資料或投資證據。沒有寫入 repo `runtime/events/`／`runtime/state/` 正式檔、正式 DATA_ROOT／OUTPUT_ROOT、Windows Scheduler 或 broker。
- 時間線自查：本卡只有治理事件觀測，沒有策略訊號、成交或金融計算；未來事件以固定 UTC 時鐘測試，維持只作未來時間診斷而不計入目前治理失敗。

## 實際變更與回滾清單

| 路徑 | 類型與內容 | 回滾方式及風險 |
|---|---|---|
| `app_module/dtos/runtime_dtos.py` | 新增 `RuntimeStateSnapshotDTO` 的讀取狀態、原始狀態、diagnostics、schema version | 先還原依賴新欄位的服務與 UI，再還原本卡欄位；舊三個必要欄位仍相容 |
| `app_module/runtime_services/snapshot_service.py` | 缺漏／無法讀取／非 object／未知 status 不冒充 IDLE，Context 型態驗證 | 只反向套用本卡 diff；恢復後舊版仍有觀測誤判風險 |
| `app_module/runtime_services/event_bus.py` | 五類訂閱回傳可重複呼叫的取消句柄；鎖定訂閱快照，回呼中取消不跳過下一訂閱 | 與 bridge 一起回退；不改其他發布端 |
| `app_module/runtime_services/runtime_controller.py` | 最近 2,000 個 event ID 同內容去重，衝突內容仍發布並保留診斷 | 反向套用本卡 diff；不刪改事件來源 |
| `ui_qt/bridges/runtime_event_bridge.py` | `dispose()`／Qt destroyed 解除全部訂閱 | 與 EventBus 一起回退；只影響 observer 生命週期 |
| `ui_qt/views/runtime_view.py` | 明示未知與讀取診斷；接收方法標示 Qt Slot | 反向套用本卡 diff，不改其他頁面 |
| `qa/full_app_healthcheck/test_inventory.py` | 登錄本卡契約、既有漏登的產業更新測試，以及已建立的 01／04 契約 | 僅移除不再存在檔案的對應項；保留其他卡登錄 |
| `tests/test_task_loop_08_contract.py` | 新增失敗重現、取消訂閱、worker→Qt、restart、去重與 QA failure 契約 | 確認沒有其他依賴後移除本卡新檔並同步 inventory |
| `scripts/qa_validate_runtime_loop.py` | 新增自備 fixture、來源 hash、明確結果與非零失敗碼的專用 QA | 確認沒有 runner 依賴後移除；不刪除來源或正式資料 |
| `docs/06_qa/TASK_LOOP_08_HANDOFF.md` | 本交接與文件補丁 | 保留歷史證據；若回退功能，標註已回退 |

回滾前先比較最新 working tree，僅還原本卡差異；不得以整檔 checkout 覆寫並行 owner 的後續修改。修改本卡新檔的其他工作必須先協調。未執行任何回滾或原始資料刪除。

## 凍結的相容契約

- `RuntimeStateSnapshotDTO.schema_version="runtime-state.v2"`。新增欄位都有預設值，舊發布端明示 IDLE 的 DTO 仍照既有方式顯示。
- `task_read_state`／`context_read_state` 為 `observed`、`degraded`、`unavailable` 或 `missing_or_unreadable`。未知 task 使用字串 `UNKNOWN`，不是新增或改寫 runtime FSM 的狀態。
- 既有 `LocalFileStore` 對不存在及部分讀取錯誤都回傳 `{}`，且不在本卡修改白名單。服務因此使用誠實的 `missing_or_unreadable`，不猜 missing 或 PermissionError；實際拋出的 exception 則保留類型 diagnostics。
- `raw_task_status` 保留未知來源值；非 object task/context、非法 active_files 以降級投影回報，不在 UI 或 app 層重新打開來源檔。
- `EventBus.subscribe_*` 回傳 `Callable[[], None]`。既有忽略回傳值的呼叫維持相容；重複訂閱各有自己的取消句柄。通知快照已建立後，該次通知仍依快照順序完成；沒有 durable queue 或背景 task 執行器。
- `QtRuntimeBridge.dispose()` 可重複呼叫；Qt 物件 destroyed 也釋放訂閱。已排入 Qt 的訊號依 Qt 連線生命週期處理，不宣稱會撤回已排入訊號。
- `RuntimeController` 在該次 observer 的最近 2,000 個非空 ID 內去重；空 ID 不猜身份。同 ID 不同內容仍發布並記錄 `runtime_event_id_conflict:<id>`。cursor reset 清除去重記錄；重啟仍 attach at tail，不重播歷史、不重跑任務。
- 治理事件健康與 scheduled saved-artifact 狀態維持不同觀測平面；沒有將 saved status 冒充 Scheduler registration、running 或 exit result。

## 驗證紀錄

所有命令使用 `.\.venv\Scripts\python.exe`，PowerShell 先設定上述隔離雙根。pytest 加 `-o addopts= -p no:cacheprovider`；停用 cache 僅避免既有 `.pytest_cache` ACL 警告，不略過測試。

1. 接手 baseline 指定既有 Runtime／inventory 測試：exit 1，41 passed／1 failed。唯一失敗為已存在的 `tests/test_data_loader_industry_index_update.py` 尚未登錄；本卡確認它使用 temp roots 與 fake request 後登錄為 `service-oracle-data-market`。
2. 新契約首次重現：exit 1，8 failed，分別重現缺來源冒充 IDLE、非 object 直接例外、缺 unsubscribe／dispose、重複 ID。
3. 本卡完整 pytest：`tests/test_runtime_health_service.py tests/test_runtime_event_stream_service.py tests/test_runtime_event_cursor.py tests/test_scheduled_operations_service.py tests/test_runtime_ui_composition.py tests/test_ui_qt_runtime_view.py tests/test_full_app_healthcheck_test_inventory.py tests/test_task_loop_08_contract.py`。最終 exit 0，59 passed，沒有 skips（2.84 秒）。
4. 專用 QA：`scripts/qa_validate_runtime_loop.py --output-json output/master_goal/TASK-LOOP-08/artifacts/runtime_qa_report.json`，exit 0，7 項通過，沒有 skips。包含 restart tail attach、missing task unknown、半行不發布、同 ID 去重、future health 排除、非法 task 診斷、解除訂閱不寫來源。
5. UI 強制 pytest：`tests/test_ui_qt_update_view_workbench.py`，exit 0，81 passed。
6. UI 強制更新 QA：最初空雙根 17 passed／5 Availability failed／4 skips；01 fixture 接線後重跑 24 passed／2 failed／4 skips。最新兩項原因是 fixture 缺 `fundamental_monthly_revenues` 與 TemporaryDirectory cleanup 的 config.log handle；已交 01 owner，未越界修復。
7. 全模組 mypy：執行完整要求，最初 01 DTO tuple 推論錯誤後已修；最近只有並行 04 的 `app_module/backtest_service.py:403`，`Path | None` 指派 `Path`。本卡檔案沒有 mypy error，最終 gate 由後續重跑記錄更新。
8. 本卡九個 Python 檔 `py_compile`：exit 0；無金融邏輯變更，金融 AST gate 於 08-B 全域整合保留。

專用 QA fixture 的 SHA-256：

- `data/runtime/events/runtime_events.jsonl`：`4142dff4d304caa1b6855600cc393c904e85cd1a0c8101805789f5c55b3e9dba`。
- `data/runtime/state/current_task.json`：`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`。

QA 的 fixture 只在 TEMP 存活；每段 observer 前後比對原檔 hash，輸出報告保存於本卡 ignored artifacts。不可將 synthetic hash 解讀為正式來源 custody。

## 集中文件補丁（交 08-B owner 套用）

`docs/07_guides/APPLICATION_MANUAL.md` 第 11.3 治理 Runtime，於事件判讀段落後新增：

> 任務狀態來源不存在、無法讀取、格式錯誤或 status 不在既有治理狀態中時，「任務流程狀態」顯示「未知（來源未確認）」。將游標移至狀態列可查看原始 status、task read state 與 diagnostics；上下文資料無法確認時也會顯示提示。未知不等於閒置，畫面不會建立或修復狀態檔。既有檔案讀取層無法區分不存在與部分讀取錯誤時，診斷會保留 `missing_or_unreadable`。
>
> 事件流只保留本次開啟後的觀測；在最近 2,000 個非空 event ID 內，相同內容的重複事件只顯示一次，同 ID 的不同內容仍保留並記錄 conflict 診斷。畫面最多呈現 500 筆不代表底層 log 被裁切。關閉／銷毀 observer 會解除事件訂閱；重啟只重新觀測，不啟動或重試 task。這不是 durable exactly-once queue。

同手冊第 11 節 QA 指引新增命令 `scripts/qa_validate_runtime_loop.py`：預設自建離線 fixture 與 TEMP 雙根，結果 JSON 預設在 `output/qa/runtime_loop/report.json`；失敗 exit 1。它驗證 observer／Qt 契約，不代表正式 runtime writer、Windows task 或 V4 readiness。

`docs/01_architecture/system_architecture.md` 的 Runtime Observatory 說明新增：

> RuntimeStateSnapshotDTO v2 保留 task/context read state、raw status 與 diagnostics。EventBus 提供可解除訂閱，Qt bridge 管理生命週期，RuntimeController 只有受限 ID 去重與唯讀輪詢；核心 JSON／JSONL store、正式狀態機及 scheduler 執行語義均未改動。

Snapshot／Roadmap Hub／6M／Index 只由整合者記錄 08-A 工程結果與本交接入口，不改 V4 gate、formal credit、source acceptance 或 production_scheduler_allowed。

## 未完成與殘餘限制

- 08-B 全部 upstream DTO／hash／manifest、架構 imports、全域量化 Gate、Full App Healthcheck 與集中 Manual／architecture 同步尚待整合者；不列為本卡可平行的 08-A domain 工作。
- 非 UI snapshot 來源仍受既有 store 的空字典語義限制，無法只靠此次白名單精確區分缺檔與被吞掉的 I/O 原因；本卡保守顯示未知。
- cursor 仍由唯讀參考 store 的 byte offset 實作。相同大小的 log 替換／外部 rotation 身份沒有新增 inode／generation 契約，未宣稱支援 durable replay／exactly-once。
- 不會建立自動 retry／dispatch、補 transition history、啟用 production Scheduler、正式切換或授予 evidence credit。

## Closeout

08-A 工程交接完成：本卡專用測試 59 passed、專用 QA 7 passed、UI 更新頁 pytest 81 passed、py_compile 通過。根任務已明確將 01 更新 QA／04 全域 mypy 的並行缺口與後續重跑交由 root／08-B 承接，08-A 不等待它們才交接；上述未通過紀錄保留，不宣稱全域 gate 通過。

08-B 尚未執行，Manual／architecture 等集中補丁仍待整合套用；因此不宣稱整體八卡閉環、正式運作或 V4 工程整合完成。

## 08-B 整合執行前 coverage 與回滾清單

2026-09-06 開始 08-B，base HEAD=`2bfe86879760966560d36b5e1aecbccd23c4c69b`。上列 08-A 歷史驗收保留，08-B 的最終狀態另於本節後補記。本輪不 stage／commit／push。

| Owner／檔案範圍 | 優先級與變更 | 回滾方式 |
|---|---|---|
| ui_qt/main.py、app_module/workbench_source_service.py（root 明確交接授權） | Must；保存推薦 provider 組裝、完整來源欄位唯讀投影 | 只反向套用 08-B hunk，不回退 07 來源契約 |
| qa/full_app_healthcheck/test_inventory.py、tests/test_task_loop_08_contract.py | Must；登錄八卡與跨卡行為驗證 | 保留 08-A 登錄／測試，只回復 08-B 差異 |
| APPLICATION_MANUAL、current/target architecture、Snapshot、Roadmap Hub、6M、Index | Must；已授權共同文件 coverage | 逐段回復本次已證實行為與交接入口；不整篇覆寫 |
| UI_FEATURES_DOCUMENTATION、BACKTEST_LAB_FEATURES、USER_GUIDE、PROJECT_NAVIGATION | Must；DOC_COVERAGE_MAP 對應精簡補丁，root 已授權 | 只回復本次契約／權威連結 |
| 本交接文件與 ignored QA artifacts | Must；逐項 completion audit、命令與 hash | 保留驗證歷史，失敗不刪證據 |

Rollback 前核對所有 owner 最新 dirty hunks，保留限定 patch，再 reverse-check 後逐 hunk 回復；不得整樹 checkout、clean、正式資料重建或無界目錄刪除。量化自查：本輪僅組裝 frozen App provider／DTO 與保存來源，沒有新撮合、評分或資金計算；未來推薦不參與歷史日期，unknown/degraded 不得被投影清除。真實 fills、正式來源接受、自然前瞻與具名 review 均不能由整合 fixtures 替代。

## 08-B 最終整合與 completion audit（2026-09-06）

08-B 的可獨立工程 DoD 已完成；本節取代上列「08-B 尚待執行」的目前狀態，保留 08-A 原始歷史。base／current HEAD 均為 `2bfe86879760966560d36b5e1aecbccd23c4c69b`。本輪為共用 working tree 的最小增量，其他卡 dirty files 保留，沒有 stage／commit／push。整體維持 `action_required`、`V3.3 Engineering Complete / V4 Evidence Accumulation`，不構成正式 V4 closeout。

### 實際整合差異與來源

- `ui_qt/main.py`：在有效 output_root 配置下為唯一 Decision Desk builder 接入 `SavedRecommendationDeskProvider`；缺 output_root 的 legacy／測試 composition 保留相容，不猜正式路徑，不注入真實 ledger writer。
- `app_module/workbench_source_service.py`：唯讀重載已保存 loop payload 的 `RecommendationDeskSummary` 與 `source_lineage`，保留 result_id、日期、品質、warnings 與 context；未來日期／損毀格式降級拒用，metadata 複製後投影，SQLite 連線明確關閉。其餘 legacy typed sections 未在此輪擴大 hydration。
- `qa/full_app_healthcheck/test_inventory.py`：八個 `test_task_loop_XX_contract.py` 均已登錄正確 service oracle。沒有為取得 coverage 把 domain 測試偽裝成 UI bridge。
- `tests/test_task_loop_08_contract.py`：保留 08-A 契約，新增 main provider composition、真實保存推薦→Desk→SQLite→Workbench 重載及 hash 不變、未來推薦拒用三項整合行為。
- `scripts/qa_validate_runtime_loop.py`：獨立 observer QA 的 upstream 結果使用 `not_evaluated_by_observer_only_qa`；最終跨卡通過依本節與 completion audit，不由 observer QA 代替。
- 03／07 owner 另完成真實 `current_result_id` 與候選來源 ID 接線：保存成功才記錄 result_id，新分析清除舊 ID，未保存維持空值；DataFrame 入口保留來源欄位並處理 pd.NA。其差異及六個新案例歸各 owner 交接，不列為 08-B 越權改檔。

推薦 context 保持 `recommendation-context.v1`，執行為 `next-session-open.v2`／明選 `legacy-same-day-close.v1`，Evidence lineage 為 `evidence-lineage.v1`，Runtime 為 `runtime-state.v2`；08-B 沒有新增 schema 版本或改寫既有 run。輸入均為各卡 synthetic fixture／隔離保存產物；八卡 handoff、contract、QA 與本輪文件的實際 SHA-256 集中於 [COMPLETION_AUDIT.json](C:/Projects/PythonProjects/technical_analysis/output/master_goal/TASK-LOOP-08/artifacts/integration/COMPLETION_AUDIT.json)。fixture hash 不等於正式來源 custody。

### 逐卡閉環覆核

| 卡片 | 本輪確認的閉環與證據 | 工程結論與外部邊界 |
|---|---|---|
| 01 DATA | 更新狀態／日期契約、讀取不寫 manifest、離線落地；contract 與更新 QA | 工程通過；25 passed／4 skipped，沒有正式下載、合併或 source acceptance |
| 02 MARKET | 日期先切片、未來追加不變、缺漏／fallback、Regime／UI 邊界；contract＋4 項 QA | 工程通過；分類匹配度不作勝率，正式 PIT 版本鏈另 Gate |
| 03 RECO | frozen 設定、unknown 因子、future／PIT 拒用、保存 ID；contract＋7 項 QA | 工程通過；缺 PIT membership 時歷史產業篩選拒用，未提升正式資格 |
| 04 EXEC | v2 T+1、gap／停牌、精確現金、末端持倉、取消、legacy；contract＋2 項 QA | 工程通過；固定組合仍 per-stock，無真實 fills／完整共享現金宣告 |
| 05 REGISTRY | 六階段故障、冪等／hash／corruption／版本、readonly query、Evidence proposal；contract＋9 項 QA | 工程通過；自然時間、producer lineage 與具名獨立 review 不由 fixture 折抵 |
| 06 PORT | append 帳本、補償、精確重建、副本 migration、缺行情；contract＋Portfolio QA | 工程通過；正式 JSONL 未切換，真實 Paper fills 缺件保持 blocked |
| 07 DESK | 候選來源 ID、同日品質聚合、callback 隔離、完整 loop 保存及來源重載；contract＋7 項 QA | 工程通過；JSON 正式預設未切換，不宣稱已刪除候選的歷史 membership |
| 08 OBS／整合 | observer 生命週期、Qt 邊界、受限去重；7 項 QA、177 代表測試、集中文件、quick／full | 工程通過；不啟動 task／scheduler／promotion／broker，人工 UI 缺口另列 |

### 當輪驗證命令與結果

一律使用 `.\.venv\Scripts\python.exe`。代表測試、mypy 與 healthcheck 設定 `DATA_ROOT=output/master_goal/TASK-LOOP-08/data`、`OUTPUT_ROOT=output/master_goal/TASK-LOOP-08/artifacts`、`PROFILE=test`、`QT_QPA_PLATFORM=offscreen`；環境中的雙根使用絕對路徑。逐卡 QA 序列執行，01～08 各用自己的 `output/master_goal/TASK-LOOP-XX/data`／`artifacts`；腳本自建 TEMP fixture 仍位於隔離根。pytest 的直接命令加 `-q -o addopts= -p no:cacheprovider`。

| 驗證 | 實際命令／範圍 | Exit／結果與產物 |
|---|---|---|
| 代表整合 | pytest：八卡 contract；test_full_app_healthcheck_test_inventory、test_ui_qt_decision_desk_main_integration、test_workbench_source_service、test_workbench_read_only_composer、test_recommendation_save_coordinator、test_ui_qt_research_run_save、test_backtest_execution_coordinator、test_portfolio_mvp、test_runtime_ui_composition，全部位於 tests/ 並帶 .py | 0；177 passed，2 個既有 pandas dtype FutureWarning；`integration/focused.log` |
| UI 強制測試 | `-m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts= -p no:cacheprovider` | 0；81 passed；`integration/update_pytest.log` |
| 01 QA | `scripts/qa_validate_update_tab.py` | 0；25 passed／4 skipped；`integration/01_update.log`、`update_qa_report.md` |
| 02 QA | `scripts/qa_validate_market_loop.py` | 0；4 passed；`integration/02_market.log` |
| 03 QA | `scripts/qa_validate_recommendation_tab.py` | 0；7 passed；`integration/03_recommendation.log`、`recommendation_qa_report.md` |
| 04 QA | `scripts/qa_validate_phase3_3b.py`（預設離線模式，沒有 legacy-full） | 0；2 passed；`integration/04_execution.log`、`execution_qa_report.json` |
| 05 QA | `scripts/qa_validate_research_registry_loop.py` | 0；9 passed；`integration/05_registry.log`、`registry_qa_report.json` |
| 06 QA | `scripts/qa_validate_portfolio_tab.py` | 0；domain、precise ledger、compensation、migration、Portfolio widget smoke 通過；`integration/06_portfolio.log` |
| 07 QA | `scripts/qa_validate_decision_loop.py --output-json output/master_goal/TASK-LOOP-08/artifacts/integration/decision_qa.json` | 0；7 checks；`integration/07_decision.log`、`decision_qa.json` |
| 08 QA | `scripts/qa_validate_runtime_loop.py --output-json output/master_goal/TASK-LOOP-08/artifacts/integration/runtime_qa.json` | 0；7 checks；`integration/08_runtime.log`、`runtime_qa.json` |
| 型別 | `-m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | 0；532 source files，2 個既有 annotation-unchecked notes；`integration/mypy.log` |
| 金融／時間防線 | `scripts/check_financial_float_boundaries.py`、`scripts/check_look_ahead_bias.py` | 各 0；此輪工具執行已核對，結果列入 completion audit |
| 語法 | `-m py_compile` 本輪五個 Python 檔；再核對全部 modified＋untracked Python 85 檔 | 各 0；後者 pycache 使用本卡 integration/pycache，未移除既有 cache |
| 分層 | 對當時 changed source 的 55 檔作 AST import audit；UI 禁 sqlite3、App 禁 Qt/UI、core domain 禁 App/UI/Qt | 0 violations；`integration/layer_audit.json`。這是 changed-source 稽核，不宣稱全庫所有歷史邊界皆已整改 |
| Quick | `scripts/run_full_app_healthcheck.py --mode quick --output-dir output/master_goal/TASK-LOOP-08/artifacts/integration/healthcheck_quick` | 0／passed；2 suites；`healthcheck_quick/20260906_173334/result.json` |
| Full | `scripts/run_full_app_healthcheck.py --mode full --output-dir output/master_goal/TASK-LOOP-08/artifacts/integration/healthcheck_full` | 0／passed；12 suites；`healthcheck_full/20260906_173515/result.json` |
| 文件／差異 | 11 份集中文件與五個 Python 檔 scoped `git diff --check`；文件 owner 檢查新增連結與 fence | 0；64 個新增絕對連結存在，fence 成對，CRLF 提示不算失敗 |

全部 integration 相對產物以上述 TASK-LOOP-08 artifacts 為根。Full runner 的 pytest 有既有 `.pytest_cache` ACL 警告，但每個 suite returncode 0；直接 pytest 停用 cache 不略過測試。更新 QA 的四個 skip 為 update_daily_Execution、update_market_Execution、update_industry_Execution、merge_daily_data_Execution；它們沒有被計為 passed。首次代表整合曾 176 passed／1 failed，原因為 fake config 無 output_root 導致整頁降級；08-B 增加有配置才注入 provider 的相容邊界後，同完整代表集重跑 177 passed。

### 集中文件完成與保留條件

已完成 Must coverage：APPLICATION_MANUAL（入口、操作、參數、判讀、限制與排錯）、PROJECT_SNAPSHOT、DEVELOPMENT_ROADMAP、ROADMAP_6M_ENGINEERING、current／target architecture、DOCUMENTATION_INDEX、UI_FEATURES_DOCUMENTATION、BACKTEST_LAB_FEATURES、USER_GUIDE、PROJECT_NAVIGATION。只同步已落地契約與來源，並校正舊同日成交／強制平倉、Registry 比較與預設 Desk 導覽的矛盾；沒有改產品方向、外部 Gate 或成熟度。文件 rollback 仍只逐段回復本輪差異。

保留以下限制，不列為本輪可獨立工程 DoD 的未完成實作：正式 source acceptance／精確可得時點／PIT sector membership、自然前瞻時間、具名獨立 review、真實 Paper producer fills／cost、Registry／technical production canary、正式 JSON／JSONL migration 與 writer 切換。固定組合共享現金、其他 legacy typed sections 完整 hydration、Runtime store 原因／log generation 也仍是明列的後續架構差距。未 opt-in 真 MainWindow 截圖 smoke，沒有人工操作／視覺驗收；現有 full healthcheck 是已路由的 UI／QA bridge，不等於全量 pytest 或人工 UI 全覆蓋。

08-B 工程 closeout 成立；formal credit 沒有增加，正式資料未寫入，production_scheduler_allowed／broker／promotion 權限未啟用。後續任務以本節與 completion audit 讀取可重現的工程證據，再按既有外部 Gate 推進。

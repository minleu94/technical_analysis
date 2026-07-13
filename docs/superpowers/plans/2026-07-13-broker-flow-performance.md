# Broker Flow SQLite-first Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and `superpowers:systematic-debugging` for any latency regression.

**Goal:** 將「主力流向」從 CSV全量載入、重複逐股聚合與GUI thread同步執行，改成唯讀SQLite範圍查詢、單次批次聚合、Top／Bottom提前裁切、batch semantics與可取消的背景載入。

**Architecture:** Repository以 `mode=ro`查最近1／5／20個實際broker交易日；application query service建立typed dashboard／detail snapshots；SmartMoney semantics只處理入選symbols並批次取價；Qt透過`TaskWorker`、request id與stale-result discard更新畫面。ETF分流不是本次根因修復，等正式security master再做。

**Tech Stack:** Python 3.11、SQLite parameterized SQL／CTE、dataclasses、Decimal、PySide6 model/view與TaskWorker、pytest-qt、mypy、read-only latency harness。

## Public Compatibility Contract

必須保留：

- `SmartMoneyFlowView(...)` 既有必要constructor arguments；新增參數只能optional。
- `SmartMoneySemanticService.build_stock_semantics(...)`。
- `SmartMoneySemanticService.build_dashboard_summary(...)`既有呼叫簽名。

新增：

- `BrokerFlowService.load_dashboard_snapshot(query)`。
- `BrokerFlowService.load_stock_branch_detail(stock_code, period, as_of_date)`。
- `BrokerFlowService.load_branch_tracker(branch_system_key, period, as_of_date)`。

## Ownership

**Create:**

- `app_module/broker_flow_dashboard_dtos.py`
- `app_module/broker_flow_sqlite_read_repository.py`
- `app_module/broker_flow_dashboard_query_service.py`
- `scripts/qa_broker_flow_dashboard_latency.py`
- `tests/test_broker_flow_sqlite_read_repository.py`
- `tests/test_broker_flow_dashboard_query_service.py`
- `docs/06_qa/BROKER_FLOW_SQLITE_DASHBOARD_PERFORMANCE_2026_07_15.md`

**Modify:**

- `app_module/broker_flow_service.py`
- `app_module/smart_money_semantic_service.py`
- `app_module/dtos/smart_money_semantic_dtos.py`
- `ui_qt/views/smart_money/**`
- `tests/test_broker_flow_units.py`
- `tests/test_smart_money_semantic_service.py`
- `tests/test_ui_qt_smart_money_flow_view.py`

**Must not modify:**

- `ui_qt/main.py`
- `ui_qt/views/decision_desk_view.py`
- `ui_qt/views/workbench_view.py`
- `app_module/decision_desk_*`
- `app_module/market_data_visibility_*`
- central Snapshot／Roadmap／Architecture／Manual files

---

## Task 1：建立現況 Benchmark 與單位契約

**Files:**

- Create: `scripts/qa_broker_flow_dashboard_latency.py`
- Modify: `tests/test_broker_flow_units.py`
- Create: `tests/test_broker_flow_dashboard_query_service.py`

- [ ] **Step 1: 保存現況分段時間**

使用正式DB唯讀與bounded scope量測：CSV load、DTO materialization、scanner aggregation、summary、per-stock semantics、Qt model build。記錄cold 1次、warm 10次與row/object counts；output放`$env:TEMP`或ignored path，不commit。

- [ ] **Step 2: 寫SQLite／CSV parity RED tests**

以同一fixture事件鎖定：`broker_flows.買進股數/賣出股數`是股；`BrokerFlowEvent.buy_qty/sell_qty`既有單位是張。Observed row須確定性除以1000；非1000整除標degraded，不靜默截斷。金額推估張數沿用`Decimal + ROUND_HALF_UP`。

- [ ] **Step 3: 寫period／as-of RED tests**

day／week／month固定為截至明確`as_of_date`最近1／5／20個broker-flow交易日；禁止用`date.today()`取代資料日期。跨週末／缺日case必須穩定。

- [ ] **Step 4: 定義query與snapshot DTO**

`BrokerFlowDashboardQuery`需含 period、scope、requested_as_of_date、limit_per_side；snapshots需含as-of、quality、warnings、source fingerprint與完整市場summary。UI limit不得縮小summary母體。

- [ ] **Step 5: RED verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_broker_flow_units.py tests/test_broker_flow_dashboard_query_service.py -q -o addopts=
git add scripts/qa_broker_flow_dashboard_latency.py tests/test_broker_flow_units.py tests/test_broker_flow_dashboard_query_service.py app_module/broker_flow_dashboard_dtos.py
git commit -m "test(broker-flow): lock sqlite parity and dashboard contracts"
```

## Task 2：唯讀 SQLite Repository

**Files:**

- Create: `app_module/broker_flow_sqlite_read_repository.py`
- Create: `tests/test_broker_flow_sqlite_read_repository.py`

- [ ] **Step 1: 寫read-only／missing schema RED tests**

Assertions：使用URI `mode=ro`、`PRAGMA query_only=ON`、parameterized SQL；run前後DB bytes／mtime不變；constructor不建立DB/table/log；缺DB／table／columns回typed missing/degraded，不偷偷fallback到25秒CSV path。

- [ ] **Step 2: 寫query pushdown RED tests**

以CTE取得最近N個實際交易日，在SQL層依stock code／branch key／date range限縮；repository不得呼叫`pd.read_csv()`、`iterrows()`或將732,020 rows全物件化。

- [ ] **Step 3: 實作市場aggregate與details queries**

市場summary使用完整母體；top/bottom candidate query只回需要欄位與limit；stock detail、branch tracker都是query-specific。回傳canonical rows／DTO而非DataFrame。

- [ ] **Step 4: EXPLAIN before index**

先以現有index跑`EXPLAIN QUERY PLAN`與benchmark。若未達gate，只在closeout附證據與working-copy index proposal；不得修改production DB index。

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_broker_flow_sqlite_read_repository.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\broker_flow_sqlite_read_repository.py
git add app_module/broker_flow_sqlite_read_repository.py tests/test_broker_flow_sqlite_read_repository.py
git commit -m "feat(broker-flow): add readonly sqlite repository"
```

## Task 3：單次聚合、Scope Pushdown 與 Batch Semantics

**Files:**

- Create: `app_module/broker_flow_dashboard_query_service.py`
- Modify: `app_module/broker_flow_service.py`
- Modify: `app_module/smart_money_semantic_service.py`
- Modify: `app_module/dtos/smart_money_semantic_dtos.py`
- Test: `tests/test_broker_flow_dashboard_query_service.py`
- Test: `tests/test_smart_money_semantic_service.py`

- [ ] **Step 1: 寫no-duplicate-scan RED tests**

以spy repository證明scanner signals與market summary共用同一aggregate；Top／Bottom 50裁切後才查5／20／60日semantics與prices；Top 100不可觸發100次price query。

- [ ] **Step 2: 實作batch semantics API**

一次接收requested stock codes與aggregated windows，按symbol分組；不得每檔copy／rescan全events。既有single-stock public API包裝batch結果以保持相容。

- [ ] **Step 3: 實作dashboard query service**

流程固定：完整市場aggregate → market summary → scope/limit → selected symbols batch semantics → typed snapshot。Cache key至少含DB mtime／schema fingerprint、as-of、period、scope、limit；source更新後失效。

- [ ] **Step 4: 接BrokerFlowService facade**

新UI走SQLite-first；legacy CSV loader只保留明確legacy/test入口，不得在missing SQLite時自動執行昂貴fallback。不要順便改正式rule score。

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_broker_flow_dashboard_query_service.py tests/test_smart_money_semantic_service.py tests/test_broker_flow_units.py -q -o addopts=
git add app_module/broker_flow_dashboard_query_service.py app_module/broker_flow_service.py app_module/smart_money_semantic_service.py app_module/dtos/smart_money_semantic_dtos.py tests/test_broker_flow_dashboard_query_service.py tests/test_smart_money_semantic_service.py tests/test_broker_flow_units.py
git commit -m "perf(broker-flow): batch dashboard and semantic queries"
```

## Task 4：Smart Money UI Off-main-thread

**Files:**

- Modify: `ui_qt/views/smart_money/smart_money_flow_view.py`
- Modify: other `ui_qt/views/smart_money/**` files only as needed
- Modify: `tests/test_ui_qt_smart_money_flow_view.py`

- [ ] **Step 1: 寫heartbeat／stale-result RED tests**

Dashboard refresh、stock detail、branch tracker各自有獨立遞增request id。慢舊request晚回時不得覆蓋新結果；refresh後300ms內Qt heartbeat仍執行。

- [ ] **Step 2: 寫lifecycle RED tests**

關頁時cooperative cancel；禁止`QThread.terminate()`。Worker exception轉頁內typed missing/degraded state，避免阻塞式error dialog。

- [ ] **Step 3: 實作三條TaskWorker paths**

UI只建立snapshot rows對應model；period/scope變更新query，不在UI重新掃signals；detail用typed table model，移除非必要DataFrame建構。

- [ ] **Step 4: 改善狀態呈現**

300ms內顯示loading；summary strip顯示真實as-of、freshness、quality與文字badge；不要以emoji作結構圖示。

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_smart_money_flow_view.py -q -o addopts=
git add ui_qt/views/smart_money/smart_money_flow_view.py tests/test_ui_qt_smart_money_flow_view.py
git diff --cached --name-only
git commit -m "perf(ui): move smart money loading off main thread"
```

若Task 4實際修改其他Smart Money model／delegate檔，逐檔review後各自stage；禁止stage整個目錄。

## Task 5：Latency／Responsiveness Acceptance Gates

**Files:**

- Modify: `scripts/qa_broker_flow_dashboard_latency.py`
- Modify: `tests/test_broker_flow_dashboard_query_service.py`
- Create: `docs/06_qa/BROKER_FLOW_SQLITE_DASHBOARD_PERFORMANCE_2026_07_15.md`

- [ ] **Step 1: 固定fixture performance regression**

用deterministic fixture驗證query count、materialized row count與no-N+1；CI gate不依賴特定硬體絕對秒數。

- [ ] **Step 2: 正式資料唯讀benchmark**

至少1 warm-up + 20 measured runs，輸出各phase與raw samples。驗收：

| Path | Gate |
|---|---:|
| week Top／Bottom 50 warm p95 | `< 2,000 ms` |
| month Top／Bottom 50 warm p95 | `< 3,000 ms` |
| cold first load | `< 5,000 ms` |
| stock branch detail warm p95 | `< 500 ms` |
| branch tracker warm p95 | `< 1,000 ms` |
| UI loading／heartbeat | `< 300 ms` |

- [ ] **Step 3: 不以ETF heuristic美化結果**

Benchmark scope保留市場真實母體。ETF／一般股票分流只登錄為future security-master工作，不用名稱猜測或提前排除。

- [ ] **Step 4: 完整驗證**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_broker_flow_units.py tests/test_broker_flow_sqlite_read_repository.py tests/test_broker_flow_dashboard_query_service.py tests/test_smart_money_semantic_service.py tests/test_ui_qt_smart_money_flow_view.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_broker_flow_dashboard_latency.py --period week --runs 20
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
git diff --check
git status --short
```

- [ ] **Step 5: Closeout commit**

```powershell
git add scripts/qa_broker_flow_dashboard_latency.py tests/test_broker_flow_dashboard_query_service.py docs/06_qa/BROKER_FLOW_SQLITE_DASHBOARD_PERFORMANCE_2026_07_15.md
git commit -m "docs(broker-flow): record sqlite performance closeout"
```

## Completion Gate

- [ ] 預設Top／Bottom不再先讀全歷史CSV或物件化全rows。
- [ ] Scanner、summary、semantics不重複全市場掃描。
- [ ] Detail／branch tracker都是query-specific。
- [ ] UI thread不做DB／CSV／domain aggregation，stale response不覆蓋新結果。
- [ ] latency gates以真實raw samples通過；未通過則如實標fail並回到根因診斷。
- [ ] 舊public signatures保持相容，正式Score未改，production DB零寫入。

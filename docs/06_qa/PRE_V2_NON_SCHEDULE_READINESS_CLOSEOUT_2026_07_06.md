# Pre-V2 Non-schedule Readiness Closeout

> 日期：2026-07-06
> 範圍：V2.0 前非排程、非時間型 gate 的可重跑檢查能力。
> 結論：已完成 read-only readiness inspector 與 CLI；多週 weekly evidence operations + history、multi-day dry-run 與 production scheduler approval 仍未完成，也不得用本檢查取代。

## 完成項目

- 新增 `app_module/pre_v2_readiness_service.py`，以 read-only 方式彙總 V2.0 前置 readiness。
- 新增 `scripts/inspect_pre_v2_readiness.py`，可輸出 JSON 或 Markdown report。
- 檢查項目包含 weekly review history、multi-day dry-run record、source gaps 與 read-only Agent report sample。
- weekly history 與 multi-day dry-run 只會依真實保存紀錄判定；不足時回 `waiting_for_time`，不以 fixture 或單次 smoke 補足。
- source gap 檢查直接使用 read-only SQLite 連線檢查 persisted recommendation / Daily Decision Desk durable snapshot，不呼叫 writable migration。
- read-only Agent report sample 使用 `AgentEvidenceAccessService` 取得 evidence rows、quality、warnings、source trace、limitations 與 follow-up questions。
- `production_scheduler_allowed` 永遠為 `false`。

## 操作方式

```powershell
.\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --db-path <working-copy-db> --decision-date 2026-07-06 --multi-day-record-path docs\06_qa\POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md --json-output
.\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --db-path <working-copy-db> --decision-date 2026-07-06 --markdown --report-output output\qa\pre_v2_readiness.md
```

`--db-path` 應指向 working-copy DB 或明確准許檢查的唯讀資料庫。CLI 不會建立 missing DB，也不會建立 schema；缺 DB / table 會回 diagnostics 與 `action_required`。

## 狀態判讀

- `ready`：該項檢查目前沒有阻擋項，可進入下一層人工判讀。
- `waiting_for_time`：需要真實多週或多日累積，不能用單次 smoke、fixture 或手動改文件替代。
- `action_required`：缺資料源、缺 table、source gap 或 report sample diagnostic 需要處理。

整體 `ready_for_v2_design` 只代表可以討論 V2.0 設計，不代表 scheduler approval、production readiness、投資有效性或交易建議。

## 安全邊界

- 不建立或修改 SQLite schema。
- 不寫 Evidence DB、Research Run DB 或正式資料。
- 不讀 UI state，不觸發 pipeline confirm，不建立 Windows Task Scheduler task。
- 不自動套用 lifecycle action，不改策略，不改持倉，不下單。
- 不把 `waiting_for_time` 轉成通過；多週 / 多日 gate 仍需真實時間累積。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_pre_v2_readiness_service.py tests\test_pre_v2_readiness_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\pre_v2_readiness_service.py scripts\inspect_pre_v2_readiness.py tests\test_pre_v2_readiness_service.py tests\test_pre_v2_readiness_cli.py
.\.venv\Scripts\python.exe -m pytest tests\test_pre_v2_readiness_service.py tests\test_pre_v2_readiness_cli.py tests\test_v1_9_agent_evidence_access.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_evidence_review_dashboards.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

結果：

- `4 passed`
- `py_compile` 通過
- `8 passed`
- Evidence Review UI contract `6 passed`
- 量化防禦檢查通過，沒有 float boundary 或 look-ahead violation
- mypy `Success: no issues found in 284 source files`

## 進 V2.0 前仍需補齊

- 多週 weekly evidence operations + history 實際紀錄。
- Evidence Review 人工 UI smoke closeout。
- 3 至 5 個交易日 multi-day dry-run record。
- 真實 watchlist / portfolio workflow 樣本。
- persisted recommendation / Daily Decision Desk snapshot / watchlist / portfolio source gaps 收斂。
- read-only Agent report sample 的人工審核。
- 若未來要推 production scheduler，仍需 explicit design、backup、rollback、diagnostics 與人工 approval 文件。

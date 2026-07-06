# V2.0 Workbench Read-only Source Adapter Closeout（2026-07-06）

## 範圍

本次完成 Phase 1.5 / Phase 2 前置的 Workbench formal read-only source adapter，目標是讓原本 `--sample` prototype 開始吃真實但唯讀的 evidence input。

已完成：

- 新增 `app_module/workbench_source_service.py`，作為 `WorkbenchSourceService`。
- `scripts/inspect_v2_workbench_prototype.py` 保留 `--sample`，並新增受控 `--db-path` / `--decision-date` / `--multi-day-record-path` / `--agent-report-limit` 等參數。
- Adapter 讀取 existing read-only sources：Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary 與 optional replay JSON summary。
- `WorkbenchReadOnlyComposer` 可接收 source diagnostics，讓 missing DB / missing table / degraded source 顯示在 dashboard warnings / review items。
- 補 missing DB、missing `decision_desk_snapshots` table、degraded snapshot source 與 CLI controlled DB path 測試。

## Read-only 邊界

- Daily Decision durable snapshot 以 SQLite `mode=ro` / `PRAGMA query_only=ON` 讀取。
- Adapter 不使用 writable repository migration，不建立 schema，不寫 evidence DB。
- missing DB 不會被建立；missing table / missing snapshot 只輸出 diagnostics。
- CLI 只輸出 JSON / Markdown 或使用者指定的 report artifact；不寫 SQLite。
- 不讀 UI state、不掛主 UI、不建立 scheduler、不下單、不套用 lifecycle action、不重算 scoring / portfolio / backtest / lifecycle。

## Phase Gate

本次不解除 Phase 0 或 Phase 5 gate：

- weekly history 仍需真實時間累積，目前 `0/3`。
- multi-day dry-run record 仍需真實時間累積，目前 `1/3`。
- `production_scheduler_allowed=false`。
- Historical replay / source adapter 只能輔助暴露 source gap、payload gap 與 Workbench 資訊架構問題，不可視為 scheduler approval 或投資有效性證據。

## 驗證命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workbench_source_service.py tests\test_v2_workbench_prototype_cli.py tests\test_workbench_read_only_composer.py tests\test_pre_v2_readiness_service.py tests\test_pre_v2_readiness_cli.py tests\test_v1_9_agent_evidence_access.py -q -o addopts=
```

結果：`25 passed in 17.44s`

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\workbench_source_service.py app_module\workbench_read_only_composer.py scripts\inspect_v2_workbench_prototype.py tests\test_workbench_source_service.py tests\test_v2_workbench_prototype_cli.py
```

結果：通過。

```powershell
.\.venv\Scripts\python.exe -m mypy app_module\workbench_source_service.py app_module\workbench_read_only_composer.py scripts\inspect_v2_workbench_prototype.py
```

結果：`Success: no issues found in 3 source files`

```powershell
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py app_module\workbench_source_service.py app_module\workbench_read_only_composer.py scripts\inspect_v2_workbench_prototype.py
```

結果：量化防禦檢查通過，未新增金融 float 或未來函數違規。

## 尚未完成

- Phase 2 主 UI 整合尚未開始。
- Background evidence feed / scheduler write-mode 尚未啟用。
- Production scheduler approval 仍需 explicit design、backup / rollback、manual approval 與 Phase 0 真實時間 gate。

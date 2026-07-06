# V2.0 Workbench Phase 1 Read-only Prototype Closeout

> 日期：2026-07-06  
> 狀態：Phase 1 read-only prototype slice completed  
> 範圍：V2.0 Unified Decision Workbench 資訊架構 prototype，不是 Phase 2 主 UI，也不是 production scheduler approval。

## 1. 交付範圍

- 新增 `app_module/workbench_dtos.py`：定義 `WorkbenchDashboardDTO`、access boundary、status strip、review item、evidence summary 與 daily checklist DTO。
- 新增 `app_module/workbench_read_only_composer.py`：把既有 Daily Decision Desk snapshot、Pre-V2 readiness report、read-only Agent sample 與可選 Historical Replay summary 組成 read-only dashboard DTO。
- 新增 `app_module/workbench_replay_summary.py`：只接受 Historical Replay JSON summary，萃取 replay metadata、totals、outcome maturity、warnings 與限制；拒絕 replay DB。
- 新增 `scripts/inspect_v2_workbench_prototype.py`：sample-only prototype CLI，輸出 JSON 或 Markdown，可選 `_reference_fix` replay summary JSON。
- 新增 focused tests：DTO contract、composer read-only boundary、replay summary adapter、prototype CLI 與 forbidden-action / forbidden-language guard。

## 2. Read-only 邊界

- CLI 目前只支援 `--sample`，不讀正式 DB。
- `access_boundary.mode` 固定為 `read_only`，`writes_allowed=false`，`production_scheduler_allowed=false`。
- 不寫 evidence、不建立 schema、不建立 Windows Task Scheduler、不觸發 pipeline confirm。
- 不下單、不調整持倉、不套用 lifecycle action。
- 不重算 `ScoringEngine`、Portfolio、Backtest、Recommendation 或 lifecycle 狀態。
- Historical Replay 只作 simulated evidence input；不計入 weekly history、多日 dry-run 或 production scheduler gate。

## 3. Historical Replay 參考輸入

參考檔：

```text
D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/historical_replay_2026-01-06_2026-07-06_reference_fix.json
```

prototype 可揭露：

- replay mode / source label / date range。
- events、outcomes、ready / pending maturity。
- missing industry benchmark、pending insufficient future data、source missing screening matrix 等限制。
- `does_not_satisfy_phase0_gate=true` 與 `production_scheduler_allowed=false`。

不得把 replay 結果解讀為策略有效、正式排程 readiness 或交易績效結論。

## 4. 驗證紀錄

本輪已通過 focused tests：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbench_read_only_composer.py tests/test_workbench_replay_summary.py tests/test_v2_workbench_prototype_cli.py -q -o addopts=
```

結果：`14 passed`。

本輪已通過 changed-file verification：

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\workbench_dtos.py app_module\workbench_read_only_composer.py app_module\workbench_replay_summary.py scripts\inspect_v2_workbench_prototype.py
.\.venv\Scripts\python.exe -m mypy app_module\workbench_dtos.py app_module\workbench_read_only_composer.py app_module\workbench_replay_summary.py scripts\inspect_v2_workbench_prototype.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py app_module\workbench_dtos.py app_module\workbench_read_only_composer.py app_module\workbench_replay_summary.py scripts\inspect_v2_workbench_prototype.py
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --sample --format markdown
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --sample --replay-summary-json D:\Min\Python\Project\FA_Data\output\evidence_pipeline\historical_replay_reference_fix_20260706\historical_replay_2026-01-06_2026-07-06_reference_fix.json --format markdown
```

結果：

- `py_compile`：exit 0。
- targeted mypy：`Success: no issues found in 4 source files`。
- quant guard：financial float boundary 與 look-ahead bias checks 皆通過。
- sample CLI smoke：輸出 `source_mode=sample_only`、`production_scheduler_allowed=false`、`writes_allowed=false`、「今日待判讀」、Evidence Mode 與「不是交易建議」。
- replay CLI smoke：輸出 `source_mode=sample_plus_historical_replay`、`simulated_scheduler`、`Historical replay simulated evidence`、`missing_industry_benchmark` 與「不是交易建議」。

2026-07-06 cleanup 後，`_reference_fix` replay summary JSON 已移到 `D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/`；repo `output/evidence_pipeline/` 不再保留該 raw output。

Repo-wide mypy 另有既有失敗：

```powershell
.\.venv\Scripts\python.exe -m mypy app_module scripts
```

結果：`Found 115 errors in 29 files (checked 235 source files)`。錯誤集中於既有 `scripts/*`、`qa/full_app_healthcheck/*` 與少數 app notes；本輪新增的 `app_module/workbench_*.py` 與 `scripts/inspect_v2_workbench_prototype.py` 已由 targeted mypy 驗證通過。

## 5. Not Done

- Phase 2 主 UI 整合未完成。
- formal read-only DB reader 未完成。
- background evidence feed 未完成。
- weekly history 仍需真實時間累積，當前 gate 仍為 `0/3`。
- multi-day dry-run 仍需真實時間累積，當前 gate 仍為 `1/3`。
- production scheduler 仍未啟用。

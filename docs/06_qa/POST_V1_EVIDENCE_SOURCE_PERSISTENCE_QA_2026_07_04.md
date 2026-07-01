# Post-V1 Evidence Source Persistence QA 2026-07-04

## Scope

本 QA 覆蓋 Round 4：Durable Daily Decision Desk snapshot repository、snapshot capture / inspect CLI、Evidence capture durable snapshot provider wiring、Recommendation optional exclusion payload，以及 source coverage inspection CLI。

本輪未建立 scheduler，未建立 Forward Performance Dashboard UI，未修改 scoring / recommendation weights / portfolio position。

## Files Changed

新增：

- `app_module/decision_desk_snapshot_storage_dtos.py`
- `app_module/decision_desk_snapshot_repository.py`
- `scripts/capture_decision_desk_snapshot.py`
- `scripts/inspect_decision_desk_snapshots.py`
- `scripts/inspect_evidence_source_coverage.py`
- `tests/test_decision_desk_snapshot_repository.py`
- `tests/test_capture_decision_desk_snapshot_cli.py`
- `tests/test_decision_desk_snapshot_evidence_importer.py`
- `tests/test_recommendation_exclusion_payload.py`
- `tests/test_evidence_source_coverage_cli.py`
- `docs/superpowers/specs/2026-07-04-post-v1-evidence-source-persistence-design.md`
- `docs/superpowers/plans/2026-07-04-post-v1-evidence-source-persistence.md`
- `docs/06_qa/POST_V1_EVIDENCE_SOURCE_PERSISTENCE_QA_2026_07_04.md`

修改：

- `app_module/dtos/__init__.py`
- `app_module/evidence_event_importers.py`
- `scripts/capture_evidence_events.py`
- `tests/test_capture_evidence_events_cli.py`
- 核心狀態文件：`DOCUMENTATION_INDEX.md`、`PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、`system_vision_specification.md`

未觸碰高風險檔案：

- `decision_module/scoring_engine.py`
- portfolio position mutation path
- Windows Task Scheduler / cron / background scheduler
- dashboard UI

## Snapshot Repository Behavior

- `save_snapshot` 對同一 `snapshot_hash` idempotent。
- 同一 `decision_date` 若保存不同 hash，新 snapshot 會成為 `active`，舊 active snapshot 會標記為 `superseded`。
- `snapshot_hash` 由 deterministic JSON content hash 產生；`generated_at` 保存於 metadata，但不進 hash。
- missing / degraded section 會保存原始 quality 與 warnings，不補中性 payload。
- CLI 預設 dry-run，只有 `--confirm` 寫入。

## Importer Source Coverage

- `recommendation`：讀 persisted `RecommendationResultDTO`。
- `watchlist-trigger`：可由 durable Daily Decision Desk snapshot 匯入。
- `portfolio-alert`：可由 durable Daily Decision Desk snapshot 匯入。
- `risk-prompt`：可由 durable Daily Decision Desk snapshot 匯入。
- 缺 durable snapshot 時回 `source_missing_snapshot`，不偽造事件。
- `--source all` 先處理 recommendation，再處理 durable Daily Decision Desk snapshot sources。

## Why Not / Liquidity Payload Status

狀態：partial。

`RecommendationResultDTO` 已新增 optional payload fields，舊 JSON 可讀。有 payload 時 importer 可產生 `WHY_NOT_EXCLUDED` 與 `LIQUIDITY_GATE_EXCLUDED` events；缺 payload 時只回 `source_missing_exclusion_payload` diagnostic。

本輪不重算 Why Not / Liquidity Gate，也不回補舊 recommendation result。

## CLI Examples

```powershell
python scripts/capture_decision_desk_snapshot.py --decision-date 2026-06-30 --dry-run
python scripts/capture_decision_desk_snapshot.py --decision-date 2026-06-30 --confirm
python scripts/inspect_decision_desk_snapshots.py --json-output
python scripts/capture_evidence_events.py --source all --decision-date 2026-06-30 --confirm --json-output
python scripts/inspect_evidence_source_coverage.py --json-output
```

## Test Commands

已執行：

```powershell
python -m pytest tests/test_decision_desk_snapshot_repository.py tests/test_capture_decision_desk_snapshot_cli.py tests/test_decision_desk_snapshot_evidence_importer.py tests/test_recommendation_exclusion_payload.py tests/test_evidence_source_coverage_cli.py -q -o addopts=
python -m pytest tests/test_evidence_pipeline_smoke.py tests/test_forward_performance_read_model.py tests/test_evidence_capture_service.py tests/test_recommendation_evidence_importer.py -q -o addopts=
python -m pytest tests/test_capture_evidence_events_cli.py tests/test_watchlist_trigger_evidence_importer.py tests/test_portfolio_alert_evidence_importer.py tests/test_risk_prompt_evidence_importer.py -q -o addopts=
```

```powershell
python scripts/check_financial_float_boundaries.py
$files = Get-ChildItem app_module,data_module,scripts -Filter *.py | ForEach-Object { $_.FullName }; python -m py_compile @files
git diff --check
```

## Test Results

- Round 4 focused tests：15 passed
- Existing evidence pipeline / read model tests：16 passed
- Capture CLI / section importer regression tests：5 passed
- Financial float boundary scan：passed，exit 0
- `py_compile`：passed。PowerShell wildcard 不會以 bash 方式展開，因此使用等價檔案清單展開命令。
- `git diff --check`：passed，exit 0；僅出現 Git Windows line-ending warning，無 whitespace error。

## Known Limitations

- Forward Performance Dashboard UI 尚未完成。
- Scheduler 尚未建立；本輪也未設計正式排程。
- Why Not / Liquidity exclusion events 只會從已保存 payload 產生；舊 recommendation results 沒 payload 時不回補、不重算。
- Durable Daily Decision Desk snapshot 若 section 原本 missing / degraded，會如實保存 degraded / missing，不提供完整事件來源。
- Close-to-close forward outcome 仍是 research basis，不是可執行績效。

## Scheduler Readiness

目前上限：`ready_for_design`。

本輪不得、也未輸出 `production_ready`。若 durable snapshot 或 recommendation persisted source 不齊，coverage CLI 會回 `not_ready` 或 `dry_run_only`。

## Not Done

- 未建立正式 scheduler。
- 未建立 dashboard UI。
- 未修改 ScoringEngine。
- 未修改推薦權重。
- 未修改 portfolio position。
- 未導入 ML。
- 未自動 promote / demote / retire。
- 未宣稱任何 evidence source 或 event type 具投資有效性。

## Next Increment

1. Forward Performance Dashboard read-only UI。
2. Scheduler dry-run design。
3. Live vs Research Gap event linkage。
4. Signal Decay Monitor。

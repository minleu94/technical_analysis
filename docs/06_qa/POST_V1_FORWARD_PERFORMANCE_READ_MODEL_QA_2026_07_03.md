# Post-V1 Forward Performance Read Model QA（2026-07-03）

## Scope

本輪涵蓋兩段：

1. Phase A：Importer → Event Store → Outcome Calculator 端到端 smoke。
2. Phase B：Forward Performance Read Model v1 與 summary CLI。

非目標：Dashboard UI、scheduler、ML、scoring 權重、portfolio position、automatic lifecycle action。

## Checkpoint commit status

- Round 1 + Round 2 checkpoint commit 已完成：`68c9d10 feat: add post-v1 evidence event store and importers`。
- 依任務要求未 push checkpoint commit。

## Files changed

新增：

- `scripts/smoke_evidence_pipeline.py`
- `scripts/summarize_forward_performance.py`
- `app_module/forward_performance_read_model.py`
- `tests/test_evidence_pipeline_smoke.py`
- `tests/test_forward_performance_read_model.py`
- `tests/test_summarize_forward_performance_cli.py`
- `docs/superpowers/specs/2026-07-03-post-v1-forward-performance-read-model-design.md`
- `docs/superpowers/plans/2026-07-03-post-v1-forward-performance-read-model.md`
- `docs/06_qa/POST_V1_FORWARD_PERFORMANCE_READ_MODEL_QA_2026_07_03.md`

修改：

- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_vision_specification.md`

## E2E smoke summary

- `scripts/smoke_evidence_pipeline.py` 預設 dry-run；沒有 `--confirm` 不寫入 event 或 outcome。
- confirm 模式會在指定 `--db-path` 的 tmp / working-copy DB 建立 evidence schema、capture recommendation event、計算 close-to-close forward outcome。
- 重複 confirm 不重複 event，outcome 以 `(event_id, window_days, return_basis)` upsert。
- future data 不足時 outcome 以 `insufficient_future_data` 呈現，不納入 ready return metric。
- benchmark / industry benchmark 缺失不阻斷 outcome，但以 warnings 與 quality/status 揭露。

## Read model coverage

支援 filters：

- start / end date
- event type / family
- source type
- symbol
- regime
- sector
- profile id
- strategy version id
- window

支援 group by：

- `event_type`
- `event_family`
- `source_type`
- `regime`
- `sector`
- `profile_id`
- `score_percentile_bucket`
- `liquidity_state`
- `data_quality`

支援 metrics：

- sample size、pending count、missing count
- mean / median forward return bp
- mean / median benchmark excess bp
- mean / median industry excess bp
- positive rate bp
- win vs benchmark / industry rate bp
- mean MAE / MFE bp
- quality counts、warning counts
- first / last event date
- summary status

## CLI examples

```powershell
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline.py --db-path <tmp.db> --recommendation-result-id rec-smoke-001 --decision-date 2026-07-01 --windows 5 --json-output
```

```powershell
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline.py --db-path <tmp.db> --recommendation-result-id rec-smoke-001 --decision-date 2026-07-01 --windows 5 --confirm --json-output
```

```powershell
.\.venv\Scripts\python.exe scripts\summarize_forward_performance.py --db-path <tmp.db> --start-date 2026-07-01 --end-date 2026-07-01 --group-by event_type --window 5 --json-output
```

## Test commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_pipeline_smoke.py tests/test_forward_performance_read_model.py tests/test_summarize_forward_performance_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_event_repository.py tests/test_evidence_event_service.py tests/test_forward_performance_service.py tests/test_evidence_capture_service.py tests/test_recommendation_evidence_importer.py tests/test_capture_evidence_events_cli.py -q -o addopts=
.\.venv\Scripts\python.exe scripts/check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile app_module/evidence_event_dtos.py app_module/evidence_event_repository.py app_module/evidence_event_service.py app_module/evidence_event_importer_dtos.py app_module/evidence_event_importers.py app_module/evidence_capture_service.py app_module/forward_performance_service.py app_module/forward_performance_read_model.py scripts/capture_evidence_events.py scripts/calculate_forward_outcomes.py scripts/inspect_evidence_events.py scripts/smoke_evidence_pipeline.py scripts/summarize_forward_performance.py
git diff --check
```

## Test results

- Phase A + Phase B focused tests：`15 passed`
- Evidence regression tests：`22 passed`
- Financial float boundary scanner：passed
- py_compile：passed
- `git diff --check`：passed，僅顯示既有 CRLF warning。

## Known limitations

- Recommendation source 若未保存 benchmark / industry benchmark，readiness 會以 missing / degraded 狀態揭露。
- DDD 類 importer 仍需 durable snapshot repository；目前 provider importers 不是 production scheduler source。
- read model 只彙總已保存 evidence，不建立 dashboard、不進行交易建議、不證明 alpha。
- MAE / MFE 只有來源 outcome 有欄位時才會彙總；Forward Outcome Calculator v1 目前主要產生 close-to-close return。

## Not done

- 未做 dashboard UI。
- 未建立 scheduler。
- 未改 ScoringEngine 或推薦權重。
- 未改 portfolio position。
- 未自動 promote / demote / retire。

## Scheduler readiness

Not ready for production schedule。下一步可做 dry-run scheduler design，但不應建立 Windows Task Scheduler、cron 或背景排程。

## Next increment

1. Forward Performance Dashboard read-only UI。
2. Daily Decision Desk durable snapshot repository。
3. Why Not / Liquidity exclusion persisted payload。
4. Scheduler dry-run design。
5. Signal Decay Monitor。

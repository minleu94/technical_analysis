# Post-V1 Historical Evidence Replay QA

日期：2026-07-06

## Scope

本 QA 記錄 Historical Evidence Replay v1。此功能用 working-copy / replay DB 模擬歷史 scheduler，每個歷史交易日只看當日以前可取得的 persisted Recommendation result 與價格資料，並把保存的 evidence metadata 標成 `historical_replay` / `simulated_scheduler`。

此功能不是正式 scheduler，不修改既有 scheduled dry-run，不寫 formal evidence DB，不取代 weekly history、多日 dry-run、manual approval 或 production scheduler gate。

## Files Changed

新增：

- `app_module/historical_evidence_replay.py`
- `scripts/replay_historical_evidence_pipeline.py`
- `tests/test_historical_evidence_replay.py`
- `tests/test_replay_historical_evidence_pipeline_cli.py`
- `docs/superpowers/plans/2026-07-06-historical-evidence-replay.md`
- `docs/06_qa/POST_V1_HISTORICAL_EVIDENCE_REPLAY_QA_2026_07_06.md`

修改：

- `app_module/evidence_pipeline_runner_dtos.py`
- `app_module/evidence_event_importer_dtos.py`
- `app_module/evidence_pipeline_runner.py`
- `app_module/evidence_capture_service.py`
- `app_module/forward_performance_service.py`
- `PROJECT_NAVIGATION.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_architecture.md`
- `docs/07_guides/APPLICATION_MANUAL.md`

## Behavior

- CLI 預設 dry-run；只有 `--confirm` 才會對 replay DB 寫入 evidence events / outcomes。
- Source DB 與 replay DB 必須不同路徑。
- Replay DB 不存在時會由 source DB 複製；已存在時必須加 `--overwrite-replay-db` 才會重建。
- `--outcome-mode final` 為 CLI 預設，逐日 capture 完成後只在 replay end date 計算一次 forward outcomes，適合半年 replay；`--outcome-mode daily` 保留逐日 maturity 語意，但大型 DB 會慢很多。
- 每日 replay 只選 `created_at <= decision_date` 的 persisted Recommendation result。
- 缺 as-of Recommendation result 時只記錄 `recommendation_asof_result_missing`，不使用未來 result 補值。
- `EvidenceCaptureService` 會將 `replay_mode`、`source_label`、`replay_run_id`、`replay_decision_date` 與 `replay_data_as_of_date` 寫入 event metadata。
- `ForwardPerformanceService.calculate(data_as_of_date=...)` 會限制 event price / outcome price search，不提前讀未來價格；service 也會 cache symbol daily price series 與 index return，避免半年 replay 重複查詢同一批價格。

## Test Commands

已執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_historical_evidence_replay.py tests\test_replay_historical_evidence_pipeline_cli.py tests\test_evidence_pipeline_runner.py tests\test_evidence_capture_service.py tests\test_recommendation_evidence_importer.py tests\test_evidence_source_coverage_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\historical_evidence_replay.py app_module\evidence_pipeline_runner_dtos.py app_module\evidence_event_importer_dtos.py app_module\evidence_pipeline_runner.py app_module\evidence_capture_service.py app_module\forward_performance_service.py scripts\replay_historical_evidence_pipeline.py tests\test_historical_evidence_replay.py tests\test_replay_historical_evidence_pipeline_cli.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
git diff --check
```

## Test Results

- Focused replay / CLI / evidence regression tests：31 passed。
- `py_compile` changed Python files：passed。
- `scripts\quant_guard_linter.py`：passed；內含 float boundary 與 look-ahead bias checks。
- `scripts\check_financial_float_boundaries.py`：passed。
- `git diff --check`：passed；僅顯示 LF/CRLF 轉換 warning，無 whitespace error。

## Scheduler Boundary

Historical replay 只能回答「如果半年前開始每天跑現在這套 evidence pipeline，可能會看到哪些 source gap / payload gap / pending outcome / V2.0 設計問題」。它不能回答 production scheduler 是否可啟用，也不能把 Phase 0 的 weekly history `0/3` 或 multi-day dry-run `1/3` 視為已完成。

正式 scheduler 仍需：

- 真實 weekly evidence operations history。
- 真實 multi-day scheduled dry-run record。
- Working-copy smoke 與 rollback / backup 檢查。
- Manual approval checklist。
- 明確 production write-mode scheduler design。

## Known Limitations

- Replay 依賴已 persisted 的 Recommendation result；若歷史當日以前沒有 result，只能記錄 source gap。
- Daily Decision Desk snapshot / watchlist / portfolio / risk prompt 仍取決於 source DB 內既有 durable snapshot 與 payload。
- Close-to-close forward outcome 仍是 research evidence，不是可執行實盤績效。
- Replay 不回補舊 recommendation payload，不重算舊 result，不產生交易建議。

# Post-V1 Signal Decay Monitor QA

日期：2026-07-09

## Scope

本輪新增 Signal Decay Monitor v1：以已保存 Evidence Event / Outcome 與 Live vs Research Gap observation 檢查 signal scope 的近期 evidence 是否相對長窗轉弱，並保存 append-only decay observation。

本輪不建立正式 scheduler、不建立 UI、不修改策略權重、不修改 portfolio、不套用 lifecycle action，也不宣稱任何訊號有效或失效。

## Files Changed

新增：

- `app_module/signal_decay_dtos.py`
- `app_module/signal_decay_repository.py`
- `app_module/signal_decay_service.py`
- `scripts/capture_signal_decay.py`
- `scripts/inspect_signal_decay.py`
- `tests/test_signal_decay_repository.py`
- `tests/test_signal_decay_service.py`
- `tests/test_signal_decay_cli.py`
- `tests/test_signal_decay_lifecycle_payload.py`
- `tests/test_signal_decay_no_trading_language.py`
- `docs/superpowers/specs/2026-07-09-post-v1-signal-decay-monitor-design.md`
- `docs/superpowers/plans/2026-07-09-post-v1-signal-decay-monitor.md`
- `docs/06_qa/POST_V1_SIGNAL_DECAY_MONITOR_QA_2026_07_09.md`

修改：

- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_vision_specification.md`
- `docs/07_guides/APPLICATION_MANUAL.md`

未觸碰：

- `decision_module/scoring_engine.py`
- 推薦權重契約
- portfolio mutation flow
- Strategy Lifecycle state apply flow
- production scheduler / Windows Task Scheduler / cron

## Repository Behavior

`SignalDecayRepository` 建立 `signal_decay_observations` table，使用 deterministic `decay_hash` 做 idempotent save。`list_observations` 可依 observation date、scope type、scope id 篩選；`summarize_decay` 回傳 status / suggestion / confidence / quality counts 與 warnings count。

## Service Behavior

`SignalDecayService` 支援：

- `evaluate_signal_scope`
- `evaluate_all_scopes`
- `save_decay_observation`
- `list_decay_observations`
- `summarize_decay`
- `build_lifecycle_proposed_evidence_payload`

v1 支援 scope：

- `event_type`
- `event_family`
- `strategy_version`
- `profile`

`factor_name` 與 portfolio source type 尚未有穩定 evidence scope key，本輪 deferred。

## Metrics

使用整數 bp：

- benchmark excess mean / median
- win rate vs benchmark
- industry excess mean
- MAE mean
- live gap vs forward evidence mean
- live gap vs benchmark mean
- quality degraded ratio

pending / missing outcome 不進平均；缺 benchmark 或 live gap 時只輸出 diagnostic 並降低 confidence。

## Status and Suggestions

狀態：

- `no_data`
- `insufficient_sample`
- `stable`
- `watch`
- `decaying`
- `severe_decay`

suggestion：

- `none`
- `hold`
- `watch`
- `demote_candidate`
- `retire_candidate`

`insufficient_sample` 永遠不產生 demote / retire candidate。`retire_candidate` 只在樣本足夠、benchmark/live gap 都存在、short/long 都弱且 live gap 支持時出現。

## Lifecycle Evidence Policy

本輪只建立 proposed payload：

- `source=signal_decay_monitor_v1`
- `status=proposed`
- `apply_action=false`

不寫 lifecycle repository，不改 strategy lifecycle state，不自動 promote / demote / retire。

## CLI Examples

```powershell
.\.venv\Scripts\python.exe scripts\inspect_signal_decay.py --observation-date 2026-07-09 --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-09 --scope event_type --scope-id recommendation_included --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-09 --scope all --confirm --db-path <working-copy-db> --json-output
```

`--confirm` 必須搭配 explicit `--db-path`；疑似正式 DB 需要額外 `--allow-production-db-confirm`。

## Test Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_signal_decay_repository.py tests\test_signal_decay_service.py tests\test_signal_decay_cli.py tests\test_signal_decay_lifecycle_payload.py tests\test_signal_decay_no_trading_language.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_live_research_gap_service.py tests\test_forward_performance_read_model.py tests\test_evidence_pipeline_runner.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile <expanded app_module and scripts python file list>
git diff --check
```

## Test Results

初始 TDD red：

- Signal Decay 測試因 `app_module.signal_decay_*` module 不存在而失敗，符合預期。

目前結果：

- `.\.venv\Scripts\python.exe -m pytest tests\test_signal_decay_repository.py tests\test_signal_decay_service.py tests\test_signal_decay_cli.py tests\test_signal_decay_lifecycle_payload.py tests\test_signal_decay_no_trading_language.py -q -o addopts=`：14 passed。
- `.\.venv\Scripts\python.exe -m pytest tests\test_live_research_gap_service.py tests\test_forward_performance_read_model.py tests\test_evidence_pipeline_runner.py -q -o addopts=`：18 passed。
- `.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py`：exit 0。
- `.\.venv\Scripts\python.exe -m py_compile <expanded app_module and scripts python file list>`：exit 0。PowerShell 以 `Get-ChildItem app_module -Filter *.py` 與 `Get-ChildItem scripts -Filter *.py` 展開 wildcard 後傳入 `py_compile`。
- `git diff --check`：exit 0；僅出現文件 LF/CRLF 轉換 warning，無 whitespace error。

## Known Limitations

- day window 參數目前保存為 metadata，v1 實際判讀以 event-count window 為主。
- `factor_name` 與 portfolio source type 尚未成為穩定 decay scope。
- Live gap 缺資料時只能降低 confidence，不能用目前資料推導完整實帳歸因。
- 小樣本轉弱只可視為資料品質與覆蓋率問題，不能視為策略失敗。
- lifecycle proposed payload 不等於 action。

## Scheduler Readiness

維持 `ready_for_manual_confirm`。本輪未建立正式 scheduler；production scheduler 仍需要人工核准、rollback / recovery 檢查與多次 dry-run 穩定紀錄。

## Not Done

- 未建立 Signal Decay Dashboard UI。
- 未建立 production scheduler。
- 未寫入或套用 lifecycle evidence。
- 未宣稱 alpha。
- 未證明任一事件類型、策略版本或 Profile 有效或失效。

## Next Increment

1. Decision Quality Review。
2. Signal Decay Dashboard read-only UI。
3. Live vs Research Gap Dashboard read-only UI。
4. production scheduler approval implementation only after explicit human approval。

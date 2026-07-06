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

## Reference Return Fix Audit

日期：2026-07-06

### Root Cause

半年度 replay 初版產物中，raw forward return 可用，但 ready outcomes 的 `benchmark_return_bp`、`industry_return_bp`、`benchmark_excess_bp` 與 `industry_excess_bp` 全缺。稽核後確認不是 ScoringEngine 或策略問題，而是 forward outcome reference lookup 問題：

- `evidence_events.benchmark_id` 全部為 `NULL`，但市場 benchmark 應可使用預設 TAIEX reference。
- `market_indices` 在目前 SQLite source 中是單一未命名市場序列：`指數名稱` 與 `收盤指數` 皆為 `NULL`，有效 close 存在 `收盤價`，原 lookup 只查 `指數名稱 = ?` 與 `收盤指數`，因此全數查不到。
- `evidence_events.industry_benchmark_id` 全部為 `NULL`；只有少數事件帶 `sector`。這些 sector 值需做保守 TWSE industry alias mapping，例如 `電子零組件業 -> 電子零組件類指數`、`塑膠工業 -> 塑膠類指數`、`化學工業, 化學生技醫療 -> 化學類指數`。
- 大多數事件沒有 sector/industry payload，這是 recommendation payload gap；不可回填舊 recommendation payload，也不可把 missing reference return 當 0。

### Fix Scope

最小修正僅限 `ForwardPerformanceService` 的 reference lookup：

- missing event benchmark 時使用 `TAIEX` 作為市場 benchmark default。
- `market_indices` 支援 named TAIEX aliases，也支援未命名單一 market series，並在 `收盤指數` 無值時 fallback 到 `收盤價`。
- `industry_indices` 支援 sector token split 與保守 suffix normalization：`工業` / `產業` / `業` 可映射到 `類指數` / `類報酬指數`。
- 查不到 reference 時仍保留 `NULL` 與 warning，不填 0。
- 未修改 portfolio、recommendation score、ScoringEngine 或 production scheduler。

修正檔案：

- `app_module/forward_performance_service.py`
- `tests/test_forward_performance_service.py`
- `docs/06_qa/POST_V1_HISTORICAL_EVIDENCE_REPLAY_QA_2026_07_06.md`

### Reproduction And Tests

新增 regression tests 先重現失敗再修正：

- event `benchmark_id=None`，`market_indices` 為未命名序列且只在 `收盤價` 有值時，應能填入 benchmark return / excess。
- event 只有 `sector="電子零組件業"`、沒有 `industry_benchmark_id` 時，應能映射到 `電子零組件類指數` 並填入 industry return / excess。

已執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_forward_performance_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_forward_performance_service.py tests\test_historical_evidence_replay.py tests\test_replay_historical_evidence_pipeline_cli.py tests\test_evidence_pipeline_smoke.py tests\test_evidence_event_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\forward_performance_service.py app_module\historical_evidence_replay.py scripts\replay_historical_evidence_pipeline.py tests\test_forward_performance_service.py tests\test_historical_evidence_replay.py tests\test_replay_historical_evidence_pipeline_cli.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
git diff --check
```

結果：

- `tests/test_forward_performance_service.py`：7 passed。
- focused replay / CLI / smoke regression：24 passed。
- `py_compile`：passed。
- `quant_guard_linter.py`：passed，包含 float boundary 與 look-ahead checks。
- `check_financial_float_boundaries.py`：passed。
- `git diff --check`：passed；只有 LF/CRLF warning，無 whitespace error。

### Replay Rerun Summary

修正後以新隔離 DB 重跑，不寫正式 evidence DB：

- DB：`tmp/historical_replay/evidence_replay_2026-01-06_2026-07-06_reference_fix.db`
- Report：`output/evidence_pipeline/historical_replay_2026-01-06_2026-07-06_reference_fix.md`
- JSON：`output/evidence_pipeline/historical_replay_2026-01-06_2026-07-06_reference_fix.json`
- Log：`output/evidence_pipeline/historical_replay_2026-01-06_2026-07-06_reference_fix.log`

本次 source DB 已包含 `2026-07-06` 交易資料，因此 rerun 為 118 trading days；舊 artifact 為 117 days，最後交易日是 `2026-07-03`。

Rerun QA：

- `evidence_events`：118,056，全部 metadata 含 `historical_replay`。
- `evidence_outcomes`：472,224。
- outcome status / quality：
  - ready / degraded：378,491。
  - ready / observed：2,029。
  - insufficient_future_data / missing：91,488。
  - missing_price / missing：216。
- ready outcomes：380,520。
- ready benchmark return / excess：380,520 / 380,520。
- ready industry return / excess：2,029 / 2,029。
- ready warning split：
  - `["missing_industry_benchmark"]`：378,491。
  - `[]`：2,029。
- daily `source_missing_screening_matrix` diagnostic：118 / 118 days，維持 payload gap 記錄，未回填舊 recommendation payload。

### Look-Ahead Bias Check

Replay outcome 仍只使用決策日後、且不超過 replay data-as-of 的價格：

- `outcome_price_date > data_as_of_date`：0。
- `event_date` / `as_of_date` / `available_date` 晚於 `decision_date`：0。
- `ForwardPerformanceService.calculate(data_as_of_date=...)` 只限制 price lookup 與 outcome maturity，不把未來價格混入 signal、feature、recommendation 或 score。

### Remaining Limitations

- industry reference 仍高度缺失，因為 118,056 events 中只有 719 events 有 sector，`benchmark_id` 與 `industry_benchmark_id` 仍都是 source payload 內的 `NULL`。本次只在既有 sector 可映射時填 industry return。
- `source_missing_screening_matrix` 仍是每日 recommendation payload gap；此修正沒有也不應該回填舊 screening matrix。
- replay 是 `historical_replay` / `simulated_scheduler` research artifact，不代表 production scheduler approval。

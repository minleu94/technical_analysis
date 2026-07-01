# Post-V1 Evidence-Driven baldr Round 3 實作計畫：E2E Smoke + Forward Performance Read Model v1

> 日期：2026-07-03  
> 狀態：已執行  
> 前置 checkpoint：Round 1 + Round 2 已通過 focused tests 並建立 local checkpoint commit `68c9d10`。

## 1. Checkpoint 與 Preflight

- [x] 執行 Round 1 + Round 2 focused pytest。
- [x] 執行 financial float boundary scanner。
- [x] 執行 `git diff --check`。
- [x] 建立 local checkpoint commit，不 push。
- [x] 閱讀 Round 1 / Round 2 spec、plan、QA、evidence event / importer / outcome calculator code 與核心文件。

## 2. Phase A：E2E Smoke

- [x] 新增 `tests/test_evidence_pipeline_smoke.py`，先覆蓋 dry-run、confirm、idempotency、future data pending、missing benchmark、禁止 UI import / 交易語言。
- [x] 新增 `scripts/smoke_evidence_pipeline.py`。
- [x] 使用 tmp `TWStockConfig` 與 tmp SQLite DB 建立 persisted Recommendation result fixture。
- [x] 驗證 persisted Recommendation result → capture service → event store → forward outcome → summary JSON。
- [x] Phase A focused tests 通過後才進 Phase B。

## 3. Phase B：Read Model

- [x] 新增 `tests/test_forward_performance_read_model.py`，覆蓋 group by、score bucket、insufficient sample、pending 排除、missing benchmark / industry。
- [x] 新增 `app_module/forward_performance_read_model.py`。
- [x] 新增 `tests/test_summarize_forward_performance_cli.py`，覆蓋 deterministic JSON、filters、CSV output、禁止 UI import / 交易語言。
- [x] 新增 `scripts/summarize_forward_performance.py`。

## 4. 文件與 QA

- [x] 新增 Round 3 design / plan。
- [x] 新增 Round 3 QA。
- [x] 更新 Documentation Index、Project Snapshot、6M Roadmap 與 System Vision。
- [x] 明確標示 dashboard 未完成、alpha 未證明、scheduler not ready for production schedule。

## 5. 驗證 Gate

- [x] Phase A + Phase B focused tests。
- [x] Evidence event / importer / capture / outcome regression tests。
- [x] Financial float boundary scanner。
- [x] py_compile。
- [x] `git diff --check`。

## 6. 未做

- 未建立 dashboard UI。
- 未建立 scheduler、Windows Task Scheduler、cron 或背景排程。
- 未改 `ScoringEngine`、推薦權重、portfolio position 或 lifecycle action。
- 未把 close-to-close research outcome 稱為實盤績效。

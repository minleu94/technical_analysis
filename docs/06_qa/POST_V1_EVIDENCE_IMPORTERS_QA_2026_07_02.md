# Post-V1 Evidence Importers QA（2026-07-02）

## Scope

本輪新增 Evidence source importer / capture pipeline v1，承接 Post-V1 Evidence Event Store v1 / Forward Outcome Calculator v1。

## Completed

- 新增 `EvidenceImportSource`、`EvidenceImportResult`、`EvidenceImportDiagnostic`、`EvidenceCaptureRequest`、`EvidenceCaptureSummary`。
- 新增 Recommendation importer v1，讀取 persisted `RecommendationResultDTO`，不重跑 scoring。
- 新增 Watchlist Trigger importer v1，讀取 `WatchlistTriggerSummary` DTO / provider。
- 新增 Portfolio Alert importer v1，讀取 `PortfolioAlertSummary` / attribution DTO，不修改 portfolio state。
- 新增 Risk Prompt importer v1，讀取 `DecisionDeskRiskPromptSummary` DTO。
- 新增 `EvidenceCaptureService`，統一 dry-run、confirm、event hash sample、duplicate counting、diagnostics 與 fail-closed 行為。
- 新增 `scripts/capture_evidence_events.py`，CLI 預設 dry-run，只有 `--confirm` 寫入 DB。

## Source Support Boundary

- `recommendation`：CLI 可透過 `RecommendationRepository` 讀 persisted result。
- `watchlist-trigger` / `portfolio-alert` / `risk-prompt`：service/importer 支援注入 DTO provider；CLI v1 未自動建構完整 DDD snapshot provider，無 provider 時回傳 `source_unsupported` diagnostic，不寫假事件。
- Why-not / Liquidity exclusion：目前 `RecommendationResultDTO` 未持久化 exclusion payload，importer 回傳 `source_missing_exclusion_payload`，不建立 excluded events。

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_capture_service.py tests\test_recommendation_evidence_importer.py tests\test_watchlist_trigger_evidence_importer.py tests\test_portfolio_alert_evidence_importer.py tests\test_risk_prompt_evidence_importer.py tests\test_capture_evidence_events_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_event_repository.py tests\test_evidence_event_service.py tests\test_forward_performance_service.py tests\test_evidence_event_cli.py tests\test_evidence_capture_service.py tests\test_recommendation_evidence_importer.py tests\test_watchlist_trigger_evidence_importer.py tests\test_portfolio_alert_evidence_importer.py tests\test_risk_prompt_evidence_importer.py tests\test_capture_evidence_events_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\evidence_event_dtos.py app_module\evidence_event_importer_dtos.py app_module\evidence_event_importers.py app_module\evidence_capture_service.py scripts\capture_evidence_events.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
git diff --check
```

Result:

- Round 2 focused importer / CLI tests: `10 passed`.
- Round 1 + Round 2 evidence focused suite: `28 passed`.
- `py_compile`: passed.
- `check_financial_float_boundaries.py`: passed.
- `git diff --check`: passed；僅有 Windows CRLF conversion warnings，無 whitespace error。

## Limitations

- 尚未建立 Forward Performance read model / dashboard。
- 尚未自動 scheduler。
- 尚未證明任何 Recommendation、Watchlist Trigger、Portfolio Alert 或 Risk Prompt 具備投資有效性。
- DDD 類來源要進入 CLI 正式批次 capture，仍需要 durable snapshot repository 或明確 provider wiring。

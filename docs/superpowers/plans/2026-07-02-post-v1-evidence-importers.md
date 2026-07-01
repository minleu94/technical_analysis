# Post-V1 Evidence Importers Implementation Plan

## Objective

新增 Evidence source importers 與 capture CLI，讓 V1 evidence event store 可從已持久化或已組成的決策 DTO 累積事件，並維持 dry-run / confirm / idempotency / fail-closed 邊界。

## Checklist

- [ ] 新增 importer DTO contract。
- [ ] 擴充 Evidence Event type enum，保留既有 generic type 相容性。
- [ ] 新增 Recommendation / Watchlist / Portfolio Alert / Risk Prompt importer。
- [ ] 新增 EvidenceCaptureService，統一 dry-run、confirm、duplicate、diagnostic summary。
- [ ] 新增 `scripts/capture_evidence_events.py`。
- [ ] 新增 importer / capture / CLI 測試。
- [ ] 更新核心文件與 QA 紀錄。
- [ ] 執行 pytest、py_compile、float boundary、diff check。

## TDD Targets

1. Capture service dry-run 不寫入，confirm 才寫入。
2. Recommendation importer 保存 persisted DTO，不重算 percentile。
3. Recommendation 重複 capture 不新增 duplicate。
4. Recommendation 缺 exclusion payload 回報 diagnostic。
5. Watchlist importer 不依賴 UI 模組。
6. Portfolio importer 不修改 portfolio state。
7. Risk prompt importer 不產生 forbidden recommendation language。
8. CLI 預設 dry-run；`--confirm` 才寫入；`--source all` 遇 unsupported 仍完成其他 source。

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_capture_service.py tests\test_recommendation_evidence_importer.py tests\test_watchlist_trigger_evidence_importer.py tests\test_portfolio_alert_evidence_importer.py tests\test_capture_evidence_events_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_event_repository.py tests\test_evidence_event_service.py tests\test_forward_performance_service.py tests\test_evidence_event_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\evidence_event_importer_dtos.py app_module\evidence_event_importers.py app_module\evidence_capture_service.py scripts\capture_evidence_events.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
git diff --check
```


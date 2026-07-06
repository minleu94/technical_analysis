# V1.7 Negative Evidence Closeout（2026-07-05）

## Scope

V1.7 將推薦流程中的入選與未入選候選保存到同一個 evidence layer，避免只留下推薦名單而缺少「為何不選」。

本次完成：

- `RecommendationResultDTO.screening_matrix_json`：保存 pass / fail / degraded / skipped / missing matrix，並維持舊 JSON 相容。
- `RecommendationService`：在推薦當下保存 selected、below threshold、outside top N、insufficient history、no signal、screening exception 等 matrix rows。
- Qt 推薦結果保存：一併保存 screening matrix、Why Not payload、Liquidity payload、quality 與 warnings。
- Evidence importer：新增 `screening_matrix_pass`、`screening_matrix_fail`、`screening_matrix_degraded`、`screening_matrix_skipped`、`screening_matrix_missing` events，並持續支援 `why_not_excluded` / `liquidity_gate_excluded`。
- Source coverage / capability registry：新增 `recommendation.screening_matrix` 與 `screening_matrix_missing` warning；舊 result 缺 matrix 時只降為 `dry_run_only` warning。
- 2026-07-06 follow-up：`RecommendationService` 會將 `min_volume_ratio` / `volume_ratio_min` 成交量門檻造成的 empty strategy result 標記為 `liquidity_volume_ratio_below_min`，並寫入 Liquidity payload；語意沿用 `StrategyConfigurator` 的量比轉百分比規則，不改 scoring、不回補舊 result。

## Not Done

- 不改 `ScoringEngine`、推薦權重、回測績效或 portfolio sizing。
- 不回補舊 Recommendation result，也不由 importer 事後重算 screening matrix。
- 不啟用 production scheduler，不寫 production evidence DB。
- 不把 negative evidence、Why Not 或 Liquidity exclusion 解讀為投資有效性證明。
- 不自動 demote / retire 策略版本；所有 lifecycle action 仍需人工審核。

## Verification

已執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_v1_7_negative_evidence.py -q -o addopts=
```

結果：`3 passed`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_evidence_importer.py tests/test_recommendation_exclusion_payload.py tests/test_evidence_source_coverage_cli.py tests/test_evidence_source_coverage_service.py tests/test_recommendation_v1_7_negative_evidence.py -q -o addopts=
```

結果：`15 passed`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_ranking_service.py tests/test_recommendation_dto_roundtrip.py tests/test_data_source_capability_registry.py -q -o addopts=
```

結果：`17 passed`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
```

結果：`38 passed`

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

結果：`通過 24 / 失敗 0 / 跳過 4`

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
```

結果：financial float boundary、look-ahead bias 與 quant guard 均通過。

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module/dtos/__init__.py app_module/recommendation_service.py ui_qt/views/recommendation_view.py app_module/evidence_event_dtos.py app_module/evidence_event_importers.py app_module/evidence_source_coverage_service.py data_module/data_source_capability_registry.py app_module/cross_sectional_factor_pipeline.py app_module/evidence_pipeline_runner.py
```

結果：通過。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_pipeline.py tests/test_evidence_pipeline_runner.py -q -o addopts=
```

結果：`17 passed`

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

結果：`Success: no issues found in 279 source files`

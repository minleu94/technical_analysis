# V1.6 Cross-sectional Factor Pipeline Closeout（2026-07-05）

## Scope

本次 closeout 完成 V1.6 Cross-sectional Factor Pipeline & Sector Rotation v2 的 v1 研究治理底座。範圍限定在保存與檢查 daily factor snapshot，不修改推薦分數、不新增 production scheduler、不抓外部資料。

## Delivered

1. Snapshot storage
   - 新增 `CrossSectionalFactorSnapshot`、`CrossSectionalFactorRow` 與 diagnostics DTO。
   - 新增 `data_module/cross_sectional_factor_migration.py`，建立 `cross_sectional_factor_snapshots` 與 `cross_sectional_factor_rows`。
   - 新增 `CrossSectionalFactorRepository`，以 snapshot hash 做 idempotent save，支援唯讀 inspection 不自動建表。

2. Factor pipeline
   - 新增 `CrossSectionalFactorPipeline`，以既有 `FactorService.build_snapshot()` / `FactorGate` 套用 `available_date <= decision_date`、quality 與 missing policy。
   - 保存通過 gate 的 factor records，並產生 deterministic rank / quantile bp。
   - sector / concept metadata 僅使用呼叫端提供的當下 snapshot；`ConceptBasketDefinition.available_date` 晚於 decision date 時只輸出 diagnostic。

3. Attribution inspection
   - 新增 `build_cross_sectional_factor_attribution_summary()`，彙總 factor、quality、rank bucket、sector、concept 與 diagnostics counts。
   - 新增 `scripts/inspect_cross_sectional_factor_snapshot.py`，支援 `--latest` / `--snapshot-id` 與 JSON / Markdown 輸出。
   - CLI 對 missing DB fail closed，不建立 DB、不寫 snapshot。

## Not Done / Boundaries

- V1.6 不把新 factor 直接接進 `ScoringEngine`，不改推薦權重、不把 rank / quantile 當作推薦。
- V1.6 不新增三大法人、信用交易、TDCC 或其他外部資料 ingestion。
- V1.6 不建立 production scheduler；snapshot 必須由受控 workflow 明確保存。
- V1.7 才接續 Screening Matrix、Why Not / Liquidity payload 完整持久化與 Negative Evidence。

## Verification

2026-07-05 final verification：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_repository.py tests/test_cross_sectional_factor_pipeline.py tests/test_cross_sectional_factor_attribution.py tests/test_inspect_cross_sectional_factor_snapshot_cli.py tests/test_factor_service_research_run.py -q -o addopts=
```

Result：`15 passed in 1.37s`

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\cross_sectional_factor_dtos.py app_module\cross_sectional_factor_repository.py app_module\cross_sectional_factor_pipeline.py app_module\cross_sectional_factor_attribution.py data_module\cross_sectional_factor_migration.py scripts\inspect_cross_sectional_factor_snapshot.py
```

Result：passed

```powershell
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
```

Result：`check_financial_float_boundaries.py` passed；`check_look_ahead_bias.py` passed。

```powershell
git diff --check
```

Result：passed；only LF-to-CRLF working-copy warnings were reported.

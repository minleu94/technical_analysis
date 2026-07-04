# V1.5 Data Credibility & Corporate Action Gate Closeout 2026-07-04

## Scope

本 closeout 覆蓋 V1.5 Data Credibility & Corporate Action Gate v1。此版本只建立資料可信度治理層與唯讀檢查入口，不抓外部資料、不重建正式資料、不改 `ScoringEngine`、不啟用 production scheduler，也不宣稱任何推薦或策略具備投資有效性。

## Delivered

1. **Data Source Capability Registry v1**
   - `data_module/data_source_capability_registry.py`
   - `scripts/inspect_data_source_capabilities.py`
   - 涵蓋 price、evidence、corporate action candidate 與 microstructure candidate source 的 status、欄位、available-date policy、missing policy 與 warnings。

2. **Corporate action / adjusted price policy**
   - `data_module/corporate_action_policy.py`
   - `scripts/inspect_corporate_action_policy.py`
   - 明確標示 raw price 是目前 decision layer 預設；full hindsight adjusted price 不得進決策特徵；decision-date adjusted candidate 必須等正式可得日治理後才可接入。

3. **Governed microstructure preflight metadata**
   - `data_module/microstructure_source_preflight.py`
   - `app_module/recommendation_portfolio_backtest_service.py`
   - 推薦組合 replay 的 `microstructure_preflight` 會輸出 governed source metadata、source capability status 與 missing policy；不改 PnL、成交價、cash ledger、sizing 或 Research Run lifecycle。

4. **Evidence Source Coverage Service**
   - `app_module/evidence_source_coverage_service.py`
   - `scripts/inspect_evidence_source_coverage.py`
   - `app_module/evidence_pipeline_runner.py`
   - `app_module/evidence_scheduler_readiness.py`
   - CLI、runner 與 readiness evaluator 共用同一份 source coverage 分級。Persisted recommendation / durable DDD snapshot section 缺口是 blocking gaps；why-not / liquidity optional payload 缺口是 warnings / `dry_run_only`。

## Verification

已執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_data_source_capability_registry.py tests/test_corporate_action_policy.py tests/test_recommendation_portfolio_backtest.py tests/test_evidence_source_coverage_service.py tests/test_evidence_source_coverage_cli.py tests/test_evidence_pipeline_runner.py tests/test_evidence_scheduler_readiness.py -q -o addopts=
```

結果：`57 passed, 24 warnings`。warnings 來自既有推薦組合回放「同日收盤訊號同日收盤成交」研究假設提示。

```powershell
.\.venv\Scripts\python.exe -m py_compile data_module\data_source_capability_registry.py data_module\corporate_action_policy.py data_module\microstructure_source_preflight.py app_module\evidence_source_coverage_service.py scripts\inspect_data_source_capabilities.py scripts\inspect_corporate_action_policy.py scripts\inspect_evidence_source_coverage.py scripts\evaluate_evidence_scheduler_readiness.py
```

結果：通過。

```powershell
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
```

結果：通過；financial float boundary 與 look-ahead bias check 均無違規。

```powershell
git diff --check
```

結果：通過；僅有 Git CRLF 換行提示。

## Boundary

- V1.5 沒有接入正式 corporate action timeline、處置股、分盤、全額交割、三大法人、信用交易或 TDCC source。
- V1.5 沒有建立 adjusted price series，也沒有把 adjusted price 接入 backtest / recommendation decision features。
- why-not / liquidity optional payload 缺口在 V1.5 只作 warning；完整 negative evidence 與 payload 持久化留待 V1.7。
- Production evidence write-mode scheduler 仍未啟用；readiness 最高仍只能走 dry-run / manual confirm / explicit approval path。

## Follow-up

1. V1.6：建立 cross-sectional factor pipeline / sector rotation v2 的可追溯 snapshot。
2. V1.7：將 screening matrix、Why Not / Liquidity payload 與 negative evidence 提升到與 recommendation evidence 同等地位。
3. 後續資料源 ingestion 必須先補 `source_id`、`available_date`、quality、missing policy 與 no-look-ahead tests，再接入任何 factor 或 evidence pipeline。

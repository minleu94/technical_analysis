# V1.8 Portfolio Sandbox Closeout（2026-07-05）

## 結論

V1.8 Portfolio Construction & Execution Trace Sandbox v1 已完成。此版本只建立 research-only allocation / virtual execution trace 邊界，不串 production broker、不寫正式資料、不修改 Portfolio position、不啟用 scheduler，也不宣稱任何配置具備投資有效性。

## 已交付

1. `app_module/portfolio_construction_dtos.py`
   - `PortfolioConstructionCandidate`
   - `PortfolioConstructionRequest`
   - `PortfolioAllocationRow`
   - `PortfolioConstructionResult`

2. `app_module/portfolio_construction_service.py`
   - `equal_weight`
   - `score_weight`
   - `inverse_volatility`
   - `max_position_weight_bp`
   - `lot_size`
   - `residual_cash` / diagnostics

3. `app_module/portfolio_execution_trace_service.py`
   - `VirtualOrderEvent`
   - `created`
   - `submitted`
   - `partially_filled`
   - `filled`
   - `rejected`

4. `scripts/inspect_portfolio_sandbox.py`
   - 只支援 `--sample`
   - 支援 `--format json|markdown`
   - 不讀正式 DB、不寫 output、不產生 broker order

## 安全邊界

- 所有 allocation result 固定 `research_basis=true`。
- 所有 virtual order event 固定 `research_only=true` 與 `source_type=portfolio_sandbox`。
- 權重使用整數 bp；金額使用 `Decimal`；股數與 lot sizing 使用整數。
- `max_position_weight_bp` 不自動重分配超出權重，避免隱性 optimizer 行為。
- `inverse_volatility` 缺 volatility 時 skip 並輸出 diagnostic，不補值。
- 此版本不接 `ScoringEngine`、不改 recommendation score、不寫 evidence DB、不建立 scheduler。

## 未完成 / 後續 residual

- 未導入 PyPortfolioOpt optimizer、Nautilus、vn.py 或 cuFOLIO。
- 未實作 cancelled lifecycle。
- 未實作零股、買賣價差、完整撮合或 gap actual execution model。
- 未把 sandbox 接進 UI；目前僅提供 service / CLI / tests。

## 驗證命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_construction_sandbox.py tests/test_portfolio_sandbox_inspection_cli.py tests/test_recommendation_portfolio_backtest.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module/portfolio_construction_dtos.py app_module/portfolio_construction_service.py app_module/portfolio_execution_trace_service.py scripts/inspect_portfolio_sandbox.py tests/test_portfolio_construction_sandbox.py tests/test_portfolio_sandbox_inspection_cli.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

## 驗證結果

- Portfolio sandbox / inspection CLI / recommendation portfolio regression：`39 passed`，僅有既有推薦回放「同日收盤成交假設」warning。
- `py_compile`：通過。
- `check_financial_float_boundaries.py`：通過。
- `quant_guard_linter.py`：通過，金融 float 與 look-ahead 檢查皆無違規。
- `mypy`：`Success: no issues found in 282 source files`。


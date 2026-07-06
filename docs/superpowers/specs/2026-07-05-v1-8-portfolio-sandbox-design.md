# V1.8 Portfolio Sandbox Design

## 目標

V1.8 建立 research-only Portfolio Construction & Execution Trace Sandbox，讓系統可比較配置方法、限制條件與虛擬委託生命週期，但不串接券商、不自動下單、不改 `ScoringEngine`、不啟用 production scheduler。

## 範圍

第一段交付 portfolio construction sandbox：

- 新增 `app_module/portfolio_construction_dtos.py` 與 `app_module/portfolio_construction_service.py`。
- 支援 `equal_weight`、`score_weight`、`inverse_volatility` 三種研究配置方法。
- 支援整數基點權重、`Decimal` 金額、單檔上限、整股 lot sizing 與 residual cash diagnostics。
- 輸出每檔 target / constrained / executable 權重與金額，並標示 `research_basis=true`。

第二段交付 virtual execution trace / inspection：

- 新增 `app_module/portfolio_execution_trace_service.py`。
- 由 allocation result 產生 `created -> submitted -> filled`、`created -> submitted -> partially_filled -> filled` 或 `created -> submitted -> rejected` 的虛擬事件序列。
- 所有 event 都標示 `research_only=true`、`source_type=portfolio_sandbox`，不得包含 broker order id 或真實下單狀態。
- 新增 `scripts/inspect_portfolio_sandbox.py`，提供 sample JSON / Markdown inspection，方便 QA 與文件引用。

## 架構邊界

- `portfolio_module/core.py` 的真實 / 模擬持倉 domain 不直接耦合 V1.8 sandbox；sandbox 是研究服務，不改既有 portfolio store。
- `RecommendationPortfolioBacktestService` 暫不改 PnL、成交價、cash ledger 或現有 replay 行為；V1.8 的 allocation / trace 可供後續 replay residual 接入。
- 金融核心數值使用 `Decimal` 與整數基點；若輸出 JSON 需要浮點，必須在 DTO / CLI presentation 邊界標示。
- No-look-ahead 自查：V1.8 只消費呼叫端傳入的決策日候選與決策日可得的價格 / 波動資訊；service 不自行讀取未來價格、不讀 SQLite、不重算推薦。

## 風險與防線

- 配置結果不是投資建議，只能標示 research basis。
- `inverse_volatility` 若缺 `volatility_bp`，該候選會降級為 skipped，不用未來波動補值。
- lot sizing 只依決策日 reference price 與 lot size 向下取整，買不起最小單位時列入 diagnostics。
- virtual execution trace 只反映研究事件生命週期，不代表真實委託送出、部分成交或成交。

## 驗收

- Focused pytest 覆蓋三種配置、max weight cap、lot sizing、residual cash、partial / rejected virtual events 與 sample CLI。
- `py_compile` 覆蓋新增 Python 檔。
- `mypy` 覆蓋 `app_module` 與 `scripts` 相關變更所在全專案指定範圍。
- `quant_guard_linter.py` 通過，確認未新增未標示裸 float 與 look-ahead AST 違規。


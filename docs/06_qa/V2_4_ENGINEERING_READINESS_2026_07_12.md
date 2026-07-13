# V2.4 Portfolio Coach Foundation Engineering Readiness

> 日期：2026-07-12
> 狀態：`engineering_readiness_recorded`；不是 V2.4 formal closeout。

## 已驗證工程能力

- research-only portfolio construction：Equal Weight、score weight、inverse volatility、整數 bp 權重、Decimal 金額、整股 lot sizing、max-position cap 與 residual cash。
- target allocation 與可執行 allocation 可從同一 result 取得；交易失敗、部分成交與拒單由 virtual execution trace 保存為 research-only event。
- Portfolio condition / alert / feedback / review service 只輸出狀態、理由與 diagnostics，不改實際持倉、不下單、不套用 lifecycle。
- 資料或假設不足時保留 warning / diagnostic 或安全輸出；sample CLI 固定 `research_basis=true`。

## 核准紙上政策接線（2026-07-12）

- `app_module/paper_portfolio_policy.py` 將已核准的 NT$500,000 初始資本、20% 最低現金、8 檔上限、15% 單檔上限、30% 產業上限、3% 再平衡 band、2% minimum trade、20% weekly turnover、5 個交易日 cooldown，以及 10 / 15 / 30 bp 成本假設固定為唯讀 policy contract。
- `scripts/inspect_paper_portfolio_policy.py --sample --format json` 只以內建樣本輸出 `PAPER_TRADE_CANDIDATE` 或 `NO_PAPER_TRADE` 與拒絕理由；不讀實際持倉、不寫資料庫、不產生 broker order。
- 政策評估器只使用 `Decimal` 資本與整數 bp，且對現金、單檔、產業、週轉與 cooldown 違反均 fail-closed。

## 本次驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_construction_sandbox.py tests/test_portfolio_sandbox_inspection_cli.py tests/test_portfolio_review_service.py tests/test_portfolio_condition_monitor.py tests/test_portfolio_alert_service.py tests/test_portfolio_feedback_service.py tests/test_portfolio_numeric_governance.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\inspect_portfolio_sandbox.py --sample --format json
```

結果：**31 passed**。sample output 顯示 allocation、created / submitted / partially_filled / filled / rejected trace 均為 `research_only=true`，並標示 `research_basis_not_trade_advice`。

## 不可自動關閉的 residual

1. 使用者需確認平衡風險政策的實際數值：最低現金、最大持倉數、單檔／產業曝險、rebalance band、minimum trade、turnover 與 cooldown。
2. 需要真實時間的 Paper Portfolio 觀察、成本與滑價假設 review、execution feasibility review，以及人工 decision journal。
3. 需確認 target/current/gap 在實際 paper position 與限制情境下仍可讀且 `NO_NEW_POSITION` 行為符合預期。
4. broker、真實下單、自動配置、自動再平衡與正式投資有效性仍不在範圍。

## 結論

V2.4 已具備可測試的 research-only engineering foundation；在上述人工政策與 paper evidence 完成前，不得標記為 formal closeout，也不得把 sandbox allocation 表示為交易指令。

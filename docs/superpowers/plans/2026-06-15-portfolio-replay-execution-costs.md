# Portfolio Replay Execution Costs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓推薦組合回放在使用者提供費用參數時，於 cash gate、cash ledger 與 summary 中反映手續費、證交稅與滑價成本。

**Architecture:** 延續 cash-constrained order flow，在建立 holding 前用 Decimal 計算 buy-side total cash requirement；退出 holding 時用 sell-side proceeds 扣除費用。預設參數仍為 `None`，維持既有無成本結果；提供任一成本參數時，`portfolio_credibility` 標記 execution costs 為 partial modeled，但整股、完整撮合與 gap 仍維持限制揭露。

**Tech Stack:** Python、pytest、Decimal money helpers、Recommendation Portfolio Backtest。

---

## Files

- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 RED 測試：提供 `fee_bps` / `slippage_bps` / `tax_bps` 時，buy ledger 扣 allocation + buy cost，sell ledger 回收 gross proceeds - sell costs。
  - 更新 credibility manifest 測試，反映 execution cost policy。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 新增 optional `fee_bps`, `slippage_bps`, `tax_bps` 參數。
  - 新增 `_build_execution_costs()` helper，集中 Decimal 成本計算。
  - cash gate 使用 buy-side total cash requirement。
  - cash ledger 附加 `gross_amount` 與 `costs` breakdown。
  - summary 增加 `total_transaction_cost`。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

---

### Task 1: RED - costs affect cash ledger and ending cash

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing test**

Add a test after `test_portfolio_backtest_exposes_cash_ledger_for_successful_holding()`:

```python
def test_portfolio_backtest_applies_optional_execution_costs_to_cash_ledger():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 80.0},
            },
            {
                "stock_code": "2317",
                "stock_name": "鴻海",
                "total_score": 80.0,
                "factor_scores": {"technical": 70.0},
            },
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=2,
        allocation_method="equal_weight",
        holding_days=4,
        fee_bps=10,
        slippage_bps=5,
        tax_bps=30,
    )

    cash_ledger = result.details["cash_ledger"]

    assert cash_ledger[0]["event"] == "buy"
    assert cash_ledger[0]["gross_amount"] == -500000.0
    assert cash_ledger[0]["costs"] == {"fee": 500.0, "tax": 0.0, "slippage": 250.0, "total": 750.0}
    assert cash_ledger[0]["amount"] == -500750.0
    assert cash_ledger[0]["cash_balance"] == 499250.0
    assert cash_ledger[1]["event"] == "sell"
    assert cash_ledger[1]["gross_amount"] == 550000.0
    assert cash_ledger[1]["costs"] == {"fee": 550.0, "tax": 1650.0, "slippage": 275.0, "total": 2475.0}
    assert cash_ledger[1]["amount"] == 547525.0
    assert result.summary["ending_cash"] == 1046775.0
    assert result.summary["total_transaction_cost"] == 3225.0
    assert result.details["unfilled_orders"][0]["reason"] == "cash_limited"
    assert result.details["portfolio_credibility"]["execution_costs"]["supported"] == "partial"
```

- [x] **Step 2: Run test to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_applies_optional_execution_costs_to_cash_ledger -q -o addopts=
```

Expected: FAIL with unexpected keyword argument `fee_bps`.

---

### Task 2: GREEN - optional execution costs

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] **Step 1: Extend signature**

Add to `run_portfolio_backtest()`:

```python
        fee_bps: float | None = None,
        slippage_bps: float | None = None,
        tax_bps: float | None = None,
```

- [x] **Step 2: Add helper**

Add `_build_execution_costs(gross_amount, fee_bps, slippage_bps, tax_bps, include_tax)` returning Decimal breakdown. Use `calculate_fee(..., minimum_fee=to_decimal("0.00"))` for fee and tax, and `gross_amount * bps_to_rate(slippage_bps)` for slippage because replay does not model shares yet.

- [x] **Step 3: Use buy total requirement in cash gate**

Compute buy costs before cash gate:

```python
buy_costs = self._build_execution_costs(
    gross_amount=allocation_amount_dec,
    fee_bps=fee_bps,
    slippage_bps=slippage_bps,
    tax_bps=tax_bps,
    include_tax=False,
)
buy_cash_required = quantize_money(allocation_amount_dec + buy_costs["total"])
```

Use `buy_cash_required` for available cash check and buy debit.

- [x] **Step 4: Attach ledger breakdown**

Buy ledger amount becomes negative `buy_cash_required`, with `gross_amount=-allocation_amount_dec` and `costs` breakdown.

- [x] **Step 5: Apply sell costs**

In `_release_exited_holdings()`, compute sell gross amount and costs. Ledger sell amount is `gross - costs["total"]`; cash balance adds that net proceeds.

- [x] **Step 6: Add summary total**

Maintain `total_transaction_cost` as Decimal and include `summary["total_transaction_cost"]`.

- [x] **Step 7: Run RED test and verify GREEN**

Run the RED test. Expected: PASS.

---

### Task 3: Docs and verification

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
- Modify: `tests/test_recommendation_portfolio_backtest.py`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Update manifest with:

```python
"execution_costs": {
    "supported": "partial" if any_cost_param else False,
    "policy": "fee_tax_slippage_bps_applied_to_cash_ledger" if any_cost_param else "not_applied",
    "fee_bps": fee_bps,
    "slippage_bps": slippage_bps,
    "tax_bps": tax_bps,
},
```

- [x] Update docs to state costs are optional and bps-based; whole-share sizing, order book execution, spread and gap remain pending.
- [x] Run focused verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

---

## Self-Review

- Spec coverage: Optional cost params, cash gate, ledger breakdown, summary and docs are all covered.
- Placeholder scan: No placeholders remain.
- Type consistency: Cost arithmetic uses Decimal and DTO/details boundaries use `numeric-boundary` comments.

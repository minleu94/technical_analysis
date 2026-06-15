# Portfolio Replay Cash-Constrained Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓推薦組合回放在建立 holding 前使用可用現金做下單 gate，現金不足時產生 `cash_limited` unfilled order。

**Architecture:** `RecommendationPortfolioBacktestService` 會在 rebalance loop 中維護一個 Decimal cash state，先處理到期 holdings 的 sell cash inflow，再依推薦排序檢查每筆 allocation 是否有足夠現金。`cash_ledger` 由這個現金 state 產生，不再只靠事後 holdings 推導；equity curve、交易成本、滑價、整股限制與 gap 模型仍維持既有限制揭露。

**Tech Stack:** Python、pytest、Decimal money helpers、Recommendation Portfolio Backtest。

---

## Files

- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 RED 測試：weekly rebalance 時，同日先賣出舊 holding 再買入新 holding。
  - 新增 RED 測試：現金不足時產生 `cash_limited` unfilled order。
  - 更新 credibility manifest 測試，反映 cash account 已用於 order sizing。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 在 rebalance loop 維護 active holdings、available cash 與 cash ledger。
  - 新增 `_release_exited_holdings()` helper。
  - 擴充 `_build_unfilled_order()` 支援 cash metadata。
  - 更新 `_build_credibility_manifest()` cash account policy。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

---

### Task 1: RED - same-day rebalance releases cash before buys

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing test**

Add a test that runs weekly replay with one stock, initial capital 1,000,000, holding_days 4, and price path 100 -> 110 -> 120. It should assert the cash ledger event order:

```python
def test_portfolio_backtest_releases_exit_cash_before_same_day_rebalance_buy():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
            {"日期": "2026-01-09", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 120},
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
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-09",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="weekly",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )

    assert [row["event"] for row in result.details["cash_ledger"]] == ["buy", "sell", "buy", "sell"]
    assert result.details["cash_ledger"][1]["date"] == "2026-01-06"
    assert result.details["cash_ledger"][1]["amount"] == 1100000.0
    assert result.details["cash_ledger"][2]["date"] == "2026-01-06"
    assert result.details["cash_ledger"][2]["amount"] == -1000000.0
    assert result.summary["ending_cash"] == 1190909.09
```

- [x] **Step 2: Run test to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_releases_exit_cash_before_same_day_rebalance_buy -q -o addopts=
```

Expected: FAIL because current derived ledger sorts all sells before buys on the same date and does not represent cash gate state per rebalance.

---

### Task 2: GREEN - maintain cash state during replay

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] **Step 1: Add cash state variables**

Inside `run_portfolio_backtest()` after list initialisation:

```python
        active_holdings: List[PeriodHoldingDTO] = []
        cash_ledger: List[Dict[str, Any]] = []
        available_cash = to_decimal(initial_capital)
```

- [x] **Step 2: Release exits at each rebalance date**

At the start of each rebalance date loop call:

```python
            available_cash = self._release_exited_holdings(
                rebalance_ts=rebalance_ts,
                active_holdings=active_holdings,
                cash_ledger=cash_ledger,
                available_cash=available_cash,
            )
```

- [x] **Step 3: Check cash before building holdings**

Before liquidity check:

```python
                allocation_amount_dec = quantize_money(to_decimal(allocation_amount))
                if allocation_amount_dec > available_cash:
                    unfilled_orders.append(
                        self._build_unfilled_order(
                            rec=rec,
                            rank=rank,
                            rebalance_ts=rebalance_ts,
                            planned_exit_ts=planned_exit_ts,
                            allocation_amount=allocation_amount,
                            allocation_weight=allocation_weight,
                            reason="cash_limited",
                            cash={
                                "available_cash": float(available_cash),  # numeric-boundary: dto
                                "required_cash": float(allocation_amount_dec),  # numeric-boundary: dto
                                "cash_shortfall": float(quantize_money(allocation_amount_dec - available_cash)),  # numeric-boundary: dto
                            },
                        )
                    )
                    continue
```

- [x] **Step 4: Debit successful buys**

After `period_holdings.append(holding)`:

```python
                active_holdings.append(holding)
                available_cash = quantize_money(available_cash - allocation_amount_dec)
                cash_ledger.append(
                    {
                        "date": holding.entry_date,
                        "stock_code": holding.stock_code,
                        "event": "buy",
                        "amount": float(-allocation_amount_dec),  # numeric-boundary: dto
                        "cash_balance": float(available_cash),  # numeric-boundary: dto
                    }
                )
```

- [x] **Step 5: Release exits through end date**

After the rebalance loop:

```python
        available_cash = self._release_exited_holdings(
            rebalance_ts=end_ts + pd.Timedelta(days=1),
            active_holdings=active_holdings,
            cash_ledger=cash_ledger,
            available_cash=available_cash,
        )
```

- [x] **Step 6: Add helper**

```python
    def _release_exited_holdings(
        self,
        *,
        rebalance_ts: pd.Timestamp,
        active_holdings: List[PeriodHoldingDTO],
        cash_ledger: List[Dict[str, Any]],
        available_cash: Decimal,
    ) -> Decimal:
        remaining = []
        for holding in active_holdings:
            exit_ts = pd.to_datetime(holding.actual_exit_date)
            if exit_ts <= rebalance_ts:
                sell_amount = quantize_money(to_decimal(holding.allocation_amount) + to_decimal(holding.pnl()))
                available_cash = quantize_money(available_cash + sell_amount)
                cash_ledger.append(
                    {
                        "date": holding.actual_exit_date,
                        "stock_code": holding.stock_code,
                        "event": "sell",
                        "amount": float(sell_amount),  # numeric-boundary: dto
                        "cash_balance": float(available_cash),  # numeric-boundary: dto
                    }
                )
            else:
                remaining.append(holding)
        active_holdings[:] = remaining
        return available_cash
```

- [x] **Step 7: Stop using derived cash ledger in result path**

Replace calls to `_build_cash_ledger()` with current `cash_ledger` and:

```python
        ending_cash = float(quantize_money(available_cash))  # numeric-boundary: dto
```

- [x] **Step 8: Run Task 1 test and verify GREEN**

Run the RED test again. Expected: PASS.

---

### Task 3: RED/GREEN - insufficient cash records cash_limited

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] **Step 1: Add failing test**

Add a test with weekly recommendations for two stocks, `top_n=2`, score-weighted allocation of 90% and 10%, where the second rebalance occurs before the first period exits. The second rebalance first requested allocation should exceed available cash and record `cash_limited`.

- [x] **Step 2: Verify RED**

Run the new test and confirm it fails before any extra implementation.

- [x] **Step 3: Extend `_build_unfilled_order()`**

Add `cash: Dict[str, Any] | None = None` and attach `order["cash"] = cash` when present.

- [x] **Step 4: Verify GREEN**

Run the new test. Expected: PASS.

---

### Task 4: Update credibility, docs, and verify

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
- Modify: `tests/test_recommendation_portfolio_backtest.py`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Update cash account manifest:

```python
"cash_account": {
    "supported": "order_sizing",
    "policy": "available_cash_checked_before_holding_creation",
},
```

- [x] Keep warnings for incomplete execution model:

```python
"rebalance_cash_reuse_partial",
"liquidity_gap_not_modeled",
"same_day_close_execution_assumption",
```

- [x] Update docs to state cash now gates holding creation, while trading costs, whole-share sizing, slippage, gap and full execution modeling remain pending.

- [x] Run focused verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

---

## Self-Review

- Spec coverage: Covers same-day sell-before-buy, cash-limited unfilled orders, manifest and docs.
- Placeholder scan: No placeholder implementation language remains.
- Type consistency: Cash state uses Decimal; DTO/details boundaries convert to float with numeric-boundary markers.

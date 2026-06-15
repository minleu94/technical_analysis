# Portfolio Replay Liquidity Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在推薦組合回放中新增第一版 liquidity gate，當推薦股票有價格但成交量不足以承接配置金額時，記錄 `liquidity_limited` unfilled order。

**Architecture:** 延續既有 `unfilled_orders` 架構，不改現金帳、不改 equity curve、不建立完整撮合引擎。`RecommendationPortfolioBacktestService` 只在 entry row 有成交量欄位且設定最大參與率時，估算可參與金額；若配置金額超過可參與金額，該推薦不建 `PeriodHoldingDTO`，改記錄 unfilled order，並更新 `portfolio_credibility["liquidity_gap"]["supported"]` 為部分支援。

**Tech Stack:** Python、pytest、Recommendation Portfolio Backtest、portfolio credibility manifest。

---

## Files

- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 RED 測試：有價格但成交量不足時，產生 `liquidity_limited` unfilled order。
  - 更新 credibility manifest 測試，反映 liquidity gate partial support。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 新增 `max_participation_rate` optional 參數，預設 `None` 以維持既有行為。
  - 在 `_build_period_holding()` 前檢查 entry row liquidity。
  - 新增 `_liquidity_unfilled_reason()` helper。
  - 將 unfilled order reason 擴充為 `liquidity_limited`。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

---

### Task 1: RED - 成交量不足必須產生 liquidity_limited unfilled order

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing test**

Add this test after `test_portfolio_backtest_records_unfilled_order_when_recommended_stock_has_no_price_rows()`:

```python
def test_portfolio_backtest_records_unfilled_order_when_liquidity_is_insufficient():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100, "成交股數": 1000},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110, "成交股數": 1000},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"volume": 70.0},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
        max_participation_rate=0.05,
    )

    unfilled_orders = result.details["unfilled_orders"]

    assert result.period_holdings == []
    assert result.summary["total_trades"] == 0
    assert result.summary["unfilled_order_count"] == 1
    assert unfilled_orders[0]["reason"] == "liquidity_limited"
    assert unfilled_orders[0]["stock_code"] == "2330"
    assert unfilled_orders[0]["allocation_amount"] == 1000000.0
    assert unfilled_orders[0]["liquidity"]["volume_shares"] == 1000
    assert unfilled_orders[0]["liquidity"]["max_participation_rate"] == 0.05
    assert unfilled_orders[0]["liquidity"]["max_participation_amount"] == 5000.0
    assert "unfilled_order:2330:liquidity_limited" in result.selection_diagnostics
    assert result.details["portfolio_credibility"]["liquidity_gap"]["supported"] == "partial"
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_unfilled_order_when_liquidity_is_insufficient -q -o addopts=
```

Expected: FAIL with `TypeError: ... unexpected keyword argument 'max_participation_rate'`.

---

### Task 2: GREEN - Implement minimal liquidity gate

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] **Step 1: Add optional argument**

Change `run_portfolio_backtest()` signature:

```python
        take_profit_pct: float | None = None,
        max_participation_rate: float | None = None,
```

- [x] **Step 2: Pass max participation into credibility manifest**

Change manifest call:

```python
        credibility_manifest = self._build_credibility_manifest(
            rebalance_frequency=rebalance_frequency,
            allocation_method=allocation_method,
            max_participation_rate=max_participation_rate,
        )
```

- [x] **Step 3: Check liquidity before building holding**

In the recommendation loop, before `_build_period_holding(...)`, compute:

```python
                allocation_amount = capital_per_period * weights[rank - 1]
                allocation_weight = weights[rank - 1]
                liquidity_unfilled = self._liquidity_unfilled_reason(
                    data=data,
                    rec=rec,
                    rebalance_ts=rebalance_ts,
                    planned_exit_ts=planned_exit_ts,
                    allocation_amount=allocation_amount,
                    max_participation_rate=max_participation_rate,
                )
                if liquidity_unfilled is not None:
                    unfilled_orders.append(
                        self._build_unfilled_order(
                            rec=rec,
                            rank=rank,
                            rebalance_ts=rebalance_ts,
                            planned_exit_ts=planned_exit_ts,
                            allocation_amount=allocation_amount,
                            allocation_weight=allocation_weight,
                            reason="liquidity_limited",
                            liquidity=liquidity_unfilled,
                        )
                    )
                    continue
```

Then pass `allocation_amount=allocation_amount` and `allocation_weight=allocation_weight` to `_build_period_holding()`.

- [x] **Step 4: Add helper**

Add before `_build_unfilled_order()`:

```python
    def _liquidity_unfilled_reason(
        self,
        *,
        data: pd.DataFrame,
        rec: Dict[str, Any],
        rebalance_ts: pd.Timestamp,
        planned_exit_ts: pd.Timestamp,
        allocation_amount: float,
        max_participation_rate: float | None,
    ) -> Dict[str, Any] | None:
        if max_participation_rate is None or max_participation_rate <= 0:
            return None
        code = str(rec.get("stock_code", ""))
        stock_rows = data[
            (data["證券代號"].astype(str) == code)
            & (data["日期"] >= rebalance_ts)
            & (data["日期"] <= planned_exit_ts)
        ]
        if stock_rows.empty:
            return None
        entry_row = stock_rows.iloc[0]
        if "成交股數" not in entry_row.index:
            return None
        volume_shares = int(pd.to_numeric(entry_row["成交股數"], errors="coerce") or 0)
        close_price = float(entry_row["收盤價"])  # numeric-boundary: analytics
        max_amount = round(float(volume_shares * close_price * max_participation_rate), 6)
        if allocation_amount <= max_amount:
            return None
        return {
            "volume_shares": volume_shares,
            "close_price": close_price,
            "max_participation_rate": max_participation_rate,
            "max_participation_amount": max_amount,
        }
```

- [x] **Step 5: Extend unfilled order helper**

Change `_build_unfilled_order()` signature:

```python
        liquidity: Dict[str, Any] | None = None,
```

Before return, build `order` dict and attach liquidity if present:

```python
        order = {...}
        if liquidity is not None:
            order["liquidity"] = liquidity
        return order
```

- [x] **Step 6: Update manifest helper**

Change signature:

```python
    def _build_credibility_manifest(
        self,
        *,
        rebalance_frequency: str,
        allocation_method: str,
        max_participation_rate: float | None = None,
    ) -> Dict[str, Any]:
```

Set:

```python
        liquidity_supported: bool | str = "partial" if max_participation_rate else False
        liquidity_policy = (
            "entry_day_volume_participation_checked"
            if max_participation_rate
            else "volume_limit_and_gap_risk_not_applied"
        )
```

Then use:

```python
            "liquidity_gap": {
                "supported": liquidity_supported,
                "policy": liquidity_policy,
                "max_participation_rate": max_participation_rate,
            },
```

- [x] **Step 7: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_unfilled_order_when_liquidity_is_insufficient -q -o addopts=
```

Expected: PASS.

---

### Task 3: Update docs and verify

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] **Step 1: Update docs**

Update wording to state that entry-day volume participation can now create `liquidity_limited` unfilled orders when `max_participation_rate` is provided, while gap and full execution modeling remain pending.

- [x] **Step 2: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
```

- [x] **Step 3: Run py_compile**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py
```

- [x] **Step 4: Run financial float boundary check**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

---

## Self-Review

- Spec coverage: Implements a first liquidity gate using entry-day volume participation only; does not claim full liquidity or gap modeling.
- Placeholder scan: No placeholders remain.
- Type consistency: liquidity metadata is nested under unfilled order dicts and credibility manifest uses `"partial"` for partial support.

# Portfolio Replay Unfilled Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將推薦組合回放中「推薦股票缺少可用價格列」的情境記錄為結構化 `unfilled_orders`，避免靜默跳過造成組合可信度被高估。

**Architecture:** 不改現有成交假設與現金帳核心；先在 `RecommendationPortfolioBacktestService` 中新增缺價型未成交紀錄。當 `_build_period_holding()` 因找不到股票價格資料回傳 `None` 時，主流程新增一筆 `unfilled_orders` dict，寫入 result `details`、`summary` 與 `selection_diagnostics`，並將 `portfolio_credibility["unfilled_orders"]["supported"]` 改為 `True`。

**Tech Stack:** Python、pytest、Recommendation Portfolio Backtest、portfolio credibility manifest。

---

## Files

- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 RED 測試：推薦清單中若有缺價股票，結果必須包含 `details["unfilled_orders"]`。
  - 更新既有 credibility manifest 測試：`unfilled_orders.supported` 應為 `True`，且不再包含 `unfilled_orders_not_modeled` warning。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 在回放 loop 中收集缺價型 unfilled orders。
  - 新增 `_build_unfilled_order()` helper。
  - 將 `unfilled_orders` 放進 normal / no-holding result details。
  - 在 summary 放入 `unfilled_order_count`。
  - 更新 credibility manifest 的 unfilled order policy。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - 更新 Month 3 Portfolio Replay 可信度狀態。
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - 更新 Month 3 狀態與立即待辦。
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - 補充推薦回放會揭露缺價型未成交紀錄。

---

### Task 1: RED - 缺價推薦必須產生 unfilled order

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing test**

Add this test after `test_portfolio_backtest_result_includes_credibility_manifest()`:

```python
def test_portfolio_backtest_records_unfilled_order_when_recommended_stock_has_no_price_rows():
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
                "factor_scores": {"volume": 70.0},
            },
            {
                "stock_code": "9999",
                "stock_name": "缺價股",
                "total_score": 80.0,
                "factor_scores": {"volume": 60.0},
            },
        ][:top_n]

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
    )

    unfilled_orders = result.details["unfilled_orders"]

    assert len(result.period_holdings) == 1
    assert result.summary["total_trades"] == 1
    assert result.summary["unfilled_order_count"] == 1
    assert unfilled_orders == [
        {
            "rebalance_date": "2026-01-02",
            "stock_code": "9999",
            "stock_name": "缺價股",
            "rank": 2,
            "reason": "missing_price_rows",
            "planned_exit_date": "2026-01-06",
            "allocation_amount": 500000.0,
            "allocation_weight": 0.5,
            "total_score": 80.0,
        }
    ]
    assert "unfilled_order:9999:missing_price_rows" in result.selection_diagnostics
    assert result.details["portfolio_credibility"]["unfilled_orders"]["supported"] is True
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_unfilled_order_when_recommended_stock_has_no_price_rows -q -o addopts=
```

Expected: FAIL with `KeyError: 'unfilled_orders'`.

---

### Task 2: GREEN - 新增缺價型 unfilled order state

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] **Step 1: Collect unfilled orders in replay loop**

In `run_portfolio_backtest()`, initialize:

```python
        unfilled_orders = []
```

Inside the recommendation loop, replace:

```python
                if holding is None:
                    continue
```

with:

```python
                if holding is None:
                    unfilled_orders.append(
                        self._build_unfilled_order(
                            rec=rec,
                            rank=rank,
                            rebalance_ts=rebalance_ts,
                            planned_exit_ts=planned_exit_ts,
                            allocation_amount=capital_per_period * weights[rank - 1],
                            allocation_weight=weights[rank - 1],
                            reason="missing_price_rows",
                        )
                    )
                    continue
```

- [x] **Step 2: Add helper**

Add before `_build_period_holding()`:

```python
    def _build_unfilled_order(
        self,
        *,
        rec: Dict[str, Any],
        rank: int,
        rebalance_ts: pd.Timestamp,
        planned_exit_ts: pd.Timestamp,
        allocation_amount: float,
        allocation_weight: float,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "rebalance_date": rebalance_ts.strftime("%Y-%m-%d"),
            "stock_code": str(rec.get("stock_code", "")),
            "stock_name": str(rec.get("stock_name", "")),
            "rank": rank,
            "reason": reason,
            "planned_exit_date": planned_exit_ts.strftime("%Y-%m-%d"),
            "allocation_amount": allocation_amount,
            "allocation_weight": allocation_weight,
            "total_score": float(rec.get("total_score", 0.0)),  # numeric-boundary: dto
        }
```

- [x] **Step 3: Include unfilled order data in results**

In no-holding `details`, add:

```python
                "unfilled_orders": unfilled_orders,
```

In no-holding `summary`, add:

```python
                    "unfilled_order_count": len(unfilled_orders),
```

In normal `summary`, add:

```python
            "unfilled_order_count": len(unfilled_orders),
```

In normal `details`, add:

```python
            "unfilled_orders": unfilled_orders,
```

For both result paths, extend `selection_diagnostics` with:

```python
                selection_diagnostics=[
                    item for snapshot in snapshots for item in snapshot.diagnostics
                ] + [
                    f"unfilled_order:{order['stock_code']}:{order['reason']}"
                    for order in unfilled_orders
                ],
```

- [x] **Step 4: Update credibility manifest**

In `_build_credibility_manifest()`, remove `"unfilled_orders_not_modeled"` from `warnings`.

Change unfilled order section to:

```python
            "unfilled_orders": {
                "supported": True,
                "policy": "missing_price_rows_are_recorded_as_unfilled_orders",
            },
```

- [x] **Step 5: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_unfilled_order_when_recommended_stock_has_no_price_rows -q -o addopts=
```

Expected: PASS.

---

### Task 3: Update existing credibility test

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Update assertion**

Change:

```python
    assert credibility["unfilled_orders"]["supported"] is False
```

to:

```python
    assert credibility["unfilled_orders"]["supported"] is True
    assert "unfilled_orders_not_modeled" not in credibility["warnings"]
```

- [x] **Step 2: Run related tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_result_includes_credibility_manifest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_unfilled_order_when_recommended_stock_has_no_price_rows -q -o addopts=
```

Expected: both PASS.

---

### Task 4: Documentation sync

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] **Step 1: Update Snapshot**

State that Recommendation Portfolio Replay now records missing-price recommendations as unfilled orders, while cash ledger, rebalance cash reuse, and liquidity/gap models remain pending.

- [x] **Step 2: Update 6M Roadmap**

Update Month 3 status and immediate todo to move unfilled order handling from pure limitation disclosure to first supported missing-price case.

- [x] **Step 3: Update Manual**

In Recommendation Replay section, explain `details["unfilled_orders"]` captures recommended stocks skipped because no price rows existed in the replay window.

---

### Task 5: Verification

- [x] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
```

- [x] **Step 2: Run py_compile**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py
```

- [x] **Step 3: Run financial float boundary check**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

- [x] **Step 4: Inspect diff**

```powershell
git diff -- app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py docs\superpowers\plans\2026-06-15-portfolio-replay-unfilled-orders.md docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\07_guides\APPLICATION_MANUAL.md
```

---

## Self-Review

- Spec coverage: This implements the first actual unfilled-order state for missing price rows without claiming volume/liquidity or gap execution modeling is complete.
- Placeholder scan: No placeholders remain.
- Type consistency: `unfilled_orders` is a list of plain dicts under result `details`, with summary count and diagnostics string references.

# Portfolio Replay Lot Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓推薦組合回放在提供 `lot_size` 時，依進場價把配置金額轉為可成交股數，買不起最小交易單位時記錄 `lot_size_limited`。

**Architecture:** 預設 `lot_size=None` 維持既有金額級回放。提供 `lot_size` 時，`RecommendationPortfolioBacktestService` 先建立候選 holding 取得進場價，再用 Decimal/整數股數向下取整；actual allocation、cash gate、ledger 與 PnL 都改用整股後的成交金額。整股 sizing 不引入委託簿、零股、買賣價差或 gap 模型。

**Tech Stack:** Python、pytest、Decimal money helpers、Recommendation Portfolio Backtest。

---

## Files

- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 RED 測試：`lot_size=1000` 時 allocation 依 entry price 向下取整，cash ledger 留下未使用現金。
  - 新增 RED 測試：資金不足一張時記錄 `lot_size_limited` unfilled order。
  - 更新 credibility manifest 測試，反映 lot sizing partial support。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 新增 optional `lot_size` 參數。
  - 新增 `_apply_lot_sizing()` helper。
  - 擴充 `_build_unfilled_order()` 支援 sizing metadata。
  - 在 `portfolio_credibility` 新增 `share_sizing` 區塊。
- Modify: `app_module/recommendation_portfolio_dtos.py`
  - `PeriodHoldingDTO` 新增 optional `shares` 欄位。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

---

### Task 1: RED - lot sizing rounds down to full lots

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing test**

Add a test after the cash ledger tests:

```python
def test_portfolio_backtest_rounds_allocation_down_to_lot_size():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 333},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 370},
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
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
        lot_size=1000,
    )

    holding = result.period_holdings[0]

    assert holding.shares == 3000
    assert holding.allocation_amount == 999000.0
    assert result.details["cash_ledger"][0]["amount"] == -999000.0
    assert result.details["cash_ledger"][0]["cash_balance"] == 1000.0
    assert result.summary["ending_cash"] == 1111000.0
    assert result.details["portfolio_credibility"]["share_sizing"]["supported"] == "partial"
```

- [x] **Step 2: Run test to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_rounds_allocation_down_to_lot_size -q -o addopts=
```

Expected: FAIL with unexpected keyword argument `lot_size`.

---

### Task 2: GREEN - implement lot sizing for holdings

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
- Modify: `app_module/recommendation_portfolio_dtos.py`

- [x] Add `lot_size: int | None = None` to `run_portfolio_backtest()`.
- [x] Add `shares: int | None = None` to `PeriodHoldingDTO`.
- [x] After candidate holding is built, call `_apply_lot_sizing(holding, planned_allocation_amount, lot_size)`.
- [x] If sizing succeeds, use actual allocation amount for buy costs, cash gate, cash ledger, holding allocation amount and PnL.
- [x] Run Task 1 test and confirm PASS.

---

### Task 3: RED/GREEN - insufficient lot size creates unfilled order

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] Add failing test where initial capital is 100000, entry price is 333, `lot_size=1000`; expect no holdings and one `lot_size_limited` order.
- [x] Extend `_build_unfilled_order()` with `sizing` metadata.
- [x] Verify the new test passes.

---

### Task 4: Docs and verification

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
- Modify: `tests/test_recommendation_portfolio_backtest.py`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Add `share_sizing` to credibility manifest.
- [x] Update docs to state lot sizing is optional full-lot sizing; odd lots, order book, spread and gap remain pending.
- [x] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py app_module\recommendation_portfolio_dtos.py tests\test_recommendation_portfolio_backtest.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

---

## Self-Review

- Spec coverage: Covers rounded lot sizing, insufficient capital, manifest and docs.
- Placeholder scan: No placeholders remain.
- Type consistency: share count is integer; money calculations use Decimal and DTO boundaries use numeric-boundary comments.

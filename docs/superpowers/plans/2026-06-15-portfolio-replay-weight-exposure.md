# Portfolio Replay Weight Exposure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 補齊推薦組合回放的權重揭露，讓每筆 holding 同時保留目標權重與成交後實際權重，並在結果 details 中保存可追溯的 `weight_exposure` 摘要。

**Architecture:** 不新增組合撮合引擎；沿用現有 cash gate、execution cost 與 full-lot sizing 流程，在 holding 成交後以實際配置金額除以初始資金計算 `actual_allocation_weight`。`allocation_weight` 繼續代表推薦配置目標權重，`actual_allocation_weight` 與 `weight_exposure` 代表可成交後曝險，所有核心金額使用既有 Decimal 邊界，float 只出現在 DTO / analytics serialization。

**Tech Stack:** Python、pytest、Decimal financial units、PySide6 DTO table serialization、Markdown docs。

---

## Files

- Modify: `app_module/recommendation_portfolio_dtos.py`
  - `PeriodHoldingDTO` 新增 `actual_allocation_weight: float | None = None`。
  - `period_holdings_dataframe()` 新增「實際配置權重」欄位。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 成交後設定 `holding.actual_allocation_weight`。
  - 新增 `details["weight_exposure"]`，彙總每期目標權重、實際權重、未成交權重與現金/整股偏離。
  - `portfolio_credibility` 新增 `weights` 區塊。
- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 failing test 驗證整股向下取整後的實際權重與 `weight_exposure`。
  - 更新 readable table test，確認「實際配置權重」欄位存在。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - 更新 Month 3 Portfolio Replay 狀態，標示權重揭露已補強。
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - 更新 Month 3 交付物與立即待辦，將「權重」從待補項移到已具備的 partial disclosure。
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - 更新推薦回放判讀，說明 `weight_exposure` 與目標/實際權重差異。

---

### Task 1: RED - DTO table exposes actual allocation weight

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing assertions**

In `test_recommendation_portfolio_result_exposes_readable_tables()`, construct `PeriodHoldingDTO` with:

```python
        actual_allocation_weight=0.4995,
```

Then add:

```python
    assert result.period_holdings_dataframe().iloc[0]["實際配置權重"] == 0.4995
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_recommendation_portfolio_result_exposes_readable_tables -q -o addopts=
```

Expected: FAIL because `PeriodHoldingDTO` does not accept `actual_allocation_weight` or the dataframe lacks「實際配置權重」.

---

### Task 2: GREEN - Add actual allocation weight to DTO

**Files:**
- Modify: `app_module/recommendation_portfolio_dtos.py`

- [x] **Step 1: Implement minimal DTO field and column**

Add to `PeriodHoldingDTO`:

```python
    actual_allocation_weight: float | None = None
```

Add「實際配置權重」after「配置權重」in `period_holdings_dataframe()` columns and rows:

```python
            "實際配置權重",
```

```python
                    "實際配置權重": holding.actual_allocation_weight,
```

- [x] **Step 2: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_recommendation_portfolio_result_exposes_readable_tables tests\test_recommendation_portfolio_backtest.py::test_recommendation_portfolio_empty_tables_keep_readable_columns -q -o addopts=
```

Expected: PASS.

---

### Task 3: RED - Service emits executable weight exposure after lot sizing

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing service test**

Add this test after `test_portfolio_backtest_rounds_allocation_down_to_lot_size()`:

```python
def test_portfolio_backtest_exposes_actual_weight_after_lot_sizing():
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
    exposure = result.details["weight_exposure"]

    assert holding.allocation_weight == 1.0
    assert holding.actual_allocation_weight == 0.999
    assert exposure["supported"] == "partial"
    assert exposure["periods"] == [
        {
            "rebalance_date": "2026-01-02",
            "target_weight": 1.0,
            "actual_weight": 0.999,
            "unfilled_weight": 0.0,
            "cash_residual_weight": 0.001,
            "holding_count": 1,
            "unfilled_order_count": 0,
        }
    ]
    assert result.details["portfolio_credibility"]["weights"]["supported"] == "partial"
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_exposes_actual_weight_after_lot_sizing -q -o addopts=
```

Expected: FAIL because `actual_allocation_weight` and `details["weight_exposure"]` are not emitted.

---

### Task 4: GREEN - Calculate executable weights and exposure manifest

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] **Step 1: Set actual weight after executable allocation is known**

After `actual_allocation_dec = quantize_money(to_decimal(holding.allocation_amount))`, add:

```python
                holding.actual_allocation_weight = self._weight_from_amount(
                    amount=actual_allocation_dec,
                    initial_capital=initial_capital,
                )
```

- [x] **Step 2: Add exposure manifest to both result paths**

Before the no-holdings return and before final DTO return, compute:

```python
        weight_exposure = self._build_weight_exposure(
            period_holdings=period_holdings,
            unfilled_orders=unfilled_orders,
        )
```

Add to `details`:

```python
                "weight_exposure": weight_exposure,
```

- [x] **Step 3: Add helper methods**

Add methods near `_calculate_weights()`:

```python
    def _weight_from_amount(self, *, amount: Decimal, initial_capital: float) -> float:
        capital = to_decimal(initial_capital)
        if capital <= 0:
            return 0.0
        return float((amount / capital).quantize(Decimal("0.000001")))  # numeric-boundary: dto

    def _build_weight_exposure(
        self,
        *,
        period_holdings: List[PeriodHoldingDTO],
        unfilled_orders: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        period_keys = sorted(
            {
                holding.rebalance_date
                for holding in period_holdings
            }
            | {
                str(order.get("rebalance_date", ""))
                for order in unfilled_orders
                if order.get("rebalance_date")
            }
        )
        periods = []
        for rebalance_date in period_keys:
            holdings = [holding for holding in period_holdings if holding.rebalance_date == rebalance_date]
            orders = [order for order in unfilled_orders if order.get("rebalance_date") == rebalance_date]
            target_weight = sum(to_decimal(holding.allocation_weight) for holding in holdings)
            target_weight += sum(to_decimal(order.get("allocation_weight", 0)) for order in orders)
            actual_weight = sum(to_decimal(holding.actual_allocation_weight or 0) for holding in holdings)
            unfilled_weight = sum(to_decimal(order.get("allocation_weight", 0)) for order in orders)
            cash_residual_weight = max(to_decimal("0"), target_weight - actual_weight - unfilled_weight)
            periods.append(
                {
                    "rebalance_date": rebalance_date,
                    "target_weight": float(target_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "actual_weight": float(actual_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "unfilled_weight": float(unfilled_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "cash_residual_weight": float(cash_residual_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "holding_count": len(holdings),
                    "unfilled_order_count": len(orders),
                }
            )
        return {
            "schema_version": 1,
            "supported": "partial",
            "policy": "target_weight_vs_executable_weight_by_rebalance_date",
            "periods": periods,
        }
```

- [x] **Step 4: Add credibility manifest weight block**

In `_build_credibility_manifest()`, add:

```python
            "weights": {
                "supported": "partial",
                "policy": "target_and_actual_executable_weights_reported",
            },
```

- [x] **Step 5: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_exposes_actual_weight_after_lot_sizing tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_rounds_allocation_down_to_lot_size tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_unfilled_order_when_lot_size_cannot_be_met -q -o addopts=
```

Expected: PASS.

---

### Task 5: Documentation sync

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] **Step 1: Update Snapshot**

In Month 3 Portfolio Replay priority, state that recommendation portfolio replay now exposes target vs executable weights via `weight_exposure`, while odd-lot/spread/gap/full matching remain future work.

- [x] **Step 2: Update 6M Roadmap**

Update Month 3 status, deliverables, and immediate todo so「權重」is no longer listed as fully missing; describe it as partial disclosure.

- [x] **Step 3: Update Manual**

In Research Lab recommendation replay section, describe:

- `allocation_weight`: target recommendation weight.
- `actual_allocation_weight`: executable weight after full-lot sizing and cash gate.
- `details["weight_exposure"]`: per rebalance date target, actual, unfilled, and cash residual weights.

---

### Task 6: Final verification and commit

**Files:**
- Verify all changed code and docs.

- [x] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
```

- [x] **Step 2: Run py_compile**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py app_module\recommendation_portfolio_dtos.py tests\test_recommendation_portfolio_backtest.py
```

- [x] **Step 3: Run financial numeric boundary check**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

- [ ] **Step 4: Inspect git diff and stage only planned files**

```powershell
git status --short
git diff -- app_module\recommendation_portfolio_backtest_service.py app_module\recommendation_portfolio_dtos.py tests\test_recommendation_portfolio_backtest.py docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\07_guides\APPLICATION_MANUAL.md docs\superpowers\plans\2026-06-15-portfolio-replay-weight-exposure.md
```

Expected: only planned files changed; no QA output or local cache files included.

---

## Rollback Checklist

| File | Change type | Rollback method | Risk |
|---|---|---|---|
| `app_module/recommendation_portfolio_dtos.py` | Modify | `git checkout HEAD -- app_module/recommendation_portfolio_dtos.py` | Low; removes optional DTO field/column |
| `app_module/recommendation_portfolio_backtest_service.py` | Modify | `git checkout HEAD -- app_module/recommendation_portfolio_backtest_service.py` | Medium; removes weight exposure manifest |
| `tests/test_recommendation_portfolio_backtest.py` | Modify | `git checkout HEAD -- tests/test_recommendation_portfolio_backtest.py` | Low; removes regression coverage |
| `docs/00_core/PROJECT_SNAPSHOT.md` | Modify | `git checkout HEAD -- docs/00_core/PROJECT_SNAPSHOT.md` | Low; docs status rolls back |
| `docs/00_core/ROADMAP_6M_ENGINEERING.md` | Modify | `git checkout HEAD -- docs/00_core/ROADMAP_6M_ENGINEERING.md` | Low; roadmap status rolls back |
| `docs/07_guides/APPLICATION_MANUAL.md` | Modify | `git checkout HEAD -- docs/07_guides/APPLICATION_MANUAL.md` | Low; manual wording rolls back |
| `docs/superpowers/plans/2026-06-15-portfolio-replay-weight-exposure.md` | Create | `Remove-Item docs\superpowers\plans\2026-06-15-portfolio-replay-weight-exposure.md` | Low; removes this plan only |

## Self-Review

- Spec coverage: Covers Month 3 Portfolio Replay weight disclosure without pretending odd-lot, spread, gap, or full order-book matching are complete.
- Placeholder scan: No TBD / TODO / implement later placeholders.
- Type consistency: `allocation_weight` remains target weight; `actual_allocation_weight` is optional DTO float at serialization boundary; `weight_exposure` stores period-level summary.

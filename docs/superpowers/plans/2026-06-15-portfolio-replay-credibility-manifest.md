# Portfolio Replay Credibility Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在推薦組合回放結果中新增結構化 `portfolio_credibility` manifest，明確揭露現金帳、再平衡、未成交、Liquidity / Gap 與成交假設狀態。

**Architecture:** 不在本切點改變交易核心、撮合假設或現金帳運算。先由 `RecommendationPortfolioBacktestService` 在 `details` 與 `summary` 中輸出可信度 manifest，讓 UI、Excel/Registry payload 與後續 Portfolio Replay 改造能讀同一份結構化限制說明。

**Tech Stack:** Python、pytest、Recommendation Portfolio Backtest、Research Run metadata。

---

## Files

- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 新增 `_build_credibility_manifest()`。
  - 在有交易與無交易結果的 `details` 放入 `portfolio_credibility`。
  - 在 `summary` 放入 `credibility_status` 與 `credibility_warning_count`，方便 UI/報告快速顯示。
- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 RED 測試，要求 manifest 揭露目前已知限制。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - 更新 Month 3 Portfolio Replay 可信度狀態。
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - 更新立即待辦，標示 credibility manifest 已開始，完整現金帳與未成交模型仍待後續。
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - 補充推薦回放結果會揭露可信度 manifest 與限制。

---

### Task 1: RED - 推薦組合回放必須輸出可信度 manifest

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [x] **Step 1: Add failing test**

Add this test after `test_portfolio_backtest_result_includes_factor_manifest_from_replay_snapshots()`:

```python
def test_portfolio_backtest_result_includes_credibility_manifest():
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
                "total_score": 82.35,
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
    )

    credibility = result.details["portfolio_credibility"]

    assert credibility["schema_version"] == 1
    assert credibility["status"] == "limited"
    assert credibility["cash_account"]["supported"] is False
    assert credibility["rebalance"]["supported"] is False
    assert credibility["unfilled_orders"]["supported"] is False
    assert credibility["liquidity_gap"]["supported"] is False
    assert credibility["execution_assumption"] == "idealized_same_day_close"
    assert "cash_account_not_modeled" in credibility["warnings"]
    assert result.summary["credibility_status"] == "limited"
    assert result.summary["credibility_warning_count"] == len(credibility["warnings"])
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_result_includes_credibility_manifest -q -o addopts=
```

Expected: FAIL with `KeyError: 'portfolio_credibility'`.

---

### Task 2: GREEN - 新增 credibility manifest

**Files:**
- Modify: `app_module/recommendation_portfolio_backtest_service.py`

- [x] **Step 1: Implement minimal manifest helper**

Add this method before `_build_factor_manifest()`:

```python
    def _build_credibility_manifest(self, *, rebalance_frequency: str, allocation_method: str) -> Dict[str, Any]:
        warnings = [
            "cash_account_not_modeled",
            "rebalance_cash_reuse_not_modeled",
            "unfilled_orders_not_modeled",
            "liquidity_gap_not_modeled",
            "same_day_close_execution_assumption",
        ]
        return {
            "schema_version": 1,
            "status": "limited",
            "execution_assumption": "idealized_same_day_close",
            "rebalance_frequency": rebalance_frequency,
            "allocation_method": allocation_method,
            "cash_account": {
                "supported": False,
                "policy": "capital_per_period_reused_without_cash_ledger",
            },
            "rebalance": {
                "supported": False,
                "policy": "period_holdings_are_independent_replay_slices",
            },
            "unfilled_orders": {
                "supported": False,
                "policy": "missing_price_rows_are_skipped_without_order_state",
            },
            "liquidity_gap": {
                "supported": False,
                "policy": "volume_limit_and_gap_risk_not_applied",
            },
            "warnings": warnings,
        }
```

- [x] **Step 2: Attach manifest to result details and summary**

At the top of `run_portfolio_backtest()` after `rebalance_dates`:

```python
        credibility_manifest = self._build_credibility_manifest(
            rebalance_frequency=rebalance_frequency,
            allocation_method=allocation_method,
        )
```

In the no-holding details:

```python
                "portfolio_credibility": credibility_manifest,
```

In the no-holding summary:

```python
                    "credibility_status": credibility_manifest["status"],
                    "credibility_warning_count": len(credibility_manifest["warnings"]),
```

In the normal summary:

```python
            "credibility_status": credibility_manifest["status"],
            "credibility_warning_count": len(credibility_manifest["warnings"]),
```

In the normal details:

```python
            "portfolio_credibility": credibility_manifest,
```

- [x] **Step 3: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_result_includes_credibility_manifest -q -o addopts=
```

Expected: PASS.

---

### Task 3: Documentation sync

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] **Step 1: Update Snapshot**

Update Month 3 Portfolio Replay priority to state that credibility manifest has started, while full cash account / rebalance / unfilled / Liquidity / Gap modeling remains pending.

- [x] **Step 2: Update 6M Roadmap**

Update the Month 3 status or immediate todo to mention `portfolio_credibility` manifest.

- [x] **Step 3: Update Manual**

In Recommendation Replay section, mention result details disclose `portfolio_credibility` warnings and should be reviewed before interpreting replay results.

---

### Task 4: Verification

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

---

## Self-Review

- Spec coverage: Covers the next Month 3 credibility step without pretending cash ledger, rebalance, unfilled order, or liquidity/gap execution model is complete.
- Placeholder scan: No placeholders remain.
- Type consistency: `portfolio_credibility` is a `dict[str, Any]` in `RecommendationPortfolioBacktestResultDTO.details`; summary fields are scalar and UI/report friendly.

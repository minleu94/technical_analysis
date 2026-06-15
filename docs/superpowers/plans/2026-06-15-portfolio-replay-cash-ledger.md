# Portfolio Replay Cash Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. Keep this as a narrow Month 3 Portfolio Replay credibility slice.

**Goal:** 在推薦組合回放結果中新增第一版 derived cash ledger，讓每筆已成交 holding 的買進、賣出與期末現金可追溯。

**Architecture:** 延續既有 `PeriodHoldingDTO` 與 equity curve 計算，不在本刀建立完整撮合引擎，也不改推薦權重分配。`RecommendationPortfolioBacktestService` 會根據已產生的 holdings 建立 `details["cash_ledger"]` 與 summary 現金欄位；`portfolio_credibility["cash_account"]` 標記為 `"partial"`，並保留完整再平衡現金重用仍未完成的 warning。

**Tech Stack:** Python、pytest、Recommendation Portfolio Backtest、Decimal financial boundary。

---

## Files

- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 RED 測試：有一筆成功 holding 時，details 包含 cash ledger，買進後現金歸零，賣出後 cash 等於 allocation + pnl。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 新增 `_build_cash_ledger()` helper。
  - 將 `cash_ledger` 放入 `details`。
  - 在 summary 加上 `ending_cash`。
  - 更新 credibility manifest 的 cash account policy。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

---

### Task 1: RED - successful holdings must expose cash ledger

- [x] Add a failing test that runs a one-stock replay from 100 to 110 with initial capital 1,000,000 and asserts:
  - `details["cash_ledger"]` exists.
  - first row is `buy`, amount `-1000000.0`, cash balance `0.0`.
  - second row is `sell`, amount `1100000.0`, cash balance `1100000.0`.
  - `summary["ending_cash"] == 1100000.0`.
  - `portfolio_credibility["cash_account"]["supported"] == "partial"`.
- [x] Run the new test and confirm it fails before implementation.

### Task 2: GREEN - implement derived ledger

- [x] Implement `_build_cash_ledger(initial_capital, period_holdings)`.
- [x] Use Decimal helpers for cash arithmetic; convert to float only at DTO/details boundary with `# numeric-boundary: dto`.
- [x] Attach `cash_ledger` to details in success and no-holding paths.
- [x] Add `ending_cash` to summary.
- [x] Update `_build_credibility_manifest()` cash account support and policy.
- [x] Run the new test and confirm it passes.

### Task 3: Docs and verification

- [x] Update Snapshot, 6M Roadmap, and Application Manual to describe partial derived cash ledger support and remaining limitations.
- [x] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

---

## Self-Review

- This is a traceability ledger, not a complete execution engine.
- Rebalance cash reuse and overlapping positions remain explicitly limited.
- No strategy signal uses future prices; the ledger is derived after holdings are built for reporting.

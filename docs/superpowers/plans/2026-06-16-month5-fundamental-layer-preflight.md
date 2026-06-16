# Month 5 Fundamental Layer Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans before implementation and superpowers:executing-plans when this preflight becomes active work. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare Month 5 Fundamental Layer without introducing look-ahead bias, ungoverned raw data ingestion, or direct scoring-engine coupling.

**Architecture:** Fundamental data must enter through explicit source inventory, announcement-date / available-date contracts, factor adapters, and diagnostics. Month 5 must not write revenue, valuation, or abnormal fundamental logic directly into `ScoringEngine`, UI views, or backtest shortcuts.

**Tech Stack:** Python, pytest, existing factor layer under `decision_module/factors/`, existing research run metadata contracts, documentation under `docs/`.

---

## Entry Conditions

Month 5 may start because Month 4 Daily Decision Desk v1 is closed as a service-backed daily workflow.

Before coding new fundamental logic, an agent must confirm:

- Daily Decision Desk remains service-snapshot only.
- Factor Layer gates still pass.
- No raw fundamental data source is treated as decision-available before its `available_date`.
- Any data-source write path has backup / migration / fallback planning.

---

## Work Packages

### WP-1: Fundamental Source Inventory

**Files to inspect first:**

- `data_module/config.py`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- existing data directories under the configured `TWStockConfig`

**Output:**

- A source inventory that lists monthly revenue, valuation, financial statement, and announcement-date availability.
- Each source must state whether it is raw, derived, manually downloaded, SQLite-backed, CSV-backed, or unavailable.

### WP-2: Available-Date Contract

**Required decision:**

- Every fundamental observation must expose `period`, `announced_date` when available, `available_date`, `source`, and `quality`.
- Backtests, recommendations, and Daily Decision Desk consumers may only use observations with `available_date <= decision_date`.

**Required tests:**

- A no-look-ahead test where a revenue observation with `available_date > decision_date` is skipped, neutralized, or fail-closed according to policy.
- A missing-date test where the factor returns diagnostics instead of silently filling future data.

### WP-3: Factor Adapter Boundary

**Allowed direction:**

- Fundamental data flows into `decision_module/factors/` adapters.
- Existing `ScoringEngine` receives governed factor outputs only.

**Forbidden direction:**

- Direct imports from raw revenue or valuation loaders inside `ScoringEngine`.
- UI views calculating revenue growth or valuation percentiles.
- Backtest code reading raw fundamental files without the factor gate.

### WP-4: First Fundamental Factors

**Candidate v1 factors:**

- Revenue YoY
- Revenue MoM
- 3-month revenue trend
- Revenue new high flag
- Relative valuation percentile for P/E, P/B, or P/S if source quality is sufficient
- `AbnormalFundamentalFlag`

**Policy:**

- If announcement dates are incomplete, factor quality must degrade.
- Valuation should be percentile / range based, not a single target price.
- Abnormal flags should mark, downweight, or warn; they must not rewrite financial statements.

### WP-5: Verification Gate

Minimum expected verification for Month 5 implementation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -o addopts=
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe -m py_compile <changed-python-files>
```

If UI is modified, also run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

---

## Non-Goals

These do not belong to Month 5 preflight:

- Odd-lot execution modeling
- Bid/ask spread execution modeling
- Full matching engine
- Actual gap execution model
- PDF research report export
- Strategy Drift
- Post-trade Attribution

They remain later execution / Strategy Lifecycle backlog unless explicitly reprioritized.

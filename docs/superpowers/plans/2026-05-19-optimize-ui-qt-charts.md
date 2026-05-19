# Optimize UI Qt Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fast, optional backtest equity chart path while preserving the current Matplotlib charts as a fallback.

**Architecture:** Keep chart data normalization outside the widget layer, then render the equity chart through a Qt WebEngine canvas widget when available. The existing Matplotlib `EquityCurveWidget` remains the compatibility fallback.

**Tech Stack:** PySide6, QtWebEngine, pandas, numpy, pytest.

---

### Task 1: Chart Payload Normalization

**Files:**
- Create: `ui_qt/widgets/chart_payloads.py`
- Test: `tests/test_ui_qt_chart_payloads.py`

- [ ] Write tests for date normalization, benchmark normalization, and trade marker extraction.
- [ ] Implement pure functions that convert pandas series/dataframes into JSON-serializable chart payloads.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest -o addopts= tests\test_ui_qt_chart_payloads.py -q`.

### Task 2: Fast Equity Widget

**Files:**
- Create: `ui_qt/widgets/fast_chart_widget.py`
- Modify: `ui_qt/widgets/__init__.py`
- Test: `tests/test_ui_qt_chart_widget_factory.py`

- [ ] Add a factory that returns the fast WebEngine equity widget when QtWebEngine imports cleanly.
- [ ] Keep the Matplotlib widget as fallback when WebEngine is unavailable or explicitly disabled.
- [ ] Run focused widget factory tests without starting the full app.

### Task 3: Backtest View Wiring

**Files:**
- Modify: `ui_qt/views/backtest_view.py`

- [ ] Replace direct `EquityCurveWidget()` construction with the factory.
- [ ] Leave drawdown, return histogram, and holding histogram on Matplotlib for this first trial.
- [ ] Run import-level checks for `BacktestView` and focused non-UI tests.

### Task 4: Verification

**Files:**
- No planned code changes.

- [ ] Run focused tests for new payload/factory behavior.
- [ ] Run a small existing baseline test with `-o addopts=` because the environment lacks `pytest-cov`.
- [ ] Summarize remaining manual UI verification needed.

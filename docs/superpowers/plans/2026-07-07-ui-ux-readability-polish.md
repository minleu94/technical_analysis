# UI UX Readability Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修補 Runtime 留白、左導覽掃描性、Workbench 總覽可讀性與市場弱勢跌幅色彩語意。

**Architecture:** 保持現有 PySide6 view / widget 邊界，只在 UI component 層增量調整。`LeftNavigationWidget` 自己管理 icon 與 collapsed state；Runtime / Workbench 只改 layout 與 presentation；弱勢頁透過 table model / delegate 層修正 `跌幅%` 顏色與顯示。

**Tech Stack:** PySide6, pytest, existing `MIDNIGHT_ANALYST` tokens, existing table models and view tests.

## Global Constraints

- 使用繁體中文回覆與更新文檔。
- 不得刪除或破壞原始資料檔。
- 不改 schedule / report output schema。
- 不寫 DB、不啟用 scheduler、不執行 replay、不補 lifecycle gate、不產生買賣建議。
- UI 修改後跑 focused pytest、`tests/test_ui_qt_update_view_workbench.py`、`scripts/qa_validate_update_tab.py`、changed Python `py_compile` 與 mypy。

---

### Task 1: Runtime Compact Layout

**Files:** `ui_qt/views/runtime_view.py`, `tests/test_ui_qt_runtime_view.py`

- [x] Write tests that assert `scope_label` uses compact maximum height and splitter starts immediately after the scope label.
- [x] Run `pytest tests/test_ui_qt_runtime_view.py -q -o addopts=` and confirm failure.
- [x] Update RuntimeView to style `scope_label` as compact banner, remove vertical stretch, and set sensible splitter minimum.
- [x] Re-run test and commit.

### Task 2: Left Navigation Icons and Collapse

**Files:** `ui_qt/widgets/left_navigation.py`, `ui_qt/main.py`, `tests/test_ui_qt_left_navigation.py`, `tests/test_ui_qt_decision_desk_main_integration.py`

- [x] Add tests for `NavigationItem.icon`, `set_collapsed(True)`, width change, icon-only button text, tooltip, and signal preservation.
- [x] Run left nav tests and confirm failure.
- [x] Implement icon text, collapse toggle button, `is_collapsed()`, `set_collapsed()`.
- [x] Update MainWindow navigation items with icons.
- [x] Re-run focused tests and commit.

### Task 3: Workbench Readability

**Files:** `ui_qt/views/workbench_view.py`, `tests/test_ui_qt_workbench_view.py`

- [x] Add tests for top summary cards / `overview_summary_label` and placeholder pages that mention summary-only / future detail lane.
- [x] Run Workbench tests and confirm failure.
- [x] Implement compact summary panel and clearer placeholder pages.
- [x] Re-run Workbench tests and commit.

### Task 4: Weak Market Semantic Color

**Files:** `ui_qt/views/weak_stocks_view.py`, `ui_qt/views/weak_industries_view.py`, related tests.

- [x] Add tests that weak stock / industry `跌幅%` displays absolute positive value and uses red foreground.
- [x] Run tests and confirm failure.
- [x] Implement a semantic table model or role override for `跌幅%`.
- [x] Re-run tests and commit.

### Task 5: Docs and QA

**Files:** Manual / Snapshot / UI design system / QA closeout as needed.

- [x] Update docs to describe Runtime compact layout, left nav collapse, Workbench future lanes, and weak-market color semantics.
- [x] Run full focused QA.
- [x] Commit docs.

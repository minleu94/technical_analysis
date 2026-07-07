# Workbench Visual Hierarchy Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將左側主導覽從文字縮寫升級為自製線條 SVG icon，並把 Workbench 總覽改成一眼可讀的指揮台摘要列。

**Architecture:** 保持既有 PySide6 widget / view 邊界。`LeftNavigationWidget` 管理 nav icon rendering；`UnifiedDecisionWorkbenchView` 只改 presentation layout 與 DTO summary text，不改 service 或 composer。

**Tech Stack:** PySide6, pytest, existing Midnight Analyst tokens.

## Global Constraints

- 使用繁體中文回覆與更新文檔。
- 不改 scheduler / report output schema。
- 不寫 DB、不啟用 scheduler、不執行 replay、不補 lifecycle gate、不產生買賣建議。
- UI 修改後跑 focused pytest、`tests/test_ui_qt_update_view_workbench.py`、`scripts/qa_validate_update_tab.py`、changed Python `py_compile` 與 mypy。

---

### Task 1: Left Navigation SVG Icons

**Files:** `ui_qt/widgets/left_navigation.py`, `ui_qt/main.py`, `tests/test_ui_qt_left_navigation.py`

- [ ] Add tests that nav buttons expose real `QIcon` objects and collapsed text no longer equals the two-letter code.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_left_navigation.py -q -o addopts=` and confirm failure.
- [ ] Add a small SVG icon registry and render icons with `QIcon` / `QPixmap`; keep text labels only for expanded mode.
- [ ] Re-run left nav tests and commit.

### Task 2: Workbench Command Summary Layout

**Files:** `ui_qt/views/workbench_view.py`, `tests/test_ui_qt_workbench_view.py`

- [ ] Add tests for four summary blocks, title pane gutter, and removal of long single-line summary label.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_workbench_view.py -q -o addopts=` and confirm failure.
- [ ] Implement four summary labels / blocks from `WorkbenchDashboardDTO`, and set consistent content margins around the overview content.
- [ ] Re-run Workbench tests and commit.

### Task 3: Docs and QA

**Files:** Manual / Snapshot / UI design system / QA closeout.

- [ ] Update docs to describe SVG nav icons, Workbench command summary, and unchanged formal data gates.
- [ ] Run required QA commands.
- [ ] Commit docs.

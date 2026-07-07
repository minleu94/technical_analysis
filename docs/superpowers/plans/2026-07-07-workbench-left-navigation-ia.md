# Workbench Left Navigation IA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將主工作區從上方 tab 改為左側主導覽，讓「決策工作台」成為預設首頁，並把「每日決策」降級成 Workbench 內的「決策來源」子頁。

**Architecture:** 新增一個純 UI 的左側導覽元件，`MainWindow` 改用 `QStackedWidget` 管理主工作區；既有市場/回測等頁面仍維持自己的上方子 tab。`UnifiedDecisionWorkbenchView` 只接收 DTO、既有 callback 與可選的決策來源 widget，不讀 DB、不啟用 scheduler、不解析排程報告。

**Tech Stack:** PySide6, pytest-qt/offscreen Qt tests, existing `ui_qt.theme` tokens, existing Workbench DTO/table models.

## Global Constraints

- 使用繁體中文回覆與更新文檔。
- 不得刪除或破壞原始資料檔。
- UI 變更不得改動 daily schedule / report output schema、scheduled evidence wrapper、morning report 或 PreV2 readiness contract。
- Workbench 維持 read-only：不寫 DB、不啟用 production scheduler、不執行 replay、不補 lifecycle gate、不產生買賣建議。
- `ui_qt/main.py` 目前已有未提交變更；修改前後都要保護既有變更，不做 revert。
- UI 修改後必跑：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
- UI 修改後必跑：`.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
- UI 修改後必跑 mypy：`.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`
- 語法檢查：對 changed Python files 跑 `.\.venv\Scripts\python.exe -m py_compile <files>`。

---

## File Structure

- Create `ui_qt/widgets/left_navigation.py`
  - Defines `NavigationItem` and `LeftNavigationWidget`.
  - Pure UI widget. No app services, no DB, no scheduler, no report parsing.
  - Emits `workspaceSelected(str)` and exposes `set_current_key(key: str)`.

- Modify `ui_qt/main.py`
  - Import left nav, `QStackedWidget`, `QHBoxLayout`, `QWidget`.
  - Build a shell with left nav + `QStackedWidget`.
  - Main workspace order: `決策工作台`, `市場探索`, `推薦分析`, `策略回測`, `觀察清單`, `持倉管理`, `數據更新`, `Runtime`。
  - Do not add `每日決策` as a main workspace.
  - Still instantiate `DecisionDeskView`; pass it into `UnifiedDecisionWorkbenchView(decision_source_widget=...)`.
  - Keep schedule/report-related services untouched.

- Modify `ui_qt/views/workbench_view.py`
  - Add optional `decision_source_widget: QWidget | None = None`.
  - Wrap existing Workbench content in an internal `QTabWidget` with tabs: `總覽`, `決策來源`, `Evidence`, `持倉追蹤`, `操作節奏`。
  - `決策來源` embeds `DecisionDeskView` when provided; fallback label when unavailable.
  - Add today review queue empty-state copy and a button/callback to `市場探索`.
  - Track queue rows viewed in memory only; never write status back to source.

- Modify tests:
  - Create `tests/test_ui_qt_left_navigation.py`.
  - Update `tests/test_ui_qt_decision_desk_main_integration.py`.
  - Update `tests/test_ui_qt_workbench_view.py`.
  - Keep `tests/test_scheduled_evidence_status_service.py` and dry-run wrapper tests as focused regression QA.

- Modify docs:
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/DEVELOPMENT_ROADMAP.md` or relevant roadmap section if UI IA status is tracked there.
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/superpowers/specs/2026-07-07-workbench-left-navigation-ia-design.md`

---

### Task 1: Left Navigation Widget

**Files:**
- Create: `ui_qt/widgets/left_navigation.py`
- Test: `tests/test_ui_qt_left_navigation.py`

**Interfaces:**
- Produces: `NavigationItem(key: str, label: str, badge: str = "", tooltip: str = "")`
- Produces: `LeftNavigationWidget(items: Sequence[NavigationItem], parent=None)`
- Produces signal: `workspaceSelected: Signal(str)`
- Produces methods: `set_current_key(key: str) -> None`, `current_key() -> str | None`, `button_for_key(key: str) -> QPushButton | None`

- [ ] **Step 1: Write failing tests**

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui_qt.widgets.left_navigation import LeftNavigationWidget, NavigationItem


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_left_navigation_renders_main_workspace_order_and_badges():
    app()
    nav = LeftNavigationWidget(
        (
            NavigationItem("workbench", "決策工作台", badge="3"),
            NavigationItem("market_explore", "市場探索"),
            NavigationItem("runtime", "Runtime", badge="!"),
        )
    )

    assert nav.item_keys() == ["workbench", "market_explore", "runtime"]
    assert nav.button_for_key("workbench").text() == "決策工作台  3"
    assert nav.button_for_key("market_explore").text() == "市場探索"
    assert nav.button_for_key("runtime").text() == "Runtime  !"


def test_left_navigation_emits_key_and_tracks_active_button():
    app()
    nav = LeftNavigationWidget(
        (
            NavigationItem("workbench", "決策工作台"),
            NavigationItem("market_explore", "市場探索"),
        )
    )
    selected: list[str] = []
    nav.workspaceSelected.connect(selected.append)

    nav.button_for_key("market_explore").click()

    assert selected == ["market_explore"]
    assert nav.current_key() == "market_explore"
    assert nav.button_for_key("market_explore").property("active") is True
    assert nav.button_for_key("workbench").property("active") is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_left_navigation.py -q -o addopts=`

Expected: FAIL because `ui_qt.widgets.left_navigation` does not exist.

- [ ] **Step 3: Implement widget**

Create `ui_qt/widgets/left_navigation.py` with the tested dataclass, signal and button behavior. Use `MIDNIGHT_ANALYST` for restrained styling, fixed left width near 184 px, and keep badge text inside the button label for the first slice.

- [ ] **Step 4: Verify**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_left_navigation.py -q -o addopts=`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui_qt/widgets/left_navigation.py tests/test_ui_qt_left_navigation.py
git commit -m "feat: add left workspace navigation widget"
```

---

### Task 2: MainWindow Left Shell

**Files:**
- Modify: `ui_qt/main.py`
- Modify test: `tests/test_ui_qt_decision_desk_main_integration.py`

**Interfaces:**
- Consumes: `LeftNavigationWidget`, `NavigationItem`
- Produces: `self.workspace_stack: QStackedWidget`
- Produces: `self.left_navigation: LeftNavigationWidget`
- Keeps compatibility: `self.tabs` may point to `self.workspace_stack` only if tests are migrated away; prefer new helpers in tests.
- Produces helper: `_add_workspace(key: str, widget: QWidget) -> int`
- Produces helper: `_select_main_workspace(key_or_label: str) -> None`

- [ ] **Step 1: Write failing integration expectations**

Update the main integration test helper from `_get_tab_names` to:

```python
def _get_nav_labels(main_window) -> list[str]:
    return [main_window.left_navigation.button_for_key(key).text().split("  ")[0] for key in main_window.left_navigation.item_keys()]
```

Change assertions:

```python
assert _get_nav_labels(target_window) == [
    "決策工作台",
    "市場探索",
    "推薦分析",
    "策略回測",
    "觀察清單",
    "持倉管理",
    "數據更新",
    "Runtime",
]
assert target_window.left_navigation.current_key() == "workbench"
assert "每日決策" not in _get_nav_labels(target_window)
assert isinstance(target_window.decision_desk_view, _RecordedDecisionDeskView)
assert target_window.workbench_view.kwargs["decision_source_widget"] is target_window.decision_desk_view
```

For Workbench callbacks:

```python
workbench_tab.kwargs["navigate_to_daily_decision_callback"]()
assert target_window.left_navigation.current_key() == "workbench"

workbench_tab.kwargs["navigate_to_market_explore_callback"]()
assert target_window.left_navigation.current_key() == "market_explore"

workbench_tab.kwargs["navigate_to_evidence_review_callback"]()
assert target_window.left_navigation.current_key() == "backtest"
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=`

Expected: FAIL because MainWindow still creates top-level tabs.

- [ ] **Step 3: Implement shell in `ui_qt/main.py`**

Add imports:

```python
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget
from ui_qt.widgets.left_navigation import LeftNavigationWidget, NavigationItem
```

Inside `_setup_ui`, replace the top-level `tabs = QTabWidget()` container with:

```python
shell = QWidget()
shell_layout = QHBoxLayout(shell)
shell_layout.setContentsMargins(0, 0, 0, 0)
shell_layout.setSpacing(0)
workspace_stack = QStackedWidget()
workspace_widgets: dict[str, QWidget] = {}

def add_workspace(key: str, widget: QWidget) -> int:
    workspace_widgets[key] = widget
    return workspace_stack.addWidget(widget)
```

Instantiate `DecisionDeskView` before `UnifiedDecisionWorkbenchView` and pass:

```python
decision_source_widget=decision_desk_view
navigate_to_market_explore_callback=self._open_workbench_market_explore
```

Add workspaces in approved order:

```python
workspace_items = (
    NavigationItem("workbench", "決策工作台"),
    NavigationItem("market_explore", "市場探索"),
    NavigationItem("recommendation", "推薦分析"),
    NavigationItem("backtest", "策略回測"),
    NavigationItem("watchlist", "觀察清單"),
    NavigationItem("portfolio", "持倉管理"),
    NavigationItem("update", "數據更新"),
    NavigationItem("runtime", "Runtime"),
)
```

Connect navigation:

```python
self.left_navigation = LeftNavigationWidget(workspace_items, parent=self)
self.left_navigation.workspaceSelected.connect(self._select_main_workspace)
shell_layout.addWidget(self.left_navigation)
shell_layout.addWidget(workspace_stack, 1)
self.setCentralWidget(shell)
self.workspace_stack = workspace_stack
self.workspace_widgets = workspace_widgets
self.left_navigation.set_current_key("workbench")
self.workspace_stack.setCurrentWidget(workspace_widgets["workbench"])
```

Update existing callback methods to use workspace keys:

```python
def _open_workbench_daily_decision(self) -> None:
    self._select_main_workspace("workbench")
    workbench_view = getattr(self, "workbench_view", None)
    if hasattr(workbench_view, "select_subtab"):
        workbench_view.select_subtab("決策來源")

def _open_workbench_market_explore(self) -> None:
    self._select_main_workspace("market_explore")

def _open_workbench_evidence_review(self) -> None:
    self._select_main_workspace("backtest")
    ...

def _open_workbench_portfolio(self) -> None:
    self._select_main_workspace("portfolio")
```

Replace tab-change refresh hooks with workspace switch hooks by calling the same load/refresh behavior in `_select_main_workspace`.

- [ ] **Step 4: Verify integration**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui_qt/main.py tests/test_ui_qt_decision_desk_main_integration.py
git commit -m "feat: move main workspaces to left navigation"
```

---

### Task 3: Workbench Internal Tabs, Empty State and Viewed Queue Feedback

**Files:**
- Modify: `ui_qt/views/workbench_view.py`
- Modify: `tests/test_ui_qt_workbench_view.py`

**Interfaces:**
- Produces constructor args:
  - `decision_source_widget: QWidget | None = None`
  - `navigate_to_market_explore_callback: Callable[[], None] | None = None`
- Produces method: `select_subtab(label: str) -> bool`
- Produces method: `viewed_review_item_ids() -> set[str]`
- Produces in-memory behavior: drilling into a review row adds `item_id` to `self._viewed_review_item_ids` and visually reduces the table opacity/selection only through UI model role or label copy.

- [ ] **Step 1: Write failing tests**

Add expectations to `test_unified_workbench_view_renders_read_only_mvp_shell_and_replay_limits`:

```python
assert [view.subtabs.tabText(i) for i in range(view.subtabs.count())] == [
    "總覽",
    "決策來源",
    "Evidence",
    "持倉追蹤",
    "操作節奏",
]
assert view.select_subtab("決策來源") is True
assert view.subtabs.tabText(view.subtabs.currentIndex()) == "決策來源"
```

Add empty state assertions:

```python
assert "今日所有風險已確認" in empty_view.review_empty_state.title_label.text()
assert "市場探索" in empty_view.review_empty_state.body_label.text()
assert empty_view.review_empty_state.isVisible() is True
assert empty_view.review_table.isVisible() is False
```

Add viewed feedback test:

```python
def test_workbench_review_queue_marks_viewed_in_memory_only() -> None:
    app()
    clicked: list[str] = []
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
        navigate_to_evidence_review_callback=lambda: clicked.append("evidence"),
    )

    view._navigate_model_row(view.review_model, 0)

    assert clicked == ["evidence"]
    assert view.viewed_review_item_ids() == {"watchlist_trigger"}
    assert "已查看 1/1" in view.review_state_label.text()
```

- [ ] **Step 2: Run failing tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_workbench_view.py -q -o addopts=`

Expected: FAIL because subtabs and empty state/viewed state do not exist.

- [ ] **Step 3: Implement Workbench UI**

In `UnifiedDecisionWorkbenchView.__init__`, store:

```python
self.decision_source_widget = decision_source_widget
self.navigate_to_market_explore_callback = navigate_to_market_explore_callback
self._viewed_review_item_ids: set[str] = set()
```

In `_setup_ui`, add `self.subtabs = QTabWidget()` as the top-level child. Move the existing scroll area into an overview page. Add the other subpages:

```python
self.subtabs.addTab(overview_page, "總覽")
self.subtabs.addTab(self._build_decision_source_page(), "決策來源")
self.subtabs.addTab(self._build_placeholder_page("Evidence", self.evidence_table), "Evidence")
self.subtabs.addTab(self._build_placeholder_page("持倉追蹤", self.action_item_table), "持倉追蹤")
self.subtabs.addTab(self._build_placeholder_page("操作節奏", self.operating_loop_table), "操作節奏")
```

Keep existing attributes usable for tests; do not duplicate models.

For empty state, add:

```python
self.review_state_label = self._make_state_label()
self.review_empty_state = EmptyStatePanel(
    "今日所有風險已確認",
    "今日待判讀佇列目前為空；可切到市場探索做研究，或等待下一次正式資料更新。",
)
```

Update `render_dashboard`:

```python
has_review_items = bool(dashboard.review_items)
self.review_table.setVisible(has_review_items)
self.review_empty_state.setVisible(not has_review_items)
self.review_state_label.setText(self._review_queue_state_text(dashboard))
```

Update `_navigate_model_row` to mark only review queue rows:

```python
if model is self.review_model and hasattr(item, "item_id"):
    self._viewed_review_item_ids.add(str(item.item_id))
    self.review_state_label.setText(self._review_queue_state_text(self._dashboard))
```

No persistence. No DB writes.

- [ ] **Step 4: Verify**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_workbench_view.py tests\test_workbench_read_only_boundary.py -q -o addopts=`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui_qt/views/workbench_view.py tests/test_ui_qt_workbench_view.py
git commit -m "feat: refine workbench command center tabs"
```

---

### Task 4: Documentation and Focused QA

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/superpowers/specs/2026-07-07-workbench-left-navigation-ia-design.md`
- Modify roadmap docs only where current UI IA status is tracked.

**Interfaces:**
- Documents must state that replay/simulated evidence remains design/validation support only.
- Documents must state formal completion still waits for production data where gates require real time: Phase 0 weekly history 0/3 and multi-day dry-run 1/3 are not completed by UI work.
- Documents must state Daily Decision is now `決策工作台 > 決策來源`.

- [ ] **Step 1: Update docs**

Add a concise section to manual:

```markdown
### 左側主導覽與決策工作台

主工作區改由左側導覽切換，預設進入「決策工作台」。每日決策已整併至「決策工作台 > 決策來源」；市場研究入口為「市場探索」。Workbench 仍只讀取既有 DTO/service，不寫 DB、不啟用 scheduler、不執行 replay，也不產生買賣建議。

若「今日待判讀」為空，畫面會顯示空狀態；這只代表目前 payload 無待判讀項目，不代表 Phase gate 已完成。Phase 0 weekly history 0/3 與 multi-day dry-run 1/3 仍需正式資料與真實時間累積。
```

- [ ] **Step 2: Run focused QA**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_left_navigation.py tests\test_ui_qt_workbench_view.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_workbench_read_only_boundary.py tests\test_scheduled_evidence_status_service.py tests\test_scheduled_evidence_pipeline_dry_run_wrapper.py tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m py_compile ui_qt\widgets\left_navigation.py ui_qt\main.py ui_qt\views\workbench_view.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: PASS. If mypy has unrelated existing failures, record exact failures and do not hide them.

- [ ] **Step 3: Commit**

```bash
git add docs/00_core/PROJECT_SNAPSHOT.md docs/07_guides/APPLICATION_MANUAL.md docs/superpowers/specs/2026-07-07-workbench-left-navigation-ia-design.md
git commit -m "docs: document left navigation workbench ia"
```

- [ ] **Step 4: Final status**

Report:
- Main UI changed from top-level tabs to left navigation.
- `每日決策` is now embedded under `決策工作台 > 決策來源`.
- `市場觀察` is now `市場探索`.
- Empty state and session-only viewed feedback added.
- Schedule/report wrappers were not modified; focused tests run.
- Items still waiting for formal data: Phase 0 weekly history 0/3 and multi-day dry-run 1/3.


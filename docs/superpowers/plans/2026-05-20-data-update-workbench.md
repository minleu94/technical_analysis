# Data Update Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Qt data update tab as a left-navigation workbench and add a safe routine "update all data" workflow.

**Architecture:** Keep `UpdateView` as the UI owner, but split the layout into small builder methods for the navigation rail, status summary, data-source pages, technical indicator page, advanced rebuild area, and shared log/progress area. Add a synchronous `_run_safe_update_all()` workflow method that can be unit tested with a fake service, then run it through `ProgressTaskWorker` from the button handler.

**Tech Stack:** Python, PySide6 widgets, existing `TaskWorker` and `ProgressTaskWorker`, pytest for service/UI contract tests.

---

## File Structure

- Modify: `ui_qt/views/update_view.py`
  - Replace the single long vertical layout with a workbench shell.
  - Add left navigation and a `QStackedWidget` content area.
  - Preserve existing controls and handlers by moving them into source-specific pages.
  - Add `_run_safe_update_all`, `_execute_safe_update_all`, progress handlers, and summary rendering.
- Create: `tests/test_ui_qt_update_view_workbench.py`
  - Add Qt-safe tests for the workbench shell and safe update sequence.
  - Use a fake update service, no network calls, no file writes.
- Modify if needed: `scripts/qa_validate_update_tab.py`
  - Only update string-based UI contract checks if the redesign changes method-call visibility in a way that breaks the existing QA script.

## Task 1: Add Workbench Shell Tests

**Files:**
- Create: `tests/test_ui_qt_update_view_workbench.py`
- Test command: `pytest tests/test_ui_qt_update_view_workbench.py -q`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_ui_qt_update_view_workbench.py` with:

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QStackedWidget, QPushButton

from ui_qt.views.update_view import UpdateView


class FakeUpdateService:
    def __init__(self):
        self.calls = []

    def check_data_status(self):
        self.calls.append(("check_data_status",))
        return {
            "daily_data": {"latest_date": "2026-05-19", "total_records": 100, "status": "ok"},
            "market_index": {"latest_date": "2026-05-19", "total_records": 10, "status": "ok"},
            "industry_index": {"latest_date": "2026-05-19", "total_records": 20, "status": "ok"},
            "broker_branch": {"latest_date": "2026-05-19", "total_records": 30, "status": "ok"},
        }

    def update_daily(self, start_date, end_date):
        self.calls.append(("update_daily", start_date, end_date))
        return {"success": True, "message": "daily ok"}

    def update_market(self, start_date, end_date):
        self.calls.append(("update_market", start_date, end_date))
        return {"success": True, "message": "market ok"}

    def update_industry(self, start_date, end_date):
        self.calls.append(("update_industry", start_date, end_date))
        return {"success": True, "message": "industry ok"}

    def update_broker_branch(self, start_date, end_date):
        self.calls.append(("update_broker_branch", start_date, end_date))
        return {"success": True, "message": "broker ok"}

    def merge_daily_data(self, force_all=False):
        self.calls.append(("merge_daily_data", force_all))
        return {"success": True, "message": "merge daily ok"}

    def merge_broker_branch_data(self):
        self.calls.append(("merge_broker_branch_data",))
        return {"success": True, "message": "merge broker ok"}

    def calculate_technical_indicators(self, target_stock=None, force_all=False, start_date=None, progress_callback=None):
        self.calls.append(("calculate_technical_indicators", target_stock, force_all, start_date))
        if progress_callback:
            progress_callback("technical indicators ok", 100)
        return {"success": True, "message": "technical ok"}


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def make_view():
    app()
    return UpdateView(FakeUpdateService())


def test_update_view_uses_workbench_navigation():
    view = make_view()

    assert isinstance(view.nav_list, QListWidget)
    assert isinstance(view.content_stack, QStackedWidget)
    assert [view.nav_list.item(i).text() for i in range(view.nav_list.count())] == [
        "全部資料",
        "每日股價",
        "大盤指數",
        "產業指數",
        "券商分點",
        "技術指標",
    ]
    assert view.content_stack.count() == 6
    assert view.nav_list.currentRow() == 0


def test_all_data_view_has_safe_update_primary_button():
    view = make_view()

    assert isinstance(view.safe_update_all_btn, QPushButton)
    assert view.safe_update_all_btn.text() == "安全更新所有數據"
```

- [ ] **Step 2: Run the tests and verify they fail for missing workbench attributes**

Run:

```powershell
pytest tests/test_ui_qt_update_view_workbench.py -q
```

Expected: FAIL with an `AttributeError` for `nav_list`, `content_stack`, or `safe_update_all_btn`.

## Task 2: Build the Workbench Layout

**Files:**
- Modify: `ui_qt/views/update_view.py`
- Test: `tests/test_ui_qt_update_view_workbench.py`

- [ ] **Step 1: Update imports**

Add the missing widget classes to the existing `PySide6.QtWidgets` import:

```python
QFrame, QListWidget, QStackedWidget, QSizePolicy
```

- [ ] **Step 2: Replace `_setup_ui` with a workbench shell**

Refactor `_setup_ui` so it creates:

```python
main_layout = QVBoxLayout(self)
title_layout = self._build_title_row()
workbench_layout = QHBoxLayout()
self.nav_list = QListWidget()
self.content_stack = QStackedWidget()
workbench_layout.addWidget(self.nav_list, stretch=0)
workbench_layout.addWidget(self.content_stack, stretch=1)
main_layout.addLayout(title_layout)
main_layout.addLayout(workbench_layout, stretch=1)
```

Add navigation items in this exact order:

```python
self._nav_items = [
    ("all", "全部資料"),
    ("daily", "每日股價"),
    ("market", "大盤指數"),
    ("industry", "產業指數"),
    ("broker_branch", "券商分點"),
    ("technical", "技術指標"),
]
```

Connect the navigation:

```python
self.nav_list.currentRowChanged.connect(self.content_stack.setCurrentIndex)
self.nav_list.setCurrentRow(0)
```

- [ ] **Step 3: Add page builder methods**

Add these methods to `UpdateView`:

```python
def _build_title_row(self) -> QHBoxLayout:
    ...

def _build_all_data_page(self) -> QWidget:
    ...

def _build_source_page(self, source_key: str, title: str) -> QWidget:
    ...

def _build_technical_page(self) -> QWidget:
    ...

def _build_progress_section(self, parent_layout: QVBoxLayout) -> None:
    ...

def _build_log_section(self, parent_layout: QVBoxLayout) -> None:
    ...
```

The first pass can reuse the existing controls and handlers directly. Do not change service behavior in this task.

- [ ] **Step 4: Run the workbench shell tests**

Run:

```powershell
pytest tests/test_ui_qt_update_view_workbench.py -q
```

Expected: PASS for the two tests from Task 1.

## Task 3: Add Safe Update All Sequence Tests

**Files:**
- Modify: `tests/test_ui_qt_update_view_workbench.py`

- [ ] **Step 1: Add a success sequence test**

Append:

```python
def test_safe_update_all_runs_conservative_sequence():
    view = make_view()
    progress = []

    result = view._run_safe_update_all(progress_callback=lambda message, pct: progress.append((message, pct)))

    assert result["success"] is True
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_status",
        "update_daily",
        "update_market",
        "update_industry",
        "update_broker_branch",
        "merge_daily_data",
        "merge_broker_branch_data",
        "calculate_technical_indicators",
        "check_data_status",
    ]
    assert view.update_service.calls[-2] == ("calculate_technical_indicators", None, False, None)
    assert progress[0][1] == 0
    assert progress[-1][1] == 100
```

- [ ] **Step 2: Add a failure stop test**

Append:

```python
class FailingMarketService(FakeUpdateService):
    def update_market(self, start_date, end_date):
        self.calls.append(("update_market", start_date, end_date))
        return {"success": False, "message": "market failed"}


def test_safe_update_all_stops_after_failed_core_step():
    app()
    view = UpdateView(FailingMarketService())

    result = view._run_safe_update_all(progress_callback=lambda message, pct: None)

    assert result["success"] is False
    assert result["failed_step"] == "大盤指數更新"
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_status",
        "update_daily",
        "update_market",
    ]
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_ui_qt_update_view_workbench.py -q
```

Expected: FAIL with `AttributeError: 'UpdateView' object has no attribute '_run_safe_update_all'`.

## Task 4: Implement Safe Update All Workflow

**Files:**
- Modify: `ui_qt/views/update_view.py`
- Test: `tests/test_ui_qt_update_view_workbench.py`

- [ ] **Step 1: Add `_get_selected_date_range` helper**

Add:

```python
def _get_selected_date_range(self) -> tuple[str, str]:
    end_date = self.end_date.date().toString("yyyy-MM-dd")
    lookback_days = self.lookback_days.value()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
    start_date_obj = end_date_obj - timedelta(days=lookback_days)
    return start_date_obj.strftime("%Y-%m-%d"), end_date
```

- [ ] **Step 2: Use the helper in `_execute_update`**

Replace the duplicated date calculation in `_execute_update` with:

```python
start_date, end_date = self._get_selected_date_range()
```

- [ ] **Step 3: Add `_run_safe_update_all`**

Add:

```python
def _run_safe_update_all(self, progress_callback=None) -> Dict[str, Any]:
    start_date, end_date = self._get_selected_date_range()
    completed = []

    def report(message: str, progress: int) -> None:
        if progress_callback:
            progress_callback(message, progress)

    def run_step(name: str, progress: int, action):
        report(name, progress)
        result = action()
        if isinstance(result, dict) and not result.get("success", True):
            return result
        completed.append({"step": name, "result": result})
        return result

    steps = [
        ("檢查資料狀態", 0, lambda: self.update_service.check_data_status()),
        ("每日股價更新", 12, lambda: self.update_service.update_daily(start_date, end_date)),
        ("大盤指數更新", 24, lambda: self.update_service.update_market(start_date, end_date)),
        ("產業指數更新", 36, lambda: self.update_service.update_industry(start_date, end_date)),
        ("券商分點更新", 48, lambda: self.update_service.update_broker_branch(start_date, end_date)),
        ("合併每日資料", 62, lambda: self.update_service.merge_daily_data(force_all=False)),
        ("合併券商分點", 74, lambda: self.update_service.merge_broker_branch_data()),
        ("增量計算技術指標", 88, lambda: self.update_service.calculate_technical_indicators(
            target_stock=None,
            force_all=False,
            start_date=None,
            progress_callback=progress_callback,
        )),
        ("刷新資料狀態", 100, lambda: self.update_service.check_data_status()),
    ]

    for name, progress, action in steps:
        result = run_step(name, progress, action)
        if isinstance(result, dict) and not result.get("success", True):
            return {
                "success": False,
                "message": result.get("message", f"{name} 失敗"),
                "failed_step": name,
                "completed_steps": completed,
                "step_result": result,
            }

    report("安全更新所有數據完成", 100)
    return {
        "success": True,
        "message": "安全更新所有數據完成",
        "completed_steps": completed,
    }
```

- [ ] **Step 4: Run safe sequence tests**

Run:

```powershell
pytest tests/test_ui_qt_update_view_workbench.py -q
```

Expected: PASS.

## Task 5: Wire Safe Update All Button

**Files:**
- Modify: `ui_qt/views/update_view.py`
- Test: `tests/test_ui_qt_update_view_workbench.py`

- [ ] **Step 1: Add the primary button on All Data page**

In `_build_all_data_page`, create:

```python
self.safe_update_all_btn = QPushButton("安全更新所有數據")
self.safe_update_all_btn.setMinimumHeight(44)
self.safe_update_all_btn.clicked.connect(self._execute_safe_update_all)
```

- [ ] **Step 2: Add `_execute_safe_update_all`**

Add:

```python
def _execute_safe_update_all(self):
    self.safe_update_all_btn.setEnabled(False)
    self.safe_update_all_btn.setText("安全更新中...")
    self.progress_bar.setVisible(True)
    self.progress_bar.setRange(0, 100)
    self.progress_bar.setValue(0)
    self.progress_label.setVisible(True)
    self.progress_label.setText("準備安全更新所有數據...")
    self.log_text.clear()
    self._log("開始安全更新所有數據")

    if self.worker and self.worker.isRunning():
        self.worker.cancel()
        self.worker.wait(3000)

    self.worker = ProgressTaskWorker(self._run_safe_update_all)
    self.worker.progress.connect(self._on_safe_update_all_progress)
    self.worker.finished.connect(self._on_safe_update_all_finished)
    self.worker.error.connect(self._on_safe_update_all_error)
    self.worker.start()
```

- [ ] **Step 3: Add progress and completion handlers**

Add:

```python
def _on_safe_update_all_progress(self, message: str, progress: int):
    self.progress_label.setText(message)
    self.progress_bar.setValue(progress)
    self._log(f"[安全更新 {progress}%] {message}")

def _on_safe_update_all_finished(self, result: Dict[str, Any]):
    self.safe_update_all_btn.setEnabled(True)
    self.safe_update_all_btn.setText("安全更新所有數據")
    self.progress_bar.setVisible(False)
    self.progress_label.setVisible(False)

    if result.get("success", False):
        self._log(result.get("message", "安全更新所有數據完成"))
        QMessageBox.information(self, "安全更新完成", result.get("message", "安全更新所有數據完成"))
        self._check_data_status()
        return

    failed_step = result.get("failed_step", "未知步驟")
    message = result.get("message", "安全更新失敗")
    self._log(f"安全更新失敗：{failed_step} - {message}")
    QMessageBox.warning(self, "安全更新未完成", f"{failed_step} 失敗：\n{message}")

def _on_safe_update_all_error(self, error_msg: str):
    self.safe_update_all_btn.setEnabled(True)
    self.safe_update_all_btn.setText("安全更新所有數據")
    self.progress_bar.setVisible(False)
    self.progress_label.setVisible(False)
    self._log(f"安全更新錯誤：{error_msg}")
    QMessageBox.critical(self, "安全更新失敗", error_msg[:500])
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_ui_qt_update_view_workbench.py -q
```

Expected: PASS.

## Task 6: Preserve Existing Single-Source Actions In Source Pages

**Files:**
- Modify: `ui_qt/views/update_view.py`
- Test command: `python scripts/qa_validate_update_tab.py`

- [ ] **Step 1: Move existing update controls into the source pages**

Keep these existing widgets as attributes so current handlers still work:

```python
self.daily_radio
self.market_radio
self.industry_radio
self.broker_branch_radio
self.end_date
self.lookback_days
self.update_btn
self.merge_btn
self.force_merge_btn
self.merge_broker_branch_btn
self.check_status_btn
self.tech_incremental_radio
self.tech_force_all_radio
self.tech_stock_input
self.calculate_tech_btn
self.progress_bar
self.progress_label
self.log_text
```

- [ ] **Step 2: Keep update type selection synchronized with navigation**

When navigating to an individual source page, set the matching radio:

```python
def _on_nav_changed(self, row: int):
    self.content_stack.setCurrentIndex(row)
    key = self._nav_items[row][0]
    if key == "daily":
        self.daily_radio.setChecked(True)
    elif key == "market":
        self.market_radio.setChecked(True)
    elif key == "industry":
        self.industry_radio.setChecked(True)
    elif key == "broker_branch":
        self.broker_branch_radio.setChecked(True)
```

Connect:

```python
self.nav_list.currentRowChanged.connect(self._on_nav_changed)
```

- [ ] **Step 3: Run the QA script**

Run:

```powershell
python scripts/qa_validate_update_tab.py
```

Expected: PASS or only documented skips for network/data-changing execution.

## Task 7: Final Verification

**Files:**
- Verify: `ui_qt/views/update_view.py`
- Verify: `tests/test_ui_qt_update_view_workbench.py`
- Verify: `scripts/qa_validate_update_tab.py`

- [ ] **Step 1: Run focused tests**

Run:

```powershell
pytest tests/test_ui_qt_update_view_workbench.py -q
```

Expected: PASS.

- [ ] **Step 2: Run existing update tab QA**

Run:

```powershell
python scripts/qa_validate_update_tab.py
```

Expected: PASS or only documented skips for real update execution.

- [ ] **Step 3: Run a syntax check**

Run:

```powershell
python -m py_compile ui_qt/views/update_view.py tests/test_ui_qt_update_view_workbench.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Review git diff**

Run:

```powershell
git diff -- ui_qt/views/update_view.py tests/test_ui_qt_update_view_workbench.py scripts/qa_validate_update_tab.py
```

Expected: only the workbench redesign, safe update all workflow, and related tests changed.

## Self-Review

Spec coverage:

- Workbench left navigation is covered by Tasks 1 and 2.
- Mixed source pages are covered by Tasks 2 and 6.
- Two-stage safe update plus advanced rebuild separation is covered by Tasks 4, 5, and 6.
- Existing actions and status/log/progress preservation are covered by Tasks 2, 5, and 6.
- Testing and validation are covered by Tasks 1, 3, and 7.

Placeholder scan:

- No `TBD`, `TODO`, "implement later", or undefined function names remain in this plan.

Type consistency:

- The plan uses the existing service method names found in `app_module/update_service.py`: `update_broker_branch`, `merge_broker_branch_data`, and `calculate_technical_indicators`.

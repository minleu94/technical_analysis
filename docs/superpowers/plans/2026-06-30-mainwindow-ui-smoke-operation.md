# MainWindow UI Smoke Operation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an opt-in Full App Healthcheck MainWindow UI smoke layer that launches the real PySide6 MainWindow, switches tabs, captures screenshots, tests resize, and verifies cancel-only dialog paths.

**Architecture:** Keep pure evidence helpers in `qa/full_app_healthcheck/mainwindow_smoke.py`, put real Qt startup/operation in `qa/full_app_healthcheck/mainwindow_smoke_runner.py`, and wire it into `scripts/run_full_app_healthcheck.py` only when `--ui-smoke` is provided. Default quick/full behavior remains unchanged.

**Tech Stack:** Python, PySide6 offscreen Qt, pytest, existing Full App Healthcheck runner.

---

### Task 1: Evidence Schema And Viewport Parsing

**Files:**
- Modify: `qa/full_app_healthcheck/mainwindow_smoke.py`
- Test: `tests/test_full_app_healthcheck_mainwindow_smoke_plan.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `parse_viewport_spec("390x844")`, reject invalid viewport strings, and verify `build_mainwindow_smoke_evidence(...)` includes screenshot / resize / dialog sections.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_mainwindow_smoke_plan.py -q -o addopts=
```

Expected: fail because the new helpers do not exist.

- [ ] **Step 3: Implement minimal helpers**

Add small dataclasses or dict builders in `mainwindow_smoke.py`; do not import PySide6.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command and confirm pass.

- [ ] **Step 5: Commit**

```powershell
git add qa\full_app_healthcheck\mainwindow_smoke.py tests\test_full_app_healthcheck_mainwindow_smoke_plan.py
git commit -m "feat: define mainwindow smoke evidence schema"
```

### Task 2: Real Qt Smoke Runner

**Files:**
- Create: `qa/full_app_healthcheck/mainwindow_smoke_runner.py`
- Test: `tests/test_full_app_healthcheck_mainwindow_smoke_runner.py`

- [ ] **Step 1: Write failing tests**

Add fake QApplication / MainWindow collaborators and assert `run_mainwindow_smoke(...)`:

- creates an evidence directory
- switches expected tabs when requested
- writes screenshot paths when requested
- records resize evidence for each viewport
- closes the window in cleanup

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_mainwindow_smoke_runner.py -q -o addopts=
```

Expected: fail because module/function do not exist.

- [ ] **Step 3: Implement runner**

Create `MainWindowSmokeOptions` and `run_mainwindow_smoke(options)`. Use dependency injection for tests; default factory imports PySide6 and `ui_qt.main.MainWindow` lazily.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command and confirm pass.

- [ ] **Step 5: Commit**

```powershell
git add qa\full_app_healthcheck\mainwindow_smoke_runner.py tests\test_full_app_healthcheck_mainwindow_smoke_runner.py
git commit -m "feat: add opt-in mainwindow smoke runner"
```

### Task 3: CLI And Manifest Opt-In

**Files:**
- Modify: `scripts/run_full_app_healthcheck.py`
- Modify: `tests/test_full_app_healthcheck_runner.py`
- Modify: `tests/test_full_app_healthcheck_actions.py`
- Modify: `qa/full_app_healthcheck/actions.py`

- [ ] **Step 1: Write failing tests**

Assert CLI parses `--ui-smoke`, `--ui-smoke-switch-tabs`, `--ui-smoke-screenshot`, `--ui-smoke-resize`, `--ui-smoke-dialog-cancel`; default parse has `ui_smoke == False`. Assert dynamic manifest includes MainWindow step only when enabled.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_runner.py tests\test_full_app_healthcheck_actions.py -q -o addopts=
```

Expected: fail because CLI flags and action are missing.

- [ ] **Step 3: Implement CLI wiring**

Add parser args, build smoke context, dynamic manifest append helper, and action `run_mainwindow_ui_smoke`.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command and confirm pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts\run_full_app_healthcheck.py qa\full_app_healthcheck\actions.py tests\test_full_app_healthcheck_runner.py tests\test_full_app_healthcheck_actions.py
git commit -m "feat: wire opt-in mainwindow ui smoke"
```

### Task 4: Dialog Cancel Path

**Files:**
- Modify: `qa/full_app_healthcheck/mainwindow_smoke_runner.py`
- Test: `tests/test_full_app_healthcheck_mainwindow_smoke_runner.py`

- [ ] **Step 1: Write failing test**

Use fake UpdateView and fake QMessageBox to verify cancel path returns `cancelled=True` and the destructive merge method is not called.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_mainwindow_smoke_runner.py -q -o addopts=
```

- [ ] **Step 3: Implement cancel-only probe**

Add a narrow UpdateView probe that calls the existing force merge dialog method only with QMessageBox patched to cancel, or records unavailable when the view/method is not present.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command and confirm pass.

- [ ] **Step 5: Commit**

```powershell
git add qa\full_app_healthcheck\mainwindow_smoke_runner.py tests\test_full_app_healthcheck_mainwindow_smoke_runner.py
git commit -m "feat: verify mainwindow dialog cancel path"
```

### Task 5: Documentation And Final Verification

**Files:**
- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md`
- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update docs**

Document the new opt-in command and clarify that MainWindow UI smoke is executable but not default.

- [ ] **Step 2: Commit docs**

```powershell
git add docs\06_qa\FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md docs\06_qa\FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md docs\07_guides\APPLICATION_MANUAL.md docs\00_core\DOCUMENTATION_INDEX.md
git commit -m "docs: document executable mainwindow ui smoke"
```

- [ ] **Step 3: Final verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_mainwindow_smoke_plan.py tests\test_full_app_healthcheck_mainwindow_smoke_runner.py tests\test_full_app_healthcheck_runner.py tests\test_full_app_healthcheck_actions.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir "$env:TEMP\baldr_hc_mainwindow_ui_smoke" --fail-fast
.\.venv\Scripts\python.exe -m py_compile scripts\run_full_app_healthcheck.py qa\full_app_healthcheck\mainwindow_smoke.py qa\full_app_healthcheck\mainwindow_smoke_runner.py qa\full_app_healthcheck\actions.py
git diff --check
git status --short --branch
```

Expected: all commands exit 0; working tree clean after commits.

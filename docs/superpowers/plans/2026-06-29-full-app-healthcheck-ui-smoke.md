# Full App Healthcheck UI Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 Full App Healthcheck 支援分 tab 驗證，並逐步接近真人 UI 操作測試，同時維持非破壞、安全可回滾。

**Architecture:** 在既有 runner 外圍新增 tab routing 與 opt-in smoke action，不改主 UI 或核心業務邏輯。`mode` 控制安全級別，`tab` 控制工作區範圍，report 顯示實際執行 suites 與 manual gaps。

**Tech Stack:** Python、pytest、PySide6 offscreen、現有 `qa/full_app_healthcheck` runner、Markdown 文件。

---

## Commit 0：設計與計畫文件

**Files:**
- Create: `docs/superpowers/specs/2026-06-29-full-app-healthcheck-ui-smoke-design.md`
- Create: `docs/superpowers/plans/2026-06-29-full-app-healthcheck-ui-smoke.md`

- [ ] **Step 1: 建立文件**

使用設計文件固定 rollback baseline、非目標、安全邊界、tab routing、MainWindow smoke 與文件同步策略。

- [ ] **Step 2: 檢查 Markdown**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Commit**

```powershell
git add docs\superpowers\specs\2026-06-29-full-app-healthcheck-ui-smoke-design.md docs\superpowers\plans\2026-06-29-full-app-healthcheck-ui-smoke.md
git commit -m "docs: plan full app healthcheck UI smoke"
```

## Commit 1：Tab Routing Model

**Files:**
- Modify: `qa/full_app_healthcheck/test_suite_bridge.py`
- Test: `tests/test_full_app_healthcheck_test_suite_bridge.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_suite_bridge import suites_for_mode_and_tabs


def test_suites_can_be_filtered_to_update_tab_only():
    suites = suites_for_mode_and_tabs(HealthcheckMode.FULL, ("update",))
    suite_ids = {suite.id for suite in suites}
    assert "ui-update-workbench" in suite_ids
    assert "qa-update-tab" in suite_ids
    assert "ui-research-workflow" not in suite_ids


def test_suites_can_be_filtered_to_research_tab_only():
    suites = suites_for_mode_and_tabs(HealthcheckMode.FULL, ("research",))
    suite_ids = {suite.id for suite in suites}
    assert "ui-research-workflow" in suite_ids
    assert "ui-run-registry-compare" in suite_ids
    assert "ui-update-workbench" not in suite_ids


def test_no_tab_filter_preserves_existing_full_mode_registry():
    unfiltered = suites_for_mode_and_tabs(HealthcheckMode.FULL, ())
    legacy = suites_for_mode(HealthcheckMode.FULL)
    assert tuple(suite.id for suite in unfiltered) == tuple(suite.id for suite in legacy)
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_test_suite_bridge.py -q -o addopts=
```

Expected: fail because `suites_for_mode_and_tabs` does not exist.

- [ ] **Step 3: Implement minimal routing**

Add `tabs: tuple[str, ...]` to `ExistingSuite`, assign known tabs to current suites, and implement `suites_for_mode_and_tabs(mode, tabs)`.

- [ ] **Step 4: Run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_test_suite_bridge.py -q -o addopts=
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add qa\full_app_healthcheck\test_suite_bridge.py tests\test_full_app_healthcheck_test_suite_bridge.py
git commit -m "feat: route healthcheck suites by tab"
```

## Commit 2：CLI `--tab`

**Files:**
- Modify: `scripts/run_full_app_healthcheck.py`
- Modify: `qa/full_app_healthcheck/runner.py` if context propagation is needed
- Test: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `parse_args(["--mode", "full", "--tab", "update"])` and assert `args.tabs == ["update"]`. Add a runner/action test that context contains selected tabs.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: fail because `--tab` is not accepted.

- [ ] **Step 3: Implement CLI**

Add repeated `--tab` choices and pass `tabs=tuple(args.tabs)` into runner context. Make `run_existing_suites_for_mode()` call `suites_for_mode_and_tabs(mode, tabs)`.

- [ ] **Step 4: Run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_runner.py tests\test_full_app_healthcheck_test_suite_bridge.py -q -o addopts=
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts\run_full_app_healthcheck.py qa\full_app_healthcheck\runner.py tests\test_full_app_healthcheck_runner.py tests\test_full_app_healthcheck_test_suite_bridge.py
git commit -m "feat: add healthcheck tab CLI filter"
```

## Commit 3：Report Evidence for Tabs

**Files:**
- Modify: `qa/full_app_healthcheck/reporting.py`
- Modify: `scripts/run_full_app_healthcheck.py`
- Test: `tests/test_full_app_healthcheck_reporting.py`

- [ ] **Step 1: Write failing tests**

Assert generated `REPORT.md` and `result.json` include selected tabs when context provides them.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_reporting.py -q -o addopts=
```

Expected: fail because tabs are not written.

- [ ] **Step 3: Implement report metadata**

Extend result evidence or report section to show `Tabs: update, research`; keep old reports stable when no tabs are selected.

- [ ] **Step 4: Run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_reporting.py -q -o addopts=
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add qa\full_app_healthcheck\reporting.py scripts\run_full_app_healthcheck.py tests\test_full_app_healthcheck_reporting.py
git commit -m "feat: report selected healthcheck tabs"
```

## Commit 4：Opt-in MainWindow Smoke Skeleton

**Files:**
- Create or Modify: `qa/full_app_healthcheck/mainwindow_smoke.py`
- Modify: `qa/full_app_healthcheck/actions.py`
- Modify: `qa/full_app_healthcheck/default_manifest.py`
- Test: `tests/test_full_app_healthcheck_mainwindow_smoke_plan.py`

- [ ] **Step 1: Write failing tests**

Assert MainWindow smoke action is not part of quick/full by default, and high-level metadata lists expected tabs.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_mainwindow_smoke_plan.py -q -o addopts=
```

Expected: fail for missing executable smoke metadata/action.

- [ ] **Step 3: Implement skeleton**

Implement a safe smoke helper that can inspect tab labels using an injected/fake app/window in tests. Do not launch real MainWindow in default quick/full path.

- [ ] **Step 4: Run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_mainwindow_smoke_plan.py -q -o addopts=
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add qa\full_app_healthcheck tests\test_full_app_healthcheck_mainwindow_smoke_plan.py
git commit -m "feat: add opt-in main window smoke skeleton"
```

## Commit 5：Candidate Safe Tab Coverage

**Files:**
- Modify: `qa/full_app_healthcheck/test_inventory.py`
- Modify: `qa/full_app_healthcheck/test_suite_bridge.py`
- Test: `tests/test_full_app_healthcheck_test_inventory.py`
- Test: `tests/test_full_app_healthcheck_test_suite_bridge.py`

- [ ] **Step 1: Write failing tests**

Add explicit tests for candidate-safe suites that can be routed by `recommendation`, `watchlist`, `portfolio`, and `runtime` without including write-risk tests.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_test_inventory.py tests\test_full_app_healthcheck_test_suite_bridge.py -q -o addopts=
```

Expected: fail for missing bridge entries.

- [ ] **Step 3: Implement candidate promotion**

Only promote tests that are UI-only, tmp-path safe, or fake-service based. Keep transaction writes, deletes, clear-all and real data actions manual.

- [ ] **Step 4: Run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_test_inventory.py tests\test_full_app_healthcheck_test_suite_bridge.py -q -o addopts=
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add qa\full_app_healthcheck tests\test_full_app_healthcheck_test_inventory.py tests\test_full_app_healthcheck_test_suite_bridge.py
git commit -m "feat: expand safe tab healthcheck bridges"
```

## Commit 6：Documentation Sync

**Files:**
- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md`
- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update QA docs**

Document `--tab`, tab coverage behavior, MainWindow smoke opt-in boundary, and remaining manual gaps.

- [ ] **Step 2: Update Manual**

Add healthcheck invocation examples:

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab update --output-dir output\qa\full_app_healthcheck_update
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab research --output-dir output\qa\full_app_healthcheck_research
```

- [ ] **Step 3: Update Index**

Add spec / plan references if required.

- [ ] **Step 4: Commit**

```powershell
git add docs\06_qa docs\07_guides\APPLICATION_MANUAL.md docs\00_core\DOCUMENTATION_INDEX.md
git commit -m "docs: document tabbed full app healthcheck"
```

## Commit 7：Final Verification

**Files:**
- No code changes unless fixing test-only defects.

- [ ] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_test_suite_bridge.py tests\test_full_app_healthcheck_runner.py tests\test_full_app_healthcheck_reporting.py tests\test_full_app_healthcheck_mainwindow_smoke_plan.py -q -o addopts=
```

- [ ] **Step 2: Run quick**

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir $env:TEMP\baldr_hc_quick --fail-fast
```

- [ ] **Step 3: Run full tab samples**

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab update --output-dir $env:TEMP\baldr_hc_update --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab research --output-dir $env:TEMP\baldr_hc_research --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab portfolio --output-dir $env:TEMP\baldr_hc_portfolio --fail-fast
```

- [ ] **Step 4: Run full default**

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --output-dir $env:TEMP\baldr_hc_full --fail-fast
```

- [ ] **Step 5: Commit verification doc if needed**

Only commit a verification note if documentation changed. Do not stage `output/qa/update_tab/` unless explicitly required.

# Month 4 Daily Decision Desk Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Month 4 by turning Daily Decision Desk v1 from a technically wired feature into a verified, documented, visually reviewable daily workflow that is ready to hand off into Month 5 Fundamental Layer.

**Architecture:** Month 4 is already functionally connected through service snapshot aggregation. Closure work must preserve the existing boundary: UI reads DTO/service results and must not recompute market breadth, sector rotation, relative strength, liquidity, watchlist scoring, portfolio alerts, broker flow, recommendation scoring, or backtest logic.

**Tech Stack:** Python, PySide6, pytest, mypy, existing `app_module` service / DTO contracts, existing `ui_qt` view patterns, project documentation under `docs/`.

---

## Current Assessment

Month 4 is close to closure. The main service wiring is already present:

- Daily Decision Desk is a top-level UI workspace.
- `DecisionDeskSnapshot` / service aggregation exists.
- Market Breadth v1 reads SQLite `daily_prices`.
- Sector Rotation v1 reads SQLite `industry_indices`.
- Relative Strength / Liquidity Ranking v1 reads SQLite `daily_prices`.
- Watchlist Trigger v1 uses `WatchlistService` and SQLite `technical_indicators`.
- Portfolio Alert v1 uses `PortfolioService`, `PortfolioConditionMonitor`, and `PortfolioChipService`.
- Portfolio Alert Attribution v1 exposes alert source, condition status, chip risk level, reason tokens, and data quality flags.
- Why Not / risk prompt v1 uses section DTO quality, warnings, weak/illiquid lists, watchlist risk, and portfolio alert signals.

The remaining closure work is not a major new engine. It is a quality gate:

1. Make the Daily Decision Desk visually acceptable enough to serve as the Month 4 reference screen.
2. Remove duplicated old/new UI presentation in the desk.
3. Lock data-quality degradation behavior with focused tests.
4. Confirm the desk does not recompute domain logic in the UI layer.
5. Update the Manual, Architecture, Snapshot, Roadmap, and design-system spec so Month 4 can be marked closed without overstating completeness.
6. Define the Month 5 handoff contract.

---

## Closure Execution Result

Status: closed as a service-backed Month 4 v1 daily workflow.

Completed closure actions:

- Daily Decision Desk section quality now renders through header badges.
- Relative Strength / Liquidity uses a single `CompactCodeList` presentation; the old duplicate text field is hidden and kept only for compatibility.
- Added `tests/test_decision_desk_ui_contract.py` to block UI imports of scoring, screening, backtest, recommendation, and portfolio-core calculation modules.
- Verified service snapshot, data-quality warnings, and Why Not / risk prompt contracts.
- Updated Snapshot, 6M Roadmap, Roadmap Hub, Architecture, Manual, design-system spec, and Documentation Index.
- Added `docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md` as the Month 5 entry plan.

Verification evidence:

- `tests/test_ui_qt_theme.py tests/test_ui_qt_decision_desk_view.py tests/test_ui_qt_decision_desk_main_integration.py tests/test_decision_desk_ui_contract.py`: 28 passed.
- `tests/test_decision_desk_service.py tests/test_decision_desk_risk_prompt_service.py`: 13 passed.
- `tests/test_ui_qt_update_view_workbench.py`: 13 passed.
- `scripts/qa_validate_update_tab.py`: 21 passed, 0 failed, 4 skipped.
- `mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`: success, 175 source files.
- `py_compile` for changed Python files: pass.

Month 5 handoff:

- Start with Fundamental Layer preflight.
- Do not ingest or score new fundamental data before source inventory, `available_date` contract, factor adapter boundary, and no-look-ahead tests are defined.

---

## File Map

### UI Reference Screen

- Modify: `ui_qt/views/decision_desk_view.py`
  - Owns Daily Decision Desk layout and display only.
  - Must use shared theme widgets and service snapshot fields.
  - Must not calculate market, recommendation, portfolio, or liquidity logic.

- Modify: `ui_qt/widgets/theme_widgets.py`
  - Owns reusable low-cost Qt widgets such as `SectionPanel`, `MetricCard`, `StatusBadge`, `CompactCodeList`, and `WarningList`.
  - Keep widgets passive and data-display only.

- Modify: `ui_qt/theme/tokens.py`
  - Owns Midnight Analyst theme tokens.
  - Do not add business-specific colors here.

- Modify: `ui_qt/theme/qss.py`
  - Owns global QSS.
  - Keep selectors broad enough for consistency, but avoid heavy effects.

### Service and Contract Regression

- Inspect/modify only if tests reveal gaps: `app_module/decision_desk_service.py`
- Inspect/modify only if tests reveal gaps: `app_module/decision_desk_dtos.py`
- Inspect/modify only if tests reveal gaps: `app_module/decision_desk_risk_prompt_service.py`

### Tests

- Modify: `tests/test_ui_qt_decision_desk_view.py`
  - Visual contract tests for compactness, duplicate suppression, and reference widgets.

- Modify: `tests/test_ui_qt_theme.py`
  - Theme token and shared widget tests.

- Modify: `tests/test_decision_desk_service.py`
  - Snapshot quality and warning contract tests.

- Modify: `tests/test_decision_desk_risk_prompt_service.py`
  - Why Not / risk prompt behavior tests.

- Optional create: `tests/test_decision_desk_ui_contract.py`
  - Static contract test that blocks domain-service calls or scoring imports in UI.

### Documentation

- Modify: `docs/01_architecture/ui_design_system_midnight_analyst.md`
  - Record final accepted Month 4 reference-screen state and known non-blocking design debt.

- Modify: `docs/01_architecture/system_architecture.md`
  - Confirm Month 4 architecture closure and UI/service boundaries.

- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - Mark Month 4 as closed only after verification passes.

- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - Move Month 4 from active closure to completed v1, and make Month 5 the next active work.

- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
  - Update short Next list after closure.

- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
  - Add this closure plan and update log entry.

- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - Update user-facing Daily Decision Desk operation, interpretation, limitations, and troubleshooting.

---

## Closure Definition

Month 4 can be considered closed when all of the following are true:

- Daily Decision Desk can be opened without widening the main UI beyond normal viewport expectations.
- Daily Decision Desk has one coherent presentation model, not mixed old labels plus new widgets.
- Strong / weak / low-liquidity lists are compact and do not stretch layout horizontally.
- Each section exposes quality and warnings clearly enough for a daily user to understand data reliability.
- Why Not / risk prompt includes liquidity, weak relative strength, watchlist risk, portfolio alert, and data-quality concerns without recomputing source logic.
- UI layer does not import or call scoring/backtest/recommendation/portfolio calculation internals beyond the approved service snapshot.
- Manual and architecture documents describe the same behavior as the implementation.
- Required tests, QA script, mypy, and py_compile pass.
- Month 5 Fundamental Layer has a clear starting contract and does not inherit unresolved Month 4 ambiguity.

---

## Task 1: Freeze Scope and Baseline

**Files:**
- Read: `docs/00_core/PROJECT_SNAPSHOT.md`
- Read: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Read: `docs/01_architecture/system_architecture.md`
- Read: `docs/01_architecture/ui_design_system_midnight_analyst.md`
- Read: `ui_qt/views/decision_desk_view.py`
- Read: `tests/test_ui_qt_decision_desk_view.py`

- [ ] **Step 1: Confirm current git status**

Run:

```powershell
git status --short
```

Expected:

- Existing user or agent changes are visible.
- Do not revert unrelated changes.
- Note which files belong to the Month 4 UI/theme work before editing.

- [ ] **Step 2: Run focused baseline tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_decision_desk_service.py tests\test_decision_desk_risk_prompt_service.py -q -o addopts=
```

Expected:

- Tests pass before closure edits, or failures are recorded as closure blockers.

- [ ] **Step 3: Record baseline blockers in this plan**

If tests fail, add a short "Baseline Blockers" section near the top of this file with:

```markdown
## Baseline Blockers

- `<test name>` fails because `<observed cause>`.
- Resolution owner: Month 4 closure.
```

---

## Task 2: Make Daily Decision Desk a Real Reference Screen

**Files:**
- Modify: `ui_qt/views/decision_desk_view.py`
- Modify if needed: `ui_qt/widgets/theme_widgets.py`
- Modify: `tests/test_ui_qt_decision_desk_view.py`

- [ ] **Step 1: Add failing tests for one-presentation UI**

Add or adjust tests so the view contract checks:

- `relative_strength_liquidity_value` is not shown as a competing full text block when `relative_strength_codes` is present.
- section quality is represented by a badge/header pattern, not repeated as noisy inline text in every row.
- strong / weak / low-liquidity lists render through `CompactCodeList`.

Suggested test names:

```python
def test_decision_desk_uses_single_relative_strength_presentation(qtbot):
    ...

def test_decision_desk_sections_use_compact_reference_widgets(qtbot):
    ...
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py -q -o addopts=
```

Expected:

- At least one new test fails before implementation if the duplicate old/new presentation still exists.

- [ ] **Step 3: Rework the view layout**

In `ui_qt/views/decision_desk_view.py`, restructure the visible Daily Decision Desk into:

- top summary strip: decision date, generated time, overall quality, market regime
- market intelligence grid: breadth, sector rotation, relative strength/liquidity
- action panel: watchlist triggers and portfolio alerts
- warning panel: Why Not / risk prompts and data-quality warnings

Implementation constraints:

- Keep calculations out of the UI.
- Use fields already present on the snapshot DTOs.
- Preserve compatibility labels only if tests require them, but hide or de-emphasize them so the visible UI has one presentation model.
- No long comma-joined stock lists.
- No nested card-inside-card visual structure.

- [ ] **Step 4: Run Daily Desk UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=
```

Expected:

- All tests pass.

---

## Task 3: Lock the UI Boundary Against Domain Recalculation

**Files:**
- Create if absent: `tests/test_decision_desk_ui_contract.py`
- Inspect: `ui_qt/views/decision_desk_view.py`

- [ ] **Step 1: Add a static import contract test**

Create `tests/test_decision_desk_ui_contract.py` with a test that reads `ui_qt/views/decision_desk_view.py` and fails if the UI imports known calculation modules directly.

Blocked import patterns:

```python
BLOCKED_PATTERNS = [
    "decision_module.scoring_engine",
    "decision_module.stock_screener",
    "decision_module.flow_signal_engine",
    "backtest_module",
    "app_module.recommendation_service",
    "app_module.recommendation_replay_service",
    "portfolio_module.core",
]
```

Allowed:

- `app_module.decision_desk_service`
- `app_module.decision_desk_dtos`
- `app_module.decision_desk_risk_prompt_service`

- [ ] **Step 2: Run the contract test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_ui_contract.py -q -o addopts=
```

Expected:

- Test passes.

---

## Task 4: Verify Data Quality and Risk Prompt Closure

**Files:**
- Modify if needed: `tests/test_decision_desk_service.py`
- Modify if needed: `tests/test_decision_desk_risk_prompt_service.py`
- Modify only if tests reveal a real gap: `app_module/decision_desk_service.py`
- Modify only if tests reveal a real gap: `app_module/decision_desk_risk_prompt_service.py`

- [ ] **Step 1: Ensure service tests cover all Month 4 sections**

Confirm tests cover:

- market regime section quality
- market breadth fallback / warnings
- sector rotation fallback / warnings
- relative strength insufficient history warning
- watchlist trigger fallback / risk alert
- portfolio alert missing / estimated / unavailable chip data
- portfolio alert attribution source labels
- snapshot-level overall quality aggregation

- [ ] **Step 2: Ensure risk prompt tests cover all Month 4 risk sources**

Confirm tests cover prompts for:

- low liquidity
- relative weakness
- watchlist risk alert
- portfolio alert
- degraded or missing section quality

- [ ] **Step 3: Run service and prompt tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py tests\test_decision_desk_risk_prompt_service.py -q -o addopts=
```

Expected:

- All tests pass.
- Any new failure is treated as a Month 4 closure blocker.

---

## Task 5: Full Required Verification Gate

**Files:**
- No code edits unless the gate exposes failures.

- [ ] **Step 1: Run required UI workbench regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected:

- Pass.

- [ ] **Step 2: Run Update Tab QA script**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

Expected:

- `21 passed, 0 failed` or equivalent project-success output.

- [ ] **Step 3: Run mypy**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected:

- Success with no issues.

- [ ] **Step 4: Run py_compile for changed Python files**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile ui_qt\main.py ui_qt\views\decision_desk_view.py ui_qt\widgets\theme_widgets.py ui_qt\theme\tokens.py ui_qt\theme\qss.py app_module\decision_desk_service.py app_module\decision_desk_dtos.py app_module\decision_desk_risk_prompt_service.py
```

Expected:

- Exit code 0.

---

## Task 6: Documentation Closure

**Files:**
- Modify: `docs/01_architecture/ui_design_system_midnight_analyst.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: Update the design system spec**

In `docs/01_architecture/ui_design_system_midnight_analyst.md`, change the Daily Decision Desk status from "not accepted as final visual direction" to one of:

- "Accepted as Month 4 v1 reference screen"
- "Accepted as functional closure, visual polish remains Month 5+ backlog"
- "Not accepted; Month 4 closure blocked"

Do not mark accepted unless Task 5 passes.

- [ ] **Step 2: Update architecture**

In `docs/01_architecture/system_architecture.md`, ensure the Daily Decision Desk section states:

- v1 is service-snapshot aggregation.
- UI does not recompute scoring, screening, portfolio, broker flow, liquidity, or backtest logic.
- Strategy Drift and Post-trade Attribution remain Month 6+ unless separately implemented.

- [ ] **Step 3: Update project snapshot**

In `docs/00_core/PROJECT_SNAPSHOT.md`, mark Month 4 as closed only if:

- Task 2 through Task 5 pass.
- Known remaining design debt is explicitly non-blocking.

- [ ] **Step 4: Update roadmap**

In `docs/00_core/ROADMAP_6M_ENGINEERING.md`, move the immediate next work from Month 4 closure to Month 5 Fundamental Layer initial specification.

Keep this wording accurate:

```markdown
Month 4 Daily Decision Desk v1 is closed as a service-backed daily workflow. Further visual refinement is design debt and does not change the data/decision contract.
```

- [ ] **Step 5: Update the user manual**

In `docs/07_guides/APPLICATION_MANUAL.md`, confirm:

- entry point is the top-level "每日決策" tab
- quality meanings are described
- warnings are described
- strong / weak / low-liquidity lists are compact summaries
- this is not auto-trading
- limitations mention degraded/missing data

- [ ] **Step 6: Update documentation index**

In `docs/00_core/DOCUMENTATION_INDEX.md`, add this plan to the Superpowers plans list and add a dated update log entry.

---

## Task 7: Month 5 Handoff Note

**Files:**
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Optional create: `docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md`

- [ ] **Step 1: Define the Month 5 entry contract**

Month 5 may start only after Month 4 closure gate passes.

Month 5 first work should be specification/preflight, not immediate raw data ingestion:

- revenue source inventory
- announcement date / available date contract
- factor adapter boundary
- no-look-ahead tests
- valuation display policy
- abnormal fundamental flag policy

- [ ] **Step 2: Explicitly carry forward non-blocking backlog**

Do not let these items block Month 4 closure:

- odd-lot execution modeling
- bid/ask spread execution modeling
- full matching engine
- actual gap execution model
- PDF research report export
- Strategy Drift
- Post-trade Attribution

They remain later execution/research lifecycle backlog unless separately prioritized.

---

## Recommended Execution Order

1. Task 1 baseline.
2. Task 2 Daily Decision Desk reference screen.
3. Task 3 UI boundary guard.
4. Task 4 data-quality and risk prompt tests.
5. Task 5 full verification gate.
6. Task 6 documentation closure.
7. Task 7 Month 5 handoff.

Do not update Snapshot/Roadmap to "closed" before verification passes.

---

## Final Closure Report Template

Use this summary when closing the work:

```markdown
Month 4 closure result:

- Daily Decision Desk v1: closed / blocked
- UI reference screen: accepted / accepted with visual debt / blocked
- Service snapshot boundary: verified / blocked
- Data quality warnings: verified / blocked
- Why Not / risk prompt: verified / blocked
- Documentation: synchronized / blocked
- Month 5 handoff: ready / blocked

Verification:

- `tests/test_ui_qt_theme.py ...`: pass/fail
- `tests/test_ui_qt_update_view_workbench.py`: pass/fail
- `scripts/qa_validate_update_tab.py`: pass/fail
- `mypy`: pass/fail
- `py_compile`: pass/fail
```

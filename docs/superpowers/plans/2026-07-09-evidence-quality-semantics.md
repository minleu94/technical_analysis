# Evidence Quality Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve MoneyDJ provenance while reporting fixed-threshold recommendations and complete mixed-quality source coverage accurately.

**Architecture:** The scheduled recommendation snapshot declares fixed-threshold metadata without manufacturing a percentile. Evidence importers retain source provenance in metadata but do not duplicate snapshot advisories onto every derived event. The pipeline separates warnings from advisories, derives `ready_with_advisories`, and propagates that status through the scheduler and UI.

**Tech Stack:** Python 3.11, dataclasses, Decimal/integer counts, pytest, PySide6.

## Global Constraints

- Do not add FinMind or an external provider.
- Do not write the production evidence DB, rewrite MoneyDJ raw CSV, or change recommendation scores.
- A missing percentile is only a warning when the result declares a ranking-based comparable universe.
- Coverage values use source-provided integer event counts; do not introduce financial float calculations.
- Preserve existing dirty-worktree changes and commit only files in this plan plus the prior evidence scheduler closeout files.

---

### Task 1: Fixed-Threshold Recommendation Metadata

**Files:**
- Modify: `scripts/scheduled/run_scheduled_recommendation_snapshot.py`
- Modify: `app_module/evidence_event_importers.py`
- Test: `tests/test_scheduled_recommendation_snapshot.py`
- Test: `tests/test_evidence_pipeline_runner.py`

**Interfaces:**
- Produces: scheduled recommendations with `threshold_mode="fixed"` and `ranking_method="fixed_threshold"`.
- Produces: no `score_percentile_missing` token when a recommendation is fixed-threshold and has no percentile.

- [ ] **Step 1: Write failing tests**

```python
def test_fixed_threshold_snapshot_marks_percentile_not_applicable(...):
    result = load_scheduled_result(...)
    assert result.recommendations[0].ranking_method == "fixed_threshold"
    assert result.recommendations[0].score_percentile_bp is None

def test_fixed_threshold_recommendation_does_not_emit_percentile_missing(...):
    summary = EvidencePipelineRunner(config).run(request)
    assert "score_percentile_missing" not in summary.warning_counts
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scheduled_recommendation_snapshot.py tests/test_evidence_pipeline_runner.py -q -o addopts=`

Expected: failure because fixed-threshold metadata and conditional warning logic are absent.

- [ ] **Step 3: Implement the minimum metadata and conditional warning rule**

```python
if threshold_mode == "fixed":
    recommendation = replace(recommendation, ranking_method="fixed_threshold")

if percentile is None and threshold_mode != "fixed":
    warnings.append("score_percentile_missing")
```

- [ ] **Step 4: Re-run the focused tests and confirm GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scheduled_recommendation_snapshot.py tests/test_evidence_pipeline_runner.py -q -o addopts=`

Expected: all selected tests pass.

### Task 2: Snapshot Advisory De-duplication

**Files:**
- Modify: `app_module/evidence_event_importers.py`
- Modify: `app_module/evidence_capture_service.py`
- Test: `tests/test_evidence_capture_service.py`
- Test: `tests/test_decision_desk_risk_prompt_service.py`

**Interfaces:**
- Produces: derived portfolio and risk-prompt event payloads with source quality stored in `metadata["source_quality_warnings"]`.
- Produces: source snapshot advisories counted once, not once per derived event.

- [ ] **Step 1: Write failing tests**

```python
def test_risk_prompt_events_do_not_repeat_snapshot_quality_warnings(...):
    result = RiskPromptEvidenceImporter(provider).collect(request)
    assert all(payload["warnings"] == () for payload in result.event_payloads)
    assert result.event_payloads[0]["metadata"]["source_quality_warnings"]

def test_capture_summary_counts_one_source_advisory_not_each_derived_event(...):
    summary = service.capture(request)
    assert summary.warning_counts["risk_prompt_source_quality:portfolio_alerts:estimated"] == 1
```

- [ ] **Step 2: Run selected tests and confirm RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_evidence_capture_service.py tests/test_decision_desk_risk_prompt_service.py -q -o addopts=`

Expected: failure because importers currently copy snapshot warnings to every payload.

- [ ] **Step 3: Implement source-level advisory transport**

```python
metadata["source_quality_warnings"] = list(summary.warnings)
payload["warnings"] = ()
```

Extend capture aggregation to count the unique source-level advisory from importer metadata once per source snapshot.

- [ ] **Step 4: Re-run selected tests and confirm GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_evidence_capture_service.py tests/test_decision_desk_risk_prompt_service.py -q -o addopts=`

Expected: all selected tests pass.

### Task 3: Pipeline Advisory Status and Report Coverage

**Files:**
- Modify: `app_module/evidence_pipeline_runner_dtos.py`
- Modify: `app_module/evidence_pipeline_runner.py`
- Modify: `app_module/portfolio_alert_service.py`
- Test: `tests/test_evidence_pipeline_runner.py`
- Test: `tests/test_relative_strength_liquidity_service.py`

**Interfaces:**
- Adds: `STEP_READY_WITH_ADVISORIES = "ready_with_advisories"`.
- Adds: advisory counts and source coverage rows to step/run summaries and Markdown report.
- Produces: `degraded` only for failures, blocking gaps, stale/missing data, or coverage below the configured threshold.

- [ ] **Step 1: Write failing tests**

```python
def test_complete_mixed_chip_coverage_is_ready_with_advisories(...):
    summary = runner.run(request)
    assert summary.overall_status == "ready_with_advisories"
    assert summary.advisory_counts["portfolio_alerts_chip_estimated:2330"] == 1

def test_report_includes_chip_observed_estimated_unavailable_counts(...):
    report = report_path.read_text(encoding="utf-8")
    assert "observed_event_count" in report
    assert "estimated_event_count" in report
```

- [ ] **Step 2: Run selected tests and confirm RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_evidence_pipeline_runner.py tests/test_relative_strength_liquidity_service.py -q -o addopts=`

Expected: failure because advisory status and coverage report rows do not exist.

- [ ] **Step 3: Implement advisory classification and reporting**

```python
if step.status == STEP_READY_WITH_ADVISORIES:
    return STEP_READY_WITH_ADVISORIES
```

Classify observed/estimated complete MoneyDJ provenance and accepted relative-strength skips as advisories. Preserve unavailable or threshold-breaching coverage as degraded. Render advisory and per-stock chip coverage sections separately from warnings.

- [ ] **Step 4: Re-run selected tests and confirm GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_evidence_pipeline_runner.py tests/test_relative_strength_liquidity_service.py -q -o addopts=`

Expected: all selected tests pass.

### Task 4: Scheduled Status, UI, and Documentation

**Files:**
- Modify: `scripts/scheduled/run_scheduled_evidence_pipeline_dry_run.py`
- Modify: `app_module/scheduled_evidence_status_service.py`
- Modify: `ui_qt/views/scheduled_evidence_status_view.py`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/07_guides/EVIDENCE_SCHEDULED_MORNING_CHECK.md`
- Modify: `scripts/scheduled/README.md`
- Test: `tests/test_scheduled_evidence_pipeline_dry_run_wrapper.py`
- Test: `tests/test_scheduled_evidence_status_service.py`
- Test: `tests/test_ui_qt_evidence_review_dashboards.py`

**Interfaces:**
- Preserves `ready_with_advisories` from pipeline summary into scheduled status and UI.
- Displays advisory count and MoneyDJ source coverage without calling it production evidence DB persistence.

- [ ] **Step 1: Write failing tests**

```python
def test_scheduled_wrapper_preserves_ready_with_advisories(...):
    assert payload["status"] == "ready_with_advisories"

def test_scheduled_view_labels_advisories_separately(...):
    assert "pipeline advisories:" in view.detail_panel.toPlainText()
```

- [ ] **Step 2: Run selected tests and confirm RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scheduled_evidence_pipeline_dry_run_wrapper.py tests/test_scheduled_evidence_status_service.py tests/test_ui_qt_evidence_review_dashboards.py -q -o addopts=`

Expected: failure because scheduled/UI models have no advisory state.

- [ ] **Step 3: Implement propagation and documentation**

```python
if pipeline_status == "ready_with_advisories":
    return "ready_with_advisories"
```

Update the UI and guides to define advisory, degraded, and failed semantics and retain the dry-run/evidence DB boundary.

- [ ] **Step 4: Re-run selected tests and confirm GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scheduled_evidence_pipeline_dry_run_wrapper.py tests/test_scheduled_evidence_status_service.py tests/test_ui_qt_evidence_review_dashboards.py -q -o addopts=`

Expected: all selected tests pass.

### Task 5: End-to-End Verification and Commit

**Files:**
- Modify: `docs/agents/shared_state/active_task.yaml`
- Modify: `docs/agents/shared_state/handoff_log.md`

- [ ] **Step 1: Run full relevant verification**

Run:
`./.venv/Scripts/python.exe -m pytest tests -k "evidence or scheduled" -q -o addopts=`
`./.venv/Scripts/python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
`./.venv/Scripts/python.exe scripts/qa_validate_update_tab.py`
`./.venv/Scripts/python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`

Expected: all applicable checks pass.

- [ ] **Step 2: Run the scheduled dry-run wrapper and readonly data audit**

Run: `cmd.exe /c "scripts\\scheduled\\run_evidence_pipeline_dry_run.cmd"`

Verify `ready_with_advisories`, report creation, `writes_evidence_db=false`, and unchanged evidence DB event count.

- [ ] **Step 3: Stage only task files and commit**

Run: `git add <reviewed task files>` then `git commit -m "fix: clarify evidence source quality advisories"`.

Expected: one commit containing only the evidence scheduler closeout and quality semantics changes.

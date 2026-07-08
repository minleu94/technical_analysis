# V3.0 Engineering Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V3.0 Evidence-Validated Decision System engineering candidate: read-only effectiveness projection, gap classifier, sample sufficiency / confidence labels, signal-alert-gate review scaffold, and manual validation report.

**Architecture:** Add a read-only application / presentation layer on top of existing Evidence Event, Forward Performance, Live Gap, Signal Decay, Decision Quality and Workbench sources. No task writes production evidence, enables scheduler, changes scoring, modifies portfolio state, places orders, or auto-applies lifecycle actions.

**Tech Stack:** Python dataclasses / existing SQLite read-only repository patterns / pytest / argparse JSON + Markdown output / PySide6 only if the dashboard slice is implemented.

## Global Constraints

- 使用繁體中文撰寫文件與 UI 文字。
- Production scheduler remains disabled: `production_scheduler_allowed=false`.
- Manual validation gaps must be represented as `PENDING_MANUAL_VALIDATION`, not treated as a reason to stop engineering work.
- No trading recommendation, auto trading, broker integration, portfolio mutation, strategy lifecycle mutation, or AI lifecycle action.
- No new bare `float` calculations in strategy, backtest, portfolio, risk, performance or benchmark core logic.
- No-look-ahead rule: any projection must use only decision-time evidence and already saved outcomes; no replay DB may be used as official Phase 0 evidence.
- Any UI-visible behavior change must update `docs/07_guides/APPLICATION_MANUAL.md`; any architecture boundary change must update `docs/01_architecture/system_architecture.md`.

---

## File Structure

- Create: `app_module/v3_effectiveness_dtos.py`
- Create: `app_module/v3_effectiveness_read_model.py`
- Create: `app_module/v3_gap_classifier.py`
- Create: `scripts/inspect_v3_evidence_effectiveness.py`
- Test: `tests/test_v3_effectiveness_read_model.py`
- Create: `app_module/v3_effectiveness_dashboard_service.py`
- Optional UI create: `ui_qt/views/v3_effectiveness_view.py`
- Optional UI create: `ui_qt/models/v3_effectiveness_table_models.py`
- Test: `tests/test_v3_effectiveness_dashboard_service.py`
- Optional UI test: `tests/test_ui_qt_v3_effectiveness_view.py`
- Create: `app_module/v3_effectiveness_review_scaffold.py`
- Create: `scripts/build_v3_effectiveness_review_scaffold.py`
- Test: `tests/test_v3_effectiveness_review_scaffold.py`
- Create: `scripts/inspect_v3_engineering_candidate_readiness.py`
- Create: `docs/06_qa/V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md`
- Modify after implementation only if needed: `docs/00_core/PROJECT_SNAPSHOT.md`, `docs/00_core/ROADMAP_6M_ENGINEERING.md`, `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`, `docs/01_architecture/system_architecture.md`, `docs/07_guides/APPLICATION_MANUAL.md`, `docs/00_core/DOCUMENTATION_INDEX.md`

## Task 1: V3 Effectiveness Read Model + Gap Classifier

**Files:**
- Create: `app_module/v3_effectiveness_dtos.py`
- Create: `app_module/v3_gap_classifier.py`
- Create: `app_module/v3_effectiveness_read_model.py`
- Create: `scripts/inspect_v3_evidence_effectiveness.py`
- Test: `tests/test_v3_effectiveness_read_model.py`

**Interfaces:**
- Consumes: existing read-only evidence summary rows, forward outcome maturity counts, source coverage diagnostics, live gap / signal decay / decision quality summaries.
- Produces:
  - `V3EffectivenessSlice.to_dict() -> dict[str, Any]`
  - `V3GapClassification.to_dict() -> dict[str, Any]`
  - `V3EffectivenessReadModel.build_report(...) -> V3EffectivenessReport`
  - `classify_v3_gap(code: str, *, source_trace: str | None = None) -> V3GapClassification`

- [ ] **Step 1: Write failing DTO and classifier tests**

```python
from app_module.v3_gap_classifier import classify_v3_gap
from app_module.v3_effectiveness_dtos import V3EffectivenessSlice


def test_v3_gap_classifier_marks_manual_validation_pending() -> None:
    gap = classify_v3_gap("manual_validation_missing", source_trace="docs/06_qa")

    assert gap.classification == "manual_validation_pending"
    assert gap.manual_validation_status == "PENDING_MANUAL_VALIDATION"
    assert gap.severity == "warning"


def test_effectiveness_slice_serializes_sufficiency_without_investment_claim() -> None:
    dto = V3EffectivenessSlice(
        slice_id="recommendation_included",
        event_family="recommendation",
        event_type="recommendation_included",
        source_type="persisted_recommendation",
        dashboard_surface="evidence_review",
        sample_count=18,
        ready_outcome_count=12,
        pending_outcome_count=6,
        missing_outcome_count=0,
        benchmark_coverage_bp=10000,
        industry_coverage_bp=500,
        sample_sufficiency_label="insufficient_sample",
        confidence_label="none",
        quality="DEGRADED",
        warnings=("sample_below_minimum",),
        limitations=("不是交易建議",),
    )

    payload = dto.to_dict()

    assert payload["sample_sufficiency_label"] == "insufficient_sample"
    assert payload["confidence_label"] == "none"
    assert "不是交易建議" in payload["limitations"]
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_read_model.py -q -o addopts=
```

Expected: FAIL because `app_module.v3_gap_classifier` and DTOs do not exist.

- [ ] **Step 3: Implement DTOs and deterministic classifier**

Implementation shape:

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class V3GapClassification:
    gap_code: str
    severity: str
    classification: str
    source_trace: str | None = None
    closeout_requirement: str = ""
    manual_validation_status: str = "NOT_REQUIRED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_code": self.gap_code,
            "severity": self.severity,
            "classification": self.classification,
            "source_trace": self.source_trace,
            "closeout_requirement": self.closeout_requirement,
            "manual_validation_status": self.manual_validation_status,
        }
```

Classifier mapping:

```python
GAP_RULES = {
    "source_missing_screening_matrix": ("warning", "payload_gap"),
    "missing_industry_benchmark": ("warning", "accepted_residual"),
    "forward_outcome_missing": ("blocking", "forward_outcome_gap"),
    "sample_below_minimum": ("warning", "sample_insufficiency"),
    "live_gap_missing": ("warning", "live_gap_missing"),
    "manual_validation_missing": ("warning", "manual_validation_pending"),
}
```

Manual validation gaps must set `manual_validation_status="PENDING_MANUAL_VALIDATION"`.

- [ ] **Step 4: Add read model tests using in-memory rows**

```python
from app_module.v3_effectiveness_read_model import V3EffectivenessReadModel


def test_read_model_labels_review_ready_when_sample_and_outcomes_sufficient() -> None:
    rows = [
        {
            "event_family": "portfolio_alert",
            "event_type": "portfolio_alert_triggered",
            "source_type": "daily_decision_snapshot",
            "ready_outcome_count": 80,
            "pending_outcome_count": 0,
            "missing_outcome_count": 0,
            "benchmark_coverage_bp": 10000,
            "industry_coverage_bp": 3500,
            "warnings": (),
        }
    ]

    report = V3EffectivenessReadModel(min_sample_size=30).build_report(rows=rows)

    first = report.slices[0]
    assert first.sample_sufficiency_label == "review_ready"
    assert first.confidence_label in {"low", "medium", "needs_manual_validation"}
    assert report.access_boundary["production_scheduler_allowed"] is False
```

- [ ] **Step 5: Implement minimal read model and CLI**

`V3EffectivenessReadModel` should:

- group supplied rows by event family / event type / source type;
- sum outcome counts;
- compute sample count as `ready + pending + missing`;
- label sample sufficiency:
  - `< min_sample_size`: `insufficient_sample`
  - `>= min_sample_size` with major warnings: `directional_only`
  - `>= min_sample_size` with manual validation missing: `needs_manual_validation`
  - otherwise: `review_ready`
- always include `access_boundary = {"mode": "read_only", "writes_allowed": False, "production_scheduler_allowed": False}`.

CLI options:

```text
--sample
--format json|markdown
--output PATH
--min-sample-size INT
```

For the first implementation, `--sample` is enough. Non-sample DB readers may be added only through explicit read-only path handling.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_read_model.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\v3_effectiveness_dtos.py app_module\v3_gap_classifier.py app_module\v3_effectiveness_read_model.py scripts\inspect_v3_evidence_effectiveness.py
```

Commit:

```powershell
git add app_module/v3_effectiveness_dtos.py app_module/v3_gap_classifier.py app_module/v3_effectiveness_read_model.py scripts/inspect_v3_evidence_effectiveness.py tests/test_v3_effectiveness_read_model.py
git commit -m "feat: add v3 effectiveness read model"
```

Rollback: remove the four new files and the focused test; no production data is changed.

## Task 2: Read-only Dashboard / CLI Disclosure Surface

**Files:**
- Create: `app_module/v3_effectiveness_dashboard_service.py`
- Optional create: `ui_qt/views/v3_effectiveness_view.py`
- Optional create: `ui_qt/models/v3_effectiveness_table_models.py`
- Test: `tests/test_v3_effectiveness_dashboard_service.py`
- Optional test: `tests/test_ui_qt_v3_effectiveness_view.py`

**Interfaces:**
- Consumes: `V3EffectivenessReport` from Task 1.
- Produces:
  - `V3EffectivenessDashboardService.build_dashboard(report: V3EffectivenessReport) -> V3EffectivenessDashboardDTO`
  - optional read-only Qt model with no repository or SQLite imports.

- [ ] **Step 1: Write dashboard service tests**

```python
from app_module.v3_effectiveness_dashboard_service import V3EffectivenessDashboardService
from app_module.v3_effectiveness_read_model import V3EffectivenessReadModel


def test_dashboard_discloses_read_only_and_sample_limitations() -> None:
    report = V3EffectivenessReadModel(min_sample_size=30).build_report(
        rows=[
            {
                "event_family": "watchlist",
                "event_type": "watchlist_trigger",
                "source_type": "daily_decision_snapshot",
                "ready_outcome_count": 4,
                "pending_outcome_count": 1,
                "missing_outcome_count": 0,
                "benchmark_coverage_bp": 10000,
                "industry_coverage_bp": 0,
                "warnings": ("sample_below_minimum",),
            }
        ]
    )

    dashboard = V3EffectivenessDashboardService().build_dashboard(report)
    payload = dashboard.to_dict()

    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["summary_cards"]["insufficient_sample_count"] == 1
    assert any("樣本不足" in item["disclosure"] for item in payload["rows"])
    assert "不是交易建議" in payload["boundary_banner"]
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_dashboard_service.py -q -o addopts=
```

Expected: FAIL with missing dashboard service.

- [ ] **Step 3: Implement dashboard service**

Minimum dashboard payload:

```python
@dataclass(frozen=True)
class V3EffectivenessDashboardDTO:
    boundary_banner: str
    summary_cards: Mapping[str, int | str]
    rows: tuple[V3EffectivenessDashboardRow, ...]
    access_boundary: Mapping[str, bool | str]
    warnings: tuple[str, ...]
```

Rows must include:

- event family / event type;
- sample count;
- sample sufficiency label;
- confidence label;
- gap classification summary;
- disclosure text.

Forbidden text in any dashboard row: `買進`, `賣出`, `保證`, `勝率保證`.

- [ ] **Step 4: Optional Qt disclosure surface**

If implementing UI, place it under existing Evidence Review or Workbench drill-down. Do not add a new top-level workspace.

Boundary test:

```python
from pathlib import Path


def test_v3_dashboard_ui_does_not_import_write_surfaces() -> None:
    path = Path("ui_qt/views/v3_effectiveness_view.py")
    text = path.read_text(encoding="utf-8")
    forbidden = ("sqlite3.connect", "EvidenceEventRepository", "ScoringEngine", "place_order", "register_scheduler")
    for token in forbidden:
        assert token not in text
```

- [ ] **Step 5: Verify and commit**

Run service tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_dashboard_service.py -q -o addopts=
```

If Qt UI changed, also run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Commit:

```powershell
git add app_module/v3_effectiveness_dashboard_service.py tests/test_v3_effectiveness_dashboard_service.py
git commit -m "feat: add v3 effectiveness disclosure surface"
```

Rollback: remove dashboard files and optional UI wiring; no schema or data migration exists.

## Task 3: Sample Sufficiency + Signal / Alert / Gate Review Scaffold

**Files:**
- Create: `app_module/v3_effectiveness_review_scaffold.py`
- Create: `scripts/build_v3_effectiveness_review_scaffold.py`
- Test: `tests/test_v3_effectiveness_review_scaffold.py`

**Interfaces:**
- Consumes: `V3EffectivenessReport` / `V3EffectivenessDashboardDTO`.
- Produces:
  - `V3ReviewScaffoldBuilder.build(report: V3EffectivenessReport) -> V3ReviewScaffold`
  - JSON / Markdown report with `PENDING_MANUAL_VALIDATION` items.

- [ ] **Step 1: Write scaffold tests**

```python
from app_module.v3_effectiveness_read_model import V3EffectivenessReadModel
from app_module.v3_effectiveness_review_scaffold import V3ReviewScaffoldBuilder


def test_scaffold_lists_signal_alert_gate_reviews_without_auto_action() -> None:
    report = V3EffectivenessReadModel(min_sample_size=30).build_report(
        rows=[
            {
                "event_family": "risk_prompt",
                "event_type": "liquidity_gate_excluded",
                "source_type": "negative_evidence",
                "ready_outcome_count": 34,
                "pending_outcome_count": 0,
                "missing_outcome_count": 0,
                "benchmark_coverage_bp": 10000,
                "industry_coverage_bp": 2000,
                "warnings": ("manual_validation_missing",),
            }
        ]
    )

    scaffold = V3ReviewScaffoldBuilder().build(report)
    first = scaffold.items[0]

    assert first.manual_validation_status == "PENDING_MANUAL_VALIDATION"
    assert first.apply_lifecycle_action is False
    assert first.auto_trading is False
    assert first.review_question
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_review_scaffold.py -q -o addopts=
```

Expected: FAIL with missing scaffold builder.

- [ ] **Step 3: Implement review scaffold**

Each scaffold item should include:

- `review_id`
- `event_family`
- `event_type`
- `review_category`: `signal`, `alert`, `gate`, `dashboard`
- `sample_sufficiency_label`
- `confidence_label`
- `review_question`
- `manual_validation_status`
- `apply_lifecycle_action=False`
- `auto_trading=False`
- `source_trace`

Review category mapping:

```python
CATEGORY_BY_FAMILY = {
    "recommendation": "signal",
    "watchlist": "signal",
    "portfolio_alert": "alert",
    "risk_prompt": "alert",
    "why_not": "gate",
    "liquidity": "gate",
    "screening_matrix": "gate",
    "decision_quality": "dashboard",
}
```

- [ ] **Step 4: Implement CLI**

`scripts/build_v3_effectiveness_review_scaffold.py`:

- supports `--sample`;
- supports `--format json|markdown`;
- supports `--output PATH`;
- emits `PENDING_MANUAL_VALIDATION` for every item requiring human review;
- never writes DB.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_review_scaffold.py tests/test_v3_effectiveness_read_model.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\v3_effectiveness_review_scaffold.py scripts\build_v3_effectiveness_review_scaffold.py
```

Commit:

```powershell
git add app_module/v3_effectiveness_review_scaffold.py scripts/build_v3_effectiveness_review_scaffold.py tests/test_v3_effectiveness_review_scaffold.py
git commit -m "feat: add v3 effectiveness review scaffold"
```

Rollback: remove scaffold files and tests; no existing modules are mutated.

## Task 4: Manual Validation Report + Candidate Readiness Inspector

**Files:**
- Create: `scripts/inspect_v3_engineering_candidate_readiness.py`
- Create: `docs/06_qa/V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md`
- Test: `tests/test_v3_engineering_candidate_readiness.py`
- Modify docs only after implementation if behavior/status changes: core Snapshot, Roadmap, Architecture, Manual, Index.

**Interfaces:**
- Consumes: outputs from Tasks 1-3.
- Produces:
  - JSON readiness status;
  - Markdown closeout report;
  - `V3_ENGINEERING_CANDIDATE_COMPLETE` only when engineering gates pass and manual validation is explicitly represented.

- [ ] **Step 1: Write readiness tests**

```python
import json
import subprocess
import sys


def test_v3_readiness_reports_pending_manual_validation_without_failure() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v3_engineering_candidate_readiness.py",
            "--sample",
            "--json-output",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)

    assert payload["active_milestone"] == "V3.0 engineering candidate"
    assert payload["manual_validation_status"] == "PENDING_MANUAL_VALIDATION"
    assert payload["production_scheduler_allowed"] is False
    assert payload["auto_trading"] is False
    assert payload["engineering_candidate_status"] in {"ready_for_manual_validation", "action_required"}
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_engineering_candidate_readiness.py -q -o addopts=
```

Expected: FAIL with missing readiness script.

- [ ] **Step 3: Implement readiness inspector**

CLI options:

```text
--sample
--json-output
--markdown
--report-output PATH
--manual-validation-status PENDING_MANUAL_VALIDATION|MANUAL_VALIDATION_READY|MANUAL_VALIDATION_ACCEPTED|MANUAL_VALIDATION_REJECTED
```

Readiness JSON must include:

- `active_milestone`
- `engineering_candidate_status`
- `manual_validation_status`
- `production_scheduler_allowed=false`
- `auto_trading=false`
- `scheduler_write_mode=false`
- `required_artifacts`
- `blocking_gaps`
- `warnings`
- `next_closeout_checks`

- [ ] **Step 4: Create manual validation report**

Report sections:

```markdown
# V3.0 Engineering Candidate Manual Validation Report

## Scope
## Engineering Artifacts
## Evidence Sources Reviewed
## Sample Sufficiency Summary
## Gap Classifier Summary
## Signal / Alert / Gate Review Items
## Manual Validation Status

- Overall: PENDING_MANUAL_VALIDATION

## Safety Boundary

- production_scheduler_allowed=false
- auto_trading=false
- lifecycle_action=false
- no investment effectiveness claim

## Pending Human Checks

| Check | Status | Required Human Action |
|---|---|---|
| Sample sufficiency threshold acceptance | PENDING_MANUAL_VALIDATION | Confirm thresholds are acceptable for V3 engineering candidate. |
| Signal / alert / gate review wording | PENDING_MANUAL_VALIDATION | Confirm no wording implies investment effectiveness. |
| Dashboard disclosure readability | PENDING_MANUAL_VALIDATION | Review UI / markdown output. |
```

- [ ] **Step 5: Documentation coverage after implementation**

If only CLI / QA docs are added, update `DOCUMENTATION_INDEX.md` if the artifacts should be daily referenced. If Qt UI or user-visible workflow changes, update:

- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/01_architecture/system_architecture.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`

Do not mark V3 complete unless the readiness inspector can produce the required status and manual validation state is explicit.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_engineering_candidate_readiness.py tests/test_v3_effectiveness_read_model.py tests/test_v3_effectiveness_review_scaffold.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile scripts\inspect_v3_engineering_candidate_readiness.py
git diff --check
```

Commit:

```powershell
git add scripts/inspect_v3_engineering_candidate_readiness.py tests/test_v3_engineering_candidate_readiness.py docs/06_qa/V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md
git commit -m "feat: add v3 engineering candidate readiness report"
```

Rollback: remove readiness script, report and test; no production data or scheduler state changes.

## Final Verification

Run the focused suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_read_model.py tests/test_v3_effectiveness_dashboard_service.py tests/test_v3_effectiveness_review_scaffold.py tests/test_v3_engineering_candidate_readiness.py -q -o addopts=
```

Run syntax checks:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\v3_effectiveness_dtos.py app_module\v3_gap_classifier.py app_module\v3_effectiveness_read_model.py app_module\v3_effectiveness_dashboard_service.py app_module\v3_effectiveness_review_scaffold.py scripts\inspect_v3_evidence_effectiveness.py scripts\build_v3_effectiveness_review_scaffold.py scripts\inspect_v3_engineering_candidate_readiness.py
```

Run mypy for touched app / script layers:

```powershell
.\.venv\Scripts\python.exe -m mypy app_module scripts
```

If Qt UI files were changed, run the mandatory UI gates:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Final status may be:

- `V3_ENGINEERING_CANDIDATE_COMPLETE`: engineering artifacts and tests complete; manual validation status is represented.
- `ready_for_manual_validation`: engineering artifacts complete, human review still `PENDING_MANUAL_VALIDATION`.
- `action_required`: missing artifacts, failing tests, or read-only boundary violation.

Never output V4/V5 readiness from this plan unless `V3_ENGINEERING_CANDIDATE_COMPLETE` is already present in latest version-loop evidence.

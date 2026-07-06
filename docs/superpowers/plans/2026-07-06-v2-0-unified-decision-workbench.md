# V2.0 Unified Decision Workbench Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 V2.0 Unified Decision Workbench Phase 1 read-only prototype：建立 Workbench DTO、唯讀 composer 與 standalone prototype artifact，讓第一屏呈現「今日任務中控台」，Evidence 作為 drill-down mode，Daily Checklist 作為每日流程檢查，不改 production UI、不寫正式 DB、不啟用 scheduler。

**Architecture:** 新增 app-layer read-only presentation boundary。`WorkbenchReadOnlyComposer` 只接收既有 DTO / report / sample payload 並轉成 `WorkbenchDashboardDTO`；CLI prototype 只產出 JSON / Markdown artifact。所有資料寫入、scheduler registration、broker/order API、ScoringEngine、推薦重算與 portfolio lifecycle action 都留在 Phase 1 scope 外。

**Tech Stack:** Python dataclasses / pytest / argparse / json / 現有 `DecisionDeskSnapshot` 與 `PreV2ReadinessReport`。

---

## File Structure

- Create: `app_module/workbench_dtos.py`
- Create: `app_module/workbench_read_only_composer.py`
- Create: `scripts/inspect_v2_workbench_prototype.py`
- Create: `tests/test_workbench_read_only_composer.py`
- Create: `tests/test_v2_workbench_prototype_cli.py`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Add QA closeout: `docs/06_qa/V2_0_WORKBENCH_PHASE1_CLOSEOUT_2026_07_06.md`

## Phase Boundary

- Phase 1 delivers a read-only prototype artifact and composer contract.
- Phase 1 does not add a Qt tab, top-level production navigation, scheduler button, approval workflow, DB migration, write repository, trading action, order API, position adjustment, strategy score change, backtest result change or external data ingestion.
- Phase 1 may use sample data in the CLI, but the sample must clearly mark itself as `sample_only`.
- If a later worker chooses to expose this inside Qt, that becomes an explicit scope change and must run the UI gates listed in this plan.

## Task 1: DTO Contract Tests

- [ ] Create `tests/test_workbench_read_only_composer.py`.
- [ ] Add tests for the DTO serialization contract before implementation.

Required test snippets:

```python
from datetime import date, datetime

from app_module.workbench_dtos import (
    WorkbenchAccessBoundary,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceSummary,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)


def test_workbench_dto_serializes_read_only_boundary() -> None:
    dto = WorkbenchDashboardDTO(
        as_of_date=date(2026, 7, 6),
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        source_mode="sample_only",
        access_boundary=WorkbenchAccessBoundary(),
        status_strip=(
            WorkbenchStatusItem(
                item_id="scheduler",
                label="Production Scheduler",
                value="off",
                status="blocked",
            ),
        ),
        review_items=(
            WorkbenchReviewItem(
                item_id="review-1",
                title="Portfolio alert review",
                severity="warning",
                source="portfolio_alert",
                summary="人工覆盤持倉警示。",
                drilldown_target="portfolio_review",
            ),
        ),
        evidence_summary=(
            WorkbenchEvidenceSummary(
                item_id="weekly_history",
                label="Weekly evidence history",
                status="waiting_for_time",
                summary="1/3 records observed.",
            ),
        ),
        market_context={"overall_quality": "observed"},
        portfolio_watchlist_summary={"portfolio_alert_count": 1},
        daily_checklist=(
            WorkbenchChecklistItem(
                item_id="freshness",
                label="資料 freshness",
                status="done",
                summary="Decision snapshot available.",
            ),
        ),
        warnings=("research_mode_only",),
    )

    payload = dto.to_dict()

    assert payload["access_boundary"]["mode"] == "read_only"
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert "place_order" in payload["access_boundary"]["denied_actions"]
    assert payload["status_strip"][0]["status"] == "blocked"
    assert payload["warnings"] == ["research_mode_only"]
```

- [ ] Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbench_read_only_composer.py -q -o addopts=
```

Expected: fails with missing `app_module.workbench_dtos`.

## Task 2: Implement Workbench DTOs

- [ ] Implement `app_module/workbench_dtos.py`.
- [ ] Use frozen dataclasses and `to_dict()` methods, matching existing `app_module/decision_desk_dtos.py` style.
- [ ] Normalize tuple/list/set warnings into tuples of strings.
- [ ] Include these dataclasses:
  - `WorkbenchAccessBoundary`
  - `WorkbenchStatusItem`
  - `WorkbenchReviewItem`
  - `WorkbenchEvidenceSummary`
  - `WorkbenchChecklistItem`
  - `WorkbenchDashboardDTO`

Core implementation shape:

```python
@dataclass(frozen=True)
class WorkbenchAccessBoundary:
    mode: str = "read_only"
    writes_allowed: bool = False
    production_scheduler_allowed: bool = False
    denied_actions: tuple[str, ...] = (
        "write_database",
        "register_scheduler",
        "place_order",
        "adjust_position",
        "apply_lifecycle_action",
        "recalculate_scoring",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "writes_allowed": self.writes_allowed,
            "production_scheduler_allowed": self.production_scheduler_allowed,
            "denied_actions": list(self.denied_actions),
        }
```

- [ ] Run DTO tests until GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbench_read_only_composer.py -q -o addopts=
```

Commit:

```powershell
git add app_module/workbench_dtos.py tests/test_workbench_read_only_composer.py
git commit -m "feat: add v2 workbench dto contract"
```

## Task 3: Composer Behavior Tests

- [ ] Extend `tests/test_workbench_read_only_composer.py` with sample builders for existing DTOs.
- [ ] Reuse existing field names from `DecisionDeskSnapshot` and `PreV2ReadinessReport`.

Required sample builder shape:

```python
from datetime import date, datetime

from app_module.decision_desk_dtos import (
    DecisionDeskActionSummary,
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    DecisionDeskSnapshot,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from app_module.pre_v2_readiness_service import (
    PreV2ReadinessItem,
    PreV2ReadinessReport,
    STATUS_READY,
    STATUS_WAITING_FOR_TIME,
)
from app_module.workbench_read_only_composer import WorkbenchReadOnlyComposer


def _decision_snapshot() -> DecisionDeskSnapshot:
    sample_date = date(2026, 7, 6)
    return DecisionDeskSnapshot(
        as_of_date=sample_date,
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        schema_version=1,
        overall_quality=DecisionDeskQuality.OBSERVED,
        market_regime=MarketRegimeSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            regime_label="risk-on",
            regime_confidence=8200,
        ),
        market_breadth=MarketBreadthSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            breadth_ratio_bp=6200,
            advancing=120,
            declining=80,
            unchanged=10,
        ),
        sector_rotation=SectorRotationSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            leading_sector="半導體",
            trailing_sector="金融",
            rotation_intensity_bp=150,
        ),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=("low_liquidity:9999",),
            top_strength_codes=("2330", "2454"),
            weak_strength_codes=("1101",),
            low_liquidity_codes=("9999",),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            trigger_count=1,
            triggered_codes=("2603",),
            top_signal="momentum_breakout",
        ),
        portfolio_alerts=PortfolioAlertSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            alert_count=1,
            alert_codes=("2330",),
            alert_level="high",
        ),
        risk_prompts=DecisionDeskRiskPromptSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            prompts=(
                DecisionDeskRiskPrompt(
                    category="portfolio",
                    severity="warning",
                    source="portfolio_alert",
                    code="2330",
                    title="Thesis invalidation review",
                    reason="持倉警示需要人工覆盤。",
                    action_hint="檢查 journal 與風險來源。",
                ),
            ),
        ),
        action_summary=DecisionDeskActionSummary(
            action_level="積極研究",
            headline="今日主結論：研究模式。",
            research_mode_note="研究模式：以下為市場與籌碼輔助判讀，不是交易建議。",
            reasons=("市場廣度偏強。",),
        ),
    )
```

Required behavior tests:

```python
def test_composer_keeps_scheduler_and_writes_off() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    assert dashboard.access_boundary.mode == "read_only"
    assert dashboard.access_boundary.writes_allowed is False
    assert dashboard.access_boundary.production_scheduler_allowed is False
    assert any(item.item_id == "scheduler" for item in dashboard.status_strip)
```

```python
def test_composer_builds_today_review_items_from_watchlist_portfolio_and_risk() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    payload = dashboard.to_dict()
    review_sources = {item["source"] for item in payload["review_items"]}

    assert {"watchlist_trigger", "portfolio_alert", "risk_prompt"}.issubset(review_sources)
    assert any(item["drilldown_target"] == "evidence_mode" for item in payload["review_items"])
```

```python
def test_composer_surfaces_waiting_for_time_as_evidence_gate_not_success() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    evidence = {item.item_id: item for item in dashboard.evidence_summary}

    assert evidence["weekly_history"].status == STATUS_WAITING_FOR_TIME
    assert "不能用單次 smoke 取代" in " ".join(dashboard.warnings)
```

```python
def test_composer_handles_missing_decision_snapshot_without_fabricating_ui_state() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=None,
        readiness_report=_readiness_report(),
        agent_report_sample=None,
    )

    assert dashboard.market_context["source_status"] == "missing"
    assert dashboard.portfolio_watchlist_summary["source_status"] == "missing"
    assert any(item.item_id == "decision_snapshot" for item in dashboard.status_strip)
```

- [ ] Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbench_read_only_composer.py -q -o addopts=
```

Expected: fails with missing `WorkbenchReadOnlyComposer`.

## Task 4: Implement Read-only Composer

- [ ] Implement `app_module/workbench_read_only_composer.py`.
- [ ] Composer constructor should take no writable repositories.
- [ ] `compose()` signature:

```python
def compose(
    self,
    *,
    decision_snapshot: DecisionDeskSnapshot | None,
    readiness_report: PreV2ReadinessReport,
    agent_report_sample: dict[str, Any] | None = None,
    source_mode: str = "read_only",
) -> WorkbenchDashboardDTO:
```

- [ ] Status strip must include:
  - `decision_snapshot`
  - `data_quality`
  - `evidence_gate`
  - `scheduler`
- [ ] Review items must include:
  - watchlist trigger summary when trigger count or triggered codes exist
  - portfolio alert summary when alert count or alert codes exist
  - risk prompts from `DecisionDeskRiskPromptSummary`
  - evidence/readiness blockers or waiting gates from `PreV2ReadinessReport`
- [ ] Evidence summary must map each readiness item into a `WorkbenchEvidenceSummary`.
- [ ] Market context must preserve `market_regime`, `market_breadth`, `sector_rotation`, `relative_strength_liquidity` quality and warning fields through `to_dict()`.
- [ ] Portfolio/watchlist summary must preserve watchlist trigger and portfolio alert summaries through `to_dict()`.
- [ ] Daily checklist must include:
  - decision snapshot freshness
  - evidence gate status
  - multi-day dry-run status
  - manual review note status as `manual_required`
  - scheduler-off confirmation
- [ ] Warnings must include:
  - research mode limitation
  - readiness limitations
  - agent report warnings
  - explicit sentence: `waiting_for_time 不能用單次 smoke 取代`
- [ ] Keep severity mapping deterministic:
  - `critical` stays `critical`
  - `warning` stays `warning`
  - `info` stays `info`
  - readiness `action_required` maps to `warning`
  - readiness `waiting_for_time` maps to `info`
  - scheduler boundary maps to `blocked`

Forbidden imports in this module:

```text
ScoringEngine
screening
broker
order
portfolio_module
backtest_module
strategy_lifecycle
```

- [ ] Run focused tests until GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbench_read_only_composer.py -q -o addopts=
```

Commit:

```powershell
git add app_module/workbench_read_only_composer.py tests/test_workbench_read_only_composer.py
git commit -m "feat: compose v2 workbench read-only dashboard"
```

## Task 5: Boundary Regression Tests

- [ ] Add import-boundary tests to `tests/test_workbench_read_only_composer.py`.

Required test:

```python
from pathlib import Path


def test_workbench_phase1_modules_do_not_import_write_or_trading_surfaces() -> None:
    forbidden = (
        "ScoringEngine",
        "screening_service",
        "broker",
        "place_order",
        "portfolio_module",
        "backtest_module",
        "strategy_lifecycle",
        "scheduler_registration",
    )
    files = (
        Path("app_module/workbench_dtos.py"),
        Path("app_module/workbench_read_only_composer.py"),
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    for token in forbidden:
        assert token not in combined
```

- [ ] Add language-boundary test:

```python
def test_workbench_payload_does_not_present_buy_sell_recommendations() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    rendered = str(dashboard.to_dict())

    assert "買進" not in rendered
    assert "賣出" not in rendered
    assert "不是交易建議" in rendered
```

- [ ] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbench_read_only_composer.py -q -o addopts=
```

Expected: all composer tests pass.

Commit:

```powershell
git add tests/test_workbench_read_only_composer.py
git commit -m "test: guard v2 workbench read-only boundary"
```

## Task 6: Prototype CLI Tests

- [ ] Create `tests/test_v2_workbench_prototype_cli.py`.
- [ ] Test JSON sample output.
- [ ] Test Markdown sample output.
- [ ] Test optional `--output` writes only the requested artifact path and does not touch evidence DB paths.

Required test snippets:

```python
import json
import subprocess
import sys
from pathlib import Path


def test_workbench_prototype_cli_outputs_sample_json() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)

    assert payload["source_mode"] == "sample_only"
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert payload["review_items"]
```

```python
def test_workbench_prototype_cli_outputs_markdown_boundary_text() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "markdown",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert "# V2.0 Unified Decision Workbench Prototype" in result.stdout
    assert "production_scheduler_allowed: `false`" in result.stdout
    assert "不是交易建議" in result.stdout
```

```python
def test_workbench_prototype_cli_writes_requested_output_only(tmp_path: Path) -> None:
    output_path = tmp_path / "workbench.json"
    untouched_db = tmp_path / "evidence.db"

    subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "json",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert output_path.exists()
    assert not untouched_db.exists()
```

- [ ] Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_workbench_prototype_cli.py -q -o addopts=
```

Expected: fails with missing script.

## Task 7: Implement Prototype CLI

- [ ] Implement `scripts/inspect_v2_workbench_prototype.py`.
- [ ] CLI options:
  - `--sample`: required for Phase 1 execution.
  - `--format json|markdown`: default `json`.
  - `--output PATH`: optional artifact destination.
- [ ] Reject non-sample execution with exit code `2` and message explaining that Phase 1 has no production DB reader.
- [ ] Build sample `DecisionDeskSnapshot`, `PreV2ReadinessReport` and agent report payload inside the script.
- [ ] Use `WorkbenchReadOnlyComposer().compose()` with the sample snapshot, readiness report and agent report payload created in the script; pass `source_mode="sample_only"`.
- [ ] JSON output should be `json.dumps(payload, ensure_ascii=False, indent=2)`.
- [ ] Markdown output should include:
  - title
  - source mode
  - generated timestamp
  - read-only boundary
  - status strip
  - 今日待判讀
  - Evidence mode summary
  - Daily checklist
  - limitations

Markdown renderer shape:

```python
def render_workbench_markdown(dashboard: WorkbenchDashboardDTO) -> str:
    payload = dashboard.to_dict()
    lines = [
        "# V2.0 Unified Decision Workbench Prototype",
        "",
        f"- source_mode: `{payload['source_mode']}`",
        f"- production_scheduler_allowed: `{str(payload['access_boundary']['production_scheduler_allowed']).lower()}`",
        f"- writes_allowed: `{str(payload['access_boundary']['writes_allowed']).lower()}`",
        "",
        "此 prototype 僅供 Phase 1 read-only design spike 使用，不是交易建議。",
    ]
    lines.extend(["", "## Status Strip", ""])
    for item in payload["status_strip"]:
        lines.append(f"- {item['label']}: `{item['status']}` - {item['value']}")
    lines.extend(["", "## 今日待判讀", ""])
    for item in payload["review_items"]:
        lines.append(f"- [{item['severity']}] {item['title']} ({item['source']}): {item['summary']}")
    lines.extend(["", "## Evidence Mode", ""])
    for item in payload["evidence_summary"]:
        lines.append(f"- {item['label']}: `{item['status']}` - {item['summary']}")
    lines.extend(["", "## Daily Checklist", ""])
    for item in payload["daily_checklist"]:
        lines.append(f"- {item['label']}: `{item['status']}` - {item['summary']}")
    if payload["warnings"]:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {warning}" for warning in payload["warnings"])
    return "\n".join(lines)
```

- [ ] Run CLI tests until GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_workbench_prototype_cli.py -q -o addopts=
```

Commit:

```powershell
git add scripts/inspect_v2_workbench_prototype.py tests/test_v2_workbench_prototype_cli.py
git commit -m "feat: add v2 workbench prototype cli"
```

## Task 8: Documentation Updates

- [ ] Update `docs/01_architecture/system_architecture.md`:
  - Add Workbench Phase 1 read-only presentation boundary.
  - Document data flow from existing DTO/report to composer to prototype artifact.
  - State no reverse call into writable repositories, scheduler or broker/order APIs.
- [ ] Update `docs/07_guides/APPLICATION_MANUAL.md`:
  - Add a developer/prototype section for `scripts/inspect_v2_workbench_prototype.py --sample`.
  - State JSON/Markdown output interpretation.
  - State safety limits: sample-only, read-only, scheduler off, no trading recommendation.
- [ ] Update `docs/00_core/PROJECT_SNAPSHOT.md`:
  - Mark V2.0 Phase 1 read-only prototype as available after implementation.
  - Keep Phase 0 evidence accumulation and Phase 5 scheduler gate language intact.
- [ ] Update `docs/00_core/DEVELOPMENT_ROADMAP.md`:
  - Add Phase 1 completion note for read-only prototype.
  - Do not mark Phase 2 MVP as complete.
- [ ] Update `docs/00_core/ROADMAP_6M_ENGINEERING.md`:
  - Mark only Phase 1 design/prototype slice as completed.
  - Keep Phase 0 gate evidence counts truthful; do not fabricate weekly or dry-run progress.
- [ ] Update `docs/00_core/DOCUMENTATION_INDEX.md`:
  - Add prototype CLI and closeout references.
- [ ] Add QA closeout `docs/06_qa/V2_0_WORKBENCH_PHASE1_CLOSEOUT_2026_07_06.md` with:
  - scope
  - changed files
  - command results
  - safety boundary
  - known remaining gates

Commit:

```powershell
git add docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/DEVELOPMENT_ROADMAP.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/DOCUMENTATION_INDEX.md docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md docs/06_qa/V2_0_WORKBENCH_PHASE1_CLOSEOUT_2026_07_06.md
git commit -m "docs: close out v2 workbench phase 1 prototype"
```

## Task 9: Verification

- [ ] Run focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbench_read_only_composer.py tests/test_v2_workbench_prototype_cli.py -q -o addopts=
```

Expected: all tests pass.

- [ ] Run syntax checks:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\workbench_dtos.py app_module\workbench_read_only_composer.py scripts\inspect_v2_workbench_prototype.py
```

Expected: command exits with code 0.

- [ ] Run quant guard linter because this feature touches decision-facing surfaces:

```powershell
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
```

Expected: command exits with code 0.

- [ ] Run type check for touched app/script areas:

```powershell
.\.venv\Scripts\python.exe -m mypy app_module scripts
```

Expected: command exits with code 0.

- [ ] If any Qt UI file is modified during execution, also run the mandatory UI gates:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: all commands exit with code 0.

## Task 10: Final Review And Branch Hygiene

- [ ] Inspect staged/uncommitted files:

```powershell
git status --short
```

Expected: only files from this plan are modified before commit; generated local artifacts and `.superpowers/` remain unstaged.

- [ ] Inspect final diff:

```powershell
git diff --check
git diff --stat
```

Expected: no whitespace errors; diff includes only Phase 1 prototype, tests, docs and QA closeout.

- [ ] Run sample CLI manually for final evidence:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --sample --format markdown
```

Expected output includes `# V2.0 Unified Decision Workbench Prototype`, `production_scheduler_allowed: false`, `writes_allowed: false`, `今日待判讀`, `Evidence mode` and `不是交易建議`.

- [ ] Commit any remaining intentional changes with a focused message.
- [ ] Final response should report:
  - commits created
  - verification commands and outcomes
  - whether Qt UI gates were required
  - remaining gates: Phase 0 evidence accumulation and Phase 5 scheduler approval

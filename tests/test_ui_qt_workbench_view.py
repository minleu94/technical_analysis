import os
import sys
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app_module.workbench_dtos import (
    WorkbenchAccessBoundary,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceSummary,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)
from ui_qt.models.workbench_table_models import WorkbenchEvidenceTableModel
from ui_qt.views.workbench_view import UnifiedDecisionWorkbenchView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def _dashboard_with_replay() -> WorkbenchDashboardDTO:
    return WorkbenchDashboardDTO(
        as_of_date=date(2026, 7, 6),
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        source_mode="read_only_sources_plus_historical_replay",
        access_boundary=WorkbenchAccessBoundary(),
        status_strip=(
            WorkbenchStatusItem(
                item_id="decision_snapshot",
                label="Daily Decision snapshot",
                value="2026-07-06",
                status="observed",
                summary="Read from WorkbenchSourceService.",
            ),
            WorkbenchStatusItem(
                item_id="evidence_gate",
                label="Evidence gate",
                value="waiting_for_time",
                status="info",
            ),
            WorkbenchStatusItem(
                item_id="scheduler",
                label="Production Scheduler",
                value="off",
                status="blocked",
                summary="production_scheduler_allowed=false",
            ),
        ),
        review_items=(
            WorkbenchReviewItem(
                item_id="watchlist_trigger",
                title="Watchlist trigger review",
                severity="warning",
                source="watchlist_trigger",
                summary="Human review required; no buy/sell recommendation is generated.",
                drilldown_target="evidence_mode",
                code="2603",
            ),
        ),
        evidence_summary=(
            WorkbenchEvidenceSummary(
                item_id="weekly_history",
                label="Weekly evidence operations history",
                status="waiting_for_time",
                summary="0/3 records observed.",
                diagnostics=("insufficient_weekly_history_records",),
            ),
            WorkbenchEvidenceSummary(
                item_id="historical_replay",
                label="Historical replay simulated evidence",
                status="degraded",
                summary=(
                    "118 days / 118056 events / 472224 outcomes; "
                    "source gap disclosed; payload gap disclosed; benchmark coverage disclosed."
                ),
                diagnostics=(
                    "simulated_scheduler",
                    "source_gap:source_missing_screening_matrix",
                    "payload_gap:missing_industry_benchmark",
                    "outcome_maturity:ready=380736,pending_future_data=91488",
                    "benchmark_coverage:covered=472224,total=472224,missing=0",
                    "missing_industry_benchmark:378491",
                    "pending_future_data:91488",
                    "phase0_gate_not_satisfied:weekly_history_and_multi_day_dry_run_require_real_time_accumulation",
                ),
            ),
        ),
        market_context={"source_status": "ready", "overall_quality": "observed"},
        portfolio_watchlist_summary={"source_status": "ready"},
        daily_checklist=(
            WorkbenchChecklistItem(
                item_id="weekly_history",
                label="Phase 0 weekly history",
                status="waiting_for_time",
                summary="0/3; must accumulate in real time.",
            ),
            WorkbenchChecklistItem(
                item_id="multi_day_dry_run",
                label="Multi-day dry-run",
                status="waiting_for_time",
                summary="1/3; replay cannot replace this gate.",
            ),
            WorkbenchChecklistItem(
                item_id="scheduler_off",
                label="Scheduler write-mode",
                status="blocked",
                summary="Production scheduler remains off.",
            ),
        ),
        warnings=(
            "historical_replay / simulated_scheduler only supports design review.",
            "replay does not satisfy Phase 0 weekly or multi-day gates.",
            "degraded_source:decision_desk_snapshot_db_missing",
        ),
    )


class _FakeWorkbenchSourceService:
    def __init__(self, dashboard: WorkbenchDashboardDTO) -> None:
        self.dashboard = dashboard
        self.calls: list[dict[str, object]] = []

    def inspect(self, **kwargs):
        self.calls.append(kwargs)
        return self.dashboard


def test_workbench_evidence_table_model_exposes_replay_diagnostics() -> None:
    app()
    replay = _dashboard_with_replay().evidence_summary[1]
    model = WorkbenchEvidenceTableModel((replay,))

    assert model.rowCount() == 1
    assert model.headerData(model.column_index("diagnostics"), Qt.Horizontal, Qt.DisplayRole) == "Diagnostics"
    diagnostics = model.data(model.index(0, model.column_index("diagnostics")))
    assert "simulated_scheduler" in diagnostics
    assert "pending_future_data:91488" in diagnostics
    assert model.raw_value(0, "diagnostics") == replay.diagnostics


def test_unified_workbench_view_renders_read_only_mvp_shell_and_replay_limits() -> None:
    app()
    view = UnifiedDecisionWorkbenchView(dashboard=_dashboard_with_replay(), auto_refresh=False)

    assert view.status_model.rowCount() == 3
    assert view.review_model.rowCount() == 1
    assert view.evidence_model.rowCount() == 2
    assert view.checklist_model.rowCount() == 3
    assert "read-only" in view.boundary_banner.text()
    assert "not trading advice" in view.boundary_banner.text()
    assert "recalculate scoring" in view.boundary_banner.text()
    assert "status strip" in view.status_section_title.text().lower()
    assert "today" in view.review_section_title.text().lower()
    assert "evidence mode" in view.evidence_section_title.text().lower()
    assert "daily checklist" in view.checklist_section_title.text().lower()

    data_quality_text = view.data_quality_limitations_label.text()
    assert "simulated_scheduler" in data_quality_text
    assert "source gap" in data_quality_text
    assert "payload gap" in data_quality_text
    assert "outcome maturity" in data_quality_text
    assert "benchmark coverage" in data_quality_text
    assert "missing industry benchmark" in data_quality_text
    assert "pending future-data" in data_quality_text
    assert "Phase 0 weekly history 0/3" in data_quality_text
    assert "multi-day dry-run 1/3" in data_quality_text
    assert "replay cannot replace" in data_quality_text
    assert "degraded_source" in view.warning_list.toPlainText()


def test_unified_workbench_view_refreshes_only_through_source_service() -> None:
    app()
    service = _FakeWorkbenchSourceService(_dashboard_with_replay())
    view = UnifiedDecisionWorkbenchView(
        source_service=service,
        decision_date="2026-07-06",
        replay_summary_json=Path("replay_summary.json"),
        auto_refresh=False,
    )

    view.refresh_dashboard()

    assert service.calls == [
        {
            "decision_date": "2026-07-06",
            "replay_summary_json": Path("replay_summary.json"),
        }
    ]
    assert view.evidence_model.rowCount() == 2


def test_workbench_view_does_not_import_db_scheduler_or_domain_calculation_modules() -> None:
    view_source = Path("ui_qt/views/workbench_view.py").read_text(encoding="utf-8")
    model_source = Path("ui_qt/models/workbench_table_models.py").read_text(encoding="utf-8")
    combined = view_source + "\n" + model_source
    blocked_patterns = [
        "sqlite3",
        "data_module.db_manager",
        "app_module.recommendation_service",
        "app_module.backtest_service",
        "app_module.portfolio_service",
        "decision_module.scoring_engine",
        "decision_module.stock_screener",
        "portfolio_module",
        "backtest_module",
        "runtime_scheduler",
        "QTimer",
    ]

    assert "app_module.workbench_dtos" in view_source
    assert "app_module.workbench_source_service" in view_source
    for pattern in blocked_patterns:
        assert pattern not in combined

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget

from app_module.decision_quality_dashboard_dtos import (
    DecisionQualityDashboardCards,
    DecisionQualityDashboardRequest,
    DecisionQualityDashboardResult,
)
from app_module.signal_decay_dashboard_dtos import (
    SignalDecayDashboardCards,
    SignalDecayDashboardRequest,
    SignalDecayDashboardResult,
)
from app_module.live_research_gap_dashboard_dtos import (
    LiveResearchGapDashboardCards,
    LiveResearchGapDashboardRequest,
    LiveResearchGapDashboardResult,
)
from ui_qt.models.signal_decay_table_model import SignalDecayTableModel
from ui_qt.views.decision_quality_view import DecisionQualityView
from ui_qt.views.evidence_review_view import EvidenceReviewView
from ui_qt.views.live_research_gap_view import LiveResearchGapView
from ui_qt.views.signal_decay_view import SignalDecayView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class FakeDashboard:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def load_dashboard(self, request):
        self.calls.append(request)
        return self.result


def test_signal_decay_table_model_formats_bp_without_changing_raw_value() -> None:
    app()
    from app_module.signal_decay_dashboard_dtos import SignalDecayDashboardRow

    row = SignalDecayDashboardRow(
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        sample_size_short=12,
        sample_size_long=40,
        forward_excess_short_bp=-700,
        forward_excess_long_bp=300,
        decay_score_bp=6500,
        decay_status="decaying",
        suggested_lifecycle_action="demote_candidate",
        confidence="medium",
        quality="degraded",
        warnings=("missing_industry_evidence",),
    )
    model = SignalDecayTableModel((row,))

    col = model.column_index("forward_excess_short_bp")
    assert model.data(model.index(0, col)) == "-7.00%"
    assert model.raw_value(0, "forward_excess_short_bp") == -700


def test_evidence_review_view_contains_four_read_only_tabs() -> None:
    app()
    view = EvidenceReviewView(
        forward_performance_widget=QTabWidget(),
        live_gap_service=FakeDashboard(LiveResearchGapDashboardResult(LiveResearchGapDashboardRequest(), LiveResearchGapDashboardCards())),
        signal_decay_service=FakeDashboard(SignalDecayDashboardResult(SignalDecayDashboardRequest(), SignalDecayDashboardCards())),
        decision_quality_service=FakeDashboard(DecisionQualityDashboardResult(DecisionQualityDashboardRequest(), DecisionQualityDashboardCards())),
    )

    labels = [view.tabs.tabText(index) for index in range(view.tabs.count())]
    assert labels == ["Forward Evidence", "Live vs Research Gap", "Signal Decay", "Decision Quality"]
    assert "不是買賣建議" in view.boundary_banner.text()


def test_dashboard_views_render_empty_states_and_ignore_stale_results() -> None:
    app()
    dq_service = FakeDashboard(
        DecisionQualityDashboardResult(
            DecisionQualityDashboardRequest(),
            DecisionQualityDashboardCards(),
            empty_state_message="尚無 decision quality review evidence。",
        )
    )
    dq_view = DecisionQualityView(dq_service, auto_refresh=False, async_refresh=False)
    dq_view.refresh_dashboard()
    assert "尚無 decision quality review evidence" in dq_view.empty_state_label.text()

    decay_service = FakeDashboard(
        SignalDecayDashboardResult(
            SignalDecayDashboardRequest(),
            SignalDecayDashboardCards(),
            empty_state_message="尚無 signal decay evidence。",
        )
    )
    decay_view = SignalDecayView(decay_service, auto_refresh=False, async_refresh=False)
    decay_view._active_request_id = 2
    decay_view._on_dashboard_loaded(decay_service.result, request_id=1)
    assert decay_view.table_model.rowCount() == 0
    decay_view._on_dashboard_loaded(decay_service.result, request_id=2)
    assert "尚無 signal decay evidence" in decay_view.empty_state_label.text()

    gap_service = FakeDashboard(
        LiveResearchGapDashboardResult(
            LiveResearchGapDashboardRequest(),
            LiveResearchGapDashboardCards(),
            empty_state_message="尚無 live research gap evidence。",
        )
    )
    gap_view = LiveResearchGapView(gap_service, auto_refresh=False, async_refresh=False)
    gap_view.refresh_dashboard()
    assert "尚無 live research gap evidence" in gap_view.empty_state_label.text()

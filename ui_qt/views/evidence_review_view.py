from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ui_qt.views.decision_quality_view import DecisionQualityView
from ui_qt.views.live_research_gap_view import LiveResearchGapView
from ui_qt.views.signal_decay_view import SignalDecayView
from ui_qt.widgets.evidence_boundary_banner import EvidenceBoundaryBanner


class EvidenceReviewView(QWidget):
    def __init__(
        self,
        *,
        forward_performance_widget: QWidget,
        live_gap_service,
        signal_decay_service,
        decision_quality_service,
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.boundary_banner = EvidenceBoundaryBanner("任何 demote / retire candidate 都只代表人工覆盤候選，不會自動執行。")
        layout.addWidget(self.boundary_banner)
        self.tabs = QTabWidget()
        self.tabs.addTab(forward_performance_widget, "Forward Evidence")
        self.tabs.addTab(LiveResearchGapView(live_gap_service, auto_refresh=False), "Live vs Research Gap")
        self.tabs.addTab(SignalDecayView(signal_decay_service, auto_refresh=False), "Signal Decay")
        self.tabs.addTab(DecisionQualityView(decision_quality_service, auto_refresh=False), "Decision Quality")
        layout.addWidget(self.tabs, stretch=1)

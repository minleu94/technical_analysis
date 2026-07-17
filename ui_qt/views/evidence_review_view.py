from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from ui_qt.views.decision_quality_view import DecisionQualityView
from ui_qt.views.evidence_operations_history_view import EvidenceOperationsHistoryView
from ui_qt.views.live_research_gap_view import LiveResearchGapView
from ui_qt.views.scheduled_evidence_status_view import ScheduledEvidenceStatusView
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
        evidence_history_service=None,
        scheduled_status_service=None,
        evidence_db_path: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.evidence_db_path = str(evidence_db_path or "").strip()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.boundary_banner = EvidenceBoundaryBanner("任何 demote / retire candidate 都只代表人工覆盤候選，不會自動執行。")
        layout.addWidget(self.boundary_banner)
        self._add_database_path_row(layout)
        self.tabs = QTabWidget()

        # 1. 今日決策
        today_decision_widget = QWidget()
        today_decision_layout = QVBoxLayout(today_decision_widget)
        today_decision_layout.setContentsMargins(0, 0, 0, 0)
        today_decision_tabs = QTabWidget()
        today_decision_tabs.addTab(DecisionQualityView(decision_quality_service, auto_refresh=False), "決策品質")
        if scheduled_status_service is not None:
            today_decision_tabs.addTab(ScheduledEvidenceStatusView(scheduled_status_service), "排程狀態")
        today_decision_layout.addWidget(today_decision_tabs)
        self.tabs.addTab(today_decision_widget, "今日決策")

        # 2. 歷史驗證
        historical_verification_widget = QWidget()
        historical_verification_layout = QVBoxLayout(historical_verification_widget)
        historical_verification_layout.setContentsMargins(0, 0, 0, 0)
        historical_verification_tabs = QTabWidget()
        historical_verification_tabs.addTab(forward_performance_widget, "前瞻證據")
        historical_verification_tabs.addTab(SignalDecayView(signal_decay_service, auto_refresh=False), "訊號衰退")
        if evidence_history_service is not None:
            historical_verification_tabs.addTab(EvidenceOperationsHistoryView(evidence_history_service, auto_refresh=False), "覆盤歷史")
        historical_verification_layout.addWidget(historical_verification_tabs)
        self.tabs.addTab(historical_verification_widget, "歷史驗證")

        # 3. 資料缺口
        data_gap_widget = QWidget()
        data_gap_layout = QVBoxLayout(data_gap_widget)
        data_gap_layout.setContentsMargins(0, 0, 0, 0)
        data_gap_layout.addWidget(LiveResearchGapView(live_gap_service, auto_refresh=False))
        self.tabs.addTab(data_gap_widget, "資料缺口")

        layout.addWidget(self.tabs, stretch=1)

    def _add_database_path_row(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        path_text = self.evidence_db_path or "未提供"
        self.evidence_db_path_label = QLabel(f"目前資料庫：{path_text}")
        self.evidence_db_path_label.setWordWrap(True)
        self.evidence_db_path_label.setTextInteractionFlags(self.evidence_db_path_label.textInteractionFlags() | Qt.TextSelectableByMouse)
        self.evidence_db_path_label.setStyleSheet(
            "padding: 6px; background: #172233; border: 1px solid #2B3A55; border-radius: 6px; color: #DDE7F0;"
        )
        row.addWidget(self.evidence_db_path_label, stretch=1)

        self.copy_db_path_button = QPushButton("複製路徑")
        self.copy_db_path_button.setEnabled(bool(self.evidence_db_path))
        self.copy_db_path_button.setToolTip("複製目前 Evidence Review 實際讀取的 SQLite 路徑")
        self.copy_db_path_button.clicked.connect(self._copy_database_path)
        row.addWidget(self.copy_db_path_button)
        layout.addLayout(row)

    def _copy_database_path(self) -> None:
        if self.evidence_db_path:
            QApplication.clipboard().setText(self.evidence_db_path)

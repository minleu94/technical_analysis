"""Lightweight research-session context strip."""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from app_module.research_session import ResearchSessionSnapshotDTO, ResearchSessionStore


class SessionContextStrip(QFrame):
    """Small status-bar widget showing shared research context."""

    def __init__(self, session_store: ResearchSessionStore, parent=None):
        super().__init__(parent)
        self.session_store = session_store
        self.setObjectName("SessionContextStrip")
        self.setFrameShape(QFrame.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(10)

        self.context_label = QLabel(self)
        self.context_label.setMinimumWidth(520)
        layout.addWidget(self.context_label)

        self.setStyleSheet(
            """
            QFrame#SessionContextStrip {
                border-left: 1px solid #5f6368;
                color: #d7dadf;
            }
            QLabel {
                color: #d7dadf;
                font-size: 11px;
            }
            """
        )

        self._unsubscribe = self.session_store.subscribe(self._render_snapshot)

    def _render_snapshot(self, snapshot: ResearchSessionSnapshotDTO) -> None:
        self.context_label.setText(
            "Session  |  "
            f"Symbol: {snapshot.active_symbol or '-'}  |  "
            f"Regime: {snapshot.active_regime or '-'}  |  "
            f"Profile: {snapshot.active_profile or '-'}  |  "
            f"Watchlist: {snapshot.selected_watchlist_id or '-'}"
        )

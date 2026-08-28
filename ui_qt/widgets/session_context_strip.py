"""Lightweight research-session context strip."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy

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
        # The status bar is present in every workspace.  A fixed 520 px
        # minimum here used to become the MainWindow minimum width after the
        # Runtime page was selected, making the requested 390 px viewport
        # impossible even though the left navigation had already collapsed.
        # Let the status bar yield space and elide the session text instead.
        self.context_label.setMinimumWidth(0)
        self.context_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.context_label)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

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

        self._full_context_text = ""
        self._unsubscribe = self.session_store.subscribe(self._render_snapshot)

    def _render_snapshot(self, snapshot: ResearchSessionSnapshotDTO) -> None:
        self._full_context_text = (
            "Session  |  "
            f"Symbol: {snapshot.active_symbol or '-'}  |  "
            f"Regime: {snapshot.active_regime or '-'}  |  "
            f"Profile: {snapshot.active_profile or '-'}  |  "
            f"Watchlist: {snapshot.selected_watchlist_id or '-'}"
        )
        self._apply_elided_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._apply_elided_text()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        # Keep the status bar's preferred width compact; the label expands
        # when desktop space is available and elides when it is not.
        return QSize(260, 18)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(0, 18)

    def _apply_elided_text(self) -> None:
        if not self._full_context_text:
            return
        available_width = max(0, self.context_label.width())
        if available_width <= 0:
            return
        metrics = QFontMetrics(self.context_label.font())
        text = metrics.elidedText(
            self._full_context_text,
            Qt.TextElideMode.ElideMiddle,
            available_width,
        )
        if self.context_label.text() != text:
            self.context_label.setText(text)

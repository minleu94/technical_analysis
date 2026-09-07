"""Lightweight research-session context strip."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy

from app_module.research_session import (
    ResearchSessionSnapshotDTO,
    ResearchSessionStore,
    ResearchStockContextDTO,
)


class SessionContextStrip(QFrame):
    """Small status-bar widget showing shared research context."""

    returnToSourceRequested = Signal(object)

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

        self.return_button = QPushButton("返回來源", self)
        self.return_button.setObjectName("ReturnToResearchSourceButton")
        self.return_button.setMinimumWidth(0)
        self.return_button.setToolTip("回到建立目前單股研究上下文的頁面")
        self.return_button.setAccessibleName("返回研究來源")
        self.return_button.clicked.connect(self._emit_return_to_source)
        # 沒有來源頁時不佔用 status bar 空間；有 source_workspace 才顯示可用動作。
        self.return_button.setVisible(False)
        layout.addWidget(self.return_button)
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
        self._current_snapshot = ResearchSessionSnapshotDTO()
        self._current_context: ResearchStockContextDTO | None = None
        self._unsubscribe = self.session_store.subscribe(self._render_snapshot)

    def _render_snapshot(self, snapshot: ResearchSessionSnapshotDTO) -> None:
        self._current_snapshot = snapshot
        context = snapshot.stock_context
        if context is None and snapshot.active_stock_code:
            # 允許舊 host 只填 snapshot 的扁平欄位，仍能呈現完整脈絡。
            context = ResearchStockContextDTO(
                stock_code=snapshot.active_stock_code,
                decision_date=snapshot.decision_date or "",
                data_date=snapshot.data_date or "",
                result_id=snapshot.result_id or "",
                profile_id=snapshot.profile_id or snapshot.active_profile or "",
                profile_version=snapshot.profile_version or "",
                source_id=snapshot.source_id or "",
                source_kind=snapshot.source_kind or "",
                source_label=snapshot.source_label or "",
                source_workspace=snapshot.source_workspace or "",
            )
        self._current_context = context
        if context is not None:
            source = context.source_label or context.source_id or "未標示"
            result = context.result_id or "未保存"
            profile = context.profile_id or snapshot.active_profile or "未標示"
            stock_label = f"{context.stock_code} {context.stock_name}".strip()
            self._full_context_text = (
                "研究上下文｜"
                f"股票：{stock_label}"
                f"｜決策日：{context.decision_date or '未標示'}"
                f"｜資料日：{context.data_date or '未標示'}"
                f"｜結果：{result}｜Profile：{profile}｜來源：{source}"
            )
        else:
            # 沒有單股上下文時仍保留原有全域 session 資訊，避免工作台空白。
            self._full_context_text = (
                "研究上下文｜"
                f"股票：{snapshot.active_symbol or '-'}｜"
                f"市場狀態：{snapshot.active_regime or '-'}｜"
                f"Profile：{snapshot.active_profile or '-'}｜"
                f"觀察清單：{snapshot.selected_watchlist_id or '-'}"
            )
        source_workspace = ""
        source_label = ""
        if context is not None:
            source_workspace = context.source_workspace
            source_label = context.source_label or context.source_id
        self.return_button.setVisible(bool(source_workspace))
        self.return_button.setEnabled(bool(source_workspace))
        if source_label:
            self.return_button.setToolTip(f"返回來源：{source_label}")
        self._apply_elided_text()

    def _emit_return_to_source(self) -> None:
        if self._current_snapshot.stock_context is not None:
            self.returnToSourceRequested.emit(self._current_snapshot)
        elif self._current_context is not None:
            self.returnToSourceRequested.emit(self._current_context)

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

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        unsubscribe = getattr(self, "_unsubscribe", None)
        if callable(unsubscribe):
            unsubscribe()
        super().closeEvent(event)

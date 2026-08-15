"""主工作區的自適應堆疊容器。"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStackedWidget, QWidget


class AdaptiveWorkspaceStack(QStackedWidget):
    """只讓目前可見的工作區決定主視窗的建議與最小尺寸。

    ``QStackedWidget`` 預設會把所有 child 的尺寸提示合併。baldr 的工作區各自
    有圖表、表格與設定面板，因此即使它們目前隱藏，也會把主視窗鎖在最大的
    child 尺寸。主 shell 只需要為目前工作區預留空間；切換工作區時再更新
    geometry，讓各工作區保留自己的可讀性限制。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.currentChanged.connect(self._refresh_geometry)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        current = self.currentWidget()
        if current is None:
            return super().sizeHint()
        return self._effective_hint(current, "sizeHint")

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        current = self.currentWidget()
        if current is None:
            return super().minimumSizeHint()
        return self._effective_hint(current, "minimumSizeHint")

    @staticmethod
    def _effective_hint(widget: QWidget, method_name: str) -> QSize:
        hinted = getattr(widget, method_name)()
        return hinted.expandedTo(widget.minimumSize())

    def _refresh_geometry(self, _index: int) -> None:
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None:
            parent.updateGeometry()

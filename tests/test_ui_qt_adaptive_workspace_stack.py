import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget

from ui_qt.widgets.adaptive_workspace_stack import AdaptiveWorkspaceStack


def app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class _SizedWorkspace(QWidget):
    def __init__(self, size: QSize) -> None:
        super().__init__()
        self._size = size

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self._size

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self._size


def test_active_workspace_alone_controls_stack_geometry_hints() -> None:
    app()
    compact = _SizedWorkspace(QSize(720, 520))
    oversized = _SizedWorkspace(QSize(1881, 1014))
    stack = AdaptiveWorkspaceStack()
    stack.addWidget(compact)
    stack.addWidget(oversized)

    stack.setCurrentWidget(compact)
    assert stack.minimumSizeHint() == QSize(720, 520)
    assert stack.sizeHint() == QSize(720, 520)

    stack.setCurrentWidget(oversized)
    assert stack.minimumSizeHint() == QSize(1881, 1014)
    assert stack.sizeHint() == QSize(1881, 1014)

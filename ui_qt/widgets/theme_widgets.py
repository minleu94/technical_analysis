from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui_qt.theme import MIDNIGHT_ANALYST


class StatusBadge(QLabel):
    def __init__(self, text: str = "", quality: str = "observed", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(22)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        self.setFont(font)
        self.set_quality(quality)

    def set_quality(self, quality: str) -> None:
        token = quality.lower()
        color = {
            "observed": MIDNIGHT_ANALYST.success,
            "estimated": MIDNIGHT_ANALYST.info,
            "degraded": MIDNIGHT_ANALYST.warning,
            "missing": MIDNIGHT_ANALYST.danger,
        }.get(token, MIDNIGHT_ANALYST.text_muted)
        self.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {color}; "
            f"border: 1px solid {color}; border-radius: {MIDNIGHT_ANALYST.radius_badge}px; "
            "padding: 2px 7px;"
        )


class SectionPanel(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("midnightSectionPanel")
        self.setStyleSheet(
            f"#midnightSectionPanel {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_primary}; font-weight: 700; font-size: 11pt;"
        )
        self.layout.addWidget(title_label)


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "N/A", parent=None):
        super().__init__(parent)
        self.setObjectName("midnightMetricCard")
        self.setStyleSheet(
            f"#midnightMetricCard {{ background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 9pt;")
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 15pt; font-weight: 700;"
        )
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)


class CompactCodeList(QLabel):
    def __init__(self, limit: int = 8, parent=None):
        super().__init__("", parent)
        self.limit = limit
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; line-height: 130%;")

    def set_groups(self, groups: Iterable[tuple[str, Sequence[str]]]) -> None:
        self.setText("\n".join(self._format_group(label, codes) for label, codes in groups))

    def _format_group(self, label: str, codes: Sequence[str]) -> str:
        items = [str(code) for code in codes if str(code)]
        if not items:
            return f"{label}：無"
        shown = items[: self.limit]
        suffix = f"（另 {len(items) - self.limit} 檔）" if len(items) > self.limit else ""
        return f"{label}：" + ", ".join(shown) + suffix


class WarningList(QLabel):
    def __init__(self, parent=None):
        super().__init__("無警示", parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 8px;"
        )

    def set_warnings(self, warnings: Sequence[str]) -> None:
        self.setText("\n".join(warnings) if warnings else "無警示")

    def toPlainText(self) -> str:
        return self.text()

    def setPlainText(self, text: str) -> None:
        self.setText(text)

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

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
            "ready": MIDNIGHT_ANALYST.success,
            "done": MIDNIGHT_ANALYST.success,
            "passed": MIDNIGHT_ANALYST.success,
            "estimated": MIDNIGHT_ANALYST.info,
            "info": MIDNIGHT_ANALYST.info,
            "manual_observed": MIDNIGHT_ANALYST.info,
            "degraded": MIDNIGHT_ANALYST.warning,
            "warning": MIDNIGHT_ANALYST.warning,
            "action_required": MIDNIGHT_ANALYST.warning,
            "manual_required": MIDNIGHT_ANALYST.warning,
            "waiting_for_time": MIDNIGHT_ANALYST.warning,
            "missing": MIDNIGHT_ANALYST.danger,
            "blocked": MIDNIGHT_ANALYST.danger,
            "critical": MIDNIGHT_ANALYST.danger,
            "off": MIDNIGHT_ANALYST.text_muted,
        }.get(token, MIDNIGHT_ANALYST.text_muted)
        self.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {color}; "
            f"border: 1px solid {color}; border-radius: {MIDNIGHT_ANALYST.radius_badge}px; "
            "padding: 2px 7px;"
        )


class SemanticChip(QLabel):
    def __init__(self, text: str, tone: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(False)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        colors = {
            "ready": (MIDNIGHT_ANALYST.success, "#0d2116"),
            "passed": (MIDNIGHT_ANALYST.success, "#0d2116"),
            "warning": (MIDNIGHT_ANALYST.warning, "#221a10"),
            "critical": (MIDNIGHT_ANALYST.danger, "#2a1114"),
            "blocked": (MIDNIGHT_ANALYST.danger, "#2a1114"),
            "info": (MIDNIGHT_ANALYST.info, "#0b1c27"),
            "manual_observed": (MIDNIGHT_ANALYST.info, "#0b1c27"),
            "read_only": (MIDNIGHT_ANALYST.text_muted, "#111827"),
            "neutral": (MIDNIGHT_ANALYST.text_muted, "#111827"),
        }
        fg, bg = colors.get(tone, colors["neutral"])
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; "
            f"border: 1px solid {fg}; border-radius: 4px; "
            "padding: 2px 6px; font-size: 10px; font-weight: 600;"
        )


class ClickableCard(QFrame):
    clicked = Signal(int)
    doubleClicked = Signal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("midnightClickableCard")
        self.setStyleSheet(
            f"#midnightClickableCard {{ background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
            f"#midnightClickableCard:hover {{ border: 1px solid {MIDNIGHT_ANALYST.accent}; }}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.index)
        super().mouseDoubleClickEvent(event)


class TimelineCard(ClickableCard):
    def __init__(self, index: int, step_num: int, title: str, summary: str, status_text: str, status_tone: str, details_text: str, chips: list[tuple[str, str]], parent=None):
        super().__init__(index, parent)
        self.setMinimumHeight(108)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        left_layout = QVBoxLayout()
        step_label = QLabel(f"{step_num:02d}")
        step_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_muted}; font-size: 14px; font-weight: 800;")
        status_badge = StatusBadge(status_text, status_tone)
        left_layout.addWidget(step_label)
        left_layout.addWidget(status_badge)
        left_layout.addStretch()
        top_layout.addLayout(left_layout)

        mid_layout = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 13px; font-weight: bold;")
        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 12px; line-height: 140%;")
        mid_layout.addWidget(title_label)
        mid_layout.addWidget(summary_label)
        mid_layout.addStretch()
        top_layout.addLayout(mid_layout, 1)

        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignTop | Qt.AlignRight)
        chip_layout = QHBoxLayout()
        chip_layout.setSpacing(4)
        for chip_text, chip_tone in chips:
            chip_layout.addWidget(SemanticChip(chip_text, chip_tone))
        chip_layout.addStretch()
        right_layout.addLayout(chip_layout)

        top_layout.addLayout(right_layout)
        layout.addWidget(top_row)

        if details_text:
            self.toggle_btn = QPushButton("展開細節")
            self.toggle_btn.setProperty("variant", "secondary")
            self.toggle_btn.setMinimumSize(96, 32)
            self.toggle_btn.clicked.connect(self._toggle_details)
            layout.addWidget(self.toggle_btn, 0, Qt.AlignRight)

        if details_text:
            self.details_label = QLabel(details_text)
            self.details_label.setWordWrap(True)
            self.details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.details_label.setStyleSheet(
                f"background: {MIDNIGHT_ANALYST.surface_1}; color: {MIDNIGHT_ANALYST.text_muted}; "
                f"border-top: 1px solid {MIDNIGHT_ANALYST.border}; padding: 10px; font-size: 11px; line-height: 140%; margin-top: 6px;"
            )
            self.details_label.setVisible(False)
            layout.addWidget(self.details_label)

    def _toggle_details(self):
        is_visible = self.details_label.isVisible()
        self.details_label.setVisible(not is_visible)
        self.toggle_btn.setText("收合細節" if not is_visible else "展開細節")


class StatusCard(ClickableCard):
    def __init__(self, index: int, title: str, summary: str, status_text: str, status_tone: str, parent=None):
        super().__init__(index, parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        badge = StatusBadge(status_text, status_tone)
        badge.setMinimumWidth(128)
        layout.addWidget(badge)

        mid_layout = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-weight: bold; font-size: 12px;")
        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 11px;")
        mid_layout.addWidget(title_label)
        mid_layout.addWidget(summary_label)
        layout.addLayout(mid_layout, 1)


class SectionPanel(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("midnightSectionPanel")
        self.setStyleSheet(
            f"#midnightSectionPanel {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-left: 4px solid {MIDNIGHT_ANALYST.accent}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_primary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border_subtle}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_badge}px; "
            "font-weight: 800; font-size: 11pt; padding: 5px 8px;"
        )
        self.layout.addWidget(title_label)


class CollapsibleSectionPanel(QFrame):
    def __init__(self, title: str, *, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self.setObjectName("midnightCollapsibleSectionPanel")
        self.setStyleSheet(
            f"#midnightCollapsibleSectionPanel {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-left: 4px solid {MIDNIGHT_ANALYST.info}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(6)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_primary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border_subtle}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_badge}px; "
            "font-weight: 800; font-size: 11pt; padding: 5px 8px;"
        )
        self.toggle_button = QPushButton("")
        self.toggle_button.setProperty("variant", "secondary")
        self.toggle_button.setFixedWidth(56)
        self.toggle_button.clicked.connect(self.toggle_collapsed)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.toggle_button)
        self.layout.addWidget(header)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)
        self.layout.addWidget(self.content_widget)
        self.set_collapsed(collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.content_widget.setVisible(not self._collapsed)
        self.toggle_button.setText("展開" if self._collapsed else "收合")


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
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.value_label.setWordWrap(True)
        self.value_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 15pt; font-weight: 700;"
        )
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label, 1)


class EmptyStatePanel(QFrame):
    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("midnightEmptyState")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet(
            f"#midnightEmptyState {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border: 1px dashed {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")

        self.body_label = QLabel(body)
        self.body_label.setWordWrap(True)
        self.body_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")

        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)


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


class WarningList(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)
        self.empty_label = QLabel("無警示")
        self.empty_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 10px;"
        )
        self.layout.addWidget(self.empty_label)
        self._warnings_text = ""

    def set_warnings(self, warnings: Sequence[str]) -> None:
        self._warnings_text = "\n".join(warnings) if warnings else ""
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is None or widget is self.empty_label:
                continue
            widget.deleteLater()

        if not warnings:
            self.empty_label.setText("無警示")
            self.empty_label.setVisible(True)
            self.layout.addWidget(self.empty_label)
            return

        self.empty_label.setVisible(False)
        groups = self._group_warnings(warnings)
        for group_name, items in groups.items():
            card = self._build_group_card(group_name, items)
            self.layout.addWidget(card)

    def _group_warnings(self, warnings: Sequence[str]) -> dict[str, list[str]]:
        groups = {
            "唯讀 / Phase Gate": [],
            "缺漏來源": [],
            "Replay / 模擬資料": [],
            "資料品質": [],
            "需要人工覆盤": [],
            "其他警示": []
        }
        for w in warnings:
            w_lower = w.lower()
            if "read-only" in w_lower or "phase gate" in w_lower or "not_production" in w_lower or "pre-v2" in w_lower or "readonly" in w_lower:
                groups["唯讀 / Phase Gate"].append(w)
            elif "missing" in w_lower or "缺漏" in w_lower or "缺口" in w_lower or "gap" in w_lower:
                groups["缺漏來源"].append(w)
            elif "replay" in w_lower or "simulated" in w_lower or "模擬" in w_lower:
                groups["Replay / 模擬資料"].append(w)
            elif "degraded" in w_lower or "quality" in w_lower or "降級" in w_lower:
                groups["資料品質"].append(w)
            elif "manual" in w_lower or "人工" in w_lower or "waiting" in w_lower or "等待" in w_lower:
                groups["需要人工覆盤"].append(w)
            else:
                groups["其他警示"].append(w)
        return {k: v for k, v in groups.items() if v}

    def _build_group_card(self, title: str, items: list[str]) -> QWidget:
        card = QFrame()
        card.setObjectName("warningGroupCard")
        is_critical = "缺漏來源" in title or "資料品質" in title
        border_color = MIDNIGHT_ANALYST.danger if is_critical else MIDNIGHT_ANALYST.warning
        bg_color = "#2a1114" if is_critical else "#221a10"

        card.setStyleSheet(
            f"#warningGroupCard {{ background: {bg_color}; "
            f"border: 1px solid {border_color}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)

        header_layout = QHBoxLayout()
        title_label = QLabel(f"{title} ({len(items)})")
        title_label.setStyleSheet(f"color: {border_color}; font-weight: bold; font-size: 13px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        shown = items[:3]
        for w in shown:
            w_label = QLabel(f"• {w}")
            w_label.setWordWrap(True)
            w_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 12px; line-height: 130%;")
            layout.addWidget(w_label)

        if len(items) > 3:
            hidden_text = "\n".join(f"• {w}" for w in items[3:])
            hidden_label = QLabel(hidden_text)
            hidden_label.setWordWrap(True)
            hidden_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 11px; line-height: 130%;")
            hidden_label.setVisible(False)
            layout.addWidget(hidden_label)

            toggle_btn = QPushButton(f"展開其餘 {len(items)-3} 項")
            toggle_btn.setProperty("variant", "secondary")
            toggle_btn.setFixedSize(120, 24)
            toggle_btn.clicked.connect(lambda _checked=False, lbl=hidden_label, btn=toggle_btn: self._toggle_warnings(lbl, btn))
            layout.addWidget(toggle_btn, 0, Qt.AlignLeft)

        return card

    def _toggle_warnings(self, label: QLabel, button: QPushButton):
        visible = label.isVisible()
        label.setVisible(not visible)
        if visible:
            count = len(label.text().strip().split("\n"))
            button.setText(f"展開其餘 {count} 項")
        else:
            button.setText("收合")

    def toPlainText(self) -> str:
        return self._warnings_text

    def setPlainText(self, text: str) -> None:
        self.set_warnings(text.split("\n") if text else [])

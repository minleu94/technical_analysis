from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ui_qt.theme import MIDNIGHT_ANALYST


_NAV_ICON_SVGS: dict[str, str] = {
    "command": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M12 4v4m0 8v4M4 12h4m8 0h4" />
            <circle cx="12" cy="12" r="3.2" />
            <circle cx="5" cy="5" r="2.2" />
            <circle cx="19" cy="5" r="2.2" />
            <circle cx="5" cy="19" r="2.2" />
            <circle cx="19" cy="19" r="2.2" />
            <path d="M6.7 6.7 9.8 9.8M17.3 6.7l-3.1 3.1M6.7 17.3l3.1-3.1M17.3 17.3l-3.1-3.1" />
        </svg>
    """,
    "radar": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="8.5" />
            <circle cx="12" cy="12" r="3" />
            <path d="M12 12 18 6" />
            <path d="M12 3.5v2M20.5 12h-2M12 20.5v-2M3.5 12h2" />
        </svg>
    """,
    "spark-list": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M8 7h11M8 12h11M8 17h7" />
            <path d="M4.5 5.5 5.2 7l1.6.7-1.6.7-.7 1.6-.7-1.6-1.6-.7 1.6-.7.7-1.5Z" />
        </svg>
    """,
    "replay": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M6 8a7 7 0 1 1 1 9.5" />
            <path d="M6 8V4H2" />
            <path d="M8 15l3-3 3 2 3-5" />
        </svg>
    """,
    "bookmark": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M7 4.5h10a1.5 1.5 0 0 1 1.5 1.5v14L12 16.2 5.5 20V6A1.5 1.5 0 0 1 7 4.5Z" />
        </svg>
    """,
    "briefcase": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M8.5 8V6.5A1.5 1.5 0 0 1 10 5h4a1.5 1.5 0 0 1 1.5 1.5V8" />
            <rect x="4" y="8" width="16" height="11" rx="2" />
            <path d="M4 12.5h16M10 12.5v1h4v-1" />
        </svg>
    """,
    "database-sync": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <ellipse cx="11" cy="6" rx="6.5" ry="2.5" />
            <path d="M4.5 6v5c0 1.4 2.9 2.5 6.5 2.5 1.3 0 2.6-.2 3.6-.5" />
            <path d="M4.5 11v5c0 1.4 2.9 2.5 6.5 2.5 1 0 1.9-.1 2.8-.3" />
            <path d="M17 13.5h3v-3M20 13.5a4.5 4.5 0 0 0-7.5-2" />
            <path d="M15 18.5h-3v3M12 18.5a4.5 4.5 0 0 0 7.5 2" />
        </svg>
    """,
    "pulse": """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M3 12h4l2-6 4 12 2-6h6" />
            <path d="M5 5.5a9 9 0 0 1 14 0M5 18.5a9 9 0 0 0 14 0" />
        </svg>
    """,
}


@dataclass(frozen=True)
class NavigationItem:
    key: str
    label: str
    icon: str = ""
    badge: str = ""
    tooltip: str = ""


class LeftNavigationWidget(QWidget):
    """Left-side main workspace navigation."""

    workspaceSelected = Signal(str)

    def __init__(self, items: Sequence[NavigationItem], parent=None) -> None:
        super().__init__(parent)
        self._items = tuple(items)
        self._buttons: dict[str, QPushButton] = {}
        self._current_key: str | None = None
        self._collapsed = False

        self.setObjectName("leftWorkspaceNavigation")
        self.setFixedWidth(184)
        self.setMaximumWidth(184)
        self.setStyleSheet(
            f"#leftWorkspaceNavigation {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border-right: 1px solid {MIDNIGHT_ANALYST.border}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(6)

        self.collapse_button = QPushButton("‹")
        self.collapse_button.setObjectName("leftNavCollapseButton")
        self.collapse_button.setToolTip("收合左側導覽")
        self.collapse_button.setMinimumHeight(30)
        self.collapse_button.clicked.connect(lambda _checked=False: self.set_collapsed(not self._collapsed))
        layout.addWidget(self.collapse_button)

        for item in self._items:
            button = QPushButton(self._button_text(item))
            button.setObjectName(f"leftNavButton_{item.key}")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(34)
            button.setIcon(self._icon_for_item(item))
            button.setIconSize(QSize(20, 20))
            button.setToolTip(item.tooltip or item.label)
            button.clicked.connect(lambda _checked=False, key=item.key: self._select_from_click(key))
            self._buttons[item.key] = button
            layout.addWidget(button)

        layout.addStretch()
        self._apply_styles()

    def item_keys(self) -> list[str]:
        return [item.key for item in self._items]

    def button_for_key(self, key: str) -> QPushButton | None:
        return self._buttons.get(key)

    def current_key(self) -> str | None:
        return self._current_key

    def label_for_key(self, key: str) -> str | None:
        for item in self._items:
            if item.key == key:
                return item.label
        return None

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        width = 58 if self._collapsed else 184
        self.setFixedWidth(width)
        self.setMaximumWidth(width)
        self.collapse_button.setText("›" if self._collapsed else "‹")
        self.collapse_button.setToolTip("展開左側導覽" if self._collapsed else "收合左側導覽")
        for item in self._items:
            button = self._buttons[item.key]
            button.setText(self._button_text(item))
            button.setIconSize(QSize(22, 22) if self._collapsed else QSize(20, 20))
            button.setToolTip(item.tooltip or item.label)

    def set_current_key(self, key: str) -> None:
        if key not in self._buttons:
            return
        self._current_key = key
        for item_key, button in self._buttons.items():
            is_active = item_key == key
            button.setChecked(is_active)
            button.setProperty("active", is_active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _select_from_click(self, key: str) -> None:
        self.set_current_key(key)
        self.workspaceSelected.emit(key)

    def _button_text(self, item: NavigationItem) -> str:
        if self._collapsed:
            return "" if item.icon in _NAV_ICON_SVGS else item.label[:1]
        pieces = []
        pieces.append(item.label)
        if item.badge:
            pieces.append(item.badge)
        return "  ".join(pieces)

    def _icon_for_item(self, item: NavigationItem) -> QIcon:
        svg = _NAV_ICON_SVGS.get(item.icon, "")
        if not svg:
            return QIcon()
        return _icon_from_svg(svg, MIDNIGHT_ANALYST.text_secondary)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            #leftWorkspaceNavigation {{
                background: {MIDNIGHT_ANALYST.surface_1};
                border-right: 1px solid {MIDNIGHT_ANALYST.border};
            }}
            QPushButton {{
                background: transparent;
                color: {MIDNIGHT_ANALYST.text_secondary};
                border: 1px solid transparent;
                border-radius: {MIDNIGHT_ANALYST.radius_panel}px;
                padding: 7px 10px;
                text-align: left;
                font-weight: 600;
            }}
            #leftNavCollapseButton {{
                color: {MIDNIGHT_ANALYST.text_muted};
                text-align: center;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {MIDNIGHT_ANALYST.surface_2};
                color: {MIDNIGHT_ANALYST.text_primary};
            }}
            QPushButton[active="true"] {{
                background: {MIDNIGHT_ANALYST.surface_3};
                color: {MIDNIGHT_ANALYST.text_primary};
                border: 1px solid {MIDNIGHT_ANALYST.accent};
            }}
            """
        )


def _icon_from_svg(svg_body: str, stroke_color: str) -> QIcon:
    svg = (
        svg_body.replace("<svg ", f'<svg fill="none" stroke="{stroke_color}" stroke-width="1.8" ')
        .replace("<path ", '<path stroke-linecap="round" stroke-linejoin="round" ')
        .replace("<circle ", '<circle stroke-linecap="round" stroke-linejoin="round" ')
        .replace("<rect ", '<rect stroke-linecap="round" stroke-linejoin="round" ')
        .replace("<ellipse ", '<ellipse stroke-linecap="round" stroke-linejoin="round" ')
    )
    pixmap = QPixmap()
    pixmap.loadFromData(svg.encode("utf-8"), "SVG")
    return QIcon(pixmap)

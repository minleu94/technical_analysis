from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ui_qt.theme import MIDNIGHT_ANALYST


@dataclass(frozen=True)
class NavigationItem:
    key: str
    label: str
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

        self.setObjectName("leftWorkspaceNavigation")
        self.setFixedWidth(184)
        self.setStyleSheet(
            f"#leftWorkspaceNavigation {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border-right: 1px solid {MIDNIGHT_ANALYST.border}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(6)

        for item in self._items:
            button = QPushButton(self._button_text(item))
            button.setObjectName(f"leftNavButton_{item.key}")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(34)
            button.setToolTip(item.tooltip)
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
        if item.badge:
            return f"{item.label}  {item.badge}"
        return item.label

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
                padding: 7px 9px;
                text-align: left;
                font-weight: 600;
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

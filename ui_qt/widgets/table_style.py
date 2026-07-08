from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from ui_qt.theme import MIDNIGHT_ANALYST


def apply_financial_table_style(table: QTableView) -> None:
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideRight)
    table.setCornerButtonEnabled(False)
    table.setShowGrid(True)
    table.setStyleSheet(
        f"""
        QTableView {{
            background: {MIDNIGHT_ANALYST.surface_1};
            alternate-background-color: {MIDNIGHT_ANALYST.surface_2};
            color: {MIDNIGHT_ANALYST.text_primary};
            gridline-color: {MIDNIGHT_ANALYST.border_subtle};
            border: 1px solid {MIDNIGHT_ANALYST.border};
            border-radius: {MIDNIGHT_ANALYST.radius_panel}px;
            selection-background-color: {MIDNIGHT_ANALYST.table_selected};
            selection-color: {MIDNIGHT_ANALYST.text_primary};
        }}
        QTableView::item {{
            padding: 5px 8px;
            border: 0;
        }}
        QTableView::item:hover {{
            background: {MIDNIGHT_ANALYST.table_hover};
        }}
        QHeaderView::section {{
            background: {MIDNIGHT_ANALYST.surface_2};
            color: {MIDNIGHT_ANALYST.text_secondary};
            padding: 6px 7px;
            border: 0;
            border-right: 1px solid {MIDNIGHT_ANALYST.border};
            border-bottom: 1px solid {MIDNIGHT_ANALYST.border};
            font-weight: 700;
        }}
        QTableCornerButton::section {{
            background: {MIDNIGHT_ANALYST.surface_2};
            border: 0;
            border-right: 1px solid {MIDNIGHT_ANALYST.border};
            border-bottom: 1px solid {MIDNIGHT_ANALYST.border};
        }}
        """
    )
    table.viewport().setStyleSheet(f"background: {MIDNIGHT_ANALYST.surface_1};")

    horizontal_header = table.horizontalHeader()
    horizontal_header.setHighlightSections(False)
    horizontal_header.setMinimumSectionSize(72)
    horizontal_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    horizontal_header.setStretchLastSection(True)

    vertical_header = table.verticalHeader()
    vertical_header.setDefaultSectionSize(30)
    vertical_header.setMinimumSectionSize(24)
    vertical_header.setHighlightSections(False)
    vertical_header.setStyleSheet(
        f"""
        QHeaderView::section {{
            background: {MIDNIGHT_ANALYST.surface_2};
            color: {MIDNIGHT_ANALYST.text_secondary};
            border: 0;
            border-right: 1px solid {MIDNIGHT_ANALYST.border};
            border-bottom: 1px solid {MIDNIGHT_ANALYST.border_subtle};
            padding: 4px;
        }}
        """
    )

    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

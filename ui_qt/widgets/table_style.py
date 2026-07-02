from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView


def apply_financial_table_style(table: QTableView) -> None:
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideRight)
    table.setCornerButtonEnabled(False)

    horizontal_header = table.horizontalHeader()
    horizontal_header.setHighlightSections(False)
    horizontal_header.setMinimumSectionSize(72)
    horizontal_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    vertical_header = table.verticalHeader()
    vertical_header.setDefaultSectionSize(30)
    vertical_header.setMinimumSectionSize(24)
    vertical_header.setHighlightSections(False)

    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

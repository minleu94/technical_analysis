from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app_module.workbench_dtos import (
    WorkbenchChecklistItem,
    WorkbenchEvidenceSummary,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)


ColumnSpec = tuple[tuple[str, str], ...]


class _WorkbenchTableModel(QAbstractTableModel):
    COLUMNS: ColumnSpec = ()

    def __init__(self, rows: Sequence[Any] = (), parent=None) -> None:
        super().__init__(parent)
        self._rows = tuple(rows)

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        field_name = self.COLUMNS[index.column()][0]
        return _display_value(getattr(self._rows[index.row()], field_name, None))

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.COLUMNS):
            return self.COLUMNS[section][1]
        return section + 1

    def column_index(self, field_name: str) -> int:
        for index, (column_field, _) in enumerate(self.COLUMNS):
            if column_field == field_name:
                return index
        raise KeyError(field_name)

    def raw_value(self, row: int, field_name: str):
        return getattr(self._rows[row], field_name)

    def row_at(self, row: int):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None


class WorkbenchStatusStripTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "Label"),
        ("value", "Value"),
        ("status", "Status"),
        ("summary", "Summary"),
    )

    def __init__(self, rows: Sequence[WorkbenchStatusItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchReviewQueueTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("severity", "Severity"),
        ("title", "Title"),
        ("source", "Source"),
        ("code", "Code"),
        ("summary", "Summary"),
        ("drilldown_target", "Drilldown"),
    )

    def __init__(self, rows: Sequence[WorkbenchReviewItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchEvidenceTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "Evidence"),
        ("status", "Status"),
        ("summary", "Summary"),
        ("diagnostics", "Diagnostics"),
    )

    def __init__(self, rows: Sequence[WorkbenchEvidenceSummary] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchChecklistTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "Checklist"),
        ("status", "Status"),
        ("summary", "Summary"),
    )

    def __init__(self, rows: Sequence[WorkbenchChecklistItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


def _display_value(value: object) -> str:
    if isinstance(value, tuple):
        return "; ".join(str(item) for item in value) or "None"
    if isinstance(value, list):
        return "; ".join(str(item) for item in value) or "None"
    if value is None:
        return ""
    return str(value)

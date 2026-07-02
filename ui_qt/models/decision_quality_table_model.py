from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app_module.decision_quality_dashboard_dtos import DecisionQualityDashboardRow


COLUMNS = (
    ("item_type", "項目類型"),
    ("symbol", "股票"),
    ("event_date", "事件日"),
    ("source_type", "來源"),
    ("severity", "嚴重度"),
    ("status", "狀態"),
    ("suggested_review_question", "覆盤問題"),
    ("reason_codes", "原因"),
    ("related_gap_id", "落差 ID"),
    ("related_decay_id", "衰退 ID"),
    ("quality", "品質"),
    ("warnings", "警告"),
)


class DecisionQualityTableModel(QAbstractTableModel):
    def __init__(self, rows: tuple[DecisionQualityDashboardRow, ...] = (), parent=None) -> None:
        super().__init__(parent)
        self._rows = tuple(rows)

    def set_rows(self, rows: tuple[DecisionQualityDashboardRow, ...]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        field_name = COLUMNS[index.column()][0]
        value = getattr(self._rows[index.row()], field_name)
        if role == Qt.DisplayRole:
            return _display_value(value)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(COLUMNS):
            return COLUMNS[section][1]
        return section + 1

    def column_index(self, field_name: str) -> int:
        for index, (column_field, _) in enumerate(COLUMNS):
            if column_field == field_name:
                return index
        raise KeyError(field_name)

    def raw_value(self, row: int, field_name: str):
        return getattr(self._rows[row], field_name)

    def row_at(self, row: int) -> DecisionQualityDashboardRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None


def _display_value(value) -> str:
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value) or "無"
    if value is None:
        return "無資料"
    return str(value)

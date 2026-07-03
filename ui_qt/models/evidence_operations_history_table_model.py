from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app_module.evidence_operations_history_dashboard_dtos import EvidenceOperationsHistoryDashboardRow


COLUMNS = (
    ("period_start", "開始日"),
    ("period_end", "結束日"),
    ("review_status", "覆盤狀態"),
    ("scheduler_readiness", "Scheduler readiness"),
    ("production_scheduler_allowed", "允許 production scheduler"),
    ("decision_quality_reviews_count", "決策覆盤"),
    ("signal_decay_observations_count", "訊號衰退"),
    ("manual_lifecycle_candidate_count", "人工候選"),
    ("warnings_count", "警告"),
    ("review_id", "紀錄 ID"),
)


class EvidenceOperationsHistoryTableModel(QAbstractTableModel):
    def __init__(self, rows: tuple[EvidenceOperationsHistoryDashboardRow, ...] = (), parent=None) -> None:
        super().__init__(parent)
        self._rows = tuple(rows)

    def set_rows(self, rows: tuple[EvidenceOperationsHistoryDashboardRow, ...]) -> None:
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

    def row_at(self, row: int) -> EvidenceOperationsHistoryDashboardRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None


def _display_value(value) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "無資料"
    return str(value)

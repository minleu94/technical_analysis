from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app_module.forward_performance_dashboard_service import format_bp_as_percent
from app_module.signal_decay_dashboard_dtos import SignalDecayDashboardRow


BP_COLUMNS = {
    "forward_excess_short_bp",
    "forward_excess_long_bp",
    "win_rate_short_bp",
    "win_rate_long_bp",
    "mae_short_bp",
    "mae_long_bp",
    "live_gap_short_bp",
    "live_gap_long_bp",
    "decay_score_bp",
}


COLUMNS = (
    ("signal_scope_type", "範圍類型"),
    ("signal_scope_id", "範圍 ID"),
    ("sample_size_short", "短窗樣本"),
    ("sample_size_long", "長窗樣本"),
    ("forward_excess_short_bp", "短窗超額"),
    ("forward_excess_long_bp", "長窗超額"),
    ("win_rate_short_bp", "短窗勝率"),
    ("win_rate_long_bp", "長窗勝率"),
    ("mae_short_bp", "短窗 MAE"),
    ("mae_long_bp", "長窗 MAE"),
    ("live_gap_short_bp", "短窗落差"),
    ("live_gap_long_bp", "長窗落差"),
    ("decay_score_bp", "衰退分數"),
    ("decay_status", "狀態"),
    ("suggested_lifecycle_action", "生命週期候選"),
    ("confidence", "信心"),
    ("quality", "品質"),
    ("warnings", "警告"),
)


class SignalDecayTableModel(QAbstractTableModel):
    def __init__(self, rows: tuple[SignalDecayDashboardRow, ...] = (), parent=None) -> None:
        super().__init__(parent)
        self._rows = tuple(rows)

    def set_rows(self, rows: tuple[SignalDecayDashboardRow, ...]) -> None:
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
            return self._display_value(field_name, value)
        if role == Qt.TextAlignmentRole and field_name not in {
            "signal_scope_type",
            "signal_scope_id",
            "decay_status",
            "suggested_lifecycle_action",
            "confidence",
            "quality",
            "warnings",
        }:
            return Qt.AlignRight | Qt.AlignVCenter
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

    def row_at(self, row: int) -> SignalDecayDashboardRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _display_value(self, field_name: str, value) -> str:
        if value is None:
            return "無資料"
        if field_name in BP_COLUMNS:
            return format_bp_as_percent(value)
        if isinstance(value, tuple):
            return ", ".join(str(item) for item in value) or "無"
        return str(value)

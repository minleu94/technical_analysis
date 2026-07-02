from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app_module.forward_performance_dashboard_dtos import ForwardPerformanceDashboardRow
from app_module.forward_performance_dashboard_service import format_bp_as_percent


BP_COLUMNS = {
    "mean_forward_return_bp",
    "median_forward_return_bp",
    "mean_benchmark_excess_bp",
    "median_benchmark_excess_bp",
    "mean_industry_excess_bp",
    "median_industry_excess_bp",
    "positive_rate_bp",
    "win_vs_benchmark_rate_bp",
    "win_vs_industry_rate_bp",
    "mean_mae_bp",
    "mean_mfe_bp",
}


COLUMNS = (
    ("group_key", "群組"),
    ("window_days", "觀察天數"),
    ("sample_size", "樣本數"),
    ("pending_count", "等待中"),
    ("missing_count", "缺失"),
    ("mean_forward_return_bp", "平均前瞻報酬"),
    ("median_forward_return_bp", "中位前瞻報酬"),
    ("mean_benchmark_excess_bp", "平均大盤超額"),
    ("median_benchmark_excess_bp", "中位大盤超額"),
    ("mean_industry_excess_bp", "平均產業超額"),
    ("median_industry_excess_bp", "中位產業超額"),
    ("positive_rate_bp", "正報酬率"),
    ("win_vs_benchmark_rate_bp", "勝大盤率"),
    ("win_vs_industry_rate_bp", "勝產業率"),
    ("mean_mae_bp", "平均 MAE"),
    ("mean_mfe_bp", "平均 MFE"),
    ("summary_status", "狀態"),
    ("first_event_date", "首筆事件日"),
    ("last_event_date", "末筆事件日"),
    ("quality_counts", "資料品質"),
    ("warning_counts", "警告"),
)


class ForwardPerformanceTableModel(QAbstractTableModel):
    def __init__(self, rows: tuple[ForwardPerformanceDashboardRow, ...] = (), parent=None):
        super().__init__(parent)
        self._rows = tuple(rows)

    def set_rows(self, rows: tuple[ForwardPerformanceDashboardRow, ...]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        field_name = COLUMNS[index.column()][0]
        value = getattr(self._rows[index.row()], field_name)
        if role == Qt.DisplayRole:
            return self._display_value(field_name, value)
        if role == Qt.TextAlignmentRole and field_name not in {"group_key", "summary_status", "quality_counts", "warning_counts"}:
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

    def row_at(self, row: int) -> ForwardPerformanceDashboardRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _display_value(self, field_name: str, value) -> str:
        if value is None:
            return "無資料"
        if field_name in BP_COLUMNS:
            return format_bp_as_percent(value)
        if isinstance(value, dict):
            return ", ".join(f"{key}:{value[key]}" for key in sorted(value)) or "無"
        return str(value)

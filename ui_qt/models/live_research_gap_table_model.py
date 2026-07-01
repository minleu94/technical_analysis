from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app_module.forward_performance_dashboard_service import format_bp_as_percent
from app_module.live_research_gap_dashboard_dtos import LiveResearchGapDashboardRow


BP_COLUMNS = {
    "portfolio_return_bp",
    "forward_evidence_return_bp",
    "benchmark_excess_bp",
    "gap_vs_research_bp",
    "gap_vs_forward_evidence_bp",
    "gap_vs_benchmark_bp",
}


COLUMNS = (
    ("symbol", "Symbol"),
    ("portfolio_mode", "Mode"),
    ("source_type", "Source"),
    ("source_id", "Source ID"),
    ("strategy_version_id", "Strategy"),
    ("entry_date", "Entry Date"),
    ("holding_days", "Holding Days"),
    ("portfolio_return_bp", "Portfolio Return"),
    ("forward_evidence_return_bp", "Forward Evidence"),
    ("benchmark_excess_bp", "Benchmark Excess"),
    ("gap_vs_research_bp", "Gap vs Research"),
    ("gap_vs_forward_evidence_bp", "Gap vs Forward"),
    ("gap_vs_benchmark_bp", "Gap vs Benchmark"),
    ("condition_status", "Condition"),
    ("chip_risk_level", "Chip Risk"),
    ("regime_at_entry", "Entry Regime"),
    ("regime_current", "Current Regime"),
    ("attribution_categories", "Attribution"),
    ("match_confidence", "Match"),
    ("quality", "Quality"),
    ("warnings", "Warnings"),
)


class LiveResearchGapTableModel(QAbstractTableModel):
    def __init__(self, rows: tuple[LiveResearchGapDashboardRow, ...] = (), parent=None) -> None:
        super().__init__(parent)
        self._rows = tuple(rows)

    def set_rows(self, rows: tuple[LiveResearchGapDashboardRow, ...]) -> None:
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
        if role == Qt.TextAlignmentRole and field_name in BP_COLUMNS | {"holding_days"}:
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

    def row_at(self, row: int) -> LiveResearchGapDashboardRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _display_value(self, field_name: str, value) -> str:
        if value is None:
            return "N/A"
        if field_name in BP_COLUMNS:
            return format_bp_as_percent(value)
        if isinstance(value, tuple):
            return ", ".join(str(item) for item in value) or "None"
        return str(value)

"""
Terminal Table Model
專門為 Smart Money Flow Scanner 設計的 QAbstractTableModel。
直接封裝 List[FlowSignalDTO]，不經過 DataFrame 轉換以保留強型別與自定義渲染所需的完整資料。
"""

from typing import List, Any
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from app_module.dtos.flow_signal_dtos import FlowSignalDTO

# 自定義 Role 用於傳遞特定結構給 Delegate
ROLE_INTENSITY = Qt.UserRole + 1
ROLE_SPARKLINE = Qt.UserRole + 2
ROLE_BADGES = Qt.UserRole + 3
ROLE_SCORE = Qt.UserRole + 4

class TerminalTableModel(QAbstractTableModel):
    def __init__(self, signals: List[FlowSignalDTO], parent=None):
        super().__init__(parent)
        self.signals = signals
        
        # 定義欄位 (Column) 映射
        self.headers = [
            "分數", "股票", "淨量", "集中度", "信號 (Badges)", "近期趨勢 (Trend)"
        ]
        
    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.signals)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self.signals)):
            return None
            
        signal = self.signals[index.row()]
        col = index.column()
        
        # -- 傳遞給 Delegate 的自定義 Role 資料 --
        if role == ROLE_INTENSITY:
            return signal.intensity_level
        if role == ROLE_SPARKLINE:
            return signal.sparkline_data
        if role == ROLE_BADGES:
            return signal.signal_tags
        if role == ROLE_SCORE:
            return signal.smart_money_score
            
        # -- 預設的字串顯示 --
        if role == Qt.DisplayRole:
            if col == 0:
                return f"{signal.smart_money_score:.1f}"
            elif col == 1:
                return f"{signal.stock_name} ({signal.stock_code})"
            elif col == 2:
                return f"{signal.aggregation.total_net_qty:,}"
            elif col == 3:
                return f"{signal.branch_concentration:.0%}"
            elif col == 4:
                return "" # 由 Delegate 繪製 Badges，不顯示字串
            elif col == 5:
                return "" # 由 Delegate 繪製 Sparkline，不顯示字串
                
        # -- 文字對齊 --
        if role == Qt.TextAlignmentRole:
            if col in [0, 2, 3]:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
            
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self.headers):
                return self.headers[section]
        return None
        
    def get_signal_at(self, row: int) -> FlowSignalDTO:
        if 0 <= row < len(self.signals):
            return self.signals[row]
        return None

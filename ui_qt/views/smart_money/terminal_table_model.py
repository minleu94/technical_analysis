"""
Terminal Table Model
專門為 Smart Money Flow Scanner 設計的 QAbstractTableModel。
直接封裝 List[FlowSignalDTO]，不經過 DataFrame 轉換以保留強型別與自定義渲染所需的完整資料。
已優化：支援欄位點擊排序與滑鼠懸浮 (ToolTip) 近期趨勢數值顯示。
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
            
        # -- 滑鼠懸浮提示 (ToolTip) --
        if role == Qt.ToolTipRole:
            if hasattr(signal, 'sparkline_details') and signal.sparkline_details:
                tooltip_lines = ["近期每日主力淨進出明細 (不分週期)："]
                for d, val in signal.sparkline_details:
                    sign = "+" if val > 0 else ""
                    tooltip_lines.append(f"• {d}: {sign}{val:+,}張")
                return "\n".join(tooltip_lines)
            
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

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        """實作點擊欄位標頭時的排序邏輯"""
        self.layoutAboutToBeChanged.emit()
        reverse = (order == Qt.DescendingOrder)
        
        if column == 0:    # 分數
            self.signals.sort(key=lambda x: x.smart_money_score, reverse=reverse)
        elif column == 1:  # 股票
            self.signals.sort(key=lambda x: (x.stock_code, x.stock_name), reverse=reverse)
        elif column == 2:  # 淨量
            self.signals.sort(key=lambda x: x.aggregation.total_net_qty, reverse=reverse)
        elif column == 3:  # 集中度
            self.signals.sort(key=lambda x: x.branch_concentration, reverse=reverse)
            
        self.layoutChanged.emit()


from app_module.dtos.broker_flow_dtos import BranchFlowAggregation
from collections import defaultdict

class BranchTrackerTableModel(QAbstractTableModel):
    """
    Branch Tracker Model: 讓 Branch 視角也能共用 TerminalScannerDelegate 渲染。
    動態將 BranchFlowAggregation 計算為 Intensity, Badges 與 Sparkline。
    """
    def __init__(self, aggregations: List[BranchFlowAggregation], parent=None):
        super().__init__(parent)
        # 依淨買賣超降序排序
        self.aggregations = sorted(aggregations, key=lambda x: x.total_net_qty, reverse=True)
        self.headers = ["淨量分數", "股票", "買進", "賣出", "信號 (Badges)", "近期趨勢 (Trend)"]
        
    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid(): return 0
        return len(self.aggregations)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid(): return 0
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self.aggregations)):
            return None
            
        agg = self.aggregations[index.row()]
        col = index.column()
        net = agg.total_net_qty
        
        # 動態計算 Intensity (-3 to 3)
        intensity = 0
        if net >= 1000: intensity = 3
        elif net >= 500: intensity = 2
        elif net >= 100: intensity = 1
        elif net <= -1000: intensity = -3
        elif net <= -500: intensity = -2
        elif net <= -100: intensity = -1
        
        if role == ROLE_INTENSITY:
            return intensity
            
        if role == ROLE_SPARKLINE:
            return agg.sparkline_data
            
        if role == ROLE_BADGES:
            return agg.sparkline_details # 這裡原先是手動計算的 tags，我們改用我們在 service 計算好且儲存在 DTO 的
            # 等等，先前 BranchTrackerTableModel 有自己計算 ROLE_BADGES:
            # badges = []
            # if net > 0: badges.append("BUY")
            # else: badges.append("SELL")
            # ...
            # 我們應該保留這個手動計算，或者在 service 做。原本的代碼：
            badges = []
            if net > 0: badges.append("買進 (BUY)")
            else: badges.append("賣出 (SELL)")
            if abs(net) >= 1000: badges.append("強大 (STRONG)")
            elif abs(net) >= 500: badges.append("中等 (MED)")
            return badges
            
        if role == ROLE_SCORE:
            return min(abs(net) / 10, 100.0)
            
        if role == Qt.DisplayRole:
            if col == 0:
                return f"{net:,}"
            elif col == 1:
                return f"{agg.stock_name} ({agg.stock_code})"
            elif col == 2:
                return f"{agg.total_buy_qty:,}"
            elif col == 3:
                return f"{agg.total_sell_qty:,}"
            elif col == 4:
                return ""
            elif col == 5:
                return ""
                
        if role == Qt.TextAlignmentRole:
            if col in [0, 2, 3]:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
            
        # -- 滑鼠懸浮提示 (ToolTip) --
        if role == Qt.ToolTipRole:
            if hasattr(agg, 'sparkline_details') and agg.sparkline_details:
                tooltip_lines = ["近期每日分點淨進出明細 (不分週期)："]
                for d, val in agg.sparkline_details:
                    sign = "+" if val > 0 else ""
                    tooltip_lines.append(f"• {d}: {sign}{val:+,}張")
                return "\n".join(tooltip_lines)
                    
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self.headers):
                return self.headers[section]
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        """實作分點追蹤表格點擊標頭排序"""
        self.layoutAboutToBeChanged.emit()
        reverse = (order == Qt.DescendingOrder)
        
        if column == 0:    # 淨量分數 (淨買賣超)
            self.aggregations.sort(key=lambda x: x.total_net_qty, reverse=reverse)
        elif column == 1:  # 股票
            self.aggregations.sort(key=lambda x: (x.stock_code, x.stock_name), reverse=reverse)
        elif column == 2:  # 買進
            self.aggregations.sort(key=lambda x: x.total_buy_qty, reverse=reverse)
        elif column == 3:  # 賣出
            self.aggregations.sort(key=lambda x: x.total_sell_qty, reverse=reverse)
            
        self.layoutChanged.emit()

"""
Pandas DataFrame 的 Qt Model
提供排序、欄位隱藏、filter/search 等功能
"""

from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex, Signal
from PySide6.QtGui import QColor
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any


class PandasTableModel(QAbstractTableModel):
    """Pandas DataFrame 的 Qt Model"""
    
    # 自定義信號
    dataChanged = Signal(QModelIndex, QModelIndex)  # 數據改變信號
    
    def __init__(self, dataframe: pd.DataFrame, parent=None):
        """初始化 Model
        
        Args:
            dataframe: 要顯示的 DataFrame
            parent: 父對象
        """
        super().__init__(parent)
        self._dataframe = dataframe.copy()
        self._original_dataframe = dataframe.copy()  # 保存原始數據用於重置
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder
        self._visible_columns = list(dataframe.columns)  # 可見欄位列表
    
    def rowCount(self, parent=QModelIndex()) -> int:
        """返回行數"""
        return len(self._dataframe)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        """返回列數（只計算可見欄位）"""
        return len(self._visible_columns)
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """返回指定索引的數據"""
        if not index.isValid():
            return None
        
        row = index.row()
        col = index.column()
        
        # 檢查索引範圍
        if row < 0 or row >= len(self._dataframe):
            return None
        if col < 0 or col >= len(self._visible_columns):
            return None
        
        try:
            col_name = self._visible_columns[col]
            
            # 檢查欄位是否存在
            if col_name not in self._dataframe.columns:
                return None
            
            value = self._dataframe.iloc[row, self._dataframe.columns.get_loc(col_name)]
            
            if role == Qt.DisplayRole:
                # 處理列表/數組類型（如 tags）
                if isinstance(value, (list, tuple, np.ndarray)):
                    if len(value) == 0:
                        return ""
                    # 將列表轉換為字符串
                    return ", ".join(str(v) for v in value)
                
                # 處理 NaN
                if pd.isna(value):
                    return ""
                
                # 格式化數值
                if isinstance(value, (int, float)):
                    # 如果是小數，保留2位
                    if isinstance(value, float) and abs(value) < 1000:
                        return f"{value:.2f}"
                    else:
                        return str(value)
                
                return str(value)
            
            elif role == Qt.TextAlignmentRole:
                # 對齊方式
                # 跳過列表/數組類型，避免布爾判斷錯誤
                if isinstance(value, (list, tuple, np.ndarray)):
                    return Qt.AlignLeft | Qt.AlignVCenter
                
                if isinstance(value, (int, float)):
                    try:
                        if not pd.isna(value):
                            return Qt.AlignRight | Qt.AlignVCenter
                    except (ValueError, TypeError):
                        pass
                return Qt.AlignLeft | Qt.AlignVCenter
            
            elif role == Qt.ForegroundRole:
                # 文字顏色（可根據數值正負設置顏色）
                # 跳過列表/數組類型，避免布爾判斷錯誤
                if isinstance(value, (list, tuple, np.ndarray)):
                    return None
                
                if isinstance(value, (int, float)):
                    try:
                        if not pd.isna(value):
                            if value > 0:
                                return QColor(0, 255, 136)  # 綠色（正數）
                            elif value < 0:
                                return QColor(255, 68, 68)   # 紅色（負數）
                    except (ValueError, TypeError):
                        pass
                
                return None
        except Exception as e:
            # 捕獲所有異常，避免程式崩潰
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"PandasTableModel.data 錯誤: {e}, row={row}, col={col}")
            return None
        
        return None
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        """返回表頭數據"""
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                # 返回欄位名稱
                if section < len(self._visible_columns):
                    return self._visible_columns[section]
            else:
                # 返回行號（從1開始）
                return str(section + 1)
        
        return None
    
    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        """排序"""
        if column < 0 or column >= len(self._visible_columns):
            return
        
        col_name = self._visible_columns[column]
        
        # 檢查欄位是否存在
        if col_name not in self._dataframe.columns:
            return
        
        self._sort_column = column
        self._sort_order = order
        
        # 執行排序
        ascending = (order == Qt.AscendingOrder)
        self._dataframe = self._dataframe.sort_values(
            by=col_name,
            ascending=ascending,
            na_position='last'
        ).reset_index(drop=True)
        
        # 發送數據改變信號
        self.layoutChanged.emit()
    
    def setDataFrame(self, dataframe: pd.DataFrame):
        """更新 DataFrame"""
        self.beginResetModel()
        self._dataframe = dataframe.copy()
        self._original_dataframe = dataframe.copy()
        # 保持可見欄位（如果新 DataFrame 有這些欄位）
        self._visible_columns = [col for col in self._visible_columns if col in dataframe.columns]
        if not self._visible_columns:
            self._visible_columns = list(dataframe.columns)
        self.endResetModel()
    
    def getDataFrame(self) -> pd.DataFrame:
        """獲取當前 DataFrame"""
        return self._dataframe.copy()
    
    def setVisibleColumns(self, columns: List[str]):
        """設置可見欄位"""
        # 只保留 DataFrame 中存在的欄位
        valid_columns = [col for col in columns if col in self._dataframe.columns]
        if valid_columns:
            self.beginResetModel()
            self._visible_columns = valid_columns
            self.endResetModel()
    
    def getVisibleColumns(self) -> List[str]:
        """獲取可見欄位列表"""
        return self._visible_columns.copy()
    
    def filter(self, column: str, value: str):
        """過濾數據（簡單的字符串匹配）"""
        if column not in self._dataframe.columns:
            return
        
        if not value:
            # 重置為原始數據
            self.setDataFrame(self._original_dataframe)
            return
        
        # 過濾
        mask = self._dataframe[column].astype(str).str.contains(value, case=False, na=False)
        filtered_df = self._original_dataframe[mask].copy()
        self.setDataFrame(filtered_df)
    
    def resetFilter(self):
        """重置過濾"""
        self.setDataFrame(self._original_dataframe)



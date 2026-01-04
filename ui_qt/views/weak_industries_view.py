"""
弱勢產業視圖
顯示弱勢產業列表（與強勢產業同架構，反向排名）
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableView, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
import pandas as pd
from typing import Optional

from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.screening_service import ScreeningService
from ui_qt.widgets.info_button import InfoButton


class WeakIndustriesView(QWidget):
    """弱勢產業視圖"""
    
    def __init__(self, screening_service: ScreeningService, parent=None):
        """初始化弱勢產業視圖
        
        Args:
            screening_service: 篩選服務實例
            parent: 父窗口
        """
        super().__init__(parent)
        self.screening_service = screening_service
        
        # 數據模型
        self.industries_model: Optional[PandasTableModel] = None
        
        # 數據緩存（避免重複計算）
        self._cached_data = {
            'day': None,  # 緩存本日的數據
            'week': None  # 緩存本周的數據
        }
        
        self._setup_ui()
        # 不自動計算，等待用戶點擊「載入數據」按鈕或切換到這個 tab
        self._show_empty_state()
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("弱勢產業")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("weak_industries", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)
        
        # 控制欄
        control_layout = QHBoxLayout()
        
        # 時間範圍選擇
        control_layout.addWidget(QLabel("時間範圍:"))
        self.period_btn_day = QPushButton("本日")
        self.period_btn_week = QPushButton("本周")
        self.period_btn_day.setCheckable(True)
        self.period_btn_week.setCheckable(True)
        self.period_btn_day.setChecked(True)
        self.period_btn_day.clicked.connect(lambda: self._on_period_changed('day'))
        self.period_btn_week.clicked.connect(lambda: self._on_period_changed('week'))
        control_layout.addWidget(self.period_btn_day)
        control_layout.addWidget(self.period_btn_week)
        
        control_layout.addStretch()
        
        # 載入數據按鈕（首次載入或強制重新計算）
        self.load_btn = QPushButton("載入數據")
        self.load_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.load_btn.clicked.connect(lambda: self._refresh_industries(use_cache=False))
        control_layout.addWidget(self.load_btn)
        
        # 刷新按鈕（強制重新計算，僅在有數據時顯示）
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setVisible(False)  # 初始隱藏
        self.refresh_btn.clicked.connect(lambda: self._refresh_industries(use_cache=False))
        control_layout.addWidget(self.refresh_btn)
        
        main_layout.addLayout(control_layout)
        
        # 表格
        self.industries_table = QTableView()
        self.industries_table.setAlternatingRowColors(True)
        self.industries_table.setSelectionBehavior(QTableView.SelectRows)
        self.industries_table.setSortingEnabled(True)
        self.industries_table.horizontalHeader().setStretchLastSection(True)
        main_layout.addWidget(self.industries_table)
    
    def _on_period_changed(self, period: str):
        """時間範圍改變"""
        if period == 'day':
            self.period_btn_week.setChecked(False)
        else:
            self.period_btn_day.setChecked(False)
        
        # 檢查緩存，如果有緩存就直接使用，不重新計算
        if self._cached_data[period] is not None:
            self._display_cached_data(period)
            self.refresh_btn.setVisible(True)
            self.load_btn.setVisible(False)
        else:
            self._show_empty_state()
            self.refresh_btn.setVisible(False)
            self.load_btn.setVisible(True)
    
    def _display_cached_data(self, period: str):
        """顯示緩存的數據（不重新計算）"""
        df = self._cached_data[period]
        if df is not None:
            self._update_table_with_data(df)
    
    def _update_table_with_data(self, df: pd.DataFrame):
        """更新表格顯示（內部方法，用於顯示數據）"""
        # 複製 DataFrame 以避免修改原始數據
        df = df.copy()
        
        # 重命名欄位以符合弱勢產業的語義
        if '漲幅%' in df.columns:
            # 將漲幅%轉換為跌幅%（弱勢產業的漲幅%通常是負數，取絕對值顯示為正數跌幅）
            df = df.rename(columns={'漲幅%': '跌幅%'})
            # 取絕對值，確保顯示為正數跌幅（因為弱勢產業的漲幅%是負數）
            if '跌幅%' in df.columns:
                df['跌幅%'] = df['跌幅%'].abs()
        
        # 確保欄位順序正確
        expected_columns = ['排名', '指數名稱', '收盤指數', '跌幅%']
        available_columns = [col for col in expected_columns if col in df.columns]
        if available_columns:
            df = df[available_columns]
        
        # 更新模型
        self.industries_model = PandasTableModel(df)
        self.industries_table.setModel(self.industries_model)
        
        # 調整列寬
        self.industries_table.resizeColumnsToContents()
    
    def _refresh_industries(self, use_cache: bool = True):
        """刷新弱勢產業數據
        
        Args:
            use_cache: 是否使用緩存（True=有緩存就不重新計算，False=強制重新計算）
        """
        try:
            # 獲取當前選擇的時間範圍
            period = 'day' if self.period_btn_day.isChecked() else 'week'
            
            # 檢查緩存
            if use_cache and self._cached_data[period] is not None:
                self._display_cached_data(period)
                return
            
            # 調用服務（重新計算）
            df = self.screening_service.get_weak_industries(period=period, top_n=50)
            
            # 檢查返回的 DataFrame
            if df is None or len(df) == 0:
                df = pd.DataFrame(columns=['排名', '指數名稱', '收盤指數', '漲幅%'])
                df.loc[0] = ['-', '沒有找到弱勢產業數據', 0, 0]
                # 重命名為跌幅%以保持一致性
                if '漲幅%' in df.columns:
                    df = df.rename(columns={'漲幅%': '跌幅%'})
            
            # 保存到緩存
            self._cached_data[period] = df.copy()
            
            # 更新表格顯示
            self._update_table_with_data(df)
            
            # 更新按鈕狀態
            self.refresh_btn.setVisible(True)
            self.load_btn.setVisible(False)
            
        except Exception as e:
            import traceback
            error_msg = f"刷新弱勢產業失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            QMessageBox.critical(self, "錯誤", error_msg)
            df = pd.DataFrame(columns=['排名', '指數名稱', '收盤指數', '跌幅%'])
            self.industries_model = PandasTableModel(df)
            self.industries_table.setModel(self.industries_model)
    
    def _show_empty_state(self):
        """顯示空狀態（提示用戶載入數據）"""
        df = pd.DataFrame(columns=['排名', '指數名稱', '收盤指數', '跌幅%'])
        df.loc[0] = ['-', '請點擊「載入數據」按鈕開始計算', 0, 0]
        self.industries_model = PandasTableModel(df)
        self.industries_table.setModel(self.industries_model)
        self.industries_table.resizeColumnsToContents()
    
    def load_data_if_needed(self):
        """如果需要，載入數據（當 tab 被點擊時調用）"""
        period = 'day' if self.period_btn_day.isChecked() else 'week'
        if self._cached_data[period] is None:
            self._show_empty_state()
            self.refresh_btn.setVisible(False)
            self.load_btn.setVisible(True)
        else:
            self._display_cached_data(period)
            self.refresh_btn.setVisible(True)
            self.load_btn.setVisible(False)


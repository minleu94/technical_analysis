"""
Dashboard 視圖
顯示強勢股、市場狀態、強勢產業
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableView, QFrame, QGroupBox,
    QTextEdit, QHeaderView
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
import pandas as pd

from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.screening_service import ScreeningService
from app_module.regime_service import RegimeService
from app_module.dtos import RegimeResultDTO


class DashboardView(QWidget):
    """Dashboard 主視圖"""
    
    # 自定義信號
    refreshRequested = Signal()  # 刷新請求
    
    def __init__(self, screening_service: ScreeningService, regime_service: RegimeService, parent=None):
        """初始化 Dashboard
        
        Args:
            screening_service: 篩選服務實例
            regime_service: 市場狀態服務實例
            parent: 父窗口
        """
        super().__init__(parent)
        self.screening_service = screening_service
        self.regime_service = regime_service
        
        # 數據模型
        self.strong_stocks_model: Optional[PandasTableModel] = None
        self.strong_industries_model: Optional[PandasTableModel] = None
        
        self._setup_ui()
        self._load_initial_data()
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 左側：強勢股表
        left_panel = self._create_stocks_panel()
        main_layout.addWidget(left_panel, 1)
        
        # 中間：市場狀態卡片
        center_panel = self._create_regime_panel()
        main_layout.addWidget(center_panel, 1)
        
        # 右側：強勢產業表
        right_panel = self._create_industries_panel()
        main_layout.addWidget(right_panel, 1)
    
    def _create_stocks_panel(self) -> QGroupBox:
        """創建強勢股面板"""
        panel = QGroupBox("強勢個股")
        layout = QVBoxLayout(panel)
        
        # 控制欄
        control_layout = QHBoxLayout()
        
        # 時間範圍選擇
        control_layout.addWidget(QLabel("時間範圍:"))
        self.stocks_period_btn_day = QPushButton("本日")
        self.stocks_period_btn_week = QPushButton("本周")
        self.stocks_period_btn_day.setCheckable(True)
        self.stocks_period_btn_week.setCheckable(True)
        self.stocks_period_btn_day.setChecked(True)
        self.stocks_period_btn_day.clicked.connect(lambda: self._on_stocks_period_changed('day'))
        self.stocks_period_btn_week.clicked.connect(lambda: self._on_stocks_period_changed('week'))
        control_layout.addWidget(self.stocks_period_btn_day)
        control_layout.addWidget(self.stocks_period_btn_week)
        
        control_layout.addStretch()
        
        # 刷新按鈕
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_stocks)
        control_layout.addWidget(refresh_btn)
        
        layout.addLayout(control_layout)
        
        # 表格
        self.stocks_table = QTableView()
        self.stocks_table.setAlternatingRowColors(True)
        self.stocks_table.setSelectionBehavior(QTableView.SelectRows)
        self.stocks_table.setSortingEnabled(True)
        self.stocks_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.stocks_table)
        
        return panel
    
    def _create_regime_panel(self) -> QGroupBox:
        """創建市場狀態面板"""
        panel = QGroupBox("大盤指數")
        layout = QVBoxLayout(panel)
        
        # 檢測按鈕
        detect_btn = QPushButton("檢測市場狀態")
        detect_btn.clicked.connect(self._detect_regime)
        layout.addWidget(detect_btn)
        
        # 狀態顯示
        self.regime_text = QTextEdit()
        self.regime_text.setReadOnly(True)
        self.regime_text.setMaximumHeight(300)
        self.regime_text.setPlaceholderText("點擊「檢測市場狀態」按鈕查看大盤信息")
        layout.addWidget(self.regime_text)
        
        layout.addStretch()
        
        return panel
    
    def _create_industries_panel(self) -> QGroupBox:
        """創建強勢產業面板"""
        panel = QGroupBox("產業指數")
        layout = QVBoxLayout(panel)
        
        # 控制欄
        control_layout = QHBoxLayout()
        
        # 時間範圍選擇
        control_layout.addWidget(QLabel("時間範圍:"))
        self.industries_period_btn_day = QPushButton("本日")
        self.industries_period_btn_week = QPushButton("本周")
        self.industries_period_btn_day.setCheckable(True)
        self.industries_period_btn_week.setCheckable(True)
        self.industries_period_btn_day.setChecked(True)
        self.industries_period_btn_day.clicked.connect(lambda: self._on_industries_period_changed('day'))
        self.industries_period_btn_week.clicked.connect(lambda: self._on_industries_period_changed('week'))
        control_layout.addWidget(self.industries_period_btn_day)
        control_layout.addWidget(self.industries_period_btn_week)
        
        control_layout.addStretch()
        
        # 刷新按鈕
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_industries)
        control_layout.addWidget(refresh_btn)
        
        layout.addLayout(control_layout)
        
        # 表格
        self.industries_table = QTableView()
        self.industries_table.setAlternatingRowColors(True)
        self.industries_table.setSelectionBehavior(QTableView.SelectRows)
        self.industries_table.setSortingEnabled(True)
        self.industries_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.industries_table)
        
        return panel
    
    def _load_initial_data(self):
        """載入初始數據"""
        self._refresh_stocks()
        self._refresh_industries()
    
    def _refresh_stocks(self):
        """刷新強勢股數據"""
        try:
            # 獲取當前選擇的時間範圍
            period = 'day' if self.stocks_period_btn_day.isChecked() else 'week'
            
            # 調用服務
            result = self.screening_service.get_strong_stocks(period=period, top_n=20)
            
            # 處理新的返回格式（元組：DataFrame, universe_count）
            if isinstance(result, tuple):
                df, universe_count = result
            else:
                # 向後兼容：如果返回的是舊格式（只有 DataFrame）
                df = result
            
            if len(df) == 0:
                # 顯示空表格
                df = pd.DataFrame(columns=['排名', '證券代號', '證券名稱', '收盤價', '漲幅%', '評分', '推薦理由'])
            
            # 更新模型
            self.strong_stocks_model = PandasTableModel(df)
            self.stocks_table.setModel(self.strong_stocks_model)
            
        except Exception as e:
            # TODO: 顯示錯誤提示
            print(f"刷新強勢股失敗: {e}")
    
    def _refresh_industries(self):
        """刷新強勢產業數據"""
        try:
            # 獲取當前選擇的時間範圍
            period = 'day' if self.industries_period_btn_day.isChecked() else 'week'
            
            # 調用服務
            df = self.screening_service.get_strong_industries(period=period, top_n=20)
            
            if len(df) == 0:
                # 顯示空表格
                df = pd.DataFrame(columns=['排名', '指數名稱', '收盤指數', '漲幅%'])
            
            # 更新模型
            self.strong_industries_model = PandasTableModel(df)
            self.industries_table.setModel(self.strong_industries_model)
            
        except Exception as e:
            # TODO: 顯示錯誤提示
            print(f"刷新強勢產業失敗: {e}")
    
    def _detect_regime(self):
        """檢測市場狀態"""
        try:
            regime_result: RegimeResultDTO = self.regime_service.detect_regime()
            
            # 格式化顯示
            text = f"市場狀態：{regime_result.regime_name_cn}\n"
            text += f"信心度：{regime_result.confidence:.0%}\n\n"
            text += "判斷依據：\n"
            
            # 將英文 key 轉換為中文
            key_map = {
                'close': '收盤價',
                'ma20': '20日均線',
                'ma60': '60日均線',
                'atr': '平均真實波幅(ATR)',
                'atr_convergence': 'ATR收斂',
                'price_near_range': '價格接近區間',
                'adx': 'ADX指標',
                'ma20_trend': 'MA20趨勢向上',
                'in_range': '價格在區間內',
            }
            
            for key, value in regime_result.details.items():
                if key != 'error' and key != 'default':
                    chinese_key = key_map.get(key, key)
                    if isinstance(value, bool):
                        chinese_value = '是' if value else '否'
                        text += f"  {chinese_key}：{chinese_value}\n"
                    elif isinstance(value, float):
                        text += f"  {chinese_key}：{value:.2f}\n"
                    else:
                        text += f"  {chinese_key}：{value}\n"
            
            self.regime_text.setPlainText(text)
            
        except Exception as e:
            self.regime_text.setPlainText(f"檢測失敗：{str(e)}")
    
    def _on_stocks_period_changed(self, period: str):
        """強勢股時間範圍改變"""
        if period == 'day':
            self.stocks_period_btn_week.setChecked(False)
        else:
            self.stocks_period_btn_day.setChecked(False)
        self._refresh_stocks()
    
    def _on_industries_period_changed(self, period: str):
        """強勢產業時間範圍改變"""
        if period == 'day':
            self.industries_period_btn_week.setChecked(False)
        else:
            self.industries_period_btn_day.setChecked(False)
        self._refresh_industries()



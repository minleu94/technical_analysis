"""
弱勢個股視圖
顯示弱勢股票列表（與強勢股同架構，反向排名）
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
from app_module.watchlist_service import WatchlistService
from ui_qt.widgets.info_button import InfoButton


class WeakStocksView(QWidget):
    """弱勢個股視圖"""
    
    def __init__(self, screening_service: ScreeningService, watchlist_service: WatchlistService = None, parent=None):
        """初始化弱勢個股視圖
        
        Args:
            screening_service: 篩選服務實例
            watchlist_service: 觀察清單服務實例（可選）
            parent: 父窗口
        """
        super().__init__(parent)
        self.screening_service = screening_service
        self.watchlist_service = watchlist_service
        
        # 數據模型
        self.stocks_model: Optional[PandasTableModel] = None
        
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
        title = QLabel("弱勢個股")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("weak_stocks", self)
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
        
        # Universe 顯示標籤
        self.universe_label = QLabel("Universe: -")
        self.universe_label.setStyleSheet("color: #666; font-size: 10px;")
        control_layout.addWidget(self.universe_label)
        
        # 加入觀察清單按鈕（僅在有數據時顯示）
        self.add_to_watchlist_btn = QPushButton("加入觀察清單")
        self.add_to_watchlist_btn.setVisible(False)  # 初始隱藏
        self.add_to_watchlist_btn.clicked.connect(self._add_selected_to_watchlist)
        if self.watchlist_service:
            control_layout.addWidget(self.add_to_watchlist_btn)
        
        # 載入數據按鈕（首次載入或強制重新計算）
        self.load_btn = QPushButton("載入數據")
        self.load_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.load_btn.clicked.connect(lambda: self._refresh_stocks(use_cache=False))
        control_layout.addWidget(self.load_btn)
        
        # 刷新按鈕（強制重新計算，僅在有數據時顯示）
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setVisible(False)  # 初始隱藏
        self.refresh_btn.clicked.connect(lambda: self._refresh_stocks(use_cache=False))
        control_layout.addWidget(self.refresh_btn)
        
        main_layout.addLayout(control_layout)
        
        # 表格
        self.stocks_table = QTableView()
        self.stocks_table.setAlternatingRowColors(True)
        self.stocks_table.setSelectionBehavior(QTableView.SelectRows)
        self.stocks_table.setSortingEnabled(True)
        self.stocks_table.horizontalHeader().setStretchLastSection(True)
        self.stocks_table.setWordWrap(True)
        main_layout.addWidget(self.stocks_table)
    
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
            if self.watchlist_service:
                self.add_to_watchlist_btn.setVisible(True)
        else:
            self._show_empty_state()
            self.refresh_btn.setVisible(False)
            self.load_btn.setVisible(True)
            if self.watchlist_service:
                self.add_to_watchlist_btn.setVisible(False)
    
    def _display_cached_data(self, period: str):
        """顯示緩存的數據（不重新計算）"""
        df = self._cached_data[period]
        if df is not None:
            self._update_table_with_data(df)
    
    def _update_table_with_data(self, df: pd.DataFrame):
        """更新表格顯示（內部方法，用於顯示數據）"""
        # 複製 DataFrame 以避免修改原始數據
        df = df.copy()
        
        # 重命名欄位以符合弱勢股的語義
        if '漲幅%' in df.columns:
            # 將漲幅%轉換為跌幅%（弱勢股的漲幅%通常是負數，取絕對值顯示為正數跌幅）
            df = df.rename(columns={'漲幅%': '跌幅%'})
            # 取絕對值，確保顯示為正數跌幅（因為弱勢股的漲幅%是負數）
            if '跌幅%' in df.columns:
                df['跌幅%'] = df['跌幅%'].abs()
        
        if '推薦理由' in df.columns:
            df = df.rename(columns={'推薦理由': '弱勢理由'})
        
        # 確保欄位順序正確
        expected_columns = ['排名', '證券代號', '證券名稱', '收盤價', '跌幅%', '評分', '弱勢理由']
        if '成交量變化率%' in df.columns and '成交量變化率%' not in expected_columns:
            idx = expected_columns.index('跌幅%') + 1
            expected_columns.insert(idx, '成交量變化率%')
        
        available_columns = [col for col in expected_columns if col in df.columns]
        for col in df.columns:
            if col not in available_columns:
                available_columns.append(col)
        
        if available_columns:
            df = df[available_columns]
        
        # 更新模型
        self.stocks_model = PandasTableModel(df)
        self.stocks_table.setModel(self.stocks_model)
        
        # 連接選擇事件
        if self.stocks_table.selectionModel():
            try:
                self.stocks_table.selectionModel().selectionChanged.disconnect()
            except:
                pass
            self.stocks_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        
        # 調整列寬
        self.stocks_table.resizeColumnsToContents()
        if '弱勢理由' in df.columns:
            reason_col_idx = list(df.columns).index('弱勢理由')
            self.stocks_table.setColumnWidth(reason_col_idx, 300)
    
    def _refresh_stocks(self, use_cache: bool = True):
        """刷新弱勢股數據
        
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
            result = self.screening_service.get_weak_stocks(period=period, top_n=50)
            
            # 處理新的返回格式（元組：DataFrame, universe_count）
            if isinstance(result, tuple):
                df, universe_count = result
            else:
                # 向後兼容：如果返回的是舊格式（只有 DataFrame）
                df = result
                universe_count = 0
            
            # 更新 Universe 顯示
            if universe_count > 0:
                self.universe_label.setText(f"Universe: {universe_count} stocks")
            else:
                self.universe_label.setText("Universe: -")
            
            # 檢查返回的 DataFrame
            if df is None:
                # 服務返回 None，可能是錯誤
                df = pd.DataFrame(columns=['排名', '證券代號', '證券名稱', '收盤價', '漲幅%', '成交量變化率%', '評分', '推薦理由'])
                df.loc[0] = ['-', '-', '服務返回空值，請檢查數據和日誌', 0, 0, 0, 0, '請確認技術指標數據是否已計算']
            elif len(df) == 0:
                # 返回空 DataFrame，沒有符合條件的股票
                df = pd.DataFrame(columns=['排名', '證券代號', '證券名稱', '收盤價', '漲幅%', '成交量變化率%', '評分', '推薦理由'])
                df.loc[0] = ['-', '-', '沒有找到符合條件的弱勢股', 0, 0, 0, 0, '請確認篩選條件或數據是否正確']
            
            # 保存到緩存
            self._cached_data[period] = df.copy()
            
            # 更新表格顯示
            self._update_table_with_data(df)
            
            # 更新按鈕狀態
            self.refresh_btn.setVisible(True)
            self.load_btn.setVisible(False)
            if self.watchlist_service:
                self.add_to_watchlist_btn.setVisible(True)
            
        except Exception as e:
            import traceback
            error_msg = f"刷新弱勢股失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            QMessageBox.critical(self, "錯誤", error_msg)
            df = pd.DataFrame(columns=['排名', '證券代號', '證券名稱', '收盤價', '跌幅%', '評分', '弱勢理由'])
            self.stocks_model = PandasTableModel(df)
            self.stocks_table.setModel(self.stocks_model)
    
    def _add_selected_to_watchlist(self):
        """將選中的股票加入觀察清單"""
        if not self.watchlist_service or not self.stocks_model:
            return
        
        selection = self.stocks_table.selectionModel().selectedRows()
        if not selection:
            QMessageBox.warning(self, "提示", "請先選擇要加入觀察清單的股票")
            return
        
        # 取得選中的股票
        df = self.stocks_model.getDataFrame()
        stocks = []
        for index in selection:
            row = index.row()
            if row < len(df):
                try:
                    # 使用更安全的方式獲取數據
                    row_data = df.iloc[row]
                    stock_code = row_data.get('證券代號') if '證券代號' in row_data.index else None
                    stock_name = row_data.get('證券名稱') if '證券名稱' in row_data.index else None
                    
                    # 處理 NaN 和 None
                    if stock_code is None or (isinstance(stock_code, float) and pd.isna(stock_code)):
                        continue
                    
                    stock_code = str(stock_code).strip()
                    if not stock_code or stock_code == '-' or stock_code == 'nan':
                        continue
                    
                    # 處理股票名稱
                    if stock_name is None or (isinstance(stock_name, float) and pd.isna(stock_name)):
                        stock_name = stock_code
                    else:
                        stock_name = str(stock_name).strip()
                        if not stock_name or stock_name == '-':
                            stock_name = stock_code
                    
                    stocks.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name
                    })
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"處理第 {row} 行股票數據時出錯: {e}")
                    continue
        
        if stocks:
            try:
                added_count = self.watchlist_service.add_stocks(stocks, source='market_watch')
                if added_count > 0:
                    QMessageBox.information(self, "成功", f"已將 {added_count} 檔股票加入觀察清單")
                else:
                    QMessageBox.warning(self, "提示", "選中的股票已在觀察清單中")
            except Exception as e:
                import traceback
                error_msg = f"加入觀察清單失敗：\n{str(e)}\n\n{traceback.format_exc()}"
                QMessageBox.critical(self, "錯誤", error_msg)
    
    def _on_selection_changed(self):
        """表格選擇改變"""
        pass
    
    def _show_empty_state(self):
        """顯示空狀態（提示用戶載入數據）"""
        df = pd.DataFrame(columns=['排名', '證券代號', '證券名稱', '收盤價', '跌幅%', '評分', '弱勢理由'])
        df.loc[0] = ['-', '-', '請點擊「載入數據」按鈕開始計算', 0, 0, 0, '']
        self.stocks_model = PandasTableModel(df)
        self.stocks_table.setModel(self.stocks_model)
        self.stocks_table.resizeColumnsToContents()
    
    def load_data_if_needed(self):
        """如果需要，載入數據（當 tab 被點擊時調用）"""
        period = 'day' if self.period_btn_day.isChecked() else 'week'
        if self._cached_data[period] is None:
            self._show_empty_state()
            self.refresh_btn.setVisible(False)
            self.load_btn.setVisible(True)
            if self.watchlist_service:
                self.add_to_watchlist_btn.setVisible(False)
        else:
            self._display_cached_data(period)
            self.refresh_btn.setVisible(True)
            self.load_btn.setVisible(False)
            if self.watchlist_service:
                self.add_to_watchlist_btn.setVisible(True)


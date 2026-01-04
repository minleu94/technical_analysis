"""
觀察清單視圖
管理跨 Tab 共用的股票觀察清單
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableView, QMessageBox, QDialog,
    QDialogButtonBox, QLineEdit, QTextEdit, QListWidget,
    QListWidgetItem, QHeaderView, QMenu, QAbstractItemView,
    QGroupBox, QSplitter
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QAction
import pandas as pd
from typing import List, Dict, Optional

from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.watchlist_service import WatchlistService
from app_module.universe_service import UniverseService
from ui_qt.widgets.info_button import InfoButton


class WatchlistView(QWidget):
    """觀察清單視圖"""
    
    # 信號：當觀察清單更新時發出
    watchlistUpdated = Signal()
    
    def __init__(self, watchlist_service: WatchlistService, config=None, parent=None):
        """初始化觀察清單視圖
        
        Args:
            watchlist_service: 觀察清單服務實例
            config: TWStockConfig 實例（用於初始化 UniverseService）
            parent: 父窗口
        """
        print("[WatchlistView] 開始初始化...")
        super().__init__(parent)
        print("[WatchlistView] 父類初始化完成")
        
        self.watchlist_service = watchlist_service
        self.config = config
        print("[WatchlistView] watchlist_service 設置完成")
        
        # 初始化選股清單服務（用於回測）
        if config:
            try:
                self.universe_service = UniverseService(config)
                print("[WatchlistView] universe_service 初始化成功")
            except Exception as e:
                print(f"[WatchlistView] 警告：universe_service 初始化失敗: {e}")
                self.universe_service = None
        else:
            self.universe_service = None
        
        # 數據模型
        self.stocks_model: Optional[PandasTableModel] = None
        
        print("[WatchlistView] 開始設置 UI...")
        self._setup_ui()
        print("[WatchlistView] UI 設置完成")
        
        # 延遲載入觀察清單，避免初始化時出錯導致整個程式崩潰
        print("[WatchlistView] 開始載入觀察清單...")
        try:
            self._load_watchlist()
            print("[WatchlistView] 觀察清單載入成功")
        except Exception as e:
            import traceback
            print(f"[WatchlistView] 錯誤：初始化時載入觀察清單失敗")
            print(f"[WatchlistView] 錯誤類型: {type(e).__name__}")
            print(f"[WatchlistView] 錯誤訊息: {str(e)}")
            print(f"[WatchlistView] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            # 顯示空表格，不阻止程式啟動
            try:
                df = pd.DataFrame(columns=['證券代號', '證券名稱', '加入時間', '來源', '備註'])
                df.loc[0] = ['-', '-', '-', '-', '載入失敗，請檢查數據文件']
                self.stocks_model = PandasTableModel(df)
                self.stocks_table.setModel(self.stocks_model)
                self.stats_label.setText("共 0 檔股票（載入失敗）")
                print("[WatchlistView] 已顯示錯誤提示")
            except Exception as e2:
                print(f"[WatchlistView] 顯示錯誤提示時也失敗: {e2}")
        
        print("[WatchlistView] 初始化完成")
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("觀察清單")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("watchlist", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)
        
        # 使用垂直 Splitter 分割主要工作區和管理區
        main_splitter = QSplitter(Qt.Vertical)
        
        # ========== 上方：主要工作區（60-70%高度）==========
        # 觀察清單表格（主要工作區）
        work_area_widget = QWidget()
        work_area_layout = QVBoxLayout(work_area_widget)
        work_area_layout.setSpacing(5)
        work_area_layout.setContentsMargins(0, 0, 0, 0)
        
        # 工作區標題（小標題）
        work_title = QLabel("觀察清單")
        work_title_font = QFont()
        work_title_font.setPointSize(11)
        work_title_font.setBold(True)
        work_title.setFont(work_title_font)
        work_area_layout.addWidget(work_title)
        
        # 表格（主要內容，佔用大部分空間）
        self.stocks_table = QTableView()
        self.stocks_table.setAlternatingRowColors(True)
        self.stocks_table.setSelectionBehavior(QTableView.SelectRows)
        self.stocks_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.stocks_table.setSortingEnabled(True)
        self.stocks_table.horizontalHeader().setStretchLastSection(True)
        
        # 右鍵選單
        self.stocks_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stocks_table.customContextMenuRequested.connect(self._show_context_menu)
        
        work_area_layout.addWidget(self.stocks_table, stretch=1)
        
        # 統計信息（放在表格下方）
        self.stats_label = QLabel("共 0 檔股票")
        work_area_layout.addWidget(self.stats_label)
        
        main_splitter.addWidget(work_area_widget)
        
        # ========== 下方：管理操作區（30-40%高度）==========
        management_widget = QWidget()
        management_layout = QHBoxLayout(management_widget)
        management_layout.setSpacing(10)
        management_layout.setContentsMargins(0, 0, 0, 0)
        
        # 使用水平 Splitter 分割左右兩側
        management_splitter = QSplitter(Qt.Horizontal)
        
        # 左側：觀察清單操作區
        watchlist_ops_group = QGroupBox("觀察清單操作")
        watchlist_ops_layout = QVBoxLayout(watchlist_ops_group)
        watchlist_ops_layout.setSpacing(8)
        watchlist_ops_layout.setContentsMargins(10, 12, 10, 10)
        
        # 操作按鈕（垂直排列，更緊湊）
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_watchlist)
        watchlist_ops_layout.addWidget(self.refresh_btn)
        
        self.add_btn = QPushButton("新增股票")
        self.add_btn.clicked.connect(self._show_add_dialog)
        watchlist_ops_layout.addWidget(self.add_btn)
        
        self.remove_btn = QPushButton("移除選中")
        self.remove_btn.clicked.connect(self._remove_selected)
        watchlist_ops_layout.addWidget(self.remove_btn)
        
        self.clear_btn = QPushButton("清空清單")
        self.clear_btn.clicked.connect(self._clear_watchlist)
        watchlist_ops_layout.addWidget(self.clear_btn)
        
        watchlist_ops_layout.addStretch()
        
        # 保存為選股清單按鈕
        self.save_to_universe_btn = QPushButton("保存為選股清單")
        self.save_to_universe_btn.clicked.connect(self._save_watchlist_to_universe)
        watchlist_ops_layout.addWidget(self.save_to_universe_btn)
        
        management_splitter.addWidget(watchlist_ops_group)
        
        # 右側：選股清單管理
        if self.universe_service:
            universe_group = QGroupBox("選股清單（用於回測）")
            universe_layout = QVBoxLayout(universe_group)
            universe_layout.setSpacing(6)
            universe_layout.setContentsMargins(10, 12, 10, 10)
            
            # 選股清單列表
            self.universe_list = QListWidget()
            self._refresh_universe_list()
            universe_layout.addWidget(self.universe_list, stretch=1)
            
            # 載入到觀察清單按鈕
            self.load_to_watchlist_btn = QPushButton("載入到觀察清單")
            self.load_to_watchlist_btn.clicked.connect(self._load_universe_to_watchlist)
            universe_layout.addWidget(self.load_to_watchlist_btn)
            
            # 管理按鈕（水平排列）
            universe_manage_layout = QHBoxLayout()
            universe_manage_layout.setSpacing(5)
            
            self.create_universe_btn = QPushButton("新增")
            self.create_universe_btn.clicked.connect(self._create_universe)
            universe_manage_layout.addWidget(self.create_universe_btn)
            
            self.edit_universe_btn = QPushButton("編輯")
            self.edit_universe_btn.clicked.connect(self._edit_universe)
            universe_manage_layout.addWidget(self.edit_universe_btn)
            
            self.delete_universe_btn = QPushButton("刪除")
            self.delete_universe_btn.clicked.connect(self._delete_universe)
            universe_manage_layout.addWidget(self.delete_universe_btn)
            
            universe_manage_layout.addStretch()
            universe_layout.addLayout(universe_manage_layout)
            
            management_splitter.addWidget(universe_group)
            management_splitter.setSizes([200, 300])  # 左側操作區較窄，右側列表區較寬
        else:
            # 如果沒有 universe_service，只顯示左側操作區
            pass
        
        management_layout.addWidget(management_splitter)
        main_splitter.addWidget(management_widget)
        
        # 設置上下比例：主要工作區 70%，管理區 30%
        main_splitter.setSizes([700, 300])
        
        main_layout.addWidget(main_splitter)
    
    def _load_watchlist(self):
        """載入觀察清單"""
        print("[WatchlistView._load_watchlist] 開始載入...")
        try:
            print("[WatchlistView._load_watchlist] 調用 watchlist_service.get_stocks()...")
            stocks = self.watchlist_service.get_stocks()
            print(f"[WatchlistView._load_watchlist] 獲取到 {len(stocks) if stocks else 0} 檔股票")
            
            if not stocks:
                # 顯示空表格
                print("[WatchlistView._load_watchlist] 觀察清單為空，顯示空表格")
                df = pd.DataFrame(columns=['證券代號', '證券名稱', '加入時間', '來源', '備註'])
                df.loc[0] = ['-', '-', '-', '-', '觀察清單為空']
            else:
                # 轉換為 DataFrame
                print("[WatchlistView._load_watchlist] 轉換為 DataFrame...")
                df = pd.DataFrame(stocks)
                df = df.rename(columns={
                    'stock_code': '證券代號',
                    'stock_name': '證券名稱',
                    'added_at': '加入時間',
                    'source': '來源',
                    'notes': '備註'
                })
                # 格式化時間
                if '加入時間' in df.columns:
                    df['加入時間'] = pd.to_datetime(df['加入時間'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
                print("[WatchlistView._load_watchlist] DataFrame 轉換完成")
            
            # 更新模型
            print("[WatchlistView._load_watchlist] 創建 PandasTableModel...")
            print(f"[WatchlistView._load_watchlist] DataFrame 形狀: {df.shape}")
            print(f"[WatchlistView._load_watchlist] DataFrame 欄位: {list(df.columns)}")
            
            try:
                self.stocks_model = PandasTableModel(df)
                # 隱藏 tags 欄位（如果存在）
                if 'tags' in df.columns:
                    visible_cols = [col for col in df.columns if col != 'tags']
                    self.stocks_model.setVisibleColumns(visible_cols)
                print("[WatchlistView._load_watchlist] PandasTableModel 創建成功")
            except Exception as e:
                print(f"[WatchlistView._load_watchlist] 創建 PandasTableModel 失敗: {e}")
                import traceback
                print(traceback.format_exc())
                raise
            
            print("[WatchlistView._load_watchlist] 設置表格模型...")
            try:
                self.stocks_table.setModel(self.stocks_model)
                print("[WatchlistView._load_watchlist] 表格模型設置成功")
            except Exception as e:
                print(f"[WatchlistView._load_watchlist] 設置表格模型失敗: {e}")
                import traceback
                print(traceback.format_exc())
                raise
            
            # 調整列寬
            print("[WatchlistView._load_watchlist] 調整列寬...")
            try:
                self.stocks_table.resizeColumnsToContents()
                print("[WatchlistView._load_watchlist] 列寬調整完成")
            except Exception as e:
                print(f"[WatchlistView._load_watchlist] 調整列寬失敗: {e}")
                # 不拋出異常，繼續執行
            
            # 更新統計
            self.stats_label.setText(f"共 {len(stocks)} 檔股票")
            print("[WatchlistView._load_watchlist] 載入完成")
            
        except Exception as e:
            import traceback
            print(f"[WatchlistView._load_watchlist] 錯誤：載入觀察清單失敗")
            print(f"[WatchlistView._load_watchlist] 錯誤類型: {type(e).__name__}")
            print(f"[WatchlistView._load_watchlist] 錯誤訊息: {str(e)}")
            print(f"[WatchlistView._load_watchlist] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            
            error_msg = f"載入觀察清單失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            try:
                QMessageBox.critical(self, "錯誤", error_msg)
            except:
                print("[WatchlistView._load_watchlist] 無法顯示錯誤對話框")
            
            # 顯示空表格，避免界面崩潰
            try:
                df = pd.DataFrame(columns=['證券代號', '證券名稱', '加入時間', '來源', '備註'])
                df.loc[0] = ['-', '-', '-', '-', '載入失敗，請檢查數據文件']
                self.stocks_model = PandasTableModel(df)
                self.stocks_table.setModel(self.stocks_model)
                self.stats_label.setText("共 0 檔股票（載入失敗）")
                print("[WatchlistView._load_watchlist] 已顯示錯誤提示")
            except Exception as e2:
                print(f"[WatchlistView._load_watchlist] 顯示錯誤提示時也失敗: {e2}")
    
    def _show_add_dialog(self):
        """顯示新增股票對話框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("新增股票到觀察清單")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # 股票代號輸入
        code_layout = QHBoxLayout()
        code_layout.addWidget(QLabel("股票代號:"))
        code_input = QLineEdit()
        code_input.setPlaceholderText("例如：2330")
        code_layout.addWidget(code_input)
        layout.addLayout(code_layout)
        
        # 股票名稱輸入（可選）
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("股票名稱:"))
        name_input = QLineEdit()
        name_input.setPlaceholderText("可選，留空將自動查詢")
        name_layout.addWidget(name_input)
        layout.addLayout(name_layout)
        
        # 備註
        notes_layout = QVBoxLayout()
        notes_layout.addWidget(QLabel("備註:"))
        notes_input = QTextEdit()
        notes_input.setMaximumHeight(80)
        notes_layout.addWidget(notes_input)
        layout.addLayout(notes_layout)
        
        # 按鈕
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            stock_code = code_input.text().strip()
            stock_name = name_input.text().strip()
            
            if not stock_code:
                QMessageBox.warning(self, "錯誤", "請輸入股票代號")
                return
            
            # 如果沒有輸入名稱，使用代號作為名稱
            if not stock_name:
                stock_name = stock_code
            
            # 新增股票
            try:
                added_count = self.watchlist_service.add_stocks(
                    stocks=[{
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'notes': notes_input.toPlainText().strip()
                    }],
                    source='manual'
                )
                
                if added_count > 0:
                    QMessageBox.information(self, "成功", f"已新增 {added_count} 檔股票到觀察清單")
                    self._load_watchlist()
                    self.watchlistUpdated.emit()
                else:
                    QMessageBox.warning(self, "提示", "該股票已在觀察清單中")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"新增股票失敗：\n{str(e)}")
    
    def _remove_selected(self):
        """移除選中的股票"""
        selection = self.stocks_table.selectionModel().selectedRows()
        if not selection or not self.stocks_model:
            QMessageBox.warning(self, "提示", "請先選擇要移除的股票")
            return
        
        # 確認對話框
        reply = QMessageBox.question(
            self, "確認", 
            f"確定要移除選中的 {len(selection)} 檔股票嗎？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 取得選中的股票代號
        df = self.stocks_model.getDataFrame()
        stock_codes = []
        for index in selection:
            row = index.row()
            if row < len(df):
                stock_code = df.iloc[row]['證券代號']
                stock_codes.append(stock_code)
        
        # 移除股票
        try:
            removed_count = self.watchlist_service.remove_stocks(stock_codes)
            if removed_count > 0:
                QMessageBox.information(self, "成功", f"已移除 {removed_count} 檔股票")
                self._load_watchlist()
                self.watchlistUpdated.emit()
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"移除股票失敗：\n{str(e)}")
    
    def _clear_watchlist(self):
        """清空觀察清單"""
        reply = QMessageBox.question(
            self, "確認", 
            "確定要清空整個觀察清單嗎？此操作無法復原。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # 取得所有股票代號
            stock_codes = self.watchlist_service.get_stock_codes()
            if stock_codes:
                self.watchlist_service.remove_stocks(stock_codes)
                QMessageBox.information(self, "成功", "已清空觀察清單")
                self._load_watchlist()
                self.watchlistUpdated.emit()
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"清空清單失敗：\n{str(e)}")
    
    def _show_context_menu(self, position):
        """顯示右鍵選單"""
        if not self.stocks_model:
            return
        
        menu = QMenu(self)
        
        # 移除選項
        remove_action = QAction("移除選中", self)
        remove_action.triggered.connect(self._remove_selected)
        menu.addAction(remove_action)
        
        menu.exec(self.stocks_table.viewport().mapToGlobal(position))
    
    def add_stocks_from_dataframe(self, df: pd.DataFrame, source: str = "unknown"):
        """
        從 DataFrame 新增股票到觀察清單
        
        Args:
            df: 包含股票資料的 DataFrame（必須有 '證券代號' 或 'stock_code' 欄位）
            source: 來源標籤
        """
        if df is None or len(df) == 0:
            return
        
        # 轉換 DataFrame 為字典列表
        stocks = []
        for _, row in df.iterrows():
            stock_code = row.get('證券代號') or row.get('stock_code')
            stock_name = row.get('證券名稱') or row.get('stock_name', stock_code)
            
            if stock_code:
                stocks.append({
                    'stock_code': str(stock_code),
                    'stock_name': str(stock_name),
                    'notes': ''
                })
        
        if stocks:
            try:
                added_count = self.watchlist_service.add_stocks(stocks, source=source)
                if added_count > 0:
                    self._load_watchlist()
                    self.watchlistUpdated.emit()
                    return added_count
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"新增股票到觀察清單失敗：\n{str(e)}")
        
        return 0
    
    def get_stock_codes(self) -> List[str]:
        """取得觀察清單中的股票代號列表"""
        return self.watchlist_service.get_stock_codes()
    
    # ========== 選股清單管理相關方法 ==========
    
    def _refresh_universe_list(self):
        """刷新選股清單列表"""
        if not self.universe_service or not hasattr(self, 'universe_list'):
            return
        
        self.universe_list.clear()
        try:
            watchlists = self.universe_service.list_watchlists()
            for watchlist in watchlists:
                name = watchlist.get('name', '')
                count = watchlist.get('count', 0)
                watchlist_id = watchlist.get('watchlist_id', '')
                display_text = f"{name} ({count}檔)"
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, watchlist_id)
                self.universe_list.addItem(item)
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"載入選股清單列表失敗：\n{str(e)}")
    
    def _save_watchlist_to_universe(self):
        """將當前觀察清單保存為選股清單"""
        if not self.universe_service:
            QMessageBox.warning(self, "錯誤", "選股清單服務未初始化")
            return
        
        # 獲取當前觀察清單的股票代號
        stock_codes = self.watchlist_service.get_stock_codes()
        if not stock_codes:
            QMessageBox.warning(self, "提示", "觀察清單為空，無法保存")
            return
        
        # 輸入清單名稱
        dialog = QDialog(self)
        dialog.setWindowTitle("保存為選股清單")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("清單名稱:"))
        name_input = QLineEdit()
        name_input.setPlaceholderText("例如：我的觀察清單")
        layout.addWidget(name_input)
        
        layout.addWidget(QLabel(f"將保存 {len(stock_codes)} 檔股票到選股清單"))
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(self, "錯誤", "請輸入清單名稱")
                return
            
            try:
                watchlist_id = self.universe_service.save_watchlist(
                    name=name,
                    codes=stock_codes,
                    source="watchlist"
                )
                QMessageBox.information(self, "成功", f"已保存為選股清單：{name}")
                self._refresh_universe_list()
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"保存失敗：\n{str(e)}")
    
    def _load_universe_to_watchlist(self):
        """從選股清單載入到觀察清單"""
        if not self.universe_service:
            QMessageBox.warning(self, "錯誤", "選股清單服務未初始化")
            return
        
        selected_items = self.universe_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "請選擇要載入的選股清單")
            return
        
        watchlist_id = selected_items[0].data(Qt.UserRole)
        watchlist = self.universe_service.load_watchlist(watchlist_id)
        
        if not watchlist:
            QMessageBox.warning(self, "錯誤", "載入選股清單失敗")
            return
        
        if not watchlist.codes:
            QMessageBox.warning(self, "提示", "選股清單為空")
            return
        
        # 確認對話框
        reply = QMessageBox.question(
            self, "確認",
            f"確定要將「{watchlist.name}」({len(watchlist.codes)}檔) 加入到觀察清單嗎？\n"
            f"（已存在的股票不會重複加入）",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 轉換為觀察清單格式
        stocks = []
        for code in watchlist.codes:
            stocks.append({
                'stock_code': str(code),
                'stock_name': str(code),  # 名稱會在加入時自動查詢
                'notes': f'來自選股清單：{watchlist.name}'
            })
        
        try:
            added_count = self.watchlist_service.add_stocks(stocks, source='universe')
            if added_count > 0:
                QMessageBox.information(self, "成功", f"已加入 {added_count} 檔股票到觀察清單")
                self._load_watchlist()
                self.watchlistUpdated.emit()
            else:
                QMessageBox.information(self, "提示", "所有股票都已存在於觀察清單中")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"載入失敗：\n{str(e)}")
    
    def _create_universe(self):
        """創建新選股清單"""
        if not self.universe_service:
            QMessageBox.warning(self, "錯誤", "選股清單服務未初始化")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("新增選股清單")
        dialog.setMinimumSize(500, 400)
        dialog_layout = QVBoxLayout(dialog)
        
        dialog_layout.addWidget(QLabel("清單名稱:"))
        name_input = QLineEdit()
        dialog_layout.addWidget(name_input)
        
        dialog_layout.addWidget(QLabel("股票代號（每行一個或逗號分隔）:"))
        codes_input = QTextEdit()
        codes_input.setMinimumHeight(200)
        dialog_layout.addWidget(codes_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(self, "錯誤", "請輸入清單名稱")
                return
            
            # 解析股票代號
            codes_text = codes_input.toPlainText().strip()
            codes = self.universe_service.parse_codes_from_text(codes_text)
            
            if not codes:
                QMessageBox.warning(self, "錯誤", "請輸入至少一個股票代號")
                return
            
            try:
                self.universe_service.save_watchlist(name=name, codes=codes)
                QMessageBox.information(self, "成功", f"清單已創建: {name}")
                self._refresh_universe_list()
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"創建失敗: {str(e)}")
    
    def _edit_universe(self):
        """編輯選股清單"""
        if not self.universe_service:
            QMessageBox.warning(self, "錯誤", "選股清單服務未初始化")
            return
        
        selected_items = self.universe_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "錯誤", "請選擇要編輯的清單")
            return
        
        watchlist_id = selected_items[0].data(Qt.UserRole)
        watchlist = self.universe_service.load_watchlist(watchlist_id)
        if not watchlist:
            QMessageBox.warning(self, "錯誤", "載入清單失敗")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("編輯選股清單")
        dialog.setMinimumSize(500, 400)
        dialog_layout = QVBoxLayout(dialog)
        
        dialog_layout.addWidget(QLabel("清單名稱:"))
        name_input = QLineEdit(watchlist.name)
        dialog_layout.addWidget(name_input)
        
        dialog_layout.addWidget(QLabel("股票代號（每行一個或逗號分隔）:"))
        codes_input = QTextEdit('\n'.join(watchlist.codes))
        codes_input.setMinimumHeight(200)
        dialog_layout.addWidget(codes_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(self, "錯誤", "請輸入清單名稱")
                return
            
            # 解析股票代號
            codes_text = codes_input.toPlainText().strip()
            codes = self.universe_service.parse_codes_from_text(codes_text)
            
            if not codes:
                QMessageBox.warning(self, "錯誤", "請輸入至少一個股票代號")
                return
            
            try:
                self.universe_service.save_watchlist(
                    name=name,
                    codes=codes,
                    watchlist_id=watchlist_id  # 更新現有清單
                )
                QMessageBox.information(self, "成功", f"清單已更新: {name}")
                self._refresh_universe_list()
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"更新失敗: {str(e)}")
    
    def _delete_universe(self):
        """刪除選股清單"""
        if not self.universe_service:
            QMessageBox.warning(self, "錯誤", "選股清單服務未初始化")
            return
        
        selected_items = self.universe_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "錯誤", "請選擇要刪除的清單")
            return
        
        watchlist_id = selected_items[0].data(Qt.UserRole)
        item_text = selected_items[0].text()
        
        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除清單「{item_text}」嗎？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                if self.universe_service.delete_watchlist(watchlist_id):
                    QMessageBox.information(self, "成功", "清單已刪除")
                    self._refresh_universe_list()
                else:
                    QMessageBox.warning(self, "錯誤", "刪除失敗")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"刪除失敗: {str(e)}")


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
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
from typing import List, Dict, Optional

from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.watchlist_service import WatchlistService
from app_module.universe_service import UniverseService
from app_module.watchlist_analysis_service import WatchlistAnalysisService
from app_module.research_session import ResearchStockContextDTO
from ui_qt.workers.task_worker import TaskWorker
from ui_qt.widgets.info_button import InfoButton
from ui_qt.widgets.table_style import apply_financial_table_style


class WatchlistView(QWidget):
    """觀察清單視圖"""
    
    # 信號：當觀察清單更新時發出
    watchlistUpdated = Signal()
    sendToBacktestRequested = Signal(dict)
    stockAnalysisRequested = Signal(str)
    stockResearchRequested = Signal(object)
    
    def __init__(self, watchlist_service: WatchlistService, config=None, parent=None):
        """初始化觀察清單視圖
        
        Args:
            watchlist_service: 觀察清單服務實例
            config: TWStockConfig 實例（用於初始化 UniverseService）
            parent: 父窗口
        """
        logger.info("[WatchlistView] 開始初始化...")
        super().__init__(parent)
        logger.info("[WatchlistView] 父類初始化完成")
        
        self.watchlist_service = watchlist_service
        self.config = config
        self.analysis_service = WatchlistAnalysisService(config) if config and hasattr(config, "output_root") else None
        self._analysis_request_id = 0
        self._analysis_worker: TaskWorker | None = None
        logger.info("[WatchlistView] watchlist_service 設置完成")
        
        # 初始化選股清單服務（用於回測）
        if config:
            try:
                self.universe_service = UniverseService(config)
                logger.info("[WatchlistView] universe_service 初始化成功")
            except Exception as e:
                logger.warning(f"[WatchlistView] 警告：universe_service 初始化失敗: {e}")
                self.universe_service = None
        else:
            self.universe_service = None
        
        # 數據模型
        self.stocks_model: Optional[PandasTableModel] = None
        
        logger.info("[WatchlistView] 開始設置 UI...")
        self._setup_ui()
        logger.info("[WatchlistView] UI 設置完成")
        
        # 延遲載入觀察清單，避免初始化時出錯導致整個程式崩潰
        logger.info("[WatchlistView] 開始載入觀察清單...")
        try:
            self._load_watchlist()
            logger.info("[WatchlistView] 觀察清單載入成功")
        except Exception as e:
            import traceback
            logger.error(f"[WatchlistView] 錯誤：初始化時載入觀察清單失敗")
            logger.error(f"[WatchlistView] 錯誤類型: {type(e).__name__}")
            logger.error(f"[WatchlistView] 錯誤訊息: {str(e)}")
            logger.error(f"[WatchlistView] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            # 顯示空表格，不阻止程式啟動
            try:
                self.stocks_model = PandasTableModel(self._empty_frame())
                self.stocks_table.setModel(self.stocks_model)
                self.stats_label.setText("共 0 檔股票（載入失敗）")
                self._set_status_label("載入失敗，請檢查數據文件", level="error")
                logger.error("[WatchlistView] 已顯示錯誤提示")
            except Exception as e2:
                logger.error(f"[WatchlistView] 顯示錯誤提示時也失敗: {e2}")
        
        logger.info("[WatchlistView] 初始化完成")
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("候選池")
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
        work_title = QLabel("觀察候選池")
        work_title_font = QFont()
        work_title_font.setPointSize(11)
        work_title_font.setBold(True)
        work_title.setFont(work_title_font)
        work_area_layout.addWidget(work_title)
        
        # 表格（主要內容，佔用大部分空間）
        self.stocks_table = QTableView()
        apply_financial_table_style(self.stocks_table)
        self.stocks_table.setSelectionBehavior(QTableView.SelectRows)
        self.stocks_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.stocks_table.setSortingEnabled(True)
        self.stocks_table.horizontalHeader().setStretchLastSection(True)
        
        # 右鍵選單
        self.stocks_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stocks_table.customContextMenuRequested.connect(self._show_context_menu)
        
        work_area_layout.addWidget(self.stocks_table, stretch=1)
        self.stocks_table.doubleClicked.connect(self._open_stock_analysis)
        self.stock_analysis_btn = QPushButton("查看選中個股分析／主力流向")
        self.stock_analysis_btn.setToolTip("選取一檔股票後開啟個股資金與分點分析；也可雙擊股票。")
        self.stock_analysis_btn.clicked.connect(self._open_stock_analysis)
        work_area_layout.addWidget(self.stock_analysis_btn)
        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setMinimumHeight(130)
        self.analysis_text.setPlaceholderText("選取一檔股票，查看已保存的推薦分數、理由與分析日期。")
        work_area_layout.addWidget(self.analysis_text)
        
        # 統計信息（放在表格下方）
        self.stats_label = QLabel("共 0 檔股票")
        work_area_layout.addWidget(self.stats_label)
        self.status_label = self.stats_label
        self._set_status_label("尚未載入", level="info")
        
        main_splitter.addWidget(work_area_widget)
        
        # ========== 下方：管理操作區（30-40%高度）==========
        management_widget = QWidget()
        management_layout = QHBoxLayout(management_widget)
        management_layout.setSpacing(10)
        management_layout.setContentsMargins(0, 0, 0, 0)
        
        # 使用水平 Splitter 分割左右兩側
        management_splitter = QSplitter(Qt.Horizontal)
        
        # 左側：候選池操作區
        watchlist_ops_group = QGroupBox("候選池操作")
        watchlist_ops_layout = QVBoxLayout(watchlist_ops_group)
        watchlist_ops_layout.setSpacing(8)
        watchlist_ops_layout.setContentsMargins(10, 12, 10, 10)
        
        # 操作按鈕（垂直排列，更緊湊）
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_watchlist)
        watchlist_ops_layout.addWidget(self.refresh_btn)
        
        self.add_btn = QPushButton("新增股票")
        self.add_btn.setProperty("variant", "primary")
        self.add_btn.clicked.connect(self._show_add_dialog)
        watchlist_ops_layout.addWidget(self.add_btn)
        
        self.remove_btn = QPushButton("移除選中")
        self.remove_btn.clicked.connect(self._remove_selected)
        watchlist_ops_layout.addWidget(self.remove_btn)
        
        self.clear_btn = QPushButton("清空候選池")
        self.clear_btn.setProperty("variant", "danger")
        self.clear_btn.clicked.connect(self._clear_watchlist)
        watchlist_ops_layout.addWidget(self.clear_btn)
        
        watchlist_ops_layout.addStretch()
        
        self.send_to_research_lab_btn = QPushButton("送 Research Lab 批次回測")
        self.send_to_research_lab_btn.setProperty("variant", "primary")
        self.send_to_research_lab_btn.setEnabled(False)
        self.send_to_research_lab_btn.setToolTip("候選池目前沒有股票，加入股票後即可送 Research Lab 批次回測。")
        self.send_to_research_lab_btn.clicked.connect(self._send_to_research_lab)
        watchlist_ops_layout.addWidget(self.send_to_research_lab_btn)

        # 保存為選股清單按鈕
        self.save_to_universe_btn = QPushButton("保存為選股清單")
        self.save_to_universe_btn.setToolTip("將目前候選池作為批次股票回測的輸入。")
        self.save_to_universe_btn.clicked.connect(self._save_watchlist_to_universe)
        watchlist_ops_layout.addWidget(self.save_to_universe_btn)
        
        management_splitter.addWidget(watchlist_ops_group)
        
        # 右側：選股清單管理
        if self.universe_service:
            universe_group = QGroupBox("選股清單（用於回測）")
            universe_layout = QVBoxLayout(universe_group)
            universe_layout.setSpacing(6)
            universe_layout.setContentsMargins(10, 12, 10, 10)
            
            # 選股清單列表標題和刷新按鈕
            list_header_layout = QHBoxLayout()
            list_header_layout.addWidget(QLabel("選股清單列表:"))
            list_header_layout.addStretch()
            self.refresh_universe_btn = QPushButton("刷新")
            self.refresh_universe_btn.setMaximumWidth(60)
            self.refresh_universe_btn.clicked.connect(self._refresh_universe_list)
            list_header_layout.addWidget(self.refresh_universe_btn)
            universe_layout.addLayout(list_header_layout)
            
            # 選股清單列表
            self.universe_list = QListWidget()
            self._refresh_universe_list()
            universe_layout.addWidget(self.universe_list, stretch=1)
            universe_layout.addWidget(QLabel("清單個股預覽（單擊看摘要，雙擊開啟主力流向）"))
            self.universe_stock_list = QListWidget()
            universe_layout.addWidget(self.universe_stock_list, stretch=1)
            self.universe_list.itemSelectionChanged.connect(self._preview_universe_stocks)
            self.universe_stock_list.currentItemChanged.connect(self._select_universe_stock)
            self.universe_stock_list.itemDoubleClicked.connect(self._open_universe_stock_analysis)
            
            # 載入到觀察清單按鈕
            self.load_to_watchlist_btn = QPushButton("載入到候選池")
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
            self.delete_universe_btn.setProperty("variant", "danger")
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

    @staticmethod
    def _empty_frame() -> pd.DataFrame:
        return pd.DataFrame(
            columns=["證券代號", "證券名稱", "加入時間", "來源", "備註"]
        )

    def _set_status_label(self, text: str, *, level: str) -> None:
        colors = {
            "info": "#94a3b8",
            "success": "#86efac",
            "warning": "#facc15",
            "error": "#fca5a5",
        }
        self.status_label.setStyleSheet(
            f"color: {colors.get(level, colors['info'])}; padding: 2px 0;"
        )
        self.status_label.setText(text)

    def _load_watchlist(self):
        """載入觀察清單"""
        self._analysis_request_id += 1
        self.analysis_text.clear()
        logger.info("[WatchlistView._load_watchlist] 開始載入...")
        self._set_status_label("載入中…", level="info")
        try:
            logger.info("[WatchlistView._load_watchlist] 調用 watchlist_service.get_stocks()...")
            stocks = self.watchlist_service.get_stocks()
            logger.info(f"[WatchlistView._load_watchlist] 獲取到 {len(stocks) if stocks else 0} 檔股票")
            
            if not stocks:
                # 顯示空表格
                logger.info("[WatchlistView._load_watchlist] 候選池為空，顯示空表格")
                df = self._empty_frame()
            else:
                # 轉換為 DataFrame
                logger.info("[WatchlistView._load_watchlist] 轉換為 DataFrame...")
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
                logger.info("[WatchlistView._load_watchlist] DataFrame 轉換完成")
            
            # 更新模型
            logger.info("[WatchlistView._load_watchlist] 創建 PandasTableModel...")
            logger.info(f"[WatchlistView._load_watchlist] DataFrame 形狀: {df.shape}")
            logger.info(f"[WatchlistView._load_watchlist] DataFrame 欄位: {list(df.columns)}")
            
            try:
                self.stocks_model = PandasTableModel(df)
                # 隱藏 tags 欄位（如果存在）
                if 'tags' in df.columns:
                    visible_cols = [col for col in df.columns if col != 'tags']
                    self.stocks_model.setVisibleColumns(visible_cols)
                logger.info("[WatchlistView._load_watchlist] PandasTableModel 創建成功")
            except Exception as e:
                logger.error(f"[WatchlistView._load_watchlist] 創建 PandasTableModel 失敗: {e}")
                import traceback
                logger.error(traceback.format_exc())
                raise
            
            logger.info("[WatchlistView._load_watchlist] 設置表格模型...")
            try:
                self.stocks_table.setModel(self.stocks_model)
                self._analysis_request_id += 1
                self.analysis_text.clear()
                self.stocks_table.selectionModel().selectionChanged.connect(self._load_selected_analysis)
                logger.info("[WatchlistView._load_watchlist] 表格模型設置成功")
            except Exception as e:
                logger.error(f"[WatchlistView._load_watchlist] 設置表格模型失敗: {e}")
                import traceback
                logger.error(traceback.format_exc())
                raise
            
            # 調整列寬
            logger.info("[WatchlistView._load_watchlist] 調整列寬...")
            try:
                self.stocks_table.resizeColumnsToContents()
                logger.info("[WatchlistView._load_watchlist] 列寬調整完成")
            except Exception as e:
                logger.error(f"[WatchlistView._load_watchlist] 調整列寬失敗: {e}")
                # 不拋出異常，繼續執行
            
            # 更新統計
            if stocks:
                self.stats_label.setText(f"共 {len(stocks)} 檔股票")
                self._set_status_label(f"已更新：{len(stocks)} 筆", level="success")
            else:
                self.stats_label.setText("共 0 檔股票（目前沒有候選）")
                self._set_status_label("已更新：0 筆；目前沒有候選", level="warning")
            self._update_research_lab_button_state(len(stocks))
            logger.info("[WatchlistView._load_watchlist] 載入完成")
            
        except Exception as e:
            import traceback
            logger.error(f"[WatchlistView._load_watchlist] 錯誤：載入觀察清單失敗")
            logger.error(f"[WatchlistView._load_watchlist] 錯誤類型: {type(e).__name__}")
            logger.error(f"[WatchlistView._load_watchlist] 錯誤訊息: {str(e)}")
            logger.error(f"[WatchlistView._load_watchlist] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            
            error_msg = f"載入觀察清單失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            try:
                QMessageBox.critical(self, "錯誤", error_msg)
            except:
                logger.error("[WatchlistView._load_watchlist] 無法顯示錯誤對話框")
            
            # 顯示空表格，避免界面崩潰
            try:
                self.stocks_model = PandasTableModel(self._empty_frame())
                self.stocks_table.setModel(self.stocks_model)
                self.stats_label.setText("共 0 檔股票（載入失敗）")
                self._set_status_label(
                    f"載入失敗：{str(e).splitlines()[0] or type(e).__name__}",
                    level="error",
                )
                self._update_research_lab_button_state(0)
                logger.error("[WatchlistView._load_watchlist] 已顯示錯誤提示")
            except Exception as e2:
                logger.error(f"[WatchlistView._load_watchlist] 顯示錯誤提示時也失敗: {e2}")

    def _update_research_lab_button_state(self, stock_count: int) -> None:
        """依候選池內容啟用或停用 Research Lab 批次回測入口。"""
        enabled = stock_count > 0
        self.send_to_research_lab_btn.setEnabled(enabled)
        if enabled:
            self.send_to_research_lab_btn.setToolTip("將目前候選池送到策略回測的批次模式。")
        else:
            self.send_to_research_lab_btn.setToolTip("候選池目前沒有股票，加入股票後即可送 Research Lab 批次回測。")

    def _send_to_research_lab(self) -> None:
        """將目前觀察清單送到策略回測的批次模式。"""
        stock_codes = [str(code).strip() for code in self.watchlist_service.get_stock_codes() if str(code).strip()]
        if not stock_codes:
            QMessageBox.warning(self, "提示", "候選池目前沒有股票，無法送 Research Lab 批次回測。")
            self._update_research_lab_button_state(0)
            return

        config = {
            "stock_list": stock_codes,
            "profile_id": "watchlist",
            "profile_name": "觀察清單",
            "strategy_config": {},
            "regime": None,
            "regime_snapshot": None,
            "source": "watchlist",
        }
        self.sendToBacktestRequested.emit(config)
        QMessageBox.information(
            self,
            "已送出",
            f"已將 {len(stock_codes)} 檔候選池股票送到 Research Lab 批次回測。\n\n"
            "請切換到「策略回測 / Research Lab」確認期間、策略與資金設定後執行。",
        )
    
    def _show_add_dialog(self):
        """顯示新增股票對話框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("新增股票到候選池")
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

            resolved = self._resolve_manual_stock(stock_code, stock_name)
            if resolved is None:
                QMessageBox.warning(
                    self,
                    "股票代號不存在",
                    f"找不到股票代號 {stock_code} 的正式資料，請確認代號是否正確。\n\n"
                    "目前手動新增只允許加入資料源中存在的股票，避免自訂代號混入正式候選池。",
                )
                return
            stock_code, stock_name = resolved
            
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
                    QMessageBox.information(self, "成功", f"已新增 {added_count} 檔股票到候選池")
                    self._load_watchlist()
                    self.watchlistUpdated.emit()
                else:
                    QMessageBox.warning(self, "提示", "該股票已在候選池中")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"新增股票失敗：\n{str(e)}")

    def _resolve_manual_stock(self, stock_code: str, stock_name: str) -> Optional[tuple[str, str]]:
        """驗證手動輸入股票代號，並在名稱空白時自動補正式名稱。"""
        code = str(stock_code).strip()
        name = str(stock_name).strip()
        if not code:
            return None

        name_map = self._query_stock_names([code])
        resolved_name = name_map.get(code)
        if not resolved_name:
            return None
        return code, name or resolved_name
    
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
            "確定要清空整個候選池嗎？此操作無法復原。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # 取得所有股票代號
            stock_codes = self.watchlist_service.get_stock_codes()
            if stock_codes:
                self.watchlist_service.remove_stocks(stock_codes)
                QMessageBox.information(self, "成功", "已清空候選池")
                self._load_watchlist()
                self.watchlistUpdated.emit()
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"清空清單失敗：\n{str(e)}")
    
    def _load_selected_analysis(self, *_args):
        self._analysis_request_id += 1
        request_id = self._analysis_request_id
        selection = self.stocks_table.selectionModel()
        rows = selection.selectedRows() if selection else []
        if self.stocks_model is None or len(rows) != 1:
            self.analysis_text.setPlainText("請選取一檔股票查看分析摘要。")
            return
        row = self.stocks_model.getDataFrame().iloc[rows[0].row()]
        code = str(row["證券代號"]).strip()
        source = row.get("source_id", "")
        source_id = source.strip() if isinstance(source, str) else ""
        self._request_stock_summary(code, source_id, request_id)

    def _request_stock_summary(self, code, source_id, request_id):
        if self.analysis_service is None:
            self.analysis_text.setPlainText(f"{code}｜分析來源尚未配置；可使用個股主力流向入口。")
            return
        self.analysis_text.setPlainText(f"{code}｜正在讀取已保存分析…")
        service = self.analysis_service
        cutoff = datetime.now(ZoneInfo("Asia/Taipei")).date()
        worker = TaskWorker(lambda: service.fetch(code, source_id, cutoff))
        self._analysis_worker = worker
        worker.finished.connect(lambda result: self._show_selected_analysis(request_id, result))
        worker.error.connect(lambda error: self._show_analysis_error(request_id, error))
        worker.native_thread_finished.connect(worker.deleteLater)
        worker.start()

    def _preview_universe_stocks(self):
        self._analysis_request_id += 1
        self.analysis_text.clear()
        self.universe_stock_list.clear()
        selected = self.universe_list.currentItem()
        if selected is None or self.universe_service is None:
            return
        try:
            universe = self.universe_service.load_watchlist(selected.data(Qt.UserRole))
            if universe is None:
                return
            codes = [str(code).strip() for code in universe.codes]
            names = self._query_stock_names(codes)
            for code in codes:
                item = QListWidgetItem(f"{code} {names.get(code, '')}")
                item.setData(Qt.UserRole, code)
                item.setData(Qt.UserRole + 1, names.get(code, ""))
                self.universe_stock_list.addItem(item)
        except Exception as error:
            self.analysis_text.setPlainText(f"清單預覽讀取失敗：{error}")

    def _select_universe_stock(self, current, _previous):
        self._analysis_request_id += 1
        if current is not None:
            self._request_stock_summary(str(current.data(Qt.UserRole)), "", self._analysis_request_id)

    def _show_selected_analysis(self, request_id, result):
        if request_id != self._analysis_request_id:
            return
        lines = [result.stock_code, result.message]
        if result.analysis_date:
            lines.append(f"分析日期：{result.analysis_date}｜來源：{result.result_id}")
        if getattr(result, "data_date", "") and result.data_date != result.analysis_date:
            lines.append(f"資料日期：{result.data_date}")
        if getattr(result, "profile_id", ""):
            profile = result.profile_id
            if getattr(result, "profile_version", ""):
                profile += f"（{result.profile_version}）"
            lines.append(f"Profile：{profile}")
        if result.status == "saved":
            lines.extend([f"當時收盤價：{result.close_price}｜推薦總分：{result.score}", f"推薦理由：{result.reasons}"])
        self.analysis_text.setPlainText("\n".join(lines))

    def _show_analysis_error(self, request_id, error):
        if request_id == self._analysis_request_id:
            self.analysis_text.setPlainText(f"分析讀取失敗：{str(error).splitlines()[0]}")

    def closeEvent(self, event):
        self._analysis_request_id += 1
        super().closeEvent(event)

    def _open_stock_analysis(self, _checked=False):
        """以畫面排序後的選取列傳送股票代號與來源脈絡。"""
        selection = self.stocks_table.selectionModel()
        rows = selection.selectedRows() if selection else []
        if self.stocks_model is None or len(rows) != 1:
            self._set_status_label("請選取一檔股票查看個股分析", level="info")
            return
        frame = self.stocks_model.getDataFrame()
        row = frame.iloc[rows[0].row()]
        code = str(row["證券代號"]).strip()
        if code:
            source_value = row.get("source_id", "")
            source_id = source_value.strip() if isinstance(source_value, str) else ""
            self.stockAnalysisRequested.emit(code)
            self.stockResearchRequested.emit(
                self._build_stock_research_context(
                    code,
                    str(row.get("證券名稱", "") or "").strip(),
                    source_id,
                )
            )

    def _open_universe_stock_analysis(self, item: QListWidgetItem) -> None:
        """由保存的選股清單下鑽；沒有 result id 時仍保留股票識別。"""

        code = str(item.data(Qt.UserRole) or "").strip()
        if not code:
            return
        name = str(item.data(Qt.UserRole + 1) or "").strip()
        self.stockAnalysisRequested.emit(code)
        self.stockResearchRequested.emit(
            self._build_stock_research_context(code, name, "")
        )

    def _build_stock_research_context(
        self,
        stock_code: str,
        stock_name: str = "",
        source_id: str = "",
    ) -> ResearchStockContextDTO:
        """從觀察清單的保存來源建立唯讀上下文，不重新計算。"""

        code = str(stock_code).strip()
        source = str(source_id or "").strip()
        result = None
        if self.analysis_service is not None and source:
            try:
                cutoff = datetime.now(ZoneInfo("Asia/Taipei")).date()
                result = self.analysis_service.fetch(code, source, cutoff)
            except Exception as error:
                logger.warning("[WatchlistView] 讀取保存來源 metadata 失敗：%s", error)

        result_id = str(getattr(result, "result_id", "") or source)
        decision_date = str(
            getattr(result, "decision_date", "")
            or getattr(result, "analysis_date", "")
            or ""
        )
        data_date = str(getattr(result, "data_date", "") or "")
        profile_id = str(getattr(result, "profile_id", "") or "")
        profile_version = str(getattr(result, "profile_version", "") or "")
        lineage_id = str(getattr(result, "source_id", "") or "")
        return ResearchStockContextDTO(
            stock_code=code,
            stock_name=stock_name,
            decision_date=decision_date,
            data_date=data_date,
            result_id=result_id,
            profile_id=profile_id,
            profile_version=profile_version,
            source_id=source or lineage_id,
            source_kind=str(getattr(result, "source_kind", "") or "recommendation"),
            source_label=("已保存推薦結果" if result_id else "觀察清單"),
            source_workspace="watchlist",
        )

    def select_stock(self, stock_code: str, result_id: str | None = None) -> bool:
        """返回觀察清單時定位既有列，不載入或重算推薦。"""

        if self.stocks_model is None:
            return False
        code = str(stock_code).strip()
        frame = self.stocks_model.getDataFrame()
        for row_number, value in enumerate(frame.get("證券代號", ())):
            if str(value).strip() == code:
                if result_id:
                    source = str(frame.iloc[row_number].get("source_id", "") or "").strip()
                    if source and source != str(result_id).strip():
                        return False
                self.stocks_table.selectRow(row_number)
                return True
        return False

    def _show_context_menu(self, position):
        """顯示右鍵選單"""
        if not self.stocks_model:
            return
        
        menu = QMenu(self)
        analysis_action = QAction("查看個股分析／主力流向", self)
        analysis_action.triggered.connect(self._open_stock_analysis)
        menu.addAction(analysis_action)
        
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
            source_id = row.get('source_id')
            if not isinstance(source_id, str) or not source_id.strip():
                source_id = row.get('result_id')
            source_id = source_id.strip() if isinstance(source_id, str) else ''
            
            if stock_code:
                stocks.append({
                    'stock_code': str(stock_code),
                    'stock_name': str(stock_name),
                    'notes': '',
                    'source_id': source_id
                })
        
        if stocks:
            try:
                added_count = self.watchlist_service.add_stocks(stocks, source=source)
                if added_count > 0:
                    self._load_watchlist()
                    self.watchlistUpdated.emit()
                    return added_count
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"新增股票到候選池失敗：\n{str(e)}")
        
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
            
            # 顯示刷新成功提示（可選，避免過於頻繁）
            if hasattr(self, '_last_refresh_time'):
                from datetime import datetime
                now = datetime.now()
                if (now - self._last_refresh_time).total_seconds() > 1:  # 至少間隔1秒才顯示
                    pass  # 可以添加狀態提示
            else:
                from datetime import datetime
                self._last_refresh_time = datetime.now()
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"載入選股清單列表失敗：\n{str(e)}")
    
    def refresh_all(self):
        """刷新所有數據（觀察清單和選股清單）"""
        """當切換到觀察清單 Tab 時調用，確保數據同步"""
        self._load_watchlist()
        self._refresh_universe_list()
    
    def _save_watchlist_to_universe(self):
        """將當前觀察清單保存為選股清單"""
        if not self.universe_service:
            QMessageBox.warning(self, "錯誤", "選股清單服務未初始化")
            return
        
        # 獲取當前觀察清單的股票代號
        stock_codes = self.watchlist_service.get_stock_codes()
        if not stock_codes:
            QMessageBox.warning(self, "提示", "候選池為空，無法保存")
            return
        
        # 輸入清單名稱
        dialog = QDialog(self)
        dialog.setWindowTitle("保存為選股清單")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("清單名稱:"))
        name_input = QLineEdit()
        name_input.setPlaceholderText("例如：我的候選池")
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
    
    def _query_stock_names(self, stock_codes: List[str]) -> Dict[str, str]:
        """名稱解析只經候選池應用服務。"""
        return self.watchlist_service.query_stock_names(stock_codes)

    def _load_universe_to_watchlist(self):
        """從選股清單載入到候選池"""
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
            f"確定要將「{watchlist.name}」({len(watchlist.codes)}檔) 加入到候選池嗎？\n"
            f"（已存在的股票不會重複加入）",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 轉換為觀察清單格式，並查詢股票名稱
        stocks = []
        stock_name_map = self._query_stock_names(watchlist.codes)
        
        for code in watchlist.codes:
            code_str = str(code).strip()
            stock_name = stock_name_map.get(code_str, code_str)
            stocks.append({
                'stock_code': code_str,
                'stock_name': stock_name,
                'notes': f'來自選股清單：{watchlist.name}'
            })
        
        try:
            added_count = self.watchlist_service.add_stocks(stocks, source='universe')
            if added_count > 0:
                QMessageBox.information(self, "成功", f"已加入 {added_count} 檔股票到候選池")
                self._load_watchlist()
                self.watchlistUpdated.emit()
            else:
                QMessageBox.information(self, "提示", "所有股票都已存在於候選池中")
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


"""
SQLite 資料庫視覺化檢視 Widget (SQLite Inspector Widget)
提供資料表選擇、受控條件篩選、資料預覽、欄位 Schema 展示與表狀態摘要。
"""

import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QPushButton, QTabWidget, QTableView, QMessageBox, QGroupBox,
    QHeaderView, QLineEdit, QDateEdit
)
from PySide6.QtCore import Qt, QDate
from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.workers.task_worker import TaskWorker
from app_module.sqlite_inspector_service import SqliteInspectorService


class SqliteInspectorWidget(QWidget):

    def __init__(self, inspector_service: SqliteInspectorService, parent=None):
        """初始化檢視面板
        
        Args:
            inspector_service: SqliteInspectorService 實例
            parent: 父組件
        """
        super().__init__(parent)
        self.inspector_service = inspector_service
        self.logger = logging.getLogger(__name__)
        
        self.current_table = ""
        self.worker: Optional[TaskWorker] = None
        self._active_workers: List[TaskWorker] = []
        
        # 表格 Model
        self.preview_model: Optional[PandasTableModel] = None
        self.schema_model: Optional[PandasTableModel] = None

        # 分頁與查詢狀態
        self.current_page = 1
        self.page_size = 100
        self.total_filtered_records = 0
        self.total_pages = 0
        self._active_request_id = 0
        self._cached_schema_table = ""
        self._cached_schema_df = pd.DataFrame()
        self.sort_column: Optional[str] = None
        self.sort_order = "desc"
        self._null_date = QDate(1900, 1, 1)
        
        self._init_ui()

    def _init_ui(self):
        """初始化 UI 布局與控制項"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 1. 頂部控制與篩選面板
        control_group = QGroupBox("資料庫資料表選擇與受控篩選")
        control_main_layout = QVBoxLayout()
        control_main_layout.setSpacing(8)

        # 第一行：表與筆數限制、載入按鈕
        row1_layout = QHBoxLayout()
        row1_layout.addWidget(QLabel("資料表:"))
        self.table_selector = QComboBox()
        self.table_selector.setMinimumWidth(200)
        self.table_selector.setToolTip(
            "【資料表】\n"
            "選擇要檢視的 SQLite 資料表。載入後可在「數據預覽」分頁瀏覽資料，在「欄位結構」分頁檢視欄位型態。\n"
            "例如每日股價表 (daily_prices)、大盤指數表 (market_indices)、技術指標表 (technical_indicators) 等。"
        )
        self.table_selector.currentTextChanged.connect(self._on_table_changed)
        row1_layout.addWidget(self.table_selector)

        row1_layout.addWidget(QLabel("每頁筆數:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 5000)
        self.limit_spin.setValue(100)
        self.limit_spin.setSingleStep(50)
        self.limit_spin.setToolTip(
            "【每頁筆數】\n"
            "設定查詢時單頁載入筆數，預設 100 筆。過大的筆數可能會導致分頁載入時介面暫時卡頓。"
        )
        row1_layout.addWidget(self.limit_spin)

        self.load_btn = QPushButton("載入數據與結構")
        self.load_btn.setMinimumHeight(30)
        self.load_btn.setToolTip(
            "【載入數據與結構】\n"
            "點擊後向資料庫發出查詢，重設為第一頁，並載入與上方篩選條件相符的資料及該表的欄位 Schema 結構。"
        )
        self.load_btn.clicked.connect(self._load_current_table_data)
        row1_layout.addWidget(self.load_btn)
        row1_layout.addStretch()
        control_main_layout.addLayout(row1_layout)

        # 第二行：篩選條件 (股票代號、股票名稱、分點、日期篩選等)
        row2_layout = QHBoxLayout()
        
        row2_layout.addWidget(QLabel("股票代號:"))
        self.stock_code_input = QLineEdit()
        self.stock_code_input.setPlaceholderText("2330 (選填)")
        self.stock_code_input.setMaximumWidth(100)
        self.stock_code_input.setToolTip(
            "【股票代號】\n"
            "輸入 4 碼股票代號（例如 2330），用以篩選該個股的資料（對應表需含有 stock_id 或相關代號欄位）。"
        )
        row2_layout.addWidget(self.stock_code_input)

        row2_layout.addWidget(QLabel("股票名稱:"))
        self.stock_name_input = QLineEdit()
        self.stock_name_input.setPlaceholderText("台積電 (選填)")
        self.stock_name_input.setMaximumWidth(120)
        self.stock_name_input.setToolTip(
            "【股票名稱】\n"
            "輸入股票中文名稱或關鍵字（例如 台積電），用以模糊篩選該個股資料。"
        )
        row2_layout.addWidget(self.stock_name_input)

        row2_layout.addWidget(QLabel("券商分點:"))
        self.broker_branch_input = QLineEdit()
        self.broker_branch_input.setPlaceholderText("分點名稱 (選填)")
        self.broker_branch_input.setMaximumWidth(140)
        self.broker_branch_input.setToolTip(
            "【券商分點】\n"
            "輸入分點名稱關鍵字（例如 凱基台北），用以篩選分點買賣超資料（僅適用於 broker_flows 表）。"
        )
        row2_layout.addWidget(self.broker_branch_input)

        row2_layout.addWidget(QLabel("單一日期:"))
        today = QDate.currentDate()
        current_month_start = QDate(today.year(), today.month(), 1)

        self.date_input = self._create_optional_date_edit(default_date=today)
        self.date_input.setToolTip(
            "【單一日期】\n"
            "點選特定交易日（格式為 YYYY-MM-DD，如 2026-05-29）來精確過濾當日數據。"
        )
        row2_layout.addWidget(self.date_input)
        self.clear_date_btn = QPushButton("清除")
        self.clear_date_btn.setMaximumWidth(52)
        self.clear_date_btn.clicked.connect(lambda: self._clear_date_edit(self.date_input))
        row2_layout.addWidget(self.clear_date_btn)

        row2_layout.addWidget(QLabel("區間:"))
        self.start_date_input = self._create_optional_date_edit(default_date=current_month_start)
        self.start_date_input.setToolTip(
            "【開始日期】\n"
            "點選日期區間的起始日（格式為 YYYY-MM-DD，如 2026-05-01），用以做範圍查詢（需與結束日期搭配）。"
        )
        row2_layout.addWidget(self.start_date_input)
        row2_layout.addWidget(QLabel("~"))
        self.end_date_input = self._create_optional_date_edit(default_date=today)
        self.end_date_input.setToolTip(
            "【結束日期】\n"
            "點選日期區間的截止日（格式為 YYYY-MM-DD，如 2026-05-29），用以做範圍查詢（需與開始日期搭配）。"
        )
        row2_layout.addWidget(self.end_date_input)
        self.clear_range_btn = QPushButton("清除")
        self.clear_range_btn.setMaximumWidth(52)
        self.clear_range_btn.clicked.connect(self._clear_range_dates)
        row2_layout.addWidget(self.clear_range_btn)

        row2_layout.addStretch()
        control_main_layout.addLayout(row2_layout)

        control_group.setLayout(control_main_layout)
        main_layout.addWidget(control_group)

        # 2. 表狀態摘要 Label
        self.summary_label = QLabel("資料庫狀態：尚未載入")
        self.summary_label.setStyleSheet("color: #555; font-weight: bold; font-size: 13px;")
        main_layout.addWidget(self.summary_label)

        # 3. 中央 TabWidget 頁面展示
        self.tabs = QTabWidget()
        
        # Tab 1: 資料數據預覽
        self.preview_tab = QWidget()
        preview_layout = QVBoxLayout(self.preview_tab)
        
        self.preview_table = QTableView()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setSortIndicatorShown(True)
        self.preview_table.horizontalHeader().sectionClicked.connect(self._on_preview_header_clicked)
        preview_layout.addWidget(self.preview_table)

        # 加入分頁控制列
        pagination_layout = QHBoxLayout()
        self.prev_btn = QPushButton("上一頁")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._on_prev_page)
        pagination_layout.addWidget(self.prev_btn)

        self.page_label = QLabel("第 0 / 0 頁")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumWidth(80)
        pagination_layout.addWidget(self.page_label)

        self.next_btn = QPushButton("下一頁")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_next_page)
        pagination_layout.addWidget(self.next_btn)

        pagination_layout.addSpacing(20)
        pagination_layout.addWidget(QLabel("跳至:"))
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(1, 1)
        self.jump_spin.setMinimumWidth(60)
        pagination_layout.addWidget(self.jump_spin)

        self.jump_btn = QPushButton("跳頁")
        self.jump_btn.setEnabled(False)
        self.jump_btn.clicked.connect(self._on_jump_page)
        pagination_layout.addWidget(self.jump_btn)

        pagination_layout.addStretch()
        self.records_label = QLabel("共 0 筆")
        self.records_label.setStyleSheet("color: #666; font-weight: bold;")
        pagination_layout.addWidget(self.records_label)

        preview_layout.addLayout(pagination_layout)
        self.tabs.addTab(self.preview_tab, "📊 數據預覽")

        # Tab 2: 欄位 Schema 結構
        self.schema_tab = QWidget()
        schema_layout = QVBoxLayout(self.schema_tab)
        self.schema_table = QTableView()
        self.schema_table.setAlternatingRowColors(True)
        schema_layout.addWidget(self.schema_table)
        self.tabs.addTab(self.schema_tab, "🧭 欄位結構 (Schema)")

        main_layout.addWidget(self.tabs, stretch=1)
        self.setLayout(main_layout)

    def _create_optional_date_edit(self, default_date: Optional[QDate] = None) -> QDateEdit:
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setMinimumDate(self._null_date)
        date_edit.setMaximumDate(QDate(2100, 12, 31))
        date_edit.setSpecialValueText("不篩選")
        date_edit.setMinimumWidth(112)
        date_edit.setMaximumWidth(128)
        date_edit.setDate(default_date or self._null_date)
        return date_edit

    def _clear_date_edit(self, date_edit: QDateEdit):
        date_edit.setDate(self._null_date)

    def _clear_range_dates(self):
        self._clear_date_edit(self.start_date_input)
        self._clear_date_edit(self.end_date_input)

    def _date_filter_value(self, date_edit: QDateEdit) -> str:
        if date_edit.date() == self._null_date:
            return ""
        return date_edit.date().toString("yyyy-MM-dd")

    def refresh_tables(self):
        """重新獲取資料表列表並刷新下拉選單"""
        if not self.inspector_service.is_enabled():
            self.summary_label.setText("資料庫狀態：SQLite 未啟用")
            self.table_selector.clear()
            self.load_btn.setEnabled(False)
            return

        tables = self.inspector_service.get_tables()
        self.table_selector.clear()
        if tables:
            self.table_selector.addItems(tables)
            self.load_btn.setEnabled(True)
            self.summary_label.setText(f"資料庫狀態：連線成功，共偵測到 {len(tables)} 個資料表")
        else:
            self.summary_label.setText("資料庫狀態：連線成功，但未找到任何資料表")
            self.load_btn.setEnabled(False)

    def _on_table_changed(self, table_name: str):
        """當下拉選單的資料表變更時"""
        self.current_table = table_name
        self.current_page = 1
        self.total_filtered_records = 0
        self.total_pages = 0
        self.sort_column = None
        self.sort_order = "desc"
        self._update_pagination_ui()

    def _load_current_table_data(self):
        """重新載入目前選定表的 Preview、Schema 與 Info (回到第一頁)"""
        if not self.current_table:
            return

        self.current_page = 1
        self.page_size = self.limit_spin.value()
        self._request_page(load_schema=True)

    def _request_page(self, *, load_schema: bool):
        """發送特定分頁的載入請求"""
        self._set_loading_state(True)
        
        # 獲取篩選值
        stock_code = self.stock_code_input.text().strip()
        stock_name = self.stock_name_input.text().strip()
        broker_branch = self.broker_branch_input.text().strip()
        date_str = self._date_filter_value(self.date_input)
        start_date = self._date_filter_value(self.start_date_input)
        end_date = self._date_filter_value(self.end_date_input)

        request_id = self._active_request_id + 1
        self._active_request_id = request_id
        
        limit = self.page_size
        offset = (self.current_page - 1) * limit
        table_name = self.current_table

        use_cached_schema = (
            not load_schema and 
            self._cached_schema_table == table_name and 
            not self._cached_schema_df.empty
        )

        def fetch_task():
            # 1. 取得 count 總數
            filtered_count = self.inspector_service.query_table_data_count(
                table_name=table_name,
                stock_code=stock_code if stock_code else None,
                stock_name=stock_name if stock_name else None,
                date_str=date_str if date_str else None,
                start_date=start_date if start_date else None,
                end_date=end_date if end_date else None,
                broker_branch=broker_branch if broker_branch else None,
            )
            
            # 2. 取得 Schema df 與 metadata
            if use_cached_schema:
                schema_df = self._cached_schema_df
                info = self.inspector_service.get_table_info(table_name)
            elif load_schema:
                schema_df = self.inspector_service.get_table_schema(table_name)
                info = self.inspector_service.get_table_info(table_name)
            else:
                schema_df = pd.DataFrame()
                info = None

            # 3. 取得分頁 Preview df
            preview_df = self.inspector_service.query_table_data(
                table_name=table_name,
                stock_code=stock_code if stock_code else None,
                stock_name=stock_name if stock_name else None,
                date_str=date_str if date_str else None,
                start_date=start_date if start_date else None,
                end_date=end_date if end_date else None,
                broker_branch=broker_branch if broker_branch else None,
                limit=limit,
                offset=offset,
                sort_column=self.sort_column,
                sort_order=self.sort_order,
            )
            return {
                'request_id': request_id,
                'table_name': table_name,
                'load_schema': load_schema or use_cached_schema,
                'info': info,
                'schema': schema_df,
                'filtered_count': filtered_count,
                'preview': preview_df
            }

        worker = TaskWorker(fetch_task)
        self.worker = worker
        self._active_workers.append(worker)
        worker.finished.connect(
            lambda payload, current_worker=worker: self._on_worker_finished(
                current_worker, payload
            )
        )
        worker.error.connect(
            lambda error_msg, current_worker=worker, current_request_id=request_id:
                self._on_worker_error(current_worker, current_request_id, error_msg)
        )
        worker.cancelled.connect(
            lambda current_worker=worker: self._release_worker(current_worker)
        )
        worker.start()

    def _release_worker(self, worker: TaskWorker):
        """Retain a worker until its thread has fully stopped."""
        if worker.isRunning():
            worker.wait()
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        if self.worker is worker:
            self.worker = None

    def _on_worker_finished(self, worker: TaskWorker, payload: Dict[str, Any]):
        try:
            self._on_table_data_loaded(payload)
        finally:
            self._release_worker(worker)

    def _on_worker_error(
        self,
        worker: TaskWorker,
        request_id: int,
        error_msg: str,
    ):
        try:
            if request_id == self._active_request_id:
                self._on_table_data_error(error_msg)
        finally:
            self._release_worker(worker)

    def _on_table_data_loaded(self, payload: Dict[str, Any]):
        """資料載入完畢，更新 UI 顯示"""
        # stale result 防護：丟棄非當前 request id 的異步結果
        if payload['request_id'] != self._active_request_id:
            return

        self._set_loading_state(False)
        
        info = payload['info']
        schema_df = payload['schema']
        preview_df = payload['preview']
        filtered_count = payload['filtered_count']
        table_name = payload['table_name']

        # 1. 更新狀態摘要 Label
        if payload['load_schema'] and info:
            if info['success']:
                summary_txt = f"資料表：【{info['table_name']}】 | 總記錄數：{info['total_records']:,} 筆 | 欄位數：{info['columns_count']} 個"
                if info['earliest_date'] and info['latest_date']:
                    summary_txt += f" | 日期區間：{info['earliest_date']} 至 {info['latest_date']}"
                self.summary_label.setText(summary_txt)
                
                # 快取 schema 避免分頁時重複拉取描述
                self._cached_schema_table = table_name
                self._cached_schema_df = schema_df
            else:
                self.summary_label.setText(f"資料表載入失敗：{info['message']}")

        # 2. 渲染數據預覽 TableView
        self.preview_model = PandasTableModel(preview_df)
        self.preview_table.setModel(self.preview_model)
        self._adjust_table_header(self.preview_table)

        # 3. 渲染 Schema TableView
        if payload['load_schema'] and not schema_df.empty:
            self.schema_model = PandasTableModel(schema_df)
            self.schema_table.setModel(self.schema_model)
            self._adjust_table_header(self.schema_table)

        # 4. 更新分頁
        self.total_filtered_records = filtered_count
        import math
        self.total_pages = math.ceil(self.total_filtered_records / self.page_size) if self.total_filtered_records else 0

        # 防禦：如果分頁因為篩選更新而越界，clamp 至末頁並重新查詢一次
        if self.current_page > self.total_pages and self.total_pages > 0:
            self.current_page = self.total_pages
            self._request_page(load_schema=False)
            return

        self._update_pagination_ui()

    def _on_preview_header_clicked(self, section: int):
        if self.preview_model is None:
            return
        columns = self.preview_model.getVisibleColumns()
        if section < 0 or section >= len(columns):
            return

        column_name = columns[section]
        if self.sort_column == column_name:
            self.sort_order = "desc" if self.sort_order == "asc" else "asc"
        else:
            self.sort_column = column_name
            self.sort_order = "asc"

        qt_order = Qt.AscendingOrder if self.sort_order == "asc" else Qt.DescendingOrder
        self.preview_table.horizontalHeader().setSortIndicator(section, qt_order)
        self.current_page = 1
        self._request_page(load_schema=False)

    def _on_table_data_error(self, error_msg: str):
        """載入出錯"""
        self._set_loading_state(False)
        QMessageBox.critical(self, "錯誤", f"讀取 SQLite 表資料失敗：\n{error_msg}")
        self.summary_label.setText("資料庫狀態：資料表載入失敗")

    def _update_pagination_ui(self):
        """更新分頁按鈕與文字狀態"""
        if self.total_pages == 0:
            self.page_label.setText("第 0 / 0 頁")
            self.records_label.setText("共 0 筆")
        else:
            self.page_label.setText(f"第 {self.current_page} / {self.total_pages} 頁")
            self.records_label.setText(f"共 {self.total_filtered_records:,} 筆")

        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < self.total_pages)
        self.jump_btn.setEnabled(self.total_pages > 0)
        self.jump_spin.setRange(1, max(1, self.total_pages))
        self.jump_spin.setValue(self.current_page)

    def _on_prev_page(self):
        """上一頁"""
        if self.current_page > 1:
            self.current_page -= 1
            self._request_page(load_schema=False)

    def _on_next_page(self):
        """下一頁"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._request_page(load_schema=False)

    def _on_jump_page(self):
        """跳頁"""
        target_page = self.jump_spin.value()
        if 1 <= target_page <= self.total_pages and target_page != self.current_page:
            self.current_page = target_page
            self._request_page(load_schema=False)

    def _adjust_table_header(self, table_view: QTableView):
        """自適應調整 TableView 欄寬"""
        header = table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table_view.resizeColumnsToContents()
        for col in range(header.count()):
            width = min(max(header.sectionSize(col), 80), 300)
            header.resizeSection(col, width)

    def _set_loading_state(self, is_loading: bool):
        """設定載入狀態"""
        self.load_btn.setEnabled(not is_loading)
        self.table_selector.setEnabled(not is_loading)
        if is_loading:
            self.load_btn.setText("載入中...")
        else:
            self.load_btn.setText("載入數據與結構")



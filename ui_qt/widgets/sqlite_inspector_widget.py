"""
SQLite 資料庫視覺化檢視 Widget (SQLite Inspector Widget)
提供資料表選擇、資料預覽、欄位 Schema 展示、以及自訂 SQL 查詢執行與展示。
"""

import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QPushButton, QTabWidget, QTableView, QTextEdit, QMessageBox, QGroupBox,
    QHeaderView
)
from PySide6.QtCore import Qt
from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.workers.task_worker import TaskWorker
from app_module.sqlite_inspector_service import SqliteInspectorService


class SqliteInspectorWidget(QWidget):
    """SQLite 資料表視覺化檢視與查詢面板"""

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
        
        # 表格 Model
        self.preview_model: Optional[PandasTableModel] = None
        self.schema_model: Optional[PandasTableModel] = None
        self.query_model: Optional[PandasTableModel] = None
        
        self._init_ui()

    def _init_ui(self):
        """初始化 UI 布局與控制項"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 1. 頂部控制面板
        control_group = QGroupBox("資料庫與資料表選擇")
        control_layout = QHBoxLayout()
        control_layout.setSpacing(15)

        # 下拉選單：資料表
        control_layout.addWidget(QLabel("資料表:"))
        self.table_selector = QComboBox()
        self.table_selector.setMinimumWidth(250)
        self.table_selector.currentTextChanged.connect(self._on_table_changed)
        control_layout.addWidget(self.table_selector)

        # SpinBox：Limit 限制
        control_layout.addWidget(QLabel("預覽筆數:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 5000)
        self.limit_spin.setValue(100)
        self.limit_spin.setSingleStep(50)
        control_layout.addWidget(self.limit_spin)

        # 按鈕：載入 Preview & Schema
        self.load_btn = QPushButton("載入數據與結構")
        self.load_btn.setMinimumHeight(35)
        self.load_btn.clicked.connect(self._load_current_table_data)
        control_layout.addWidget(self.load_btn)

        control_layout.addStretch()
        control_group.setLayout(control_layout)
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
        preview_layout.addWidget(self.preview_table)
        self.tabs.addTab(self.preview_tab, "📊 數據預覽")

        # Tab 2: 欄位 Schema 結構
        self.schema_tab = QWidget()
        schema_layout = QVBoxLayout(self.schema_tab)
        self.schema_table = QTableView()
        self.schema_table.setAlternatingRowColors(True)
        schema_layout.addWidget(self.schema_table)
        self.tabs.addTab(self.schema_tab, "🧭 欄位結構 (Schema)")

        # Tab 3: 自訂 SQL 唯讀查詢
        self.query_tab = QWidget()
        query_layout = QVBoxLayout(self.query_tab)
        
        # SQL Editor 控制區
        sql_input_group = QGroupBox("自訂 SQL 唯讀查詢編輯器")
        sql_input_layout = QVBoxLayout()
        
        self.sql_editor = QTextEdit()
        self.sql_editor.setPlaceholderText("請輸入唯讀 SELECT 查詢，例如：\nSELECT * FROM daily_prices WHERE 證券代號 = '2330' ORDER BY 日期 DESC LIMIT 50;")
        self.sql_editor.setMinimumHeight(100)
        self.sql_editor.setMaximumHeight(150)
        sql_input_layout.addWidget(self.sql_editor)
        
        sql_btn_layout = QHBoxLayout()
        self.run_sql_btn = QPushButton("執行 SQL 查詢")
        self.run_sql_btn.setMinimumHeight(35)
        self.run_sql_btn.clicked.connect(self._execute_custom_sql)
        sql_btn_layout.addWidget(self.run_sql_btn)
        
        self.clear_sql_btn = QPushButton("清空編輯器")
        self.clear_sql_btn.clicked.connect(self.sql_editor.clear)
        sql_btn_layout.addWidget(self.clear_sql_btn)
        sql_btn_layout.addStretch()
        
        sql_input_layout.addLayout(sql_btn_layout)
        sql_input_group.setLayout(sql_input_layout)
        query_layout.addWidget(sql_input_group)
        
        # SQL 結果展示區
        sql_result_group = QGroupBox("查詢結果")
        sql_result_layout = QVBoxLayout()
        self.query_table = QTableView()
        self.query_table.setAlternatingRowColors(True)
        sql_result_layout.addWidget(self.query_table)
        
        # SQL 錯誤顯示 Label
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red; font-family: Consolas; font-size: 13px;")
        self.error_label.setWordWrap(True)
        sql_result_layout.addWidget(self.error_label)
        
        sql_result_group.setLayout(sql_result_layout)
        query_layout.addWidget(sql_result_group, stretch=1)
        
        self.tabs.addTab(self.query_tab, "⚡ 自訂 SQL 查詢")

        main_layout.addWidget(self.tabs, stretch=1)
        self.setLayout(main_layout)

    def refresh_tables(self):
        """重新獲取資料表列表並刷新下拉選單"""
        if not self.inspector_service.is_enabled():
            self.summary_label.setText("資料庫狀態：SQLite 未啟用")
            self.table_selector.clear()
            self.load_btn.setEnabled(False)
            self.run_sql_btn.setEnabled(False)
            return

        tables = self.inspector_service.get_tables()
        self.table_selector.clear()
        if tables:
            self.table_selector.addItems(tables)
            self.load_btn.setEnabled(True)
            self.run_sql_btn.setEnabled(True)
            self.summary_label.setText(f"資料庫狀態：連線成功，共偵測到 {len(tables)} 個資料表")
        else:
            self.summary_label.setText("資料庫狀態：連線成功，但未找到任何資料表")
            self.load_btn.setEnabled(False)

    def _on_table_changed(self, table_name: str):
        """當下拉選單的資料表變更時"""
        self.current_table = table_name

    def _load_current_table_data(self):
        """背景線程載入目前選定表的 Preview、Schema 與 Info"""
        if not self.current_table:
            return

        self._set_loading_state(True)
        
        # 取消之前的 Worker
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()

        limit = self.limit_spin.value()
        table_name = self.current_table

        def fetch_task():
            # 1. 取得表 metadata
            info = self.inspector_service.get_table_info(table_name)
            # 2. 取得 Schema df
            schema_df = self.inspector_service.get_table_schema(table_name)
            # 3. 取得 Preview df (使用 execute_query 保障 Limit)
            preview_df = self.inspector_service.execute_query(f"SELECT * FROM {table_name}", limit=limit)
            return {
                'info': info,
                'schema': schema_df,
                'preview': preview_df
            }

        self.worker = TaskWorker(fetch_task)
        self.worker.finished.connect(self._on_table_data_loaded)
        self.worker.error.connect(self._on_table_data_error)
        self.worker.start()

    def _on_table_data_loaded(self, payload: Dict[str, Any]):
        """資料載入完畢，更新 UI 顯示"""
        self._set_loading_state(False)
        
        info = payload['info']
        schema_df = payload['schema']
        preview_df = payload['preview']

        # 1. 更新狀態摘要 Label
        if info['success']:
            summary_txt = f"資料表：【{info['table_name']}】 | 總記錄數：{info['total_records']:,} 筆 | 欄位數：{info['columns_count']} 個"
            if info['earliest_date'] and info['latest_date']:
                summary_txt += f" | 日期區間：{info['earliest_date']} 至 {info['latest_date']}"
            self.summary_label.setText(summary_txt)
        else:
            self.summary_label.setText(f"資料表載入失敗：{info['message']}")

        # 2. 渲染數據預覽 TableView
        self.preview_model = PandasTableModel(preview_df)
        self.preview_table.setModel(self.preview_model)
        self._adjust_table_header(self.preview_table)

        # 3. 渲染 Schema TableView
        self.schema_model = PandasTableModel(schema_df)
        self.schema_table.setModel(self.schema_model)
        self._adjust_table_header(self.schema_table)

    def _on_table_data_error(self, error_msg: str):
        """載入出錯"""
        self._set_loading_state(False)
        QMessageBox.critical(self, "錯誤", f"讀取 SQLite 表資料失敗：\n{error_msg}")
        self.summary_label.setText("資料庫狀態：資料表載入失敗")

    def _execute_custom_sql(self):
        """執行自訂 SQL 查詢"""
        sql_text = self.sql_editor.toPlainText().strip()
        if not sql_text:
            QMessageBox.warning(self, "警告", "請先輸入 SQL 語法！")
            return

        self._set_query_loading_state(True)
        self.error_label.clear()

        # 取消之前的 Worker
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()

        limit = self.limit_spin.value()

        def query_task():
            # 調用 inspector 執行安全唯讀查詢
            return self.inspector_service.execute_query(sql_text, limit=limit)

        self.worker = TaskWorker(query_task)
        self.worker.finished.connect(self._on_query_success)
        self.worker.error.connect(self._on_query_error)
        self.worker.start()

    def _on_query_success(self, df: pd.DataFrame):
        """自訂 SQL 執行成功"""
        self._set_query_loading_state(False)
        
        self.query_model = PandasTableModel(df)
        self.query_table.setModel(self.query_model)
        self._adjust_table_header(self.query_table)
        
        # 提示訊息
        self.error_label.setStyleSheet("color: green; font-weight: bold;")
        self.error_label.setText(f"查詢執行成功，共獲取 {len(df)} 筆資料。")

    def _on_query_error(self, error_msg: str):
        """自訂 SQL 執行出錯"""
        self._set_query_loading_state(False)
        
        # 清空舊結果
        self.query_table.setModel(None)
        
        # 顯示詳細 Traceback 與錯誤字串
        self.error_label.setStyleSheet("color: red; font-family: Consolas; font-size: 13px;")
        self.error_label.setText(f"SQL 執行失敗，錯誤訊息如下：\n{error_msg}")

    def _adjust_table_header(self, table_view: QTableView):
        """自適應調整 TableView 欄寬"""
        header = table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        # 先根據內容自適應，再還原為 Interactive 方便使用者拉伸
        table_view.resizeColumnsToContents()
        # 防禦性設定最大欄寬，防止超大欄位拉得太長
        for col in range(header.count()):
            width = min(max(header.sectionSize(col), 80), 300)
            header.resizeSection(col, width)

    def _set_loading_state(self, is_loading: bool):
        """設定載入狀態按鈕 disable"""
        self.load_btn.setEnabled(not is_loading)
        self.table_selector.setEnabled(not is_loading)
        if is_loading:
            self.load_btn.setText("載入中...")
        else:
            self.load_btn.setText("載入數據與結構")

    def _set_query_loading_state(self, is_loading: bool):
        """設定查詢按鈕 disable"""
        self.run_sql_btn.setEnabled(not is_loading)
        if is_loading:
            self.run_sql_btn.setText("查詢執行中...")
        else:
            self.run_sql_btn.setText("執行 SQL 查詢")

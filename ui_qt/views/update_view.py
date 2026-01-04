"""
數據更新視圖
提供數據更新功能界面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGroupBox, QProgressBar,
    QTextEdit, QRadioButton, QButtonGroup,
    QDateEdit, QMessageBox, QFormLayout, QSpinBox, QLineEdit
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont
from typing import Dict, Any
from datetime import datetime, timedelta

from ui_qt.workers.task_worker import TaskWorker, ProgressTaskWorker
from app_module.update_service import UpdateService
from ui_qt.widgets.info_button import InfoButton


class UpdateView(QWidget):
    """數據更新視圖"""
    
    def __init__(self, update_service: UpdateService, parent=None):
        """初始化數據更新視圖
        
        Args:
            update_service: 數據更新服務實例
            parent: 父窗口
        """
        super().__init__(parent)
        self.update_service = update_service
        
        # Worker
        self.worker: TaskWorker = None
        
        self._setup_ui()
        self._check_data_status()
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("數據更新")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("update", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)
        
        # 數據狀態面板
        status_group = QGroupBox("數據狀態")
        status_layout = QHBoxLayout()  # 改為水平布局，四個區塊並排顯示
        
        # 每日股票數據區塊
        daily_group = QGroupBox("每日股票數據")
        daily_layout = QVBoxLayout()
        self.daily_status_text = QTextEdit()
        self.daily_status_text.setReadOnly(True)
        self.daily_status_text.setMaximumHeight(120)  # 固定高度，不需要滾動
        daily_layout.addWidget(self.daily_status_text)
        daily_group.setLayout(daily_layout)
        status_layout.addWidget(daily_group, stretch=1)
        
        # 大盤指數數據區塊
        market_group = QGroupBox("大盤指數數據")
        market_layout = QVBoxLayout()
        self.market_status_text = QTextEdit()
        self.market_status_text.setReadOnly(True)
        self.market_status_text.setMaximumHeight(120)
        market_layout.addWidget(self.market_status_text)
        market_group.setLayout(market_layout)
        status_layout.addWidget(market_group, stretch=1)
        
        # 產業指數數據區塊
        industry_group = QGroupBox("產業指數數據")
        industry_layout = QVBoxLayout()
        self.industry_status_text = QTextEdit()
        self.industry_status_text.setReadOnly(True)
        self.industry_status_text.setMaximumHeight(120)
        industry_layout.addWidget(self.industry_status_text)
        industry_group.setLayout(industry_layout)
        status_layout.addWidget(industry_group, stretch=1)
        
        # 券商分點數據區塊
        broker_branch_group = QGroupBox("券商分點數據")
        broker_branch_layout = QVBoxLayout()
        self.broker_branch_status_text = QTextEdit()
        self.broker_branch_status_text.setReadOnly(True)
        self.broker_branch_status_text.setMaximumHeight(120)
        broker_branch_layout.addWidget(self.broker_branch_status_text)
        broker_branch_group.setLayout(broker_branch_layout)
        status_layout.addWidget(broker_branch_group, stretch=1)
        
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        # 初始化四個區塊的顯示
        self.daily_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.market_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.industry_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.broker_branch_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        
        # 更新配置面板
        config_group = QGroupBox("更新配置")
        config_layout = QVBoxLayout()
        config_layout.setSpacing(8)  # 減少配置面板的間距
        
        # 更新類型選擇
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("更新類型:"))
        self.update_type_group = QButtonGroup(self)
        
        self.daily_radio = QRadioButton("每日股票數據")
        self.daily_radio.setChecked(True)
        self.update_type_group.addButton(self.daily_radio, 0)
        type_layout.addWidget(self.daily_radio)
        
        self.market_radio = QRadioButton("大盤指數數據")
        self.update_type_group.addButton(self.market_radio, 1)
        type_layout.addWidget(self.market_radio)
        
        self.industry_radio = QRadioButton("產業指數數據")
        self.update_type_group.addButton(self.industry_radio, 2)
        type_layout.addWidget(self.industry_radio)
        
        self.broker_branch_radio = QRadioButton("券商分點資料")
        self.update_type_group.addButton(self.broker_branch_radio, 3)
        type_layout.addWidget(self.broker_branch_radio)
        
        type_layout.addStretch()
        config_layout.addLayout(type_layout)
        
        # 查找缺失日期範圍（用於檢查哪些日期需要下載）
        date_layout = QFormLayout()
        date_layout.setSpacing(5)  # 減少表單布局的間距
        
        # 查找範圍說明
        date_info = QLabel("查找缺失日期範圍（用於檢查需要下載的日期）")
        date_info.setStyleSheet("color: #888; font-size: 13px; padding: 0px;")
        date_layout.addRow("", date_info)
        
        # 結束日期（默認為今天）
        self.end_date = QDateEdit()
        self.end_date.setDate(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        date_layout.addRow("結束日期:", self.end_date)
        
        # 查找範圍（天數）
        self.lookback_days = QSpinBox()
        self.lookback_days.setMinimum(1)
        self.lookback_days.setMaximum(365)
        self.lookback_days.setValue(10)  # 預設改為10天
        self.lookback_days.setSuffix(" 天")
        lookback_layout = QHBoxLayout()
        lookback_layout.addWidget(QLabel("查找範圍:"))
        lookback_layout.addWidget(QLabel("最近"))
        lookback_layout.addWidget(self.lookback_days)
        lookback_layout.addStretch()
        date_layout.addRow("", lookback_layout)
        
        # 說明文字
        note_label = QLabel("說明：系統會在指定範圍內查找缺失的日期並下載。合併時會合併 daily_price/ 目錄中的所有數據（不受範圍限制）。")
        note_label.setStyleSheet("color: #666; font-size: 13px; padding: 0px; margin: 0px;")
        note_label.setWordWrap(True)
        date_layout.addRow("", note_label)
        
        config_layout.addLayout(date_layout)
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)
        
        # 操作按鈕
        button_layout = QHBoxLayout()
        
        self.update_btn = QPushButton("開始更新")
        self.update_btn.setMinimumHeight(40)
        self.update_btn.clicked.connect(self._execute_update)
        button_layout.addWidget(self.update_btn)
        
        self.merge_btn = QPushButton("合併每日數據")
        self.merge_btn.setMinimumHeight(40)
        self.merge_btn.clicked.connect(self._execute_merge)
        button_layout.addWidget(self.merge_btn)
        
        self.force_merge_btn = QPushButton("強制重新合併")
        self.force_merge_btn.setMinimumHeight(40)
        self.force_merge_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; }")
        self.force_merge_btn.clicked.connect(self._execute_force_merge)
        button_layout.addWidget(self.force_merge_btn)
        
        self.merge_broker_branch_btn = QPushButton("合併券商分點資料")
        self.merge_broker_branch_btn.setMinimumHeight(40)
        self.merge_broker_branch_btn.clicked.connect(self._execute_merge_broker_branch)
        button_layout.addWidget(self.merge_broker_branch_btn)
        
        self.check_status_btn = QPushButton("檢查數據狀態")
        self.check_status_btn.setMinimumHeight(40)
        self.check_status_btn.clicked.connect(self._check_data_status)
        button_layout.addWidget(self.check_status_btn)
        
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
        
        # 技術指標計算配置面板
        tech_indicator_group = QGroupBox("技術指標計算")
        tech_layout = QVBoxLayout()
        tech_layout.setSpacing(8)
        
        # 計算模式選擇
        tech_mode_layout = QHBoxLayout()
        tech_mode_layout.addWidget(QLabel("計算模式:"))
        self.tech_mode_group = QButtonGroup(self)
        
        self.tech_incremental_radio = QRadioButton("增量更新（只計算新數據）")
        self.tech_incremental_radio.setChecked(True)
        self.tech_mode_group.addButton(self.tech_incremental_radio, 0)
        tech_mode_layout.addWidget(self.tech_incremental_radio)
        
        self.tech_force_all_radio = QRadioButton("強制全量更新（重新計算所有數據）")
        self.tech_mode_group.addButton(self.tech_force_all_radio, 1)
        tech_mode_layout.addWidget(self.tech_force_all_radio)
        
        tech_mode_layout.addStretch()
        tech_layout.addLayout(tech_mode_layout)
        
        # 股票選擇（可選）
        stock_layout = QFormLayout()
        stock_layout.setSpacing(5)
        
        self.tech_stock_input = QLineEdit()
        self.tech_stock_input.setPlaceholderText("留空則處理所有股票，例如：2330")
        stock_layout.addRow("股票代號（可選）:", self.tech_stock_input)
        
        tech_layout.addLayout(stock_layout)
        
        # 說明文字
        tech_note = QLabel("說明：增量更新會自動檢測最新指標日期，只計算新數據。強制全量更新會重新計算所有股票的技術指標。")
        tech_note.setStyleSheet("color: #666; font-size: 13px; padding: 0px; margin: 0px;")
        tech_note.setWordWrap(True)
        tech_layout.addWidget(tech_note)
        
        tech_indicator_group.setLayout(tech_layout)
        main_layout.addWidget(tech_indicator_group)
        
        # 技術指標計算按鈕
        tech_button_layout = QHBoxLayout()
        
        self.calculate_tech_btn = QPushButton("計算技術指標")
        self.calculate_tech_btn.setMinimumHeight(40)
        self.calculate_tech_btn.clicked.connect(self._execute_calculate_technical_indicators)
        tech_button_layout.addWidget(self.calculate_tech_btn)
        
        tech_button_layout.addStretch()
        main_layout.addLayout(tech_button_layout)
        
        # 進度條
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # 進度文本
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        main_layout.addWidget(self.progress_label)
        
        # 日誌輸出
        log_group = QGroupBox("更新日誌")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group, stretch=2)  # 添加stretch讓日誌區域也能隨視窗縮放
    
    def _check_data_status(self):
        """檢查數據狀態"""
        try:
            # ✅ 取消之前的 Worker（如果存在）
            if self.worker and self.worker.isRunning():
                self.worker.cancel()
                self.worker.wait(3000)  # 等待最多 3 秒
            
            self.check_status_btn.setEnabled(False)
            self.check_status_btn.setText("檢查中...")
            
            # 在背景執行
            def check_task():
                return self.update_service.check_data_status()
            
            self.worker = TaskWorker(check_task)
            self.worker.finished.connect(self._on_status_checked)
            self.worker.error.connect(self._on_status_error)
            self.worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"檢查數據狀態失敗：\n{str(e)}")
            self.check_status_btn.setEnabled(True)
            self.check_status_btn.setText("檢查數據狀態")
    
    def _on_status_checked(self, status: Dict[str, Any]):
        """數據狀態檢查完成"""
        self.check_status_btn.setEnabled(True)
        self.check_status_btn.setText("檢查數據狀態")
        
        # 分別更新四個區塊
        daily_text = ""
        market_text = ""
        industry_text = ""
        broker_branch_text = ""
        
        for key, value in status.items():
            latest_date = value.get('latest_date', '未知')
            total_records = value.get('total_records', 0)
            status_str = value.get('status', 'unknown')
            
            status_display = f"最新日期：{latest_date}\n總記錄數：{total_records:,}\n狀態：{status_str}"
            
            if key == 'daily_data':
                daily_text = status_display
            elif key == 'market_index':
                market_text = status_display
            elif key == 'industry_index':
                industry_text = status_display
            elif key == 'broker_branch':
                broker_branch_text = status_display
        
        # 如果沒有數據，顯示提示
        if not daily_text:
            daily_text = "尚未檢查"
        if not market_text:
            market_text = "尚未檢查"
        if not industry_text:
            industry_text = "尚未檢查"
        if not broker_branch_text:
            broker_branch_text = "尚未檢查"
        
        self.daily_status_text.setPlainText(daily_text)
        self.market_status_text.setPlainText(market_text)
        self.industry_status_text.setPlainText(industry_text)
        self.broker_branch_status_text.setPlainText(broker_branch_text)
        self._log(f"數據狀態檢查完成")
    
    def _on_status_error(self, error_msg: str):
        """數據狀態檢查出錯"""
        self.check_status_btn.setEnabled(True)
        self.check_status_btn.setText("檢查數據狀態")
        QMessageBox.critical(self, "錯誤", f"檢查數據狀態失敗：\n{error_msg}")
        self._log(f"錯誤：{error_msg}")
    
    def _execute_update(self):
        """執行數據更新"""
        # 獲取更新類型
        update_type = None
        if self.daily_radio.isChecked():
            update_type = 'daily'
        elif self.market_radio.isChecked():
            update_type = 'market'
        elif self.industry_radio.isChecked():
            update_type = 'industry'
        elif self.broker_branch_radio.isChecked():
            update_type = 'broker_branch'
        
        # 獲取查找範圍
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        lookback_days = self.lookback_days.value()
        
        # 計算開始日期（從結束日期往前推）
        from datetime import datetime, timedelta
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        start_date_obj = end_date_obj - timedelta(days=lookback_days)
        start_date = start_date_obj.strftime("%Y-%m-%d")
        
        # 禁用按鈕
        self.update_btn.setEnabled(False)
        self.update_btn.setText("更新中...")
        
        # 顯示進度條
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不確定進度
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"正在更新{self._get_update_type_name(update_type)}...")
        
        # 清空日誌
        self.log_text.clear()
        self._log(f"開始更新 {self._get_update_type_name(update_type)}")
        self._log(f"查找範圍：{start_date} 至 {end_date}（最近 {lookback_days} 天）")
        self._log(f"說明：系統會在該範圍內查找缺失的日期並下載，合併時會合併所有數據")
        
        # ✅ 取消之前的 Worker（如果存在）
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)  # 等待最多 3 秒
        
        # 創建 Worker 任務
        def update_task():
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行更新任務: update_type={update_type}")
                if update_type == 'daily':
                    result = self.update_service.update_daily(start_date, end_date)
                elif update_type == 'market':
                    result = self.update_service.update_market(start_date, end_date)
                elif update_type == 'industry':
                    result = self.update_service.update_industry(start_date, end_date)
                elif update_type == 'broker_branch':
                    result = self.update_service.update_broker_branch(start_date, end_date)
                else:
                    raise ValueError(f"未知的更新類型：{update_type}")
                logger.info(f"[UpdateView] 更新任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"更新任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                # ✅ 不要 raise，讓 Worker 的異常處理機制處理
                raise
        
        self.worker = TaskWorker(update_task)
        self.worker.finished.connect(self._on_update_finished)
        self.worker.error.connect(self._on_update_error)
        self.worker.start()
    
    def _on_update_finished(self, result: Dict[str, Any]):
        """更新完成"""
        # 恢復按鈕
        self.update_btn.setEnabled(True)
        self.update_btn.setText("開始更新")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示結果
        if result.get('success', False):
            message = result.get('message', '更新完成')
            updated_dates = result.get('updated_dates', [])
            failed_dates = result.get('failed_dates', [])
            
            self._log(f"更新完成：{message}")
            if updated_dates:
                self._log(f"成功更新日期：{len(updated_dates)} 個")
            if failed_dates:
                self._log(f"失敗日期：{len(failed_dates)} 個")
            
            QMessageBox.information(self, "更新完成", message)
            
            # 自動刷新數據狀態
            self._check_data_status()
        else:
            message = result.get('message', '更新失敗')
            self._log(f"更新失敗：{message}")
            QMessageBox.warning(self, "更新失敗", message)
    
    def _on_update_error(self, error_msg: str):
        """更新出錯"""
        # 恢復按鈕
        self.update_btn.setEnabled(True)
        self.update_btn.setText("開始更新")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")
        QMessageBox.critical(self, "更新失敗", f"數據更新失敗：\n{error_msg}")
    
    def _get_update_type_name(self, update_type: str) -> str:
        """獲取更新類型名稱"""
        names = {
            'daily': '每日股票數據',
            'market': '大盤指數數據',
            'industry': '產業指數數據',
            'broker_branch': '券商分點資料'
        }
        return names.get(update_type, update_type)
    
    def _execute_merge(self):
        """執行數據合併（增量合併）"""
        # 確認對話框
        reply = QMessageBox.question(
            self, 
            "確認合併", 
            "確定要合併每日股票數據嗎？\n這將把 daily_price/ 目錄中的新 CSV 文件合併到 stock_data_whole.csv\n（只合併新數據，不會重新合併已有數據）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self._do_merge(force_all=False)
    
    def _execute_force_merge(self):
        """執行強制重新合併所有數據"""
        # 警告對話框
        reply = QMessageBox.warning(
            self, 
            "警告：強制重新合併", 
            "確定要強制重新合併所有數據嗎？\n\n"
            "⚠️ 這將：\n"
            "• 忽略現有的 stock_data_whole.csv\n"
            "• 重新合併 daily_price/ 目錄中的所有 CSV 文件\n"
            "• 可能需要較長時間\n\n"
            "建議：只有在需要完全重建數據時才使用此功能",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self._do_merge(force_all=True)
    
    def _do_merge(self, force_all: bool = False):
        """執行合併操作（內部方法）"""
        # 禁用按鈕
        if force_all:
            self.force_merge_btn.setEnabled(False)
            self.force_merge_btn.setText("強制合併中...")
        else:
            self.merge_btn.setEnabled(False)
            self.merge_btn.setText("合併中...")
        
        # 顯示進度條
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不確定進度
        self.progress_label.setVisible(True)
        if force_all:
            self.progress_label.setText("正在強制重新合併所有每日股票數據...")
        else:
            self.progress_label.setText("正在合併每日股票數據...")
        
        # 清空日誌
        self.log_text.clear()
        if force_all:
            self._log("開始強制重新合併所有每日股票數據")
        else:
            self._log("開始合併每日股票數據（增量模式）")
        
        # ✅ 取消之前的 Worker（如果存在）
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)  # 等待最多 3 秒
        
        # 創建 Worker 任務
        def merge_task():
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行合併任務: force_all={force_all}")
                result = self.update_service.merge_daily_data(force_all=force_all)
                logger.info(f"[UpdateView] 合併任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"合併任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                # ✅ 不要 raise，讓 Worker 的異常處理機制處理
                raise
        
        self.worker = TaskWorker(merge_task)
        self.worker.finished.connect(self._on_merge_finished)
        self.worker.error.connect(self._on_merge_error)
        self.worker.start()
    
    def _on_merge_finished(self, result: Dict[str, Any]):
        """合併完成"""
        # 恢復按鈕
        self.merge_btn.setEnabled(True)
        self.merge_btn.setText("合併每日數據")
        self.force_merge_btn.setEnabled(True)
        self.force_merge_btn.setText("強制重新合併")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示結果
        if result.get('success', False):
            message = result.get('message', '合併完成')
            total_records = result.get('total_records', 0)
            merged_files = result.get('merged_files', 0)
            
            self._log(f"合併完成：{message}")
            if total_records > 0:
                self._log(f"總記錄數：{total_records:,}")
            if merged_files > 0:
                self._log(f"合併文件數：{merged_files}")
            
            QMessageBox.information(self, "合併完成", f"{message}\n總記錄數：{total_records:,}")
            
            # 自動刷新數據狀態
            self._check_data_status()
        else:
            message = result.get('message', '合併失敗')
            self._log(f"合併失敗：{message}")
            QMessageBox.warning(self, "合併失敗", message)
    
    def _on_merge_error(self, error_msg: str):
        """合併出錯"""
        import logging
        logger = logging.getLogger(__name__)
        
        # ✅ 記錄錯誤
        logger.error(f"[UpdateView] 合併數據時發生錯誤: {error_msg}")
        
        # 恢復按鈕
        self.merge_btn.setEnabled(True)
        self.merge_btn.setText("合併每日數據")
        self.force_merge_btn.setEnabled(True)
        self.force_merge_btn.setText("強制重新合併")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")
        
        # ✅ 顯示更友好的錯誤訊息
        error_display = error_msg
        if len(error_msg) > 500:
            error_display = error_msg[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整信息）"
        
        QMessageBox.critical(
            self, 
            "合併失敗", 
            f"數據合併失敗：\n\n{error_display}\n\n請查看日誌獲取詳細信息。"
        )
    
    def _execute_merge_broker_branch(self):
        """執行券商分點資料合併"""
        # 確認對話框
        reply = QMessageBox.question(
            self,
            "確認合併",
            "確定要合併券商分點資料嗎？\n這將把各分點的 daily/ 目錄中的新 CSV 文件合併到 meta/merged.csv\n（只合併新數據，不會重新合併已有數據）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 禁用按鈕
        self.merge_broker_branch_btn.setEnabled(False)
        self.merge_broker_branch_btn.setText("合併中...")
        
        # 顯示進度條
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不確定進度
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在合併券商分點資料...")
        
        # 清空日誌
        self.log_text.clear()
        self._log("開始合併券商分點資料（增量模式）")
        
        # ✅ 取消之前的 Worker（如果存在）
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        
        # 創建 Worker 任務
        def merge_task():
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行券商分點資料合併任務")
                result = self.update_service.merge_broker_branch_data()
                logger.info(f"[UpdateView] 券商分點資料合併任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"券商分點資料合併任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                raise
        
        self.worker = TaskWorker(merge_task)
        self.worker.finished.connect(self._on_merge_broker_branch_finished)
        self.worker.error.connect(self._on_merge_broker_branch_error)
        self.worker.start()
    
    def _on_merge_broker_branch_finished(self, result: Dict[str, Any]):
        """券商分點資料合併完成"""
        # 恢復按鈕
        self.merge_broker_branch_btn.setEnabled(True)
        self.merge_broker_branch_btn.setText("合併券商分點資料")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
            # 顯示結果
        if result.get('success', False):
            message = result.get('message', '合併完成')
            merged_branches = result.get('merged_branches', [])
            new_records = result.get('new_records', 0)
            total_records = result.get('total_records', 0)
            date_range = result.get('date_range', {})
            
            self._log(f"合併完成：{message}")
            if merged_branches:
                self._log(f"成功合併的分點：{len(merged_branches)} 個")
            if new_records > 0:
                self._log(f"新增記錄數：{new_records:,}")
            if total_records > 0:
                self._log(f"總記錄數：{total_records:,}")
            
            # 構建詳細訊息
            detail_message = f"{message}\n\n成功合併分點：{len(merged_branches)} 個\n新增記錄：{new_records:,}\n總記錄：{total_records:,}"
            if date_range.get('start_date') and date_range.get('end_date'):
                detail_message += f"\n\n日期範圍：{date_range['start_date']} 至 {date_range['end_date']}"
                detail_message += f"\n最新日期：{date_range['end_date']}"
            
            QMessageBox.information(
                self,
                "券商分點資料合併完成",
                detail_message
            )
            
            # 自動刷新數據狀態
            self._check_data_status()
        else:
            message = result.get('message', '合併失敗')
            self._log(f"合併失敗：{message}")
            QMessageBox.warning(self, "合併失敗", message)
    
    def _on_merge_broker_branch_error(self, error_msg: str):
        """券商分點資料合併出錯"""
        # 恢復按鈕
        self.merge_broker_branch_btn.setEnabled(True)
        self.merge_broker_branch_btn.setText("合併券商分點資料")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")
        
        # 顯示友好的錯誤訊息
        error_display = error_msg
        if len(error_msg) > 500:
            error_display = error_msg[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整信息）"
        
        QMessageBox.critical(
            self,
            "合併失敗",
            f"券商分點資料合併失敗：\n\n{error_display}\n\n請查看日誌獲取詳細信息。"
        )
    
    def _log(self, message: str):
        """添加日誌"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def _execute_calculate_technical_indicators(self):
        """執行技術指標計算"""
        # 獲取計算模式
        force_all = self.tech_force_all_radio.isChecked()
        
        # 獲取股票代號（如果指定）
        target_stock = self.tech_stock_input.text().strip()
        if not target_stock:
            target_stock = None
        
        # 確認對話框
        if force_all:
            reply = QMessageBox.question(
                self,
                "確認計算",
                "確定要強制全量更新技術指標嗎？\n\n"
                "⚠️ 這將重新計算所有股票的技術指標，可能需要較長時間。\n\n"
                "建議：只有在需要完全重建指標時才使用此功能。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self,
                "確認計算",
                f"確定要計算技術指標嗎？\n\n"
                f"模式：增量更新（只計算新數據）\n"
                f"{'股票：' + target_stock if target_stock else '股票：全部'}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
        
        if reply != QMessageBox.Yes:
            return
        
        # 禁用按鈕
        self.calculate_tech_btn.setEnabled(False)
        self.calculate_tech_btn.setText("計算中...")
        
        # 顯示進度條
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("準備開始計算技術指標...")
        
        # 清空日誌
        self.log_text.clear()
        mode_text = "強制全量更新" if force_all else "增量更新"
        stock_text = f"股票：{target_stock}" if target_stock else "股票：全部"
        self._log(f"開始計算技術指標（{mode_text}，{stock_text}）")
        
        # ✅ 取消之前的 Worker（如果存在）
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        
        # 創建 Worker 任務（使用 ProgressTaskWorker 支持進度回調）
        def calculate_task(progress_callback=None):
            """技術指標計算任務（支持進度回調）"""
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行技術指標計算任務: target_stock={target_stock}, force_all={force_all}")
                result = self.update_service.calculate_technical_indicators(
                    target_stock=target_stock,
                    force_all=force_all,
                    start_date=None,
                    progress_callback=progress_callback
                )
                logger.info(f"[UpdateView] 技術指標計算任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"技術指標計算任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                raise
        
        self.worker = ProgressTaskWorker(calculate_task)
        self.worker.progress.connect(self._on_tech_progress)
        self.worker.finished.connect(self._on_tech_calculate_finished)
        self.worker.error.connect(self._on_tech_calculate_error)
        self.worker.start()
    
    def _on_tech_progress(self, message: str, progress: int):
        """技術指標計算進度更新"""
        self.progress_label.setText(message)
        self.progress_bar.setValue(progress)
        self._log(f"[進度 {progress}%] {message}")
    
    def _on_tech_calculate_finished(self, result: Dict[str, Any]):
        """技術指標計算完成"""
        # 恢復按鈕
        self.calculate_tech_btn.setEnabled(True)
        self.calculate_tech_btn.setText("計算技術指標")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示結果
        if result.get('success', False):
            message = result.get('message', '計算完成')
            total_stocks = result.get('total_stocks', 0)
            success_count = result.get('success_count', 0)
            fail_count = result.get('fail_count', 0)
            insufficient_count = result.get('insufficient_data_count', 0)
            updated_stocks = result.get('updated_stocks', [])
            failed_stocks = result.get('failed_stocks', [])
            
            self._log(f"計算完成：{message}")
            if updated_stocks:
                self._log(f"成功更新的股票：{len(updated_stocks)} 檔")
                if len(updated_stocks) <= 10:
                    self._log(f"股票列表：{', '.join(updated_stocks)}")
            if failed_stocks:
                self._log(f"失敗的股票：{len(failed_stocks)} 檔")
                if len(failed_stocks) <= 10:
                    self._log(f"股票列表：{', '.join(failed_stocks)}")
            
            # 顯示詳細結果對話框
            detail_message = (
                f"技術指標計算完成\n\n"
                f"總處理股票數：{total_stocks}\n"
                f"成功處理數：{success_count}\n"
                f"失敗數：{fail_count}\n"
                f"數據不足股票數：{insufficient_count}\n"
                f"處理數據日期範圍：{result.get('start_date', '未知')} 至 {result.get('end_date', '未知')}"
            )
            
            QMessageBox.information(self, "計算完成", detail_message)
        else:
            message = result.get('message', '計算失敗')
            self._log(f"計算失敗：{message}")
            QMessageBox.warning(self, "計算失敗", message)
    
    def _on_tech_calculate_error(self, error_msg: str):
        """技術指標計算出錯"""
        # 恢復按鈕
        self.calculate_tech_btn.setEnabled(True)
        self.calculate_tech_btn.setText("計算技術指標")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")
        
        # 顯示友好的錯誤訊息
        error_display = error_msg
        if len(error_msg) > 500:
            error_display = error_msg[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整信息）"
        
        QMessageBox.critical(
            self,
            "計算失敗",
            f"技術指標計算失敗：\n\n{error_display}\n\n請查看日誌獲取詳細信息。"
        )
    
    def closeEvent(self, event):
        """關閉事件"""
        # ✅ 取消正在運行的 Worker 並等待完成
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            # 等待線程完成（最多等待 5 秒）
            if not self.worker.wait(5000):
                # 如果等待超時，強制終止
                self.worker.terminate()
                self.worker.wait(1000)
        event.accept()


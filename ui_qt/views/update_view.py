"""
數據更新視圖
提供數據更新功能界面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGroupBox, QProgressBar,
    QTextEdit, QRadioButton, QButtonGroup,
    QDateEdit, QMessageBox, QFormLayout, QSpinBox, QLineEdit,
    QListWidget, QStackedWidget, QFrame
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from ui_qt.workers.task_worker import TaskWorker, ProgressTaskWorker
from app_module.update_service import UpdateService
from ui_qt.widgets.info_button import InfoButton





class StatusCard(QFrame):
    """自訂美化數據狀態卡片，與 QTextEdit 介面相容 (Sci-Fi 暗色風格)"""
    def __init__(self, title: str, icon_str: str = "📊", parent=None):
        super().__init__(parent)
        self.title = title
        self.icon_str = icon_str
        self._raw_text = ""
        
        self.setObjectName("CardFrame")
        # 設置現代暗色玻璃擬態樣式
        self.setStyleSheet("""
            QFrame#CardFrame {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(30, 41, 59, 0.65), 
                    stop:1 rgba(15, 23, 42, 0.8)
                );
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            QFrame#CardFrame:hover {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(51, 65, 85, 0.75), 
                    stop:1 rgba(30, 41, 59, 0.85)
                );
                border: 1px solid rgba(255, 255, 255, 0.18);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        
        # 頂部：圖示 + 標題 + 狀態燈
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)
        
        self.title_label = QLabel(f"<span style='font-size:12px; font-weight:bold; color:#cbd5e1;'>{icon_str} {title}</span>")
        self.indicator_label = QLabel("<span style='font-size:13px; color:#94a3b8;'>⚪</span>")
        
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.indicator_label)
        layout.addLayout(header_layout)
        
        # 中間最新日期
        self.date_label = QLabel("<span style='color:#94a3b8;'>最新日期：</span><b style='color:#f8fafc;'>--</b>")
        self.date_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.date_label)
        
        # 總筆數
        self.records_label = QLabel("<span style='color:#94a3b8;'>總記錄數：</span><b style='color:#f8fafc;'>--</b>")
        self.records_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.records_label)
        
        # 額外資訊（例如技術指標數量）
        self.extra_label = QLabel("")
        self.extra_label.setStyleSheet("color:#94a3b8; font-size: 11px;")
        self.extra_label.setVisible(False)
        layout.addWidget(self.extra_label)
        
    def setPlainText(self, text: str):
        """相容 QTextEdit.setPlainText，用於解析並更新卡片 UI"""
        self._raw_text = text
        
        latest_date = "未知"
        total_records = "--"
        status_str = "unknown"
        extra_info = ""
        
        lines = text.split('\n')
        for line in lines:
            if "最新日期" in line:
                latest_date = line.split("：")[-1].strip()
            elif "總記錄數" in line:
                total_records = line.split("：")[-1].strip()
            elif "狀態" in line:
                status_str = line.split("：")[-1].strip()
            elif "指標檔數" in line:
                extra_info = line.strip()
                
        self.date_label.setText(f"<span style='color:#94a3b8;'>最新日期：</span><b style='color:#f8fafc;'>{latest_date}</b>")
        self.records_label.setText(f"<span style='color:#94a3b8;'>總記錄數：</span><b style='color:#f8fafc;'>{total_records}</b>")
        
        if extra_info:
            self.extra_label.setText(f"<span style='color:#94a3b8;'>{extra_info}</span>")
            self.extra_label.setVisible(True)
        else:
            self.extra_label.setVisible(False)
            
        # 燈號判定
        if "點擊" in text or "尚未檢查" in text:
            self.indicator_label.setText("<span style='font-size:13px; color:#94a3b8;'>⚪</span>") # 未檢查
        elif "錯誤" in text or "失敗" in text or "異常" in text:
            self.indicator_label.setText("<span style='font-size:13px; color:#ef4444;'>🔴</span>") # 異常
        elif "success" in status_str or "正常" in status_str or "最新" in text:
            self.indicator_label.setText("<span style='font-size:13px; color:#22c55e;'>🟢</span>") # 正常/最新
        else:
            self.indicator_label.setText("<span style='font-size:13px; color:#eab308;'>🟡</span>") # 待更新
            
    def toPlainText(self) -> str:
        """相容 QTextEdit.toPlainText"""
        return self._raw_text

    def setReadOnly(self, ro: bool):
        """相容 QTextEdit.setReadOnly"""
        pass
        
    def setMaximumHeight(self, h: int):
        """相容 QTextEdit.setMaximumHeight"""
        pass
        
    def clear(self):
        """清除卡片"""
        self.date_label.setText("最新日期：--")
        self.records_label.setText("總記錄數：--")
        self.extra_label.setVisible(False)
        self.indicator_label.setText("⚪")


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
        self._loaded_detail_sources: set[str] = set()
        
        # Worker
        self.worker: Optional[TaskWorker] = None
        
        self._setup_ui()
        self._check_data_status()
    
    def _setup_ui(self):
        """設置 UI"""
        # 最外層主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # 1. 隱藏的 Radio Buttons（保留底層代碼的屬性相容性，使之不受改動影響）
        self.hidden_widget = QWidget()
        hidden_layout = QVBoxLayout(self.hidden_widget)
        self.update_type_group = QButtonGroup(self)
        self.daily_radio = QRadioButton("每日股票數據")
        self.market_radio = QRadioButton("大盤指數數據")
        self.industry_radio = QRadioButton("產業指數數據")
        self.broker_branch_radio = QRadioButton("券商分點資料")
        self.update_type_group.addButton(self.daily_radio, 0)
        self.update_type_group.addButton(self.market_radio, 1)
        self.update_type_group.addButton(self.industry_radio, 2)
        self.update_type_group.addButton(self.broker_branch_radio, 3)
        self.daily_radio.setChecked(True)
        hidden_layout.addWidget(self.daily_radio)
        hidden_layout.addWidget(self.market_radio)
        hidden_layout.addWidget(self.industry_radio)
        hidden_layout.addWidget(self.broker_branch_radio)
        self.hidden_widget.setVisible(False)
        main_layout.addWidget(self.hidden_widget)

        # 2. 隱藏的全域日期變數（使底層一鍵更新/單項更新抓取 UI 輸入的邏輯直接生效）
        self.end_date = QDateEdit()
        self.end_date.setDate(QDate.currentDate())
        self.lookback_days = QSpinBox()
        self.lookback_days.setRange(1, 365)
        self.lookback_days.setValue(10)

        # 3. 左右分欄的導覽區域
        workbench_layout = QHBoxLayout()
        workbench_layout.setSpacing(15)

        # 左側導覽列
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(160)
        self.nav_list.setStyleSheet("""
            QListWidget {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                background-color: rgba(15, 23, 42, 0.5);
                padding: 5px;
            }
            QListWidget::item {
                height: 38px;
                border-radius: 6px;
                padding-left: 10px;
                margin-bottom: 2px;
                color: #cbd5e1;
            }
            QListWidget::item:hover {
                background-color: rgba(51, 65, 85, 0.5);
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
            }
        """)

        self._nav_items = [
            ("all", "全部資料"),
            ("daily", "每日股價"),
            ("market", "大盤指數"),
            ("industry", "產業指數"),
            ("broker_branch", "券商分點"),
            ("technical", "技術指標"),
            ("db_inspector", "SQLite 資料檢視"),
        ]
        for _, label in self._nav_items:
            self.nav_list.addItem(label)

        # 右側堆疊視窗
        self.content_stack = QStackedWidget()
        
        # 建立看板（全部資料）頁面
        all_page = QWidget()
        all_layout = QVBoxLayout(all_page)
        all_layout.setSpacing(15)
        all_layout.setContentsMargins(0, 0, 0, 0)
        
        # 頂部標題列
        title_layout = QHBoxLayout()
        title = QLabel("數據更新看板")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #f8fafc;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("update", self)
        title_layout.addWidget(info_btn)
        all_layout.addLayout(title_layout)

        # 看板說明
        desc_label = QLabel("此處提供整個系統的資料狀態概覽。您可以點選下方一鍵安全更新來同步最新資料，或點選左側進行個別資料維護。")
        desc_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        desc_label.setWordWrap(True)
        all_layout.addWidget(desc_label)

        # 數據狀態卡片網格（精美 StatusCard 呈現，取代原先 status_group 內 5 個 TextEdit）
        # 我們將它們宣告為 class member，使底層 _on_status_checked 能直接使用
        self.daily_status_text = StatusCard("每日股票數據", "📊", self)
        self.market_status_text = StatusCard("大盤指數數據", "🧭", self)
        self.industry_status_text = StatusCard("產業指數數據", "🏢", self)
        self.broker_branch_status_text = StatusCard("券商分點數據", "🤝", self)
        self.technical_status_text = StatusCard("技術指標數據", "📈", self)

        # 卡片佈局
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)
        cards_layout.addWidget(self.daily_status_text)
        cards_layout.addWidget(self.market_status_text)
        cards_layout.addWidget(self.industry_status_text)
        cards_layout.addWidget(self.broker_branch_status_text)
        cards_layout.addWidget(self.technical_status_text)
        all_layout.addLayout(cards_layout)

        # 一鍵安全更新與輔助按鈕
        actions_layout = QHBoxLayout()
        self.safe_update_all_btn = QPushButton("安全更新所有數據")
        self.safe_update_all_btn.setMinimumHeight(45)
        self.safe_update_all_btn.setToolTip(
            "【安全更新所有數據】\n"
            "日常維護最推薦！一鍵自動執行資料狀態檢查、下載缺失資料、\n"
            "增量同步寫入 SQLite 資料庫、智慧增量重算技術指標並自動刷新大看板。\n"
            "出錯時會自動中止並回報失敗步驟，是最安全的日常更新方式。"
        )
        self.safe_update_all_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 24px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
            QPushButton:pressed {
                background: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #cbd5e1;
                color: #94a3b8;
            }
        """)
        self.safe_update_all_btn.clicked.connect(self._execute_safe_update_all)

        self.check_status_btn = QPushButton("🔍 檢查數據狀態")
        self.check_status_btn.setMinimumHeight(45)
        self.check_status_btn.setToolTip(
            "【🔍 檢查數據狀態】\n"
            "查詢並重新偵測 SQLite 資料庫與本地 Raw 原始檔案的最新交易日與總記錄數，\n"
            "並更新上方 5 張狀態卡片的狀態燈號（🟢最新/🟡待更新/🔴異常/⚪未檢查）。\n"
            "檢查結果會同步呈現在頂部卡片與下方日誌主控台中。"
        )
        self.check_status_btn.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
            }
            QPushButton:pressed {
                background-color: #cbd5e1;
            }
            QPushButton:disabled {
                background-color: #f8fafc;
                color: #cbd5e1;
            }
        """)
        self.check_status_btn.clicked.connect(self._check_data_status)

        actions_layout.addWidget(self.safe_update_all_btn, stretch=2)
        actions_layout.addWidget(self.check_status_btn, stretch=1)
        all_layout.addLayout(actions_layout)
        all_layout.addStretch()
        
        self.content_stack.addWidget(all_page)

        # 建立其他分頁
        for key, label in self._nav_items[1:]:
            if key == "db_inspector":
                config = getattr(self.update_service, "config", None)
                if config is None:
                    page = QWidget()
                    page_layout = QVBoxLayout(page)
                    page_layout.addWidget(QLabel("SQLite 未啟用或測試環境中無 Config"))
                    self.content_stack.addWidget(page)
                    continue
                
                from app_module.sqlite_inspector_service import SqliteInspectorService
                from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
                service = SqliteInspectorService(config)
                page = SqliteInspectorWidget(service, self)
                self.content_stack.addWidget(page)
                continue

            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(15)
            
            # 分頁標題
            sub_title_layout = QHBoxLayout()
            sub_title = QLabel(label)
            sub_title_font = QFont()
            sub_title_font.setPointSize(13)
            sub_title_font.setBold(True)
            sub_title.setFont(sub_title_font)
            sub_title.setStyleSheet("color: #1e293b;")
            sub_title_layout.addWidget(sub_title)
            sub_title_layout.addStretch()
            page_layout.addLayout(sub_title_layout)

            self._add_source_tab_content(page_layout, key)
            self.content_stack.addWidget(page)

        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        
        workbench_layout.addWidget(self.nav_list)
        workbench_layout.addWidget(self.content_stack, stretch=1)
        main_layout.addLayout(workbench_layout)
        
        # 4. 底部全域共享的進度條與日誌 console
        main_layout.addWidget(QLabel("")) # 微小間隔
        
        # 進度文字與進度條
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #475569; font-size: 12px;")
        self.progress_label.setVisible(False)
        main_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                text-align: center;
                background-color: #f1f5f9;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 5px;
            }
        """)
        main_layout.addWidget(self.progress_bar)

        # 日誌 Console
        log_group = QGroupBox("日誌主控台")
        log_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 15px;
                font-weight: bold;
                color: #475569;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(10, 15, 10, 10)
        
        # 日誌輔助工具列 (如清除日誌)
        log_toolbar = QHBoxLayout()
        log_toolbar.addStretch()
        clear_log_btn = QPushButton("🧹 清除日誌")
        clear_log_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #64748b;
                border: none;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #ef4444;
            }
        """)
        clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        log_toolbar.addWidget(clear_log_btn)
        log_layout.addLayout(log_toolbar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #0f172a;
                color: #cbd5e1;
                font-family: 'Consolas', 'Fira Code', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #1e293b;
                border-radius: 6px;
            }
        """)
        log_layout.addWidget(self.log_text)
        log_group.setMaximumHeight(180)  # 固定主控台高度
        main_layout.addWidget(log_group)

        # 初始化四個區塊的顯示 (卡片)
        self.daily_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.market_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.industry_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.broker_branch_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.technical_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")

        self.nav_list.setCurrentRow(0)

    def _add_source_tab_content(self, layout: QVBoxLayout, key: str):
        """為個別資料源維護分頁建立專屬操作與手動配置界面"""
        descriptions = {
            "daily": "檢查與維護每日股價原始資料與 SQLite 對應數據。此處支援增量合併與 Danger Zone 強制重新合併。",
            "market": "檢查與更新加權指數大盤數據。此處會將大盤資料同步儲存至資料庫的 market_indices 表。",
            "industry": "檢查與更新產業指數數據，可將各產業分類的歷史指數同步至 industry_indices 表。",
            "broker_branch": "維護 MoneyDJ 的 6 大追蹤分點之買賣超資料，並可執行券商分點合併至 SQLite broker_flows 表。",
            "technical": "增量或全量重新計算個股的技術指標（KD, MACD, RSI 等），並高速批量儲存至資料庫中。",
        }
        
        desc_label = QLabel(descriptions.get(key, "檢查此資料來源的更新狀態。"))
        desc_label.setStyleSheet("color: #64748b; font-size: 12px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # 針對需要日期設定的分頁（daily, market, industry, broker_branch）
        if key in {"daily", "market", "industry", "broker_branch"}:
            date_group = QGroupBox("手動下載日期範圍")
            date_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            date_layout = QFormLayout(date_group)
            date_layout.setSpacing(8)
            
            end_date_edit = QDateEdit()
            end_date_edit.setDate(QDate.currentDate())
            end_date_edit.setCalendarPopup(True)
            end_date_edit.setDisplayFormat("yyyy-MM-dd")
            end_date_edit.setToolTip(
                "【結束日期】\n"
                "設定下載或更新資料的截止日期。\n"
                "當您在任何一個分頁修改此日期，其他分頁的結束日期將同步聯動更新。"
            )
            
            lookback_spin = QSpinBox()
            lookback_spin.setRange(1, 365)
            lookback_spin.setValue(10)
            lookback_spin.setSuffix(" 天")
            lookback_spin.setToolTip(
                "【最近範圍】\n"
                "設定從「結束日期」往前推算的查找天數。\n"
                "例如設定 10 天，代表下載或檢查結束日期前 10 天內的所有交易日資料。"
            )
            
            date_layout.addRow("結束日期:", end_date_edit)
            date_layout.addRow("最近範圍:", lookback_spin)
            layout.addWidget(date_group)
            
            setattr(self, f"{key}_end_date", end_date_edit)
            setattr(self, f"{key}_lookback", lookback_spin)
            
            end_date_edit.dateChanged.connect(lambda _d, k=key: self._sync_dates(k))
            lookback_spin.valueChanged.connect(lambda _v, k=key: self._sync_dates(k))
            
            if key == "daily":
                self.end_date = end_date_edit
                self.lookback_days = lookback_spin

        # 針對技術指標計算分頁
        if key == "technical":
            tech_group = QGroupBox("技術指標計算配置")
            tech_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            tech_layout = QVBoxLayout(tech_group)
            tech_layout.setSpacing(8)
            
            mode_layout = QHBoxLayout()
            mode_layout.addWidget(QLabel("計算模式:"))
            
            self.tech_incremental_radio = QRadioButton("增量更新（只計算新數據）")
            self.tech_incremental_radio.setChecked(True)
            self.tech_incremental_radio.setToolTip(
                "【增量更新模式】\n"
                "僅針對資料庫中最新交易日或尚未計算過指標的新股價數據進行計算。\n"
                "計算速度極快，是日常更新的首選模式。"
            )
            mode_layout.addWidget(self.tech_incremental_radio)
            
            self.tech_force_all_radio = QRadioButton("強制全量更新（重新計算所有數據）")
            self.tech_force_all_radio.setToolTip(
                "【強制全量更新模式】\n"
                "忽略已計算好的歷史指標，重新對資料庫內的所有股票歷史數據計算技術指標。\n"
                "運算時間較長，通常僅在修改了技術指標算法邏輯時使用。"
            )
            mode_layout.addWidget(self.tech_force_all_radio)
            mode_layout.addStretch()
            tech_layout.addLayout(mode_layout)
            
            stock_form = QFormLayout()
            self.tech_stock_input = QLineEdit()
            self.tech_stock_input.setPlaceholderText("留空則處理所有股票，例如：2330")
            self.tech_stock_input.setToolTip(
                "【股票代號（選填）】\n"
                "如果只想重算特定一檔股票的技術指標，請在此輸入股票代號（如 2330）。\n"
                "若保持留空，則會對資料庫中所有的股票進行計算。"
            )
            stock_form.addRow("股票代號（可選）:", self.tech_stock_input)
            tech_layout.addLayout(stock_form)
            
            layout.addWidget(tech_group)

        # 操作按鈕面板
        op_group = QGroupBox("數據操作")
        op_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                color: #475569;
                font-weight: bold;
            }
        """)
        button_layout = QHBoxLayout(op_group)
        button_layout.setSpacing(10)

        check_btn = QPushButton("🔍 檢查此資料源狀態")
        check_btn.setMinimumHeight(35)
        check_btn.setToolTip(
            "【檢查此資料源狀態】\n"
            "單獨檢查此項資料來源在本地原始檔案目錄以及 SQLite 資料庫中的最新狀態（最新日期、總記錄數），\n"
            "並更新頂部的對應數據卡片與下方日誌主控台。"
        )
        check_btn.setStyleSheet("""
            QPushButton {
                background-color: #f8fafc;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
            }
        """)
        check_btn.clicked.connect(lambda _checked=False, source=key: self._check_source_detail(source, force=True))
        button_layout.addWidget(check_btn)

        if key in {"daily", "market", "industry", "broker_branch"}:
            update_btn = QPushButton("📥 手動下載此資料源")
            setattr(self, f"{key}_update_btn", update_btn)
            update_btn.setMinimumHeight(35)
            update_btn.setToolTip(
                f"【手動下載此資料源】\n"
                f"依據上方設定的日期範圍，手動向 API/網頁端發出下載請求，將原始 CSV 檔案下載至本地 raw/ 目錄。\n"
                f"注意：手動下載僅會儲存本地 CSV 原始檔，必須再點擊「合併」按鈕或執行「安全更新所有數據」，\n"
                f"資料才會真正寫入 SQLite 資料庫以供策略推薦和回測使用。"
            )
            update_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
            """)
            update_btn.clicked.connect(lambda _checked=False, k=key: self._dispatch_update(k))
            button_layout.addWidget(update_btn)

        if key == "daily":
            self.merge_btn = QPushButton("⚙️ 合併每日股價")
            self.merge_btn.setMinimumHeight(35)
            self.merge_btn.setToolTip(
                "【⚙️ 合併每日股價】\n"
                "將本地 raw/daily_price/ 目錄下下載好的單日股價原始 CSV 檔案，\n"
                "增量同步寫入至 SQLite 資料庫的 daily_prices 表中，\n"
                "以便大盤檢測、策略推薦與回測引擎能夠讀取到最新數據。"
            )
            self.merge_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
            self.merge_btn.clicked.connect(self._execute_merge)
            button_layout.addWidget(self.merge_btn)
        elif key == "broker_branch":
            self.merge_broker_branch_btn = QPushButton("⚙️ 合併券商分點")
            self.merge_broker_branch_btn.setMinimumHeight(35)
            self.merge_broker_branch_btn.setToolTip(
                "【⚙️ 合併券商分點】\n"
                "將本地 raw/ 內 6 大追蹤分點的買賣超 CSV 數據進行增量合併，\n"
                "並同步寫入至 SQLite 資料庫的 broker_flows 表中，供主力流向分析使用。"
            )
            self.merge_broker_branch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
            self.merge_broker_branch_btn.clicked.connect(self._execute_merge_broker_branch)
            button_layout.addWidget(self.merge_broker_branch_btn)
        elif key == "technical":
            self.calculate_tech_btn = QPushButton("🚀 計算技術指標")
            self.calculate_tech_btn.setMinimumHeight(35)
            self.calculate_tech_btn.setToolTip(
                "【🚀 計算技術指標】\n"
                "依據上方的指標配置，計算個股的 KD, MACD, RSI, ADX 與均線等技術指標，\n"
                "並將計算結果高速儲存至 SQLite 資料庫中。推薦與回測引擎非常依賴此指標，\n"
                "因此手動合併完股價後，務必要點擊此處計算技術指標，系統功能才能正常運作。"
            )
            self.calculate_tech_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10b981, stop:1 #059669);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #34d399, stop:1 #10b981);
                }
            """)
            self.calculate_tech_btn.clicked.connect(self._execute_calculate_technical_indicators)
            button_layout.addWidget(self.calculate_tech_btn)

        export_btn = QPushButton("📤 匯出 CSV 備案")
        export_btn.setMinimumHeight(35)
        export_btn.setToolTip(
            "【📤 匯出 CSV 備案】\n"
            "將 SQLite 資料庫中此資料來源所屬的資料表，匯出為 Excel 可直接開啟的\n"
            "UTF-8 with BOM 編碼的 CSV 檔案。您可以選擇匯出「最近範圍」或「全部歷史」。\n"
            "這屬於離線備份與人工調研的輔助備案功能，日常更新不需要使用。"
        )
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                border-color: #94a3b8;
            }
        """)
        export_btn.clicked.connect(lambda _checked=False, source=key: self._execute_export_csv(source))
        button_layout.addWidget(export_btn)
        button_layout.addStretch()
        layout.addWidget(op_group)

        if key == "daily":
            danger_group = QGroupBox("⚠️ 高風險操作區 (Danger Zone)")
            danger_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #ef4444;
                    border-radius: 8px;
                    margin-top: 15px;
                    padding-top: 10px;
                    font-weight: bold;
                    color: #ef4444;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }
            """)
            danger_layout = QVBoxLayout(danger_group)
            danger_layout.setSpacing(6)
            
            danger_desc = QLabel("注意：強制重新合併將完全忽略現有合併結果，並重新讀取 daily_price/ 底下的所有 CSV 檔案寫入資料庫。\n此操作耗時較長，通常僅在資料庫損毀或修復資料時使用。")
            danger_desc.setStyleSheet("color: #64748b; font-size: 11px;")
            danger_desc.setWordWrap(True)
            
            self.force_merge_btn = QPushButton("⚠️ 強制重新合併所有每日股價")
            self.force_merge_btn.setMinimumHeight(35)
            self.force_merge_btn.setToolTip(
                "【⚠️ 強制重新合併所有每日股價】\n"
                "⚠️ 高風險操作！忽略資料庫中已有的合併狀態，全量掃描並重新將\n"
                "raw/daily_price/ 底下的所有歷史股價 CSV 檔案重新寫入資料庫的 daily_prices 表。\n"
                "可能需要非常長的時間，通常僅在資料庫損毀或需要完全修復重整數據時使用。"
            )
            self.force_merge_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #dc2626;
                }
                QPushButton:pressed {
                    background-color: #991b1b;
                }
            """)
            self.force_merge_btn.clicked.connect(self._execute_force_merge)
            
            danger_layout.addWidget(danger_desc)
            danger_layout.addWidget(self.force_merge_btn)
            layout.addWidget(danger_group)

        layout.addStretch()

    def _sync_dates(self, source_name: str):
        """同步不同分頁的日期範圍元件"""
        try:
            end_date_widget = getattr(self, f"{source_name}_end_date", None)
            lookback_widget = getattr(self, f"{source_name}_lookback", None)
            
            if not end_date_widget or not lookback_widget:
                return
                
            target_date = end_date_widget.date()
            target_days = lookback_widget.value()
            
            # 同步全域變數 (供底層業務代碼使用)
            self.end_date.setDate(target_date)
            self.lookback_days.setValue(target_days)
            
            # 同步其他分頁的元件
            for name in ["daily", "market", "industry", "broker_branch"]:
                if name == source_name:
                    continue
                
                other_date = getattr(self, f"{name}_end_date", None)
                other_days = getattr(self, f"{name}_lookback", None)
                
                if other_date:
                    other_date.blockSignals(True)
                    other_date.setDate(target_date)
                    other_date.blockSignals(False)
                    
                if other_days:
                    other_days.blockSignals(True)
                    other_days.setValue(target_days)
                    other_days.blockSignals(False)
        except Exception:
            pass

    def _dispatch_update(self, key: str):
        """代理各分頁的開始下載更新，並設定對應的 Radio 按鈕與日期"""
        radio_map = {
            "daily": self.daily_radio,
            "market": self.market_radio,
            "industry": self.industry_radio,
            "broker_branch": self.broker_branch_radio
        }
        radio_btn = radio_map.get(key)
        if radio_btn:
            radio_btn.setChecked(True)
            
        end_date_widget = getattr(self, f"{key}_end_date", None)
        lookback_widget = getattr(self, f"{key}_lookback", None)
        if end_date_widget and lookback_widget:
            self.end_date.setDate(end_date_widget.date())
            self.lookback_days.setValue(lookback_widget.value())
            
        self._execute_update()

    def _on_nav_changed(self, row: int):
        """切換工作台頁面並同步單項更新類型"""
        if row < 0:
            return
        self.content_stack.setCurrentIndex(row)
        key = self._nav_items[row][0]
        
        if key == "daily":
            self.daily_radio.setChecked(True)
        elif key == "market":
            self.market_radio.setChecked(True)
        elif key == "industry":
            self.industry_radio.setChecked(True)
        elif key == "broker_branch":
            self.broker_branch_radio.setChecked(True)
        elif key == "db_inspector":
            inspector_widget = self.content_stack.widget(row)
            if hasattr(inspector_widget, "refresh_tables"):
                inspector_widget.refresh_tables()
            return

        if key != "all" and key not in self._loaded_detail_sources:
            self._check_source_detail(key)

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
                return self._get_overview_status()
            
            self.worker = TaskWorker(check_task)
            self.worker.finished.connect(self._on_status_checked)
            self.worker.error.connect(self._on_status_error)
            self.worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"檢查數據狀態失敗：\n{str(e)}")
            self.check_status_btn.setEnabled(True)
            self.check_status_btn.setText("檢查數據狀態")

    def _get_overview_status(self) -> Dict[str, Any]:
        """取得全部資料頁使用的輕量狀態"""
        if hasattr(self.update_service, "check_data_overview"):
            return self.update_service.check_data_overview()
        return self.update_service.check_data_status()

    def _get_source_detail(self, source: str) -> Dict[str, Any]:
        """取得單一資料來源詳細狀態並包成 UI 可套用的狀態 dict"""
        source_map = {
            "daily": "daily_data",
            "market": "market_index",
            "industry": "industry_index",
            "broker_branch": "broker_branch",
            "technical": "technical_indicators",
        }
        status_key = source_map.get(source, source)
        if hasattr(self.update_service, "check_source_detail"):
            return {status_key: self.update_service.check_source_detail(source)}
        return {status_key: self.update_service.check_data_status().get(status_key, {})}

    def _check_source_detail(self, source: str, force: bool = False):
        """背景載入單一資料來源的詳細狀態"""
        if not force and source in self._loaded_detail_sources:
            return
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)

        def check_task():
            return {"source": source, "status": self._get_source_detail(source)}

        self.worker = TaskWorker(check_task)
        self.worker.finished.connect(self._on_source_detail_checked)
        self.worker.error.connect(self._on_status_error)
        self.worker.start()

    def _on_source_detail_checked(self, payload: Dict[str, Any]):
        """單一資料來源詳細狀態載入完成"""
        source = payload.get("source")
        status = payload.get("status", {})
        if source:
            self._loaded_detail_sources.add(source)
        self._on_status_checked(status)
    
    def _on_status_checked(self, status: Dict[str, Any]):
        """數據狀態檢查完成"""
        self.check_status_btn.setEnabled(True)
        self.check_status_btn.setText("檢查數據狀態")
        
        # 分別更新四個區塊
        daily_text = self.daily_status_text.toPlainText()
        market_text = self.market_status_text.toPlainText()
        industry_text = self.industry_status_text.toPlainText()
        broker_branch_text = self.broker_branch_status_text.toPlainText()
        technical_text = self.technical_status_text.toPlainText()
        
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
            elif key == 'technical_indicators':
                file_count = value.get('file_count')
                if file_count is not None:
                    status_display += f"\n指標檔數：{file_count:,}"
                technical_text = status_display
        
        # 如果沒有數據，顯示提示
        if not daily_text:
            daily_text = "尚未檢查"
        if not market_text:
            market_text = "尚未檢查"
        if not industry_text:
            industry_text = "尚未檢查"
        if not broker_branch_text:
            broker_branch_text = "尚未檢查"
        if not technical_text:
            technical_text = "尚未檢查"
        
        self.daily_status_text.setPlainText(daily_text)
        self.market_status_text.setPlainText(market_text)
        self.industry_status_text.setPlainText(industry_text)
        self.broker_branch_status_text.setPlainText(broker_branch_text)
        self.technical_status_text.setPlainText(technical_text)
        self._log(f"數據狀態檢查完成")
    
    def _on_status_error(self, error_msg: str):
        """數據狀態檢查出錯"""
        self.check_status_btn.setEnabled(True)
        self.check_status_btn.setText("檢查數據狀態")
        QMessageBox.critical(self, "錯誤", f"檢查數據狀態失敗：\n{error_msg}")
        self._log(f"錯誤：{error_msg}")
    
    def _get_selected_date_range(self) -> tuple[str, str]:
        """取得目前 UI 選定的查找日期範圍"""
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        lookback_days = self.lookback_days.value()
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        start_date_obj = end_date_obj - timedelta(days=lookback_days)
        return start_date_obj.strftime("%Y-%m-%d"), end_date

    def _run_safe_update_all(self, progress_callback=None) -> Dict[str, Any]:
        """執行保守的一鍵安全更新流程，供 UI worker 與測試共用"""
        start_date, end_date = self._get_selected_date_range()
        completed = []

        def report(message: str, progress: int) -> None:
            if progress_callback:
                progress_callback(message, progress)

        def run_step(name: str, progress: int, action):
            report(name, progress)
            result = action()
            if isinstance(result, dict) and not result.get("success", True):
                return result
            completed.append({"step": name, "result": result})
            return result

        use_sqlite = getattr(self.update_service.config, "use_sqlite", False)
        
        steps = [
            ("檢查資料狀態", 0, lambda: self._get_overview_status()),
            ("每日股價更新", 12, lambda: self.update_service.update_daily(start_date, end_date)),
            ("同步每日股價至 SQLite", 18, lambda: self.update_service.sync_source_to_sqlite("daily_price_files", start_date, end_date)),
            ("大盤指數更新", 24, lambda: self.update_service.update_market(start_date, end_date)),
            ("同步大盤指數至 SQLite", 30, lambda: self.update_service.sync_source_to_sqlite("market_index")),
            ("產業指數更新", 36, lambda: self.update_service.update_industry(start_date, end_date)),
            ("同步產業指數至 SQLite", 42, lambda: self.update_service.sync_source_to_sqlite("industry_index")),
            ("券商分點更新", 48, lambda: self.update_service.update_broker_branch(start_date, end_date)),
        ]
        
        if use_sqlite:
            # 啟用 SQLite 時，跳過重寫大型 CSV 合併，改由單日檔案直接同步到 SQLite
            steps.extend([
                ("同步券商分點至 SQLite (直接檔案同步)", 65, lambda: self.update_service.sync_source_to_sqlite("broker_branch_files", start_date, end_date)),
            ])
        else:
            steps.extend([
                ("合併每日資料", 55, lambda: self.update_service.merge_daily_data(force_all=False)),
                ("同步合併每日資料至 SQLite", 62, lambda: self.update_service.sync_source_to_sqlite("daily_data")),
                ("合併券商分點", 69, lambda: self.update_service.merge_broker_branch_data()),
                ("同步券商分點至 SQLite", 76, lambda: self.update_service.sync_source_to_sqlite("broker_branch")),
            ])
            
        steps.extend([
            (
                "增量計算技術指標",
                88,
                lambda: self.update_service.calculate_technical_indicators(
                    target_stock=None,
                    force_all=False,
                    start_date=None,
                    progress_callback=progress_callback,
                    incremental_lookback_days=250,
                ),
            ),
            ("刷新資料狀態", 100, lambda: self._get_overview_status()),
        ])

        for name, progress, action in steps:
            result = run_step(name, progress, action)
            if isinstance(result, dict) and not result.get("success", True):
                return {
                    "success": False,
                    "message": result.get("message", f"{name} 失敗"),
                    "failed_step": name,
                    "completed_steps": completed,
                    "step_result": result,
                }

        report("安全更新所有數據完成", 100)
        return {
            "success": True,
            "message": "安全更新所有數據完成",
            "completed_steps": completed,
        }

    def _execute_safe_update_all(self):
        """以背景工作執行安全更新所有數據"""
        self.safe_update_all_btn.setEnabled(False)
        self.safe_update_all_btn.setText("安全更新中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("準備安全更新所有數據...")
        self.log_text.clear()
        self._log("開始安全更新所有數據")

        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)

        self.worker = ProgressTaskWorker(self._run_safe_update_all)
        self.worker.progress.connect(self._on_safe_update_all_progress)
        self.worker.finished.connect(self._on_safe_update_all_finished)
        self.worker.error.connect(self._on_safe_update_all_error)
        self.worker.start()

    def _on_safe_update_all_progress(self, message: str, progress: int):
        """更新安全更新流程進度"""
        self.progress_label.setText(message)
        self.progress_bar.setValue(progress)
        self._log(f"[安全更新 {progress}%] {message}")

    def _on_safe_update_all_finished(self, result: Dict[str, Any]):
        """安全更新流程完成"""
        self.safe_update_all_btn.setEnabled(True)
        self.safe_update_all_btn.setText("安全更新所有數據")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        if result.get("success", False):
            message = result.get("message", "安全更新所有數據完成")
            self._log(message)
            QMessageBox.information(self, "安全更新完成", message)
            self._check_data_status()
            return

        failed_step = result.get("failed_step", "未知步驟")
        message = result.get("message", "安全更新失敗")
        self._log(f"安全更新失敗：{failed_step} - {message}")
        QMessageBox.warning(self, "安全更新未完成", f"{failed_step} 失敗：\n{message}")

    def _on_safe_update_all_error(self, error_msg: str):
        """安全更新流程出錯"""
        self.safe_update_all_btn.setEnabled(True)
        self.safe_update_all_btn.setText("安全更新所有數據")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self._log(f"安全更新錯誤：{error_msg}")
        error_display = error_msg
        if len(error_display) > 500:
            error_display = error_display[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整訊息）"
        QMessageBox.critical(self, "安全更新失敗", error_display)

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
        
        self._active_update_type = update_type
        
        # 獲取查找範圍
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        lookback_days = self.lookback_days.value()
        
        # 計算開始日期（從結束日期往前推）
        from datetime import datetime, timedelta
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        start_date_obj = end_date_obj - timedelta(days=lookback_days)
        start_date = start_date_obj.strftime("%Y-%m-%d")
        
        # 禁用按鈕
        current_update_btn = getattr(self, f"{update_type}_update_btn", None)
        if current_update_btn:
            current_update_btn.setEnabled(False)
            current_update_btn.setText("更新中...")
        
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
        def update_task(progress_callback=None):
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
                    result = self.update_service.update_broker_branch(
                        start_date=start_date, 
                        end_date=end_date,
                        progress_callback=progress_callback
                    )
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
        
        self.worker = ProgressTaskWorker(update_task)
        self.worker.progress.connect(self._on_update_progress)
        self.worker.finished.connect(self._on_update_finished)
        self.worker.error.connect(self._on_update_error)
        self.worker.start()
    
    def _on_update_progress(self, message: str, percentage: int):
        """更新進度回調"""
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_label.setText(message)
        self.progress_bar.setValue(percentage)
        # 只在有實際進度變更時才記錄，避免日誌過多
        if percentage % 10 == 0 or percentage == 100:
            self._log(f"[進度 {percentage}%] {message}")
    
    def _on_update_finished(self, result: Dict[str, Any]):
        """更新完成"""
        # 恢復按鈕
        active_type = getattr(self, "_active_update_type", "daily")
        current_update_btn = getattr(self, f"{active_type}_update_btn", None)
        if current_update_btn:
            current_update_btn.setEnabled(True)
            current_update_btn.setText("📥 手動下載此資料源")
        
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
        active_type = getattr(self, "_active_update_type", "daily")
        current_update_btn = getattr(self, f"{active_type}_update_btn", None)
        if current_update_btn:
            current_update_btn.setEnabled(True)
            current_update_btn.setText("📥 手動下載此資料源")
        
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
    
    def _execute_export_csv(self, source: str):
        """執行 CSV 匯出邏輯（支援範圍選擇與非同步處理）"""
        table_mapping = {
            "daily": "daily_prices",
            "market": "market_indices",
            "industry": "industry_indices",
            "broker_branch": "broker_flows",
            "technical": "technical_indicators",
        }
        
        table_name = table_mapping.get(source)
        if not table_name:
            QMessageBox.warning(self, "警告", f"未知的匯出來源：{source}")
            return
            
        # 1. 取得 UI 設定日期範圍並彈出選擇對話框
        start_date, end_date = self._get_selected_date_range()
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("匯出 CSV 範圍選擇")
        msg_box.setText("請選擇要匯出的資料日期範圍：")
        msg_box.setInformativeText(
            f"目前的 UI 設定範圍：{start_date} 至 {end_date}\n\n"
            f"點選「最近範圍」將只匯出此區間資料。\n"
            f"點選「全部歷史」將匯出該資料表內的所有歷史資料。"
        )
        
        btn_range = msg_box.addButton("最近範圍", QMessageBox.ButtonRole.YesRole)
        btn_all = msg_box.addButton("全部歷史", QMessageBox.ButtonRole.NoRole)
        btn_cancel = msg_box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()
        
        if msg_box.clickedButton() == btn_cancel:
            return
        elif msg_box.clickedButton() == btn_range:
            s_date, e_date = start_date, end_date
        else:
            s_date, e_date = None, None
            
        # 2. 選擇檔案儲存路徑
        import os
        from pathlib import Path
        
        export_date = datetime.now().strftime("%Y%m%d")
        default_filename = f"{table_name}_export_{export_date}.csv"
        
        # 預設儲存於 config 的 data_root 或是 專案根目錄/exports
        default_dir = getattr(self.update_service.config, "data_root", Path.cwd())
        default_path = Path(default_dir) / default_filename
        
        from PySide6.QtWidgets import QFileDialog
        file_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "選擇儲存的 CSV 檔案",
            str(default_path),
            "CSV 檔案 (*.csv)"
        )
        
        if not file_path_str:
            return
            
        target_path = Path(file_path_str)
        
        # 3. 啟動背景 Worker 執行匯出
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0) # 跑馬燈模式
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"正在匯出 {table_name} 資料至 CSV...")
        self._log(f"開始匯出 {table_name} 資料至 {target_path}")
        
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
            
        def export_task():
            return self.update_service.export_table_to_csv(
                table_name=table_name,
                target_path=target_path,
                start_date=s_date,
                end_date=e_date
            )
            
        self.worker = TaskWorker(export_task)
        
        def on_export_finished(result: Dict[str, Any]):
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)
            if result.get("success", False):
                msg = result.get("message", "匯出成功")
                self._log(f"匯出成功：{msg}")
                QMessageBox.information(self, "匯出完成", msg)
            else:
                msg = result.get("message", "匯出失敗")
                self._log(f"匯出失敗：{msg}")
                QMessageBox.warning(self, "匯出失敗", msg)
                
        def on_export_error(error_msg: str):
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)
            self._log(f"匯出出錯：{error_msg}")
            QMessageBox.critical(self, "匯出失敗", f"匯出過程發生錯誤：\n{error_msg}")
            
        self.worker.finished.connect(on_export_finished)
        self.worker.error.connect(on_export_error)
        self.worker.start()

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

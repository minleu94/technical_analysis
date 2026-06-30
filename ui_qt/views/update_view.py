"""
數據更新視圖
提供數據更新功能界面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QProgressBar,
    QTextEdit, QRadioButton, QButtonGroup,
    QDateEdit, QMessageBox, QFormLayout, QSpinBox, QLineEdit,
    QListWidget, QStackedWidget, QFrame, QCalendarWidget
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import subprocess
import sys

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
        self._active_workers: List[TaskWorker] = []
        meta_data_dir = getattr(
            self.update_service.config,
            "meta_data_dir",
            Path(getattr(self.update_service.config, "data_root", ".")) / "meta_data",
        )
        self.tpex_refresh_state_file = Path(meta_data_dir) / "tpex_full_refresh_status.json"
        self._tpex_background_process: Optional[subprocess.Popen] = None

        self._setup_ui()

    def _start_worker(self, worker: TaskWorker) -> TaskWorker:
        """Keep background tasks alive independently until they finish."""
        self.worker = worker
        self._active_workers.append(worker)
        if hasattr(worker, "cancelled"):
            worker.cancelled.connect(lambda current_worker=worker: self._release_worker(current_worker))
        return worker

    def _release_worker(self, worker: TaskWorker):
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        if self.worker is worker:
            self.worker = self._active_workers[-1] if self._active_workers else None

    def _attach_worker_cleanup(self, worker: TaskWorker):
        worker.finished.connect(lambda _payload, current_worker=worker: self._release_worker(current_worker))
        worker.error.connect(lambda _message, current_worker=worker: self._release_worker(current_worker))

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
        self._configure_date_edit(self.end_date)
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
            ("monthly_revenue", "月營收"),
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

        # 數據狀態卡片網格（精美 StatusCard 呈現，取代原先 status_group 內多個 TextEdit）
        # 我們將它們宣告為 class member，使底層 _on_status_checked 能直接使用
        self.daily_status_text = StatusCard("每日股票數據", "📊", self)
        self.market_status_text = StatusCard("大盤指數數據", "🧭", self)
        self.industry_status_text = StatusCard("產業指數數據", "🏢", self)
        self.broker_branch_status_text = StatusCard("券商分點數據", "🤝", self)
        self.technical_status_text = StatusCard("技術指標數據", "📈", self)
        self.monthly_revenue_status_text = StatusCard("月營收資料", "月", self)

        # 卡片佈局
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)
        cards_layout.addWidget(self.daily_status_text)
        cards_layout.addWidget(self.market_status_text)
        cards_layout.addWidget(self.industry_status_text)
        cards_layout.addWidget(self.broker_branch_status_text)
        cards_layout.addWidget(self.technical_status_text)
        cards_layout.addWidget(self.monthly_revenue_status_text)
        all_layout.addLayout(cards_layout)

        # 一鍵更新與輔助按鈕
        actions_layout = QHBoxLayout()

        self.quick_update_all_btn = QPushButton("⚡ 快速更新 (跳過大型合併)")
        self.quick_update_all_btn.setMinimumHeight(45)
        self.quick_update_all_btn.setToolTip(
            "【⚡ 快速更新 (跳過大型合併)】\n"
            "速度優先。TWSE 每日股價、TPEX 每日股價與券商分點都更新結束日前最近 10 個工作日。\n"
            "TPEX 使用官方歷史查詢 endpoint，會先跳過本機已有 CSV，只補缺少日期。\n"
            "資料會直接增量同步 SQLite，但跳過 stock_data_whole 與分點 merged.csv 的大型合併重寫。"
        )
        self.quick_update_all_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8b5cf6, stop:1 #6d28d9);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #a78bfa, stop:1 #7c3aed);
            }
            QPushButton:pressed {
                background: #5b21b6;
            }
            QPushButton:disabled {
                background-color: #cbd5e1;
                color: #94a3b8;
            }
        """)
        self.quick_update_all_btn.clicked.connect(self._execute_quick_update_all)

        self.safe_update_all_btn = QPushButton("🛡️ 安全更新 (完整 CSV + SQLite)")
        self.safe_update_all_btn.setMinimumHeight(45)
        self.safe_update_all_btn.setToolTip(
            "【🛡️ 安全更新 (完整 CSV + SQLite)】\n"
            "備份完整性優先。TWSE 每日股價與 TPEX 每日股價會依上方日期範圍檢查並補齊缺少 CSV。\n"
            "券商分點會依上方日期範圍更新目前啟用的 40 家追蹤分點。\n"
            "完成下載後會重建每日股價大表與分點 merged.csv，再同步寫入 SQLite。\n"
            "此流程耗時較長，但能保證 CSV 歷史資料庫的完整備份。"
        )
        self.safe_update_all_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
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
            "並更新上方 6 張狀態卡片的狀態燈號（🟢最新/🟡待更新/🔴異常/⚪未檢查）。\n"
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

        actions_layout.addWidget(self.quick_update_all_btn, stretch=2)
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
        main_layout.addLayout(workbench_layout, stretch=1)

        # 4. 底部全域共享的進度條與日誌 console
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
                margin-top: 8px;
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
        log_layout.setContentsMargins(10, 2, 10, 6)
        log_layout.setSpacing(4)

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

        # 日誌輔助工具列放在底部，避免標題下方出現整條空白列
        log_toolbar = QHBoxLayout()
        log_toolbar.setContentsMargins(0, 0, 0, 0)
        log_toolbar.setSpacing(0)
        log_toolbar.addStretch()
        clear_log_btn = QPushButton("🧹 清除日誌")
        clear_log_btn.setFixedHeight(16)
        clear_log_btn.setStyleSheet("""
            QPushButton {
                min-height: 0px;
                padding: 0px 4px;
                background-color: transparent;
                color: #64748b;
                border: none;
                font-size: 10px;
            }
            QPushButton:hover {
                color: #ef4444;
            }
        """)
        clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        log_toolbar.addWidget(clear_log_btn)
        log_layout.addLayout(log_toolbar)

        log_group.setMaximumHeight(118)  # 緊湊主控台高度，保留更多空間給上方表格
        main_layout.addWidget(log_group)

        # 初始化各資料區塊的顯示 (卡片)
        self.daily_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.market_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.industry_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.broker_branch_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.technical_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.monthly_revenue_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")

        self.nav_list.setCurrentRow(0)

    def _add_source_tab_content(self, layout: QVBoxLayout, key: str):
        """為個別資料源維護分頁建立專屬操作與手動配置界面"""
        descriptions = {
            "daily": "檢查與維護每日股價原始資料（TWSE + TPEX）與 SQLite 對應數據。此處支援增量合併與 Danger Zone 強制重新合併。",
            "market": "檢查與更新加權指數大盤數據。此處會將大盤資料同步儲存至資料庫的 market_indices 表。",
            "industry": "檢查與更新產業指數數據，可將各產業分類的歷史指數同步至 industry_indices 表。",
            "broker_branch": "維護 MoneyDJ 目前啟用的 40 家追蹤分點之買賣超資料，並可執行券商分點合併至 SQLite broker_flows 表。",
            "technical": "增量或全量重新計算個股的技術指標（KD, MACD, RSI 等），並高速批量儲存至資料庫中。",
            "monthly_revenue": "使用 MOPS 月營收快照檔搭配正式可得日對照檔，先檢查筆數與診斷結果，再受控寫入正式月營收資料表。",
        }

        desc_label = QLabel(descriptions.get(key, "檢查此資料來源的更新狀態。"))
        desc_label.setStyleSheet("color: #64748b; font-size: 12px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        if key == "monthly_revenue":
            config_group = QGroupBox("MOPS 月營收回填設定")
            config_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            form_layout = QFormLayout(config_group)
            form_layout.setSpacing(8)

            self.monthly_revenue_snapshot_input = QLineEdit()
            self.monthly_revenue_snapshot_input.setObjectName("monthly_revenue_snapshot_input")
            self.monthly_revenue_snapshot_input.setText(str(self._default_monthly_revenue_snapshot_path()))
            self.monthly_revenue_snapshot_input.setToolTip(
                "MOPS 月營收快照檔。系統會從這個檔案讀取各公司每月營收金額；先檢查與正式寫入都使用同一份檔案。"
            )

            self.monthly_revenue_availability_input = QLineEdit()
            self.monthly_revenue_availability_input.setObjectName("monthly_revenue_availability_input")
            self.monthly_revenue_availability_input.setText(str(self._default_monthly_revenue_availability_path()))
            self.monthly_revenue_availability_input.setToolTip(
                "正式可得日對照檔。此檔決定每筆月營收從哪一天起可被因子層讀取，用來避免偷看未來資料。"
            )

            self.monthly_revenue_source_version_input = QLineEdit()
            self.monthly_revenue_source_version_input.setObjectName("monthly_revenue_source_version_input")
            default_version = getattr(
                self.update_service,
                "monthly_revenue_source_version",
                "mops-static-snapshot-monthly-revenue-2026-06-16",
            )
            self.monthly_revenue_source_version_input.setText(default_version)
            self.monthly_revenue_source_version_input.setToolTip(
                "本次寫入版本名稱。用來區分不同批次的月營收資料，未來重跑或比對時可以追溯來源。"
            )

            form_layout.addRow("MOPS 月營收快照檔：", self.monthly_revenue_snapshot_input)
            form_layout.addRow("正式可得日對照檔：", self.monthly_revenue_availability_input)
            form_layout.addRow("本次寫入版本名稱：", self.monthly_revenue_source_version_input)
            layout.addWidget(config_group)

            op_group = QGroupBox("月營收資料操作")
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

            self.monthly_revenue_dry_run_btn = QPushButton("先檢查，不寫入")
            self.monthly_revenue_dry_run_btn.setObjectName("monthly_revenue_dry_run_btn")
            self.monthly_revenue_dry_run_btn.setMinimumHeight(35)
            self.monthly_revenue_dry_run_btn.setToolTip("只檢查可回填筆數與診斷結果，不寫入正式資料庫。")
            self.monthly_revenue_dry_run_btn.clicked.connect(
                lambda _checked=False: self._execute_monthly_revenue_backfill(apply=False)
            )
            button_layout.addWidget(self.monthly_revenue_dry_run_btn)

            self.monthly_revenue_apply_btn = QPushButton("確認後寫入月營收")
            self.monthly_revenue_apply_btn.setObjectName("monthly_revenue_apply_btn")
            self.monthly_revenue_apply_btn.setMinimumHeight(35)
            self.monthly_revenue_apply_btn.setToolTip("跳出確認視窗後，使用正式可得日對照檔把 MOPS 月營收寫入正式月營收資料表。")
            self.monthly_revenue_apply_btn.setStyleSheet("""
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
            self.monthly_revenue_apply_btn.clicked.connect(
                lambda _checked=False: self._execute_monthly_revenue_backfill(apply=True)
            )
            button_layout.addWidget(self.monthly_revenue_apply_btn)
            button_layout.addStretch()
            layout.addWidget(op_group)
            layout.addStretch()
            return

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
            self._configure_date_edit(end_date_edit)
            end_date_edit.setToolTip(
                "【結束日期】\n"
                "設定下載或更新資料的截止日期。\n"
                "當您在任何一個分頁修改此日期，其他分頁的結束日期將同步聯動更新。"
            )
            today_btn = QPushButton("今日")
            today_btn.setMaximumWidth(52)
            today_btn.setToolTip("將結束日期設定為今天。")
            today_btn.clicked.connect(lambda _checked=False, k=key: self._set_shared_end_date_today(k))

            lookback_spin = QSpinBox()
            lookback_spin.setRange(1, 365)
            lookback_spin.setValue(10)
            lookback_spin.setSuffix(" 天")
            lookback_spin.setToolTip(
                "【最近範圍】\n"
                "設定從「結束日期」往前推算的查找天數。\n"
                "例如設定 10 天，代表下載或檢查結束日期前 10 天內的所有交易日資料。"
            )

            end_date_row = QHBoxLayout()
            end_date_row.addWidget(end_date_edit)
            end_date_row.addWidget(self._create_calendar_button(end_date_edit))
            end_date_row.addWidget(today_btn)
            end_date_row.addStretch()
            date_layout.addRow("結束日期:", end_date_row)
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
                f"每日股價手動下載會跑 TWSE 日期範圍，TPEX 則改為區間流程嘗試抓取每個交易日；若 API 只回傳最近交易日，會自動以回應日覆蓋對應檔案。\n"
                f"提交後會自動同步 daily_price / daily_price_tpex 到 SQLite，並進行增量技術指標計算。"
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
                self.tpex_background_btn = QPushButton("🚀 背景補齊 TPEX + 技術指標")
                self.tpex_background_btn.setMinimumHeight(35)
                self.tpex_background_btn.setToolTip(
                    "【🚀 背景補齊 TPEX + 技術指標】\n"
                    "將以背景方式執行 TPEX 區間抓取（含 fallback / 重複日短路）、同步日價到 SQLite，並立即進行技術指標增量更新。\n"
                    "任務會寫入背景狀態檔，可用「📡 檢查背景任務狀態」隨時查看最新進度。"
                )
                self.tpex_background_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f59e0b, stop:1 #d97706);
                        color: white;
                        border: none;
                        border-radius: 6px;
                        font-weight: bold;
                        padding: 6px 12px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fbbf24, stop:1 #f59e0b);
                    }
                """)
                self.tpex_background_btn.clicked.connect(self._execute_background_tpex_refresh)
                button_layout.addWidget(self.tpex_background_btn)

                self.tpex_background_status_btn = QPushButton("📡 檢查背景任務狀態")
                self.tpex_background_status_btn.setMinimumHeight(35)
                self.tpex_background_status_btn.setToolTip(
                    "【📡 檢查背景任務狀態】\n"
                    "讀取背景任務的 JSON 狀態檔，確認目前是 running / done / failed，以及 TPEX、SQLite、技術指標三個步驟結果。"
                )
                self.tpex_background_status_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f8fafc;
                        color: #334155;
                        border: 1px solid #cbd5e1;
                        border-radius: 6px;
                        font-weight: bold;
                        padding: 6px 12px;
                    }
                    QPushButton:hover {
                        background-color: #e2e8f0;
                    }
                """)
                self.tpex_background_status_btn.clicked.connect(self._show_tpex_background_status)
                button_layout.addWidget(self.tpex_background_status_btn)

        if key == "daily":
            self.merge_btn = QPushButton("⚙️ 合併每日股價")
            self.merge_btn.setMinimumHeight(35)
            self.merge_btn.setToolTip(
                "【⚙️ 合併每日股價】\n"
                "將本地 daily_price/ 與 daily_price_tpex/ 目錄下下載好的單日股價 CSV 檔案，\n"
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
                "將本地 broker_flow/ 內目前啟用的 40 家追蹤分點買賣超 CSV 數據進行增量合併，\n"
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

        if key in {"daily", "broker_branch"}:
            detail_status = QLabel("尚未檢查此資料源狀態")
            detail_status.setWordWrap(True)
            detail_status.setStyleSheet("""
                QLabel {
                    background-color: #f8fafc;
                    color: #334155;
                    border: 1px solid #cbd5e1;
                    border-radius: 6px;
                    padding: 8px 10px;
                    font-size: 12px;
                    line-height: 1.4;
                }
            """)
            if key == "daily":
                self.daily_detail_status_label = detail_status
            else:
                self.broker_branch_detail_status_label = detail_status
            layout.addWidget(detail_status)

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

    def _default_monthly_revenue_snapshot_path(self) -> Path:
        config = getattr(self.update_service, "config", None)
        if config is None:
            return Path("")
        snapshot_dir = getattr(config, "output_root", Path("")) / "monthly_revenue_mops_snapshots"
        candidates = [
            path
            for path in snapshot_dir.glob("mops_monthly_revenue_snapshot_*.csv")
            if ".before_" not in path.name
        ]
        if not candidates:
            return snapshot_dir
        return max(candidates, key=lambda path: path.stat().st_size)

    def _default_monthly_revenue_availability_path(self) -> Path:
        config = getattr(self.update_service, "config", None)
        if config is None:
            return Path("")
        return getattr(config, "monthly_revenue_availability_file", Path(""))

    def _set_monthly_revenue_buttons_enabled(self, enabled: bool):
        for attr in ("monthly_revenue_dry_run_btn", "monthly_revenue_apply_btn"):
            button = getattr(self, attr, None)
            if button:
                button.setEnabled(enabled)

    def _execute_monthly_revenue_backfill(self, apply: bool = False):
        """Run MOPS monthly revenue dry-run or controlled SQLite apply."""
        if apply:
            reply = QMessageBox.question(
                self,
                "確認寫入月營收",
                "確定要正式寫入 fundamental_monthly_revenues 嗎？\n\n"
                "系統會先建立 SQLite 備份，再用 MOPS snapshot 與正式 availability mapping 回填月營收。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        snapshot_text = self.monthly_revenue_snapshot_input.text().strip()
        availability_text = self.monthly_revenue_availability_input.text().strip()
        source_version = self.monthly_revenue_source_version_input.text().strip()

        self._set_monthly_revenue_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在處理 MOPS 月營收...")
        self.log_text.clear()
        mode_text = "正式寫入" if apply else "dry-run"
        self._log(f"開始 MOPS 月營收 {mode_text}")
        self._log(f"MOPS snapshot: {snapshot_text}")
        self._log(f"Availability mapping: {availability_text}")

        def task():
            kwargs = {
                "snapshot_file": Path(snapshot_text) if snapshot_text else None,
                "availability_file": Path(availability_text) if availability_text else None,
                "source_version": source_version or None,
            }
            if apply:
                return self.update_service.apply_mops_monthly_revenue_backfill(**kwargs)
            return self.update_service.dry_run_mops_monthly_revenue_backfill(**kwargs)

        worker = self._start_worker(TaskWorker(task))
        worker.finished.connect(lambda result, apply_mode=apply: self._on_monthly_revenue_finished(result, apply_mode))
        worker.error.connect(self._on_monthly_revenue_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_monthly_revenue_finished(self, result: Dict[str, Any], apply: bool):
        self._set_monthly_revenue_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        message = result.get("message", "月營收處理完成")
        self._log(message)
        self._log(f"raw rows: {result.get('raw_row_count', 0):,}")
        self._log(f"normalized records: {result.get('normalized_record_count', result.get('inserted_count', 0)):,}")
        self._log(f"diagnostics: {result.get('diagnostic_count', 0):,}")
        backup_file = result.get("backup_file")
        if backup_file:
            self._log(f"SQLite backup: {backup_file}")

        if result.get("success", False):
            QMessageBox.information(self, "月營收處理完成", message)
            if apply:
                self._check_source_detail("monthly_revenue", force=True)
        else:
            QMessageBox.warning(self, "月營收處理失敗", message)

    def _on_monthly_revenue_error(self, error_msg: str):
        self._set_monthly_revenue_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self._log(f"錯誤：{error_msg}")
        QMessageBox.critical(self, "月營收處理失敗", error_msg)

    def _configure_date_edit(self, date_edit: QDateEdit):
        date_edit.setCalendarPopup(False)
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setMinimumWidth(132)
        date_edit.setMaximumWidth(150)
        date_edit.setStyleSheet("""
            QDateEdit {
                padding-right: 7px;
            }
        """)

    def _create_calendar_button(self, date_edit: QDateEdit) -> QPushButton:
        button = QPushButton("日曆")
        button.setMaximumWidth(52)
        button.setToolTip("開啟日曆選擇日期")
        button.setStyleSheet("""
            QPushButton {
                background-color: #f8fafc;
                color: #334155;
                border: 1px solid #94a3b8;
                border-radius: 5px;
                padding: 3px 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #e0f2fe;
                border-color: #0284c7;
            }
            QPushButton:pressed {
                background-color: #bae6fd;
            }
        """)
        button.clicked.connect(lambda _checked=False, edit=date_edit, anchor=button: self._show_calendar_popup(edit, anchor))
        return button

    def _show_calendar_popup(self, date_edit: QDateEdit, anchor: QPushButton):
        popup = QFrame(None, Qt.Popup)
        popup.setFrameShape(QFrame.StyledPanel)
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(4, 4, 4, 4)
        calendar = QCalendarWidget(popup)
        selected_date = date_edit.date()
        calendar.setGridVisible(True)
        calendar.setMinimumSize(340, 280)
        calendar.setCurrentPage(selected_date.year(), selected_date.month())
        calendar.setSelectedDate(selected_date)
        calendar.setStyleSheet("""
            QCalendarWidget QToolButton {
                min-width: 44px;
                min-height: 24px;
                padding: 2px 6px;
            }
            QCalendarWidget QAbstractItemView {
                font-size: 12px;
                min-width: 300px;
                min-height: 210px;
                selection-background-color: #2563eb;
                selection-color: white;
            }
        """)
        calendar.clicked.connect(lambda selected, edit=date_edit, frame=popup: self._apply_calendar_date(edit, selected, frame))
        popup_layout.addWidget(calendar)
        popup.move(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        self._calendar_popup = popup
        popup.show()

    def _apply_calendar_date(self, date_edit: QDateEdit, selected_date: QDate, popup: QFrame):
        date_edit.setDate(selected_date)
        popup.close()

    def _set_shared_end_date_today(self, source_name: str):
        end_date_widget = getattr(self, f"{source_name}_end_date", None)
        if end_date_widget:
            end_date_widget.setDate(QDate.currentDate())
            self._sync_dates(source_name)

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
            self.check_status_btn.setEnabled(False)
            self.check_status_btn.setText("檢查中...")

            # 在背景執行
            def check_task():
                return self._get_overview_status()

            worker = self._start_worker(TaskWorker(check_task))
            worker.finished.connect(self._on_status_checked)
            worker.error.connect(self._on_status_error)
            self._attach_worker_cleanup(worker)
            worker.start()

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
            "monthly_revenue": "monthly_revenue",
        }
        status_key = source_map.get(source, source)
        if hasattr(self.update_service, "check_source_detail"):
            return {status_key: self.update_service.check_source_detail(source)}
        return {status_key: self.update_service.check_data_status().get(status_key, {})}

    def _check_source_detail(self, source: str, force: bool = False):
        """背景載入單一資料來源的詳細狀態"""
        if not force and source in self._loaded_detail_sources:
            return

        def check_task():
            return {"source": source, "status": self._get_source_detail(source)}

        worker = self._start_worker(TaskWorker(check_task))
        worker.finished.connect(self._on_source_detail_checked)
        worker.error.connect(self._on_status_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_source_detail_checked(self, payload: Dict[str, Any]):
        """單一資料來源詳細狀態載入完成"""
        source = payload.get("source")
        status = payload.get("status", {})
        if source:
            self._loaded_detail_sources.add(source)
        self._on_status_checked(status)
        self._render_source_detail_status(str(source or ""), status)

    def _format_status_token(self, status: Any) -> str:
        mapping = {
            "ok": "正常",
            "warning": "需注意",
            "error": "異常",
            "missing": "缺漏",
            "unknown": "未知",
        }
        return mapping.get(str(status).lower(), str(status or "未知"))

    def _format_source_detail_summary(self, source: str, detail: Dict[str, Any]) -> str:
        latest_date = detail.get("latest_date") or "未知"
        total_records = int(detail.get("total_records") or 0)
        lines = [
            f"最新日期：{latest_date}",
            f"SQLite 筆數：{total_records:,}",
            f"狀態：{self._format_status_token(detail.get('status'))}",
        ]
        if source == "daily":
            csv_count = detail.get("csv_file_count") or detail.get("file_count")
            if csv_count is not None:
                lines.append(f"CSV 日檔數：{int(csv_count):,}")
            missing_dates = detail.get("missing_dates") or []
            if missing_dates:
                lines.append("缺漏日期：" + "、".join(str(date) for date in missing_dates[:8]))
        elif source == "broker_branch":
            lines.append(f"實際天數：{int(detail.get('date_count') or 0):,}")
            lines.append(f"雙榜紀錄：{int(detail.get('dual_count') or 0):,}")
            lines.append(f"張數榜專屬：{int(detail.get('e_only_count') or 0):,}")
            lines.append(f"金額榜專屬：{int(detail.get('b_only_count') or 0):,}")
        warnings = detail.get("warnings") or detail.get("quality_warnings") or []
        if warnings:
            lines.append("提醒：" + "；".join(str(item) for item in warnings[:3]))
        return "\n".join(lines)

    def _render_source_detail_status(self, source: str, status: Dict[str, Any]) -> None:
        source_to_key = {
            "daily": "daily_data",
            "broker_branch": "broker_branch",
        }
        source_to_label = {
            "daily": getattr(self, "daily_detail_status_label", None),
            "broker_branch": getattr(self, "broker_branch_detail_status_label", None),
        }
        key = source_to_key.get(source)
        label = source_to_label.get(source)
        if not key or label is None:
            return
        detail = status.get(key) or {}
        label.setText(self._format_source_detail_summary(source, detail))

    def _on_status_checked(self, status: Dict[str, Any]):
        """數據狀態檢查完成"""
        self.check_status_btn.setEnabled(True)
        self.check_status_btn.setText("檢查數據狀態")

        # 分別更新各資料區塊
        daily_text = self.daily_status_text.toPlainText()
        market_text = self.market_status_text.toPlainText()
        industry_text = self.industry_status_text.toPlainText()
        broker_branch_text = self.broker_branch_status_text.toPlainText()
        technical_text = self.technical_status_text.toPlainText()
        monthly_revenue_text = self.monthly_revenue_status_text.toPlainText()

        for key, value in status.items():
            latest_date = value.get('latest_date', '未知')
            total_records = value.get('total_records', 0)
            status_str = value.get('status', 'unknown')

            if key == 'broker_branch':
                date_count = value.get('date_count', 0)
                e_only = value.get('e_only_count', 0)
                b_only = value.get('b_only_count', 0)
                dual = value.get('dual_count', 0)
                status_display = (
                    f"最新日期：{latest_date}\n"
                    f"實際天數：{date_count} 天\n"
                    f"雙榜紀錄 (E&B)：{dual:,}\n"
                    f"張數榜專屬 (E-only)：{e_only:,}\n"
                    f"金額榜專屬 (B-only)：{b_only:,}\n"
                    f"總記錄數：{total_records:,}\n"
                    f"狀態：{status_str}"
                )
            else:
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
            elif key == 'monthly_revenue':
                monthly_revenue_text = status_display

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
        if not monthly_revenue_text:
            monthly_revenue_text = "尚未檢查"

        self.daily_status_text.setPlainText(daily_text)
        self.market_status_text.setPlainText(market_text)
        self.industry_status_text.setPlainText(industry_text)
        self.broker_branch_status_text.setPlainText(broker_branch_text)
        self.technical_status_text.setPlainText(technical_text)
        self.monthly_revenue_status_text.setPlainText(monthly_revenue_text)
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
        return self._get_recent_business_day_range(end_date, lookback_days)

    @staticmethod
    def _get_recent_business_day_range(end_date: str, business_days: int) -> tuple[str, str]:
        """以週一至週五計算最近 N 個工作日，結束日仍保留使用者選定日期。"""
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        remaining_days = max(1, int(business_days))
        cursor = end_date_obj
        start_date_obj = end_date_obj
        while remaining_days > 0:
            if cursor.weekday() < 5:
                start_date_obj = cursor
                remaining_days -= 1
            cursor = cursor - timedelta(days=1)
        return start_date_obj.strftime("%Y-%m-%d"), end_date

    def _get_tpex_reference_date(self, end_date: str) -> str:
        """將結束日調整為最近交易日（至少避開週末）。"""
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        for _ in range(7):
            if end_dt.weekday() < 5:
                break
            end_dt = end_dt - timedelta(days=1)
        return end_dt.strftime("%Y-%m-%d")

    def _update_tpex_daily_prices(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """更新 TPEX 日價；舊 service 測試替身可退回單日 API。"""
        update_range = getattr(self.update_service, "update_tpex_daily_price_range", None)
        if update_range is not None:
            return update_range(
                start_date,
                end_date,
                delay_seconds=1.0,
                sync_to_sqlite=False,
                force_refresh=False,
                break_on_repeated_source_date=False,
            )
        return self.update_service.update_tpex_daily_price(end_date)

    def _write_tpex_background_status(self, payload: Dict[str, Any]) -> None:
        """寫入背景任務狀態 JSON，供狀態按鈕即時讀取。"""
        try:
            self.tpex_refresh_state_file.parent.mkdir(parents=True, exist_ok=True)
            payload.update({"updated_at": datetime.now().isoformat(timespec="seconds")})
            self.tpex_refresh_state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _execute_background_tpex_refresh(self):
        """以獨立進程背景執行 TPEX + TWSE + 技術指標完整流程。"""
        if self._tpex_background_process is not None and self._tpex_background_process.poll() is None:
            QMessageBox.information(
                self,
                "背景任務進行中",
                "TPEX 背景任務尚未結束，請先完成後再啟動下一次。",
            )
            return

        start_date, end_date = self._get_selected_date_range()
        script_path = self.update_service.scripts_dir / "run_tpex_full_refresh_and_technical.py"
        if not script_path.exists():
            QMessageBox.critical(self, "背景任務啟動失敗", f"找不到背景腳本：{script_path}")
            return

        self.tpex_background_btn.setEnabled(False)
        self.tpex_background_btn.setText("背景補齊中...")

        initial_status = {
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "tpex_full_refresh_and_technical",
            "start_date": start_date,
            "end_date": end_date,
            "steps": {},
        }
        self._write_tpex_background_status(initial_status)

        env = os.environ.copy()
        env["DATA_ROOT"] = str(self.update_service.config.data_root)
        env["OUTPUT_ROOT"] = str(self.update_service.config.output_root)
        env["PROFILE"] = str(self.update_service.config.profile)

        cmd = [
            sys.executable,
            str(script_path),
            "--start-date",
            start_date,
            "--end-date",
            end_date,
            "--state-file",
            str(self.tpex_refresh_state_file),
            "--delay-seconds",
            "1.0",
            "--sync-sqlite",
        ]
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            self._log("開始啟動 TPEX 背景補齊流程（含 SQLite 同步與技術指標增量檢查）")
            self._tpex_background_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
            self._log(
                f"TPEX 背景任務已啟動，PID={self._tpex_background_process.pid}，可點『📡 檢查背景任務狀態』查看進度。"
            )
        except Exception as exc:
            self.tpex_background_btn.setEnabled(True)
            self.tpex_background_btn.setText("🚀 背景補齊 TPEX + 技術指標")
            error_msg = f"背景任務啟動失敗：{exc}"
            self._write_tpex_background_status({"status": "failed", "message": error_msg})
            QMessageBox.critical(self, "背景任務啟動失敗", error_msg)

    def _show_tpex_background_status(self):
        """讀取並顯示背景任務 JSON 狀態。"""
        if not self.tpex_refresh_state_file.exists():
            QMessageBox.information(self, "背景任務狀態", "目前尚未啟動 TPEX 背景補齊任務。")
            return

        try:
            raw = json.loads(self.tpex_refresh_state_file.read_text(encoding="utf-8"))
            lines = [
                f"狀態：{raw.get('status', 'unknown')}",
                f"啟動時間：{raw.get('started_at', '-')}",
                f"最後更新：{raw.get('updated_at', '-')}",
                f"區間：{raw.get('start_date', '-') or '-'} 至 {raw.get('end_date', '-') or '-'}",
                f"模式：{raw.get('mode', '-')}",
            ]

            steps = raw.get("steps", {}) or {}
            twse = steps.get("twse_daily", {})
            tpex = steps.get("tpex_daily", {})
            sqlite = steps.get("sqlite", {})
            tech = steps.get("technical", {})

            def _fmt_step(name: str, payload: Dict[str, Any]) -> str:
                return (
                    f"{name}: {payload.get('status', '-')}, "
                    f"rows={payload.get('rows', '-')}, message={payload.get('message', '-') or '-'}"
                )

            lines.append("---")
            lines.append(_fmt_step("TWSE 每日", twse))
            lines.append(_fmt_step("TPEX 每日", tpex))
            lines.append(_fmt_step("SQLite", sqlite))
            lines.append(_fmt_step("技術指標", tech))

            if raw.get("status") == "failed":
                lines.append(f"錯誤訊息：{raw.get('message', '-')}")

            self._log("\n".join(lines))
            QMessageBox.information(self, "背景任務狀態", "\n".join(lines))

            if raw.get("status") in {"done", "failed"}:
                self.tpex_background_btn.setEnabled(True)
                self.tpex_background_btn.setText("🚀 背景補齊 TPEX + 技術指標")
        except Exception as exc:
            QMessageBox.critical(self, "背景任務狀態", f"讀取狀態失敗：{exc}")
    def _run_update_all(self, mode="quick", progress_callback=None) -> Dict[str, Any]:
        """一鍵更新所有數據流程（支援快速與安全分流）"""
        start_date, end_date = self._get_selected_date_range()
        tpex_reference_date = self._get_tpex_reference_date(end_date)
        completed = []
        warnings = []

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
        is_quick_mode = (mode == "quick" and use_sqlite)

        # 快速更新仍跳過大型合併，但資料補齊窗口與安全更新一致使用最近工作日範圍。
        quick_start_date = start_date

        daily_update_start_date = quick_start_date if is_quick_mode else start_date

        steps = [
            ("檢查資料狀態", 0, lambda: self._get_overview_status()),
            ("每日股價更新", 12, lambda: self.update_service.update_daily(daily_update_start_date, end_date)),
            (
                "TPEX 每日股價更新",
                16,
                lambda: self._update_tpex_daily_prices(daily_update_start_date, end_date),
            ),
            ("同步每日股價至 SQLite", 18, lambda: self.update_service.sync_source_to_sqlite("daily_price_files", daily_update_start_date, end_date)),
            ("大盤指數更新", 24, lambda: self.update_service.update_market(start_date, end_date)),
            ("同步大盤指數至 SQLite", 30, lambda: self.update_service.sync_source_to_sqlite("market_index")),
            ("產業指數更新", 36, lambda: self.update_service.update_industry(start_date, end_date)),
            ("同步產業指數至 SQLite", 42, lambda: self.update_service.sync_source_to_sqlite("industry_index")),
            ("券商分點更新", 48, lambda: self.update_service.update_broker_branch(quick_start_date, end_date)),
        ]

        is_quick_mode = (mode == "quick" and use_sqlite)

        if is_quick_mode:
            # ⚡ 快速更新：跳過大型合併 CSV，直接同步單日檔案至 SQLite
            steps.extend([
                ("同步券商分點至 SQLite (直接檔案同步)", 65, lambda: self.update_service.sync_source_to_sqlite("broker_branch_files", quick_start_date, end_date)),
            ])
        else:
            # 🛡️ 安全更新：執行完整 CSV 合併整合與 SQLite 同步
            steps.extend([
                ("合併每日資料", 55, lambda: self.update_service.merge_daily_data(force_all=False)),
                ("同步合併每日資料至 SQLite", 62, lambda: self.update_service.sync_source_to_sqlite("daily_data")),
                ("合併券商分點", 69, lambda: self.update_service.merge_broker_branch_data()),
                ("同步券商分點至 SQLite", 76, lambda: self.update_service.sync_source_to_sqlite("broker_branch")),
            ])

        steps.extend([
            (
                "檢查並增量計算技術指標",
                88,
                lambda: self._run_incremental_technical_if_needed(progress_callback),
            ),
            ("刷新資料狀態", 100, lambda: self._get_overview_status()),
        ])

        for name, progress, action in steps:
            result = run_step(name, progress, action)
            if isinstance(result, dict) and not result.get("success", True):
                if name.startswith("TPEX 每日股價更新"):
                    warning = f"{name}: {result.get('message', f'{name} 失敗')}"
                    warnings.append(warning)
                    completed.append({"step": name, "result": result, "warning": True})
                    continue
                return {
                    "success": False,
                    "message": result.get("message", f"{name} 失敗"),
                    "failed_step": name,
                    "completed_steps": completed,
                    "step_result": result,
                }

        final_msg = "快速更新所有數據完成" if is_quick_mode else "安全更新所有數據完成"
        report(final_msg, 100)
        return {
            "success": True,
            "message": final_msg,
            "completed_steps": completed,
            "warnings": warnings,
        }

    def _run_incremental_technical_if_needed(self, progress_callback=None) -> Dict[str, Any]:
        """Skip technical indicator calculation when the overview already shows it is current."""
        status = self._get_overview_status()
        daily_latest = self._parse_status_date(status.get("daily_data", {}).get("latest_date"))
        technical_latest = self._parse_status_date(status.get("technical_indicators", {}).get("latest_date"))

        if daily_latest is not None and technical_latest is not None and technical_latest >= daily_latest:
            message = (
                f"技術指標已是最新（{technical_latest.strftime('%Y-%m-%d')}），"
                "跳過增量計算"
            )
            if progress_callback:
                progress_callback(message, 88)
            self._log(message)
            return {
                "success": True,
                "message": message,
                "skipped": True,
                "skip_reason": "technical_indicators_current",
                "daily_latest": daily_latest.strftime("%Y-%m-%d"),
                "technical_latest": technical_latest.strftime("%Y-%m-%d"),
                "total_stocks": 0,
                "success_count": 0,
                "fail_count": 0,
                "updated_stocks": [],
                "failed_stocks": [],
            }

        return self.update_service.calculate_technical_indicators(
            target_stock=None,
            force_all=False,
            start_date=None,
            progress_callback=progress_callback,
            incremental_lookback_days=120,
        )

    @staticmethod
    def _parse_status_date(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        value_str = str(value).strip()
        if not value_str or value_str.lower() in {"nan", "nat", "none"}:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value_str[:10] if fmt == "%Y-%m-%d" else value_str[:8], fmt)
            except ValueError:
                continue
        return None

    def _run_safe_update_all(self, progress_callback=None) -> Dict[str, Any]:
        """執行保守的一鍵安全更新流程，供 UI worker 與測試共用，保持向後相容"""
        use_sqlite = getattr(self.update_service.config, "use_sqlite", False)
        mode = "quick" if use_sqlite else "safe"
        return self._run_update_all(mode=mode, progress_callback=progress_callback)

    def _execute_quick_update_all(self):
        """以背景工作執行快速更新所有數據"""
        self._execute_update_all(mode="quick")

    def _execute_safe_update_all(self):
        """以背景工作執行安全更新所有數據"""
        self._execute_update_all(mode="safe")

    def _execute_update_all(self, mode="quick"):
        """以背景工作執行更新所有數據"""
        self._current_update_mode = mode

        self.quick_update_all_btn.setEnabled(False)
        self.safe_update_all_btn.setEnabled(False)

        mode_name = "快速更新" if mode == "quick" else "安全更新"
        btn_text = "快速更新中..." if mode == "quick" else "安全更新中..."

        if mode == "quick":
            self.quick_update_all_btn.setText(btn_text)
        else:
            self.safe_update_all_btn.setText(btn_text)

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"準備{mode_name}所有數據...")
        self.log_text.clear()
        self._log(f"開始{mode_name}所有數據")

        worker = self._start_worker(ProgressTaskWorker(self._run_update_all, mode=mode))
        worker.progress.connect(self._on_update_all_progress)
        worker.finished.connect(self._on_update_all_finished)
        worker.error.connect(self._on_update_all_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_update_all_progress(self, message: str, progress: int):
        """更新更新流程進度"""
        mode_name = "快速更新" if getattr(self, "_current_update_mode", "quick") == "quick" else "安全更新"
        self.progress_label.setText(message)
        self.progress_bar.setValue(progress)
        self._log(f"[{mode_name} {progress}%] {message}")

    def _on_update_all_finished(self, result: Dict[str, Any]):
        """更新流程完成"""
        self.quick_update_all_btn.setEnabled(True)
        self.safe_update_all_btn.setEnabled(True)
        self.quick_update_all_btn.setText("⚡ 快速更新 (跳過大型合併)")
        self.safe_update_all_btn.setText("🛡️ 安全更新 (完整 CSV + SQLite)")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        mode_name = "快速更新" if getattr(self, "_current_update_mode", "quick") == "quick" else "安全更新"

        if result.get("success", False):
            message = result.get("message", f"{mode_name}完成")
            warnings = result.get("warnings") or []
            if warnings:
                warning_text = "\n".join(str(warning) for warning in warnings)
                self._log(f"{message}；警告：{warning_text}")
                QMessageBox.warning(self, f"{mode_name}完成但有警告", f"{message}\n\n警告：\n{warning_text}")
            else:
                self._log(message)
                QMessageBox.information(self, f"{mode_name}完成", message)
            self._check_data_status()
            return

        failed_step = result.get("failed_step", "未知步驟")
        message = result.get("message", f"{mode_name}失敗")
        self._log(f"{mode_name}失敗：{failed_step} - {message}")
        QMessageBox.warning(self, f"{mode_name}未完成", f"{failed_step} 失敗：\n{message}")

    def _on_update_all_error(self, error_msg: str):
        """更新流程出錯"""
        self.quick_update_all_btn.setEnabled(True)
        self.safe_update_all_btn.setEnabled(True)
        self.quick_update_all_btn.setText("⚡ 快速更新 (跳過大型合併)")
        self.safe_update_all_btn.setText("🛡️ 安全更新 (完整 CSV + SQLite)")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        mode_name = "快速更新" if getattr(self, "_current_update_mode", "quick") == "quick" else "安全更新"
        self._log(f"{mode_name}錯誤：{error_msg}")

        error_display = error_msg
        if len(error_display) > 500:
            error_display = error_display[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整訊息）"
        QMessageBox.critical(self, f"{mode_name}失敗", error_display)

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

        # 創建 Worker 任務
        def update_task(progress_callback=None):
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行更新任務: update_type={update_type}")
                if update_type == 'daily':
                    if progress_callback:
                        progress_callback("更新 TWSE 每日股價", 15)
                    result = self.update_service.update_daily(start_date, end_date)
                    if progress_callback:
                        progress_callback("更新 TPEX 每日收盤行情", 30)
                    tpex_result = self._update_tpex_daily_prices(start_date, end_date)
                    warnings = list(result.get('warnings', []))
                    if tpex_result.get('success', False):
                        result['message'] = (
                            f"{result.get('message', '每日股票數據更新完成')}\n"
                            f"TPEX 每日股價更新: {tpex_result.get('message', '完成')}"
                        )
                        result['updated_dates'] = list(result.get('updated_dates', [])) + list(
                            tpex_result.get('updated_dates', [])
                        )
                    else:
                        warnings.append(
                            f"TPEX 每日股價更新: {tpex_result.get('message', 'unknown error')}"
                        )

                    if progress_callback:
                        progress_callback("同步每日股價到 SQLite", 55)
                    sqlite_result = self.update_service.sync_source_to_sqlite(
                        "daily_price_files",
                        start_date,
                        end_date,
                    )
                    if not sqlite_result.get("success", True):
                        warnings.append(
                            f"同步 daily_price_files 到 SQLite 失敗: {sqlite_result.get('message', 'unknown error')}"
                        )
                    else:
                        result["synced_records"] = int(result.get("synced_records", 0)) + int(
                            sqlite_result.get("synced_records", 0)
                        )

                    if progress_callback:
                        progress_callback("更新技術指標（增量）", 85)
                    indicator_result = self.update_service.calculate_technical_indicators(
                        target_stock=None,
                        force_all=False,
                        start_date=None,
                        progress_callback=progress_callback,
                    )
                    if not indicator_result.get("success", False):
                        warnings.append(
                            f"技術指標計算失敗: {indicator_result.get('message', 'unknown error')}"
                        )
                    if warnings:
                        result['warnings'] = warnings
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

        worker = self._start_worker(ProgressTaskWorker(update_task))
        worker.progress.connect(self._on_update_progress)
        worker.finished.connect(self._on_update_finished)
        worker.error.connect(self._on_update_error)
        self._attach_worker_cleanup(worker)
        worker.start()

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
            warnings = result.get('warnings', [])

            self._log(f"更新完成：{message}")
            if updated_dates:
                self._log(f"成功更新日期：{len(updated_dates)} 個")
            if failed_dates:
                self._log(f"失敗日期：{len(failed_dates)} 個")
            for warning in warnings:
                self._log(f"警告：{warning}")

            display_message = message
            if warnings:
                display_message = f"{message}\n\n警告：\n" + "\n".join(warnings)

            QMessageBox.information(self, "更新完成", display_message)

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
        data_root = getattr(getattr(self, "config", None), "data_root", None) or "{DATA_ROOT}"
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("確認強制合併")
        msg_box.setText("強制重新合併所有每日股價會重建 SQLite 匯入與索引。")
        msg_box.setInformativeText(
            "此操作會重新讀取 CSV 並重建每日股價相關 SQLite 資料，可能需要較長時間。"
            f"\n\n強制合併是針對 SQLite 資料庫重新進行 CSV 匯入與索引建立，"
            f"不應亦不會修改或刪除 {data_root} 底下的 raw CSV 原始檔案，以保障資料安全性。"
            "\n\n建議在執行前確認近期備份狀態；若只是測試取消流程，請按「取消」。"
        )
        cancel_button = msg_box.addButton("取消", QMessageBox.RejectRole)
        confirm_button = msg_box.addButton("確認強制合併", QMessageBox.DestructiveRole)
        msg_box.setDefaultButton(cancel_button)
        msg_box.exec()
        if msg_box.clickedButton() is not confirm_button:
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

        worker = self._start_worker(TaskWorker(merge_task))
        worker.finished.connect(self._on_merge_finished)
        worker.error.connect(self._on_merge_error)
        self._attach_worker_cleanup(worker)
        worker.start()

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

        worker = self._start_worker(TaskWorker(merge_task))
        worker.finished.connect(self._on_merge_broker_branch_finished)
        worker.error.connect(self._on_merge_broker_branch_error)
        self._attach_worker_cleanup(worker)
        worker.start()

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

        worker = self._start_worker(ProgressTaskWorker(calculate_task))
        worker.progress.connect(self._on_tech_progress)
        worker.finished.connect(self._on_tech_calculate_finished)
        worker.error.connect(self._on_tech_calculate_error)
        self._attach_worker_cleanup(worker)
        worker.start()

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

        def export_task():
            return self.update_service.export_table_to_csv(
                table_name=table_name,
                target_path=target_path,
                start_date=s_date,
                end_date=e_date
            )

        worker = self._start_worker(TaskWorker(export_task))

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

        worker.finished.connect(on_export_finished)
        worker.error.connect(on_export_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def closeEvent(self, event):
        """關閉事件"""
        for worker in list(self._active_workers):
            if worker.isRunning():
                if hasattr(worker, "cancel"):
                    worker.cancel()
                if not worker.wait(5000) and hasattr(worker, "terminate"):
                    worker.terminate()
                    worker.wait(1000)
        event.accept()

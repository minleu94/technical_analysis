"""
持倉管理與交易日誌視圖 (Phase 4.1 Portfolio MVP)
提供手動交易記錄、衍生持倉加載、交易日誌管理以及基於推薦引擎的持倉狀態條件監控。
"""

import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from uuid import uuid4

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QMessageBox, QDialog, QDialogButtonBox, QLineEdit,
    QTextEdit, QListWidget, QListWidgetItem, QHeaderView, QMenu,
    QAbstractItemView, QGroupBox, QSplitter, QComboBox, QDateEdit,
    QDoubleSpinBox, QSpinBox, QFormLayout, QTabWidget, QFrame, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QSize, QDate
from PySide6.QtGui import QFont, QColor, QPalette, QBrush

from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.portfolio_service import PortfolioService
from app_module.dtos.portfolio_dtos import PortfolioDTO
from app_module.journal_service import JournalService
from app_module.recommendation_service import RecommendationService
from app_module.broker_flow_service import BrokerFlowService
from app_module.portfolio_condition_monitor import (
    PortfolioConditionMonitor,
    PortfolioCurrentSnapshot,
)
from portfolio_module import PortfolioValidationError
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.info_button import InfoButton
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.workers.task_worker import TaskWorker
from app_module.strategy_version_service import StrategyVersionService
from app_module.portfolio_chip_service import PortfolioChipService
from app_module.portfolio_feedback_service import PortfolioFeedbackService
from app_module.portfolio_stress_lab_service import (
    PortfolioStressLabService,
)
from app_module.portfolio_stress_history import (
    DEFAULT_STRESS_HISTORY_FILENAME,
    PortfolioStressHistoryReadService,
    PortfolioStressHistoryRecord,
    PortfolioStressHistoryRepository,
)
from app_module.paper_portfolio_readiness_service import (
    PaperPortfolioReadinessService,
)
from app_module.paper_portfolio_weekly_evidence_service import (
    PaperPortfolioWeeklyEvidenceService,
)
from app_module.paper_equal_weight_benchmark_builder import (
    PaperEqualWeightBenchmarkBuilder,
)
from app_module.paper_trade_import_service import PaperTradeImportService
from app_module.trade_import_service import TradeImportService

logger = logging.getLogger(__name__)


def _first_error_line(message: object) -> str:
    """Normalize empty worker exceptions for a stable UI diagnostic."""

    for line in str(message or "").splitlines():
        if line.strip():
            return line.strip()
    return "未提供錯誤訊息"


def _paper_status_text(value: Any) -> str:
    """Render Paper readiness tokens with a Chinese explanation and raw token."""

    raw_status = str(value or "unknown").strip().lower() or "unknown"
    labels = {
        "ready": "可用",
        "partial": "部分完成",
        "degraded": "降級",
        "not_configured": "尚未配置",
        "not_computable": "尚不可計算",
        "not_computable_cost_ledger_missing": "尚不可計算（成本帳缺漏）",
        "not_computable_cost_ledger_incomplete": "尚不可計算（成本帳不完整）",
        "not_computable_future_dated": "尚不可計算（日期超前）",
        "not_computable_boundary_mismatch": "尚不可計算（期間邊界不符）",
        "invalid": "格式異常",
        "missing": "缺漏",
        "unknown": "未知",
    }
    return f"{labels.get(raw_status, raw_status)}（{raw_status}）"


class GradientCard(QFrame):
    """精美 HSL 漸層資訊展示卡片"""

    def __init__(self, title: str, value: str, gradient_style: str, parent=None):
        super().__init__(parent)
        self.setObjectName("portfolioMetricCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setMinimumHeight(86)
        self.setMaximumHeight(96)

        # 設置漸層樣式與圓角、陰影
        self.setStyleSheet(f"""
            QFrame#portfolioMetricCard {{
                background: {gradient_style};
                border-radius: {MIDNIGHT_ANALYST.radius_panel}px;
                border: 1px solid {MIDNIGHT_ANALYST.border};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(4)

        # 標題
        self.title_label = QLabel(title)
        title_font = QFont(MIDNIGHT_ANALYST.font_family, 9)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        layout.addWidget(self.title_label)

        # 數值
        self.value_label = QLabel(value)
        value_font = QFont(MIDNIGHT_ANALYST.mono_family, 18)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        layout.addWidget(self.value_label)

    def update_value(self, new_value: str):
        self.value_label.setText(new_value)


class AddTradeDialog(QDialog):
    """手動交易記錄對話框"""

    def __init__(self, recommendation_service: Optional[RecommendationService] = None, parent=None):
        super().__init__(parent)
        self.recommendation_service = recommendation_service
        self.setWindowTitle("手動記錄交易")
        self.setMinimumWidth(420)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        # 證券代號
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("例如：2330")
        self.code_input.textChanged.connect(self._auto_query_stock_name)
        form_layout.addRow("證券代號 *:", self.code_input)

        self.code_error_label = QLabel("")
        self.code_error_label.setStyleSheet("color: #f56565;")
        self.code_error_label.setWordWrap(True)
        form_layout.addRow("", self.code_error_label)

        # 證券名稱
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("自動查詢或手動輸入")
        form_layout.addRow("證券名稱 *:", self.name_input)

        # 交易別
        self.side_combo = QComboBox()
        self.side_combo.addItem("買入", "buy")
        self.side_combo.addItem("賣出", "sell")
        form_layout.addRow("交易類別 *:", self.side_combo)

        # 股數
        self.qty_input = QDoubleSpinBox()
        self.qty_input.setRange(0.01, 10000000.0)
        self.qty_input.setDecimals(2)
        self.qty_input.setSingleStep(1000.0)
        self.qty_input.setValue(1000.0)
        form_layout.addRow("交易股數 *:", self.qty_input)

        # 單價
        self.price_input = QDoubleSpinBox()
        self.price_input.setRange(0.01, 100000.0)
        self.price_input.setDecimals(2)
        self.price_input.setValue(100.0)
        form_layout.addRow("成交單價 *:", self.price_input)

        # 日期
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        form_layout.addRow("交易日期 *:", self.date_input)

        # 手續費
        self.fees_input = QDoubleSpinBox()
        self.fees_input.setRange(0.0, 1000000.0)
        self.fees_input.setValue(0.0)
        form_layout.addRow("交易費用 (手續費):", self.fees_input)

        # 稅金
        self.taxes_input = QDoubleSpinBox()
        self.taxes_input.setRange(0.0, 1000000.0)
        self.taxes_input.setValue(0.0)
        form_layout.addRow("交易稅金 (賣出時):", self.taxes_input)

        self._fees_manually_edited = False
        self._taxes_manually_edited = False
        self.qty_input.valueChanged.connect(self._refresh_default_costs)
        self.price_input.valueChanged.connect(self._refresh_default_costs)
        self.side_combo.currentIndexChanged.connect(self._refresh_default_costs)
        self.fees_input.valueChanged.connect(lambda _value: setattr(self, "_fees_manually_edited", True))
        self.taxes_input.valueChanged.connect(lambda _value: setattr(self, "_taxes_manually_edited", True))
        self._refresh_default_costs()

        # 策略關聯
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("無關聯 / 手動交易", "")
        self.strategy_combo.addItem("暴衝突破策略 (breakout)", "breakout")
        self.strategy_combo.addItem("穩健均值回歸策略 (mean_reversion)", "mean_reversion")
        form_layout.addRow("策略脈絡:", self.strategy_combo)

        # 備註
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(60)
        form_layout.addRow("備註 / 交易細節:", self.notes_input)

        layout.addLayout(form_layout)

        # 按鈕
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _auto_query_stock_name(self):
        """輸入證券代號時，若有 recommendation_service，嘗試解析或帶入股名"""
        code = self.code_input.text().strip()
        self.code_error_label.setText("")
        if not code or not self.recommendation_service:
            return

        # 嘗試從 config 的數據庫或已加載的名稱對照中搜尋（如果可用）
        try:
            # 這裡提供一個極簡的靜態映射，或是動態查詢 fallback
            mapper = getattr(self.recommendation_service, 'industry_mapper', None)
            if mapper and hasattr(mapper, 'get_stock_name'):
                name = mapper.get_stock_name(code)
                if name and name != code:
                    self.name_input.setText(name)
                    self.code_error_label.setText("")
                elif len(code) >= 4:
                    self.code_error_label.setText("找不到正式股票代號，請確認代號或手動補入名稱。")
        except Exception as e:
            logger.debug("Auto query stock name failed: %s", e)

    def _money_to_spin_value(self, value: Decimal) -> float:
        rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return float(rounded)  # numeric-boundary: presentation

    def _refresh_default_costs(self):
        notional = Decimal(str(self.qty_input.value())) * Decimal(str(self.price_input.value()))
        fee = notional * Decimal("0.001425")
        tax = notional * Decimal("0.003") if self.side_combo.currentData() == "sell" else Decimal("0")
        if not self._fees_manually_edited:
            self.fees_input.blockSignals(True)
            self.fees_input.setValue(self._money_to_spin_value(fee))
            self.fees_input.blockSignals(False)
        if not self._taxes_manually_edited:
            self.taxes_input.blockSignals(True)
            self.taxes_input.setValue(self._money_to_spin_value(tax))
            self.taxes_input.blockSignals(False)

    def _validate_and_accept(self):
        if not self.code_input.text().strip():
            QMessageBox.warning(self, "驗證失敗", "請輸入證券代號")
            return
        if self.code_error_label.text() and not self.name_input.text().strip():
            QMessageBox.warning(self, "驗證失敗", self.code_error_label.text())
            return
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "驗證失敗", "請輸入證券名稱")
            return
        self.accept()

    def get_trade_data(self) -> Dict[str, Any]:
        return {
            "stock_code": self.code_input.text().strip(),
            "stock_name": self.name_input.text().strip(),
            "side": self.side_combo.currentData(),
            "quantity": float(self.qty_input.value()),
            "price": float(self.price_input.value()),
            "trade_date": self.date_input.date().toString("yyyy-MM-dd"),
            "fees": float(self.fees_input.value()),
            "taxes": float(self.taxes_input.value()),
            "source_type": "strategy" if self.strategy_combo.currentData() else "",
            "source_id": self.strategy_combo.currentData(),
            "notes": self.notes_input.toPlainText().strip()
        }


class AddJournalDialog(QDialog):
    """新增交易日誌對話框"""

    def __init__(self, default_stock_code: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增交易日誌")
        self.setMinimumWidth(400)
        self._setup_ui(default_stock_code)

    def _setup_ui(self, default_stock_code: str):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # 標題
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("例如：TSMC 買入理由")
        form_layout.addRow("日記標題 *:", self.title_input)

        # 關聯股票
        self.stock_input = QLineEdit(default_stock_code)
        self.stock_input.setPlaceholderText("選填，例如：2330")
        form_layout.addRow("關聯證券代號:", self.stock_input)

        # 內容
        self.body_input = QTextEdit()
        self.body_input.setPlaceholderText("在此輸入您的交易心得、覆盤筆記或持倉檢查理由...")
        self.body_input.setMinimumHeight(150)
        form_layout.addRow("日記內容 *:", self.body_input)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self):
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "驗證失敗", "請輸入日記標題")
            return
        if not self.body_input.toPlainText().strip():
            QMessageBox.warning(self, "驗證失敗", "請輸入日記內容")
            return
        self.accept()

    def get_journal_data(self) -> Dict[str, Any]:
        return {
            "title": self.title_input.text().strip(),
            "stock_code": self.stock_input.text().strip(),
            "body": self.body_input.toPlainText().strip()
        }


class PortfolioView(QWidget):
    """持倉管理與交易日誌主 UI 視圖"""

    # 信號：當持倉數據或交易更新時發出
    portfolioUpdated = Signal()

    def __init__(
        self,
        portfolio_service: PortfolioService,
        journal_service: JournalService,
        recommendation_service: Optional[RecommendationService] = None,
        broker_flow_service: Optional[BrokerFlowService] = None,
        condition_monitor: Optional[PortfolioConditionMonitor] = None,
        parent=None,
        *,
        async_refresh: bool = False,
    ):
        super().__init__(parent)
        self.portfolio_service = portfolio_service
        self.journal_service = journal_service
        self.recommendation_service = recommendation_service
        self.condition_monitor = condition_monitor or PortfolioConditionMonitor()
        self.strategy_version_service = StrategyVersionService(self.portfolio_service.config)
        self.portfolio_feedback_service = PortfolioFeedbackService()
        self.stress_lab_service = PortfolioStressLabService()
        self.stress_history_db_path = (
            self.portfolio_service.config.output_root
            / "portfolio"
            / DEFAULT_STRESS_HISTORY_FILENAME
        )
        self.stress_history_read_service = PortfolioStressHistoryReadService(
            self.stress_history_db_path,
        )
        self.paper_readiness_service = PaperPortfolioReadinessService(
            output_root=self.portfolio_service.config.output_root,
        )
        self.paper_weekly_evidence_service = PaperPortfolioWeeklyEvidenceService(
            output_root=self.portfolio_service.config.output_root,
            benchmark_db_path=self.paper_readiness_service.benchmark_db_path,
            cost_ledger_db_path=self.paper_readiness_service.cost_ledger_db_path,
        )
        self.paper_benchmark_builder = PaperEqualWeightBenchmarkBuilder()
        self.paper_trade_import_service = PaperTradeImportService()
        self.trade_import_service = TradeImportService()
        self.chip_service = PortfolioChipService(
            self.portfolio_service.config,
            broker_flow_service,
        )

        self.positions_model: Optional[PandasTableModel] = None
        self.trades_model: Optional[PandasTableModel] = None
        # Summary 與明細表必須來自同一個 service DTO，避免一次 refresh 中
        # 分別讀取而顯示不同版本的持倉狀態。
        self._last_portfolio_dto: PortfolioDTO | None = None
        self.selected_stock_code: str = ""
        self.selected_trade_id: str = ""
        # PortfolioService 讀取可能同時掃描 JSONL、SQLite 與價格來源；主
        # 視窗採用既有 TaskWorker，且只把同一份 PortfolioDTO 交給摘要／表格。
        # 舊的同步呼叫端仍可明確使用預設模式，避免改變既有測試與嵌入頁面契約。
        self.async_refresh = bool(async_refresh)
        self._refresh_generation = 0
        self._worker_generation = 0
        self._refresh_worker: TaskWorker | None = None
        self._refresh_pending = False
        self._closing = False

        # 緩存最新推薦結果，用以在背景進行 Condition Monitor 條件監控
        self.rec_cache: Dict[str, Dict[str, Any]] = {}

        self._setup_ui()
        self.refresh_all()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("持倉與覆盤管理")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("portfolio", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)

        # ========== 1. 頂部狀態看板 (Summary Dashboard) ==========
        dashboard_layout = QHBoxLayout()
        dashboard_layout.setSpacing(10)

        self.card_net_val = GradientCard(
            "持倉市值（未含現金）", "N/A",
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a365d, stop:1 #2a4365)"
        )
        self.card_invested = GradientCard(
            "總投入資金", "TWD 0",
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2d3748, stop:1 #4a5568)"
        )
        self.card_pnl = GradientCard(
            "已實現損益", "TWD 0",
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a202c, stop:1 #2d3748)"
        )
        self.card_positions = GradientCard(
            "活躍持倉部位", "0 檔",
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #234e52, stop:1 #2c7a7b)"
        )

        dashboard_layout.addWidget(self.card_net_val)
        dashboard_layout.addWidget(self.card_invested)
        dashboard_layout.addWidget(self.card_pnl)
        dashboard_layout.addWidget(self.card_positions)
        main_layout.addLayout(dashboard_layout)

        self.active_positions_summary_label = QLabel("活躍持倉：0 檔")
        self.active_positions_summary_label.setWordWrap(True)
        self.active_positions_summary_label.setMaximumHeight(58)
        self.active_positions_summary_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; background-color: {MIDNIGHT_ANALYST.surface_1}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 7px 10px;"
        )
        main_layout.addWidget(self.active_positions_summary_label)

        self.portfolio_refresh_status_label = QLabel("持倉資料尚未載入")
        self.portfolio_refresh_status_label.setWordWrap(True)
        self.portfolio_refresh_status_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; padding: 2px 4px;"
        )
        main_layout.addWidget(self.portfolio_refresh_status_label)

        # ========== 2. 中部核心分割區 (Splitter) ==========
        main_splitter = QSplitter(Qt.Horizontal)

        # Left Panel: 持倉列表與操作
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_title = QLabel("當前持倉部位 (Positions)")
        left_title_font = QFont("Inter", 11)
        left_title_font.setBold(True)
        left_title.setFont(left_title_font)
        left_layout.addWidget(left_title)

        self.positions_table = QTableView()
        apply_financial_table_style(self.positions_table)
        self.positions_table.setSelectionBehavior(QTableView.SelectRows)
        self.positions_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.positions_table.setSortingEnabled(True)
        self.positions_table.horizontalHeader().setStretchLastSection(True)

        # 監聽持倉選擇事件，用以更新右側明細與日記
        self.positions_table.clicked.connect(self._on_position_selected)

        # 右鍵選單
        self.positions_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.positions_table.customContextMenuRequested.connect(self._show_position_context_menu)

        left_layout.addWidget(self.positions_table, stretch=1)

        # 左側底部操作按鈕
        btn_layout = QHBoxLayout()
        self.btn_record_trade = QPushButton("手動記錄交易")
        self.btn_record_trade.setProperty("variant", "primary")
        self.btn_record_trade.clicked.connect(self._show_record_trade_dialog)
        btn_layout.addWidget(self.btn_record_trade)

        self.btn_import_trades = QPushButton("匯入交易 CSV")
        self.btn_import_trades.setProperty("variant", "secondary")
        self.btn_import_trades.setToolTip("先唯讀預覽與驗證；二次確認後才會寫入交易紀錄。")
        self.btn_import_trades.clicked.connect(self._show_import_trades_dialog)
        btn_layout.addWidget(self.btn_import_trades)

        self.btn_add_journal = QPushButton("新增日記")
        self.btn_add_journal.clicked.connect(self._show_add_journal_dialog)
        btn_layout.addWidget(self.btn_add_journal)

        self.btn_refresh = QPushButton("整理刷新")
        self.btn_refresh.setAccessibleName("重新整理持倉資料")
        self.btn_refresh.setAccessibleDescription(
            "背景讀取單一 PortfolioDTO；完成後同步更新摘要與持倉表。"
        )
        self.btn_refresh.setToolTip("背景讀取既有持倉資料；不會寫入交易或資料庫。")
        self.btn_refresh.clicked.connect(self.refresh_all)
        btn_layout.addWidget(self.btn_refresh)

        # 🗑️ 清空全體數據按鈕
        self.btn_clear_all = QPushButton("清空全體數據")
        self.btn_clear_all.setProperty("variant", "danger")
        self.btn_clear_all.clicked.connect(self._show_clear_all_dialog)
        btn_layout.addWidget(self.btn_clear_all)

        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)

        main_splitter.addWidget(left_widget)

        # Right Panel: 歷史明細與日記
        right_widget = QTabWidget()

        # Right Tab 1: 交易歷史 (Trade History)
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(6, 6, 6, 6)

        history_filter_layout = QHBoxLayout()
        self.trade_filter_status_label = QLabel("顯示全部交易歷史")
        self.trade_filter_status_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        self.clear_trade_filter_button = QPushButton("清除篩選 / 顯示全部交易歷史")
        self.clear_trade_filter_button.setProperty("variant", "ghost")
        self.clear_trade_filter_button.clicked.connect(self._clear_trade_history_filter)
        history_filter_layout.addWidget(self.trade_filter_status_label)
        history_filter_layout.addStretch()
        history_filter_layout.addWidget(self.clear_trade_filter_button)
        history_layout.addLayout(history_filter_layout)

        self.trades_table = QTableView()
        apply_financial_table_style(self.trades_table)
        self.trades_table.setSelectionBehavior(QTableView.SelectRows)
        self.trades_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trades_table.horizontalHeader().setStretchLastSection(True)
        # 啟用右鍵選單
        self.trades_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trades_table.customContextMenuRequested.connect(self._show_trade_context_menu)
        history_layout.addWidget(self.trades_table)

        trade_action_layout = QHBoxLayout()
        self.trade_selection_hint_label = QLabel("選取一筆交易後，可安全刪除該筆紀錄。")
        self.trade_selection_hint_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 11px;"
        )
        self.trade_selection_hint_label.setWordWrap(True)
        trade_action_layout.addWidget(self.trade_selection_hint_label, 1)
        self.delete_selected_trade_button = QPushButton("刪除選取交易")
        self.delete_selected_trade_button.setObjectName("deleteSelectedTradeButton")
        self.delete_selected_trade_button.setProperty("variant", "danger")
        self.delete_selected_trade_button.setEnabled(False)
        self.delete_selected_trade_button.setToolTip(
            "選取一筆交易後才可刪除；系統會先驗證剩餘交易仍能重算合法持倉。"
        )
        self.delete_selected_trade_button.clicked.connect(self._delete_selected_trade)
        trade_action_layout.addWidget(self.delete_selected_trade_button)
        history_layout.addLayout(trade_action_layout)

        right_widget.addTab(history_tab, "交易歷史")

        # Right Tab 2: 覆盤日記 (Journal)
        journal_tab = QWidget()
        journal_layout = QVBoxLayout(journal_tab)
        journal_layout.setContentsMargins(6, 6, 6, 6)

        self.journal_list = QListWidget()
        self.journal_list.setWordWrap(True)
        # 啟用右鍵選單
        self.journal_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.journal_list.customContextMenuRequested.connect(self._show_journal_context_menu)
        journal_layout.addWidget(self.journal_list)

        right_widget.addTab(journal_tab, "覆盤日誌")

        # Right Tab 3: Paper Portfolio / Equal Weight（唯讀狀態）
        paper_tab = QWidget()
        paper_layout = QVBoxLayout(paper_tab)
        paper_layout.setContentsMargins(10, 10, 10, 10)
        paper_layout.setSpacing(10)

        paper_intro = QLabel(
            "這裡顯示排程 Paper Portfolio 的已保存 snapshot 與 Equal Weight 狀態。\n"
            "只讀既有 status／ledger，不建立資料庫、不補值，也不代表實盤績效。"
        )
        paper_intro.setWordWrap(True)
        paper_intro.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        paper_layout.addWidget(paper_intro)

        paper_controls = QHBoxLayout()
        self.btn_refresh_paper = QPushButton("重新讀取 Paper 狀態")
        self.btn_refresh_paper.setProperty("variant", "secondary")
        self.btn_refresh_paper.setToolTip("只讀 status JSON 與既有 append-only ledger，不會寫入資料。")
        self.btn_refresh_paper.clicked.connect(self._load_paper_readiness)
        paper_controls.addWidget(self.btn_refresh_paper)
        self.btn_build_paper_benchmark = QPushButton("預覽／建立 Equal Weight")
        self.btn_build_paper_benchmark.setProperty("variant", "secondary")
        self.btn_build_paper_benchmark.setToolTip(
            "先以 baseline、snapshot 與市場資料產生唯讀 preview；確認後才建立新的研究用 benchmark ledger，既有檔案不覆寫。"
        )
        self.btn_build_paper_benchmark.clicked.connect(self._build_paper_benchmark)
        paper_controls.addWidget(self.btn_build_paper_benchmark)
        self.btn_import_paper_fills = QPushButton("匯入 Paper 成交 CSV")
        self.btn_import_paper_fills.setProperty("variant", "secondary")
        self.btn_import_paper_fills.setToolTip(
            "要求完整 paper fill、成本、turnover 與 execution gap；確認後只寫入 Paper Trade Ledger。"
        )
        self.btn_import_paper_fills.clicked.connect(self._show_import_paper_fills_dialog)
        paper_controls.addWidget(self.btn_import_paper_fills)
        self.btn_export_paper_template = QPushButton("匯出成交範本")
        self.btn_export_paper_template.setProperty("variant", "secondary")
        self.btn_export_paper_template.setToolTip(
            "只建立空白 Paper fills CSV 欄位範本，不建立 ledger、不填入示例成交。"
        )
        self.btn_export_paper_template.clicked.connect(self._export_paper_fills_template)
        paper_controls.addWidget(self.btn_export_paper_template)
        self.paper_weekly_expected_days = QSpinBox()
        self.paper_weekly_expected_days.setRange(1, 31)
        self.paper_weekly_expected_days.setValue(5)
        self.paper_weekly_expected_days.setSuffix(" 個交易日")
        self.paper_weekly_expected_days.setToolTip("只用來標示 expected trading days；不足時週報會顯示 degraded。")
        paper_controls.addWidget(self.paper_weekly_expected_days)
        self.btn_refresh_paper_weekly = QPushButton("計算最近週報")
        self.btn_refresh_paper_weekly.setProperty("variant", "secondary")
        self.btn_refresh_paper_weekly.setToolTip("只讀最近 snapshot 邊界、benchmark 與成本帳，不會寫入資料。")
        self.btn_refresh_paper_weekly.clicked.connect(self._load_paper_weekly_evidence)
        paper_controls.addWidget(self.btn_refresh_paper_weekly)
        paper_controls.addStretch()
        paper_layout.addLayout(paper_controls)

        self.paper_readiness_summary_label = QLabel("尚未讀取 Paper Portfolio 狀態。")
        self.paper_readiness_summary_label.setWordWrap(True)
        self.paper_readiness_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        paper_layout.addWidget(self.paper_readiness_summary_label)
        self.paper_readiness_detail_label = QLabel("")
        self.paper_readiness_detail_label.setWordWrap(True)
        self.paper_readiness_detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        paper_layout.addWidget(self.paper_readiness_detail_label)

        self.paper_weekly_report_label = QLabel("尚未計算 Paper Portfolio 週報。")
        self.paper_weekly_report_label.setWordWrap(True)
        self.paper_weekly_report_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        paper_layout.addWidget(self.paper_weekly_report_label)

        self.paper_snapshot_table = QTableView()
        apply_financial_table_style(self.paper_snapshot_table)
        self.paper_snapshot_table.setSelectionBehavior(QTableView.SelectRows)
        self.paper_snapshot_table.horizontalHeader().setStretchLastSection(True)
        paper_layout.addWidget(self.paper_snapshot_table, 1)
        right_widget.addTab(paper_tab, "Paper Portfolio")

        # Right Tab 4: 情境與壓力測試（唯讀研究投影）
        stress_tab = QWidget()
        stress_layout = QVBoxLayout(stress_tab)
        stress_layout.setContentsMargins(10, 10, 10, 10)
        stress_layout.setSpacing(10)

        stress_intro = QLabel(
            "只對目前持倉套用明確的靜態情境；缺最新價格時不補值、不外推。\n"
            "結果是研究用敏感度分析，不是預測、績效證據或交易指令。"
        )
        stress_intro.setWordWrap(True)
        stress_intro.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        stress_layout.addWidget(stress_intro)

        stress_controls = QHBoxLayout()
        self.stress_scenario_combo = QComboBox()
        for scenario in self.stress_lab_service.list_scenarios():
            self.stress_scenario_combo.addItem(scenario.label, scenario.scenario_id)
        self.stress_scenario_combo.setToolTip("情境為靜態壓力假設，不代表市場預測。")
        stress_controls.addWidget(self.stress_scenario_combo, 1)
        self.btn_run_stress = QPushButton("執行情境")
        self.btn_run_stress.setProperty("variant", "secondary")
        self.btn_run_stress.clicked.connect(self._load_stress_lab)
        stress_controls.addWidget(self.btn_run_stress)
        self.btn_save_stress_history = QPushButton("保存研究快照")
        self.btn_save_stress_history.setProperty("variant", "secondary")
        self.btn_save_stress_history.setToolTip(
            "只在確認後保存目前 Stress Lab 結果；這是研究歷史，不是正式績效或交易證據。"
        )
        self.btn_save_stress_history.clicked.connect(self._save_stress_history)
        stress_controls.addWidget(self.btn_save_stress_history)
        stress_layout.addLayout(stress_controls)

        self.stress_summary_label = QLabel("尚未執行情境。")
        self.stress_summary_label.setWordWrap(True)
        self.stress_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        stress_layout.addWidget(self.stress_summary_label)
        self.stress_detail_label = QLabel("")
        self.stress_detail_label.setWordWrap(True)
        self.stress_detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        stress_layout.addWidget(self.stress_detail_label)

        self.stress_positions_table = QTableView()
        apply_financial_table_style(self.stress_positions_table)
        self.stress_positions_table.setSelectionBehavior(QTableView.SelectRows)
        self.stress_positions_table.horizontalHeader().setStretchLastSection(True)
        stress_layout.addWidget(self.stress_positions_table, 1)

        self.stress_history_summary_label = QLabel("Stress 歷史尚未讀取。")
        self.stress_history_summary_label.setWordWrap(True)
        self.stress_history_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        stress_layout.addWidget(self.stress_history_summary_label)

        self.stress_history_table = QTableView()
        apply_financial_table_style(self.stress_history_table)
        self.stress_history_table.setSelectionBehavior(QTableView.SelectRows)
        self.stress_history_table.horizontalHeader().setStretchLastSection(True)
        self.stress_history_table.setMaximumHeight(190)
        stress_layout.addWidget(self.stress_history_table)
        right_widget.addTab(stress_tab, "情境壓力")

        # Right Tab 5: 策略與價格監控 (Strategy & Price Monitor)
        monitor_tab = QWidget()
        monitor_layout = QVBoxLayout(monitor_tab)
        monitor_layout.setContentsMargins(10, 10, 10, 10)
        monitor_layout.setSpacing(10)

        # 價格對比區 (Entry vs Current vs SL/TP)
        price_group = QGroupBox("價格與停損停利對照")
        price_form = QFormLayout(price_group)
        price_form.setSpacing(8)

        self.lbl_mon_entry_price = QLabel("-")
        self.lbl_mon_current_price = QLabel("-")
        self.lbl_mon_pnl_pct = QLabel("-")
        self.lbl_mon_stop_loss = QLabel("-")
        self.lbl_mon_take_profit = QLabel("-")
        self.lbl_mon_status = QLabel("-")

        price_form.addRow("進場平均成本:", self.lbl_mon_entry_price)
        price_form.addRow("最新價格:", self.lbl_mon_current_price)
        price_form.addRow("未實現損益%:", self.lbl_mon_pnl_pct)
        price_form.addRow("停損門檻 (Stop Loss):", self.lbl_mon_stop_loss)
        price_form.addRow("停利門檻 (Take Profit):", self.lbl_mon_take_profit)
        price_form.addRow("監控判定狀態:", self.lbl_mon_status)

        monitor_layout.addWidget(price_group)

        # 策略版本詳情區
        strategy_group = QGroupBox("關聯策略與回測版本")
        strategy_form = QFormLayout(strategy_group)
        strategy_form.setSpacing(8)

        self.lbl_strat_id = QLabel("-")
        self.lbl_strat_version = QLabel("-")
        self.lbl_strat_params = QLabel("-")
        self.lbl_strat_perf = QLabel("-")

        strategy_form.addRow("策略 ID / 來源:", self.lbl_strat_id)
        strategy_form.addRow("推薦/版本細節:", self.lbl_strat_version)
        strategy_form.addRow("參數設定:", self.lbl_strat_params)
        strategy_form.addRow("回測/歷史績效:", self.lbl_strat_perf)

        monitor_layout.addWidget(strategy_group)
        monitor_layout.addStretch()

        right_widget.addTab(monitor_tab, "策略與價格監控")

        # Right Tab 6: 生命週期回顧 (Lifecycle Review)
        lifecycle_tab = QWidget()
        lifecycle_layout = QVBoxLayout(lifecycle_tab)
        lifecycle_layout.setContentsMargins(10, 10, 10, 10)
        lifecycle_layout.setSpacing(10)

        lifecycle_group = QGroupBox("Post-trade Attribution / Live vs Research Gap")
        lifecycle_form = QFormLayout(lifecycle_group)
        lifecycle_form.setSpacing(8)

        self.lbl_lifecycle_status = QLabel("-")
        self.lbl_lifecycle_source = QLabel("-")
        self.lbl_lifecycle_execution = QLabel("-")
        self.lbl_lifecycle_signal = QLabel("-")
        self.lbl_lifecycle_market = QLabel("-")
        self.lbl_lifecycle_data_quality = QLabel("-")
        self.lbl_lifecycle_tokens = QLabel("-")
        for label in [
            self.lbl_lifecycle_status,
            self.lbl_lifecycle_source,
            self.lbl_lifecycle_execution,
            self.lbl_lifecycle_signal,
            self.lbl_lifecycle_market,
            self.lbl_lifecycle_data_quality,
            self.lbl_lifecycle_tokens,
        ]:
            label.setWordWrap(True)

        lifecycle_form.addRow("Thesis 狀態:", self.lbl_lifecycle_status)
        lifecycle_form.addRow("來源追溯:", self.lbl_lifecycle_source)
        lifecycle_form.addRow("執行落差:", self.lbl_lifecycle_execution)
        lifecycle_form.addRow("訊號落差:", self.lbl_lifecycle_signal)
        lifecycle_form.addRow("市場體制:", self.lbl_lifecycle_market)
        lifecycle_form.addRow("資料品質:", self.lbl_lifecycle_data_quality)
        lifecycle_form.addRow("摘要 tokens:", self.lbl_lifecycle_tokens)

        lifecycle_layout.addWidget(lifecycle_group)
        lifecycle_layout.addStretch()
        right_widget.addTab(lifecycle_tab, "生命週期回顧")

        # Right Tab 7: 籌碼監控 (Chip Monitor)
        chip_tab = QWidget()
        chip_layout = QVBoxLayout(chip_tab)
        chip_layout.setContentsMargins(10, 10, 10, 10)
        chip_layout.setSpacing(10)

        # 1. 籌碼狀態與風險警告區
        chip_risk_group = QGroupBox("主力籌碼風險警示")
        chip_risk_form = QFormLayout(chip_risk_group)
        chip_risk_form.setSpacing(8)

        self.lbl_chip_risk_level = QLabel("-")
        self.lbl_chip_consecutive = QLabel("-")
        self.lbl_chip_net_5d = QLabel("-")
        self.lbl_chip_concentration = QLabel("-")
        self.lbl_chip_reasons = QLabel("-")
        self.lbl_chip_reasons.setWordWrap(True)

        chip_risk_form.addRow("籌碼風險評級:", self.lbl_chip_risk_level)
        chip_risk_form.addRow("連續買賣超天數:", self.lbl_chip_consecutive)
        chip_risk_form.addRow("近 5 日累計淨買賣超:", self.lbl_chip_net_5d)
        chip_risk_form.addRow("主力籌碼集中度:", self.lbl_chip_concentration)
        chip_risk_form.addRow("警示原因:", self.lbl_chip_reasons)

        chip_layout.addWidget(chip_risk_group)

        # 2. 分點買賣明細表
        chip_detail_group = QGroupBox("追蹤分點近 5 日買賣明細 (張)")
        chip_detail_layout = QVBoxLayout(chip_detail_group)
        chip_detail_layout.setContentsMargins(6, 6, 6, 6)

        self.chip_detail_table = QTableView()
        apply_financial_table_style(self.chip_detail_table)
        self.chip_detail_table.setSelectionBehavior(QTableView.SelectRows)
        self.chip_detail_table.horizontalHeader().setStretchLastSection(True)
        chip_detail_layout.addWidget(self.chip_detail_table)

        chip_layout.addWidget(chip_detail_group)

        # 3. 下鑽詳細主力流向按鈕
        self.btn_drill_down_chip = QPushButton("下鑽詳細主力流向")
        self.btn_drill_down_chip.setProperty("variant", "primary")
        self.btn_drill_down_chip.clicked.connect(self._on_drill_down_chip_clicked)
        chip_layout.addWidget(self.btn_drill_down_chip)

        right_widget.addTab(chip_tab, "籌碼監控")

        main_splitter.addWidget(right_widget)

        # 設定左右分割比例（60% : 40%）
        main_splitter.setSizes([720, 480])
        main_layout.addWidget(main_splitter)

    def refresh_all(self) -> None:
        """重新整理持倉資料；正式 UI 入口使用背景 worker。"""

        self._refresh_generation += 1
        if self.async_refresh:
            self._start_refresh_worker()
            return
        self._refresh_all_sync()

    def _refresh_all_sync(self) -> None:
        """保留同步相容入口，與背景完成回呼共用同一個套用路徑。"""

        logger.info("[PortfolioView] Refreshing all data synchronously...")
        try:
            portfolio = self._fetch_portfolio_dto()
        except Exception as error:  # noqa: BLE001
            self._handle_portfolio_refresh_error(str(error))
            return
        self._apply_portfolio_dto(portfolio)

    def _fetch_portfolio_dto(self, cancel_callback=None) -> PortfolioDTO:
        """在 worker 執行緒讀取一次 DTO，不在背景執行緒觸碰 Qt model。"""

        if callable(cancel_callback) and cancel_callback():
            raise RuntimeError("portfolio refresh cancelled before read")
        portfolio = self.portfolio_service.get_portfolio()
        if not isinstance(portfolio, PortfolioDTO):
            raise TypeError("PortfolioService.get_portfolio must return PortfolioDTO")
        return portfolio

    def _apply_portfolio_dto(self, portfolio: PortfolioDTO) -> None:
        """以單一 DTO 更新摘要／持倉表，再刷新其餘只讀區塊。"""

        self._last_portfolio_dto = portfolio
        self._load_portfolio_summary(portfolio)
        self._load_positions_table(portfolio)
        self._load_trades_history()
        self._load_journal_entries()
        self._load_paper_readiness()
        self._load_paper_weekly_evidence()
        self._load_stress_lab(portfolio=portfolio)
        self._load_stress_history()
        self._update_monitoring_tab(portfolio)
        self.portfolio_refresh_status_label.setText(
            f"持倉資料已更新｜DTO updated_at={portfolio.updated_at or '未提供'}｜"
            "摘要與持倉表使用同一份 DTO；只讀。"
        )

    def _start_refresh_worker(self) -> None:
        if self._closing:
            return
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            self._refresh_pending = True
            self.portfolio_refresh_status_label.setText(
                "持倉背景刷新已排隊；正在取消較早一輪，保留最新 generation。"
            )
            self._refresh_worker.cancel(cooperative=True, wait=False)
            return

        self._refresh_pending = False
        generation = self._refresh_generation
        self._worker_generation = generation
        self.btn_refresh.setEnabled(False)
        self.portfolio_refresh_status_label.setText(
            f"持倉資料背景讀取中（generation={generation}）；目前畫面保留既有資料。"
        )
        worker = TaskWorker(self._fetch_portfolio_dto)
        self._refresh_worker = worker
        worker.finished.connect(
            lambda portfolio, item=worker, value=generation: self._on_refresh_worker_finished(
                portfolio, value, item
            )
        )
        worker.error.connect(
            lambda message, item=worker, value=generation: self._on_refresh_worker_error(
                message, value, item
            )
        )
        worker.cancelled.connect(
            lambda item=worker, value=generation: self._on_refresh_worker_cancelled(value, item)
        )
        worker.start()

    def _on_refresh_worker_finished(
        self,
        portfolio: object,
        generation: int,
        worker: TaskWorker,
    ) -> None:
        if worker is not self._refresh_worker:
            worker.deleteLater()
            return
        if generation == self._refresh_generation and not self._closing:
            if not isinstance(portfolio, PortfolioDTO):
                self._handle_portfolio_refresh_error(
                    "PortfolioService worker returned a non-PortfolioDTO result"
                )
            else:
                self._apply_portfolio_dto(portfolio)
        self._release_refresh_worker(worker)

    def _on_refresh_worker_error(
        self,
        message: str,
        generation: int,
        worker: TaskWorker,
    ) -> None:
        if worker is not self._refresh_worker:
            worker.deleteLater()
            return
        if generation == self._refresh_generation and not self._closing:
            self._handle_portfolio_refresh_error(message)
        self._release_refresh_worker(worker)

    def _on_refresh_worker_cancelled(self, generation: int, worker: TaskWorker) -> None:
        if worker is not self._refresh_worker:
            worker.deleteLater()
            return
        if generation == self._refresh_generation and not self._closing:
            self.portfolio_refresh_status_label.setText(
                "持倉背景刷新已取消；畫面保留最近一次資料。"
            )
        self._release_refresh_worker(worker)

    def _release_refresh_worker(self, worker: TaskWorker) -> None:
        if worker is not self._refresh_worker:
            worker.deleteLater()
            return
        self._refresh_worker = None
        worker.deleteLater()
        if self._refresh_pending and not self._closing:
            self._refresh_pending = False
            self._start_refresh_worker()
            return
        self.btn_refresh.setEnabled(not self._closing)

    def _handle_portfolio_refresh_error(self, message: str) -> None:
        error_line = _first_error_line(message)
        logger.error("Failed to load portfolio DTO: %s", error_line)
        if self._last_portfolio_dto is not None:
            self.portfolio_refresh_status_label.setText(
                "持倉背景刷新失敗；保留最近一次 PortfolioDTO。"
                f"原因：{error_line}"
            )
            return
        self.portfolio_refresh_status_label.setText(
            f"持倉資料狀態未知；尚無可信 PortfolioDTO。原因：{error_line}"
        )

    def cancel_refresh(self) -> None:
        """合作式取消目前背景讀取，供視窗關閉與測試使用。"""

        self._refresh_generation += 1
        self._refresh_pending = False
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            self._refresh_worker.cancel(cooperative=True, wait=False)
            self.portfolio_refresh_status_label.setText(
                "正在取消持倉背景刷新；目前資料仍保留。"
            )

    def closeEvent(self, event) -> None:
        """關閉前合作式取消 worker，避免回呼在 widget 銷毀後套用。"""

        self._closing = True
        self._refresh_generation += 1
        self._refresh_pending = False
        worker = self._refresh_worker
        if worker is not None and worker.isRunning():
            worker.cancel(cooperative=True, wait=False)
            self.portfolio_refresh_status_label.setText(
                "已請求取消持倉背景刷新；工作安全結束後再關閉。"
            )
            event.ignore()
            return
        if worker is not None:
            self._refresh_worker = None
            worker.deleteLater()
        super().closeEvent(event)

    def _load_paper_readiness(self):
        """只讀顯示 Paper Portfolio／Equal Weight 的實際累積狀態。"""
        try:
            result = self.paper_readiness_service.inspect()
            self._paper_readiness = result
            self._render_paper_readiness(result)
        except Exception as exc:
            logger.error("Failed to load paper portfolio readiness: %s", exc)
            self._paper_readiness = None
            self.paper_readiness_summary_label.setText("Paper Portfolio 狀態讀取失敗；未修改任何資料。")
            self.paper_readiness_detail_label.setText(f"診斷：{exc}")
            self.paper_snapshot_table.setModel(
                PandasTableModel(pd.DataFrame(columns=["日期", "證券代號", "狀態"]))
            )

    def _render_paper_readiness(self, result) -> None:
        status_text = _paper_status_text(result.status)
        cost_status_text = _paper_status_text(result.cost_ledger_status)
        weekly_status_text = _paper_status_text(result.weekly_report_status)
        total_text = (
            f"TWD {result.latest_total_value:,.2f}"
            if result.latest_total_value is not None
            else "N/A"
        )
        cash_text = f"TWD {result.latest_cash:,.2f}" if result.latest_cash is not None else "N/A"
        benchmark_text = (
            f"{result.benchmark_observation_count} 筆"
            if result.benchmark_observation_count
            else "尚無"
        )
        self.paper_readiness_summary_label.setText(
            f"Paper Portfolio｜狀態：{status_text}\n"
            f"最新可採用 snapshot：{result.latest_snapshot_date or 'N/A'}｜"
            f"raw 累積 {result.snapshot_count} 筆｜持倉 {result.latest_position_count} 檔｜"
            f"總值 {total_text}｜現金 {cash_text}\n"
            f"Equal Weight：{benchmark_text}｜"
            f"成本帳：{cost_status_text}（{result.cost_record_count} 筆）｜"
            f"週報：{weekly_status_text}"
        )
        details = [
            f"status：{_paper_status_text(result.latest_status)}",
            f"snapshot DB：{result.state_db_path}",
            f"daily status：{result.status_path}",
            f"benchmark DB：{result.benchmark_db_path or '未設定 PAPER_EQUAL_WEIGHT_BENCHMARK_PATH'}",
            f"cost ledger DB：{result.cost_ledger_db_path or '未設定 PAPER_TRADE_LEDGER_PATH'}",
            (
                f"成本帳：{cost_status_text}｜"
                f"總成本 {result.cost_total_cost if result.cost_total_cost is not None else 'N/A'}｜"
                f"full fill {result.filled_event_count}／partial fill {result.partial_fill_event_count}／"
                f"reject {result.rejected_event_count}／override {result.override_event_count}"
            ),
            (
                f"欄位缺口：execution gap {result.missing_execution_gap_count} 筆、"
                f"turnover {result.missing_turnover_count} 筆、"
                f"future-dated fill {result.future_dated_event_count} 筆"
            ),
            "研究用途；read_only=true、writes_allowed=false、broker_execution=false、auto_rebalance_allowed=false。",
        ]
        details.extend(f"阻擋：{item}" for item in result.blockers)
        details.extend(f"警告：{item}" for item in result.warnings)
        self.paper_readiness_detail_label.setText("\n".join(details))

        rows = [
            {
                "日期": result.latest_snapshot_date or "N/A",
                "證券代號": item.stock_code,
                "股數": item.quantity,
                "標記價格": str(item.mark_price),
                "市值": str(item.market_value),
                "權重(bp)": item.weight_bp,
            }
            for item in result.latest_positions
        ]
        if not rows:
            rows = [{"日期": result.latest_snapshot_date or "N/A", "證券代號": "N/A", "狀態": "沒有可顯示的 snapshot 持倉"}]
        columns = ["日期", "證券代號", "股數", "標記價格", "市值", "權重(bp)"]
        if not result.latest_positions:
            columns = ["日期", "證券代號", "狀態"]
        self.paper_snapshot_table.setModel(PandasTableModel(pd.DataFrame(rows, columns=columns)))
        self.paper_snapshot_table.resizeColumnsToContents()

    def _load_paper_weekly_evidence(self) -> None:
        """只讀重建最近 Paper 週報；沒有完整 evidence 時明確顯示原因。"""
        try:
            expected_days = int(self.paper_weekly_expected_days.value())
            result = self.paper_weekly_evidence_service.build_latest(
                expected_trading_days=expected_days,
            )
            self._paper_weekly_evidence = result
            self._render_paper_weekly_evidence(result)
        except Exception as exc:
            logger.error("Failed to load paper portfolio weekly evidence: %s", exc)
            self._paper_weekly_evidence = None
            self.paper_weekly_report_label.setText(
                f"Paper 週報讀取失敗；未修改任何資料。診斷：{exc}"
            )

    def _render_paper_weekly_evidence(self, result) -> None:
        status_text = _paper_status_text(result.status)
        if result.report is None:
            summary = (
                f"最近週報｜狀態：{status_text}｜"
                f"區間 {result.period_start or 'N/A'} → {result.period_end or 'N/A'}｜"
                f"snapshot {result.snapshot_count} 筆／benchmark {result.benchmark_observation_count} 筆／"
                f"成本列 {result.cost_record_count} 筆"
            )
        else:
            report = result.report
            summary = (
                f"最近週報｜狀態：{status_text}｜"
                f"區間 {report.period_start} → {report.period_end}｜"
                f"觀測 {report.observed_trading_days}/{result.expected_trading_days} 交易日\n"
                f"毛報酬 {report.gross_return_bp} bp｜淨報酬 {report.net_return_bp} bp｜"
                f"Equal Weight {report.benchmark_return_bp} bp｜超額 {report.net_excess_return_bp} bp｜"
                f"成本 TWD {report.total_cost}｜換手 {report.turnover_bp} bp｜"
                f"資料品質 {report.data_quality}"
            )
        details = [
            f"週報 evidence：{_paper_status_text(result.weekly_report_status)}",
            f"snapshot DB：{result.state_db_path}",
            f"benchmark DB：{result.benchmark_db_path or '未設定'}",
            f"cost ledger DB：{result.cost_ledger_db_path or '未設定'}",
            "研究用途；research_only=true、investment_effectiveness_claim=false、"
            "read_only=true、writes_allowed=false、broker_execution=false、auto_rebalance_allowed=false。",
        ]
        details.extend(f"阻擋：{item}" for item in result.blockers)
        details.extend(f"警告：{item}" for item in result.warnings)
        if result.report is not None:
            details.extend(f"報告警告：{item}" for item in result.report.warnings)
        if result.diagnostics:
            details.extend(f"診斷：{item}" for item in result.diagnostics)
        self.paper_weekly_report_label.setText(summary + "\n" + "\n".join(details))

    def _build_paper_benchmark(self) -> None:
        """預覽並在二次確認後建立新的 Equal Weight benchmark ledger。"""
        config = self.portfolio_service.config
        configured_market_db = getattr(config, "db_file", None)
        if configured_market_db is None:
            configured_market_db = Path(getattr(config, "data_dir", config.output_root)) / "sqlite" / "twstock.db"
        market_db_path = Path(configured_market_db)
        try:
            preview = self.paper_benchmark_builder.preview(
                baseline_path=self.paper_readiness_service.baseline_path,
                state_db_path=self.paper_readiness_service.state_db_path,
                market_db_path=market_db_path,
                output_ledger_path=self.paper_readiness_service.benchmark_db_path,
            )
        except Exception as exc:
            logger.error("Paper Equal Weight benchmark preview failed: %s", exc)
            QMessageBox.warning(
                self,
                "Equal Weight benchmark 無法預覽",
                f"未建立任何檔案。\n診斷：{exc}",
            )
            return

        output_path = preview.output_ledger_path
        if output_path.exists():
            QMessageBox.information(
                self,
                "Equal Weight benchmark 已存在",
                f"預覽成功，但為避免覆寫既有 ledger，這次不會寫入：\n{output_path}",
            )
            return
        summary = (
            f"frozen constituents：{preview.constituent_count} 檔（{', '.join(preview.constituents)}）\n"
            f"觀測：{preview.observation_count} 筆｜{preview.first_date} → {preview.latest_date}\n"
            f"初始值：TWD {preview.initial_value}｜最新值：TWD {preview.latest_value}\n"
            f"baseline：{preview.baseline_path}\n"
            f"snapshot DB：{preview.state_db_path}\n"
            f"市場 DB（只讀 T-1）：{preview.market_db_path}\n"
            f"目標 ledger：{output_path}\n\n"
            "按『是』才會建立新的研究用 append-only Equal Weight ledger；不修改市場 DB、Paper snapshot、手動 Portfolio，也不會下單。"
        )
        if QMessageBox.question(
            self,
            "確認建立 Equal Weight benchmark",
            summary,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            built_path = self.paper_benchmark_builder.commit(preview, confirm=True)
        except Exception as exc:
            logger.error("Paper Equal Weight benchmark build failed: %s", exc)
            QMessageBox.warning(self, "Equal Weight benchmark 未建立", str(exc))
            return
        self._load_paper_readiness()
        self._load_paper_weekly_evidence()
        QMessageBox.information(
            self,
            "Equal Weight benchmark 已建立",
            f"已保存 {preview.observation_count} 筆 benchmark observation：\n{built_path}\n\n"
            "這只補齊 benchmark 輸入；Paper Trade Ledger 仍需真實 execution fills 才能計算成本後週報。",
        )

    def _load_stress_lab(
        self,
        _checked: bool = False,
        *,
        portfolio: PortfolioDTO | None = None,
    ):
        """以目前持倉做唯讀情境投影；不寫入任何資料或交易紀錄。"""
        try:
            scenario_id = self.stress_scenario_combo.currentData() or "fast_drop"
            positions = (
                list(portfolio.positions)
                if portfolio is not None
                else self.portfolio_service.list_positions()
            )
            result = self.stress_lab_service.evaluate_positions(
                positions,
                scenario_id=str(scenario_id),
            )
            self._stress_result = result
            self._render_stress_lab(result)
        except Exception as exc:
            logger.error("Failed to load portfolio stress lab: %s", exc)
            self._stress_result = None
            self.stress_summary_label.setText("情境壓力測試載入失敗；未修改持倉。")
            self.stress_detail_label.setText(f"診斷：{exc}")
            self.stress_positions_table.setModel(
                PandasTableModel(pd.DataFrame(columns=["證券代號", "狀態"]))
            )

    def _render_stress_lab(self, result) -> None:
        status_labels = {
            "ready": "可計算",
            "partial": "部分可計算",
            "not_computable": "不可計算",
        }
        status_text = status_labels.get(str(result.status), str(result.status))
        if result.base_market_value is None:
            value_text = "基準市值：N/A"
        else:
            value_text = (
                f"基準市值：TWD {result.base_market_value:,.2f}｜"
                f"壓力後：TWD {result.stressed_market_value:,.2f}｜"
                f"變動：TWD {result.value_delta:+,.2f}"
            )
        self.stress_summary_label.setText(
            f"{result.scenario.label}｜狀態：{status_text}｜"
            f"已標記 {result.priced_position_count}/{result.total_position_count} 檔\n"
            f"{value_text}"
        )
        diagnostics = [
            *(f"阻擋：{item}" for item in result.blockers),
            *(f"警告：{item}" for item in result.warnings),
        ]
        if result.missing_price_codes:
            diagnostics.append(
                f"缺最新價：{', '.join(result.missing_price_codes)}；只計算已標記持倉。"
            )
        diagnostics.append("研究用途；情境不是預測，不代表投資有效性或可交易性。")
        self.stress_detail_label.setText("\n".join(diagnostics))

        rows = [
            {
                "證券代號": item.stock_code,
                "證券名稱": item.stock_name,
                "基準市值": str(item.base_value),
                "衝擊(bp)": item.shock_bp,
                "壓力後市值": str(item.stressed_value),
                "變動": str(item.value_delta),
                "狀態": item.status,
            }
            for item in result.positions
        ]
        columns = ["證券代號", "證券名稱", "基準市值", "衝擊(bp)", "壓力後市值", "變動", "狀態"]
        self.stress_positions_table.setModel(PandasTableModel(pd.DataFrame(rows, columns=columns)))
        self.stress_positions_table.resizeColumnsToContents()

    def _load_stress_history(self) -> None:
        """只讀顯示已保存的 Stress Lab 研究快照；缺資料庫時不初始化。"""
        try:
            result = self.stress_history_read_service.inspect()
            self._stress_history_result = result
            self._render_stress_history(result)
        except Exception as exc:
            logger.error("Failed to load portfolio stress history: %s", exc)
            self._stress_history_result = None
            self.stress_history_summary_label.setText(
                f"Stress 歷史讀取失敗；未修改任何資料。診斷：{exc}"
            )
            self.stress_history_table.setModel(
                PandasTableModel(pd.DataFrame(columns=["執行時間", "情境", "狀態"]))
            )

    def _render_stress_history(self, result) -> None:
        status_labels = {
            "ready": "可用",
            "partial": "部分完成",
            "degraded": "降級",
            "not_configured": "尚未配置",
        }
        status_text = status_labels.get(str(result.status), str(result.status))
        self.stress_history_summary_label.setText(
            f"Stress 歷史｜狀態：{status_text}｜保存 {len(result.records)} 筆｜"
            f"資料庫：{result.db_path}\n"
            "研究用途；research_only=true、investment_effectiveness_claim=false、"
            "read_only=true、writes_allowed=false。"
            + ("\n" + "\n".join(f"阻擋：{item}" for item in result.blockers) if result.blockers else "")
            + ("\n" + "\n".join(f"警告：{item}" for item in result.warnings) if result.warnings else "")
        )
        rows = [
            {
                "執行時間": item.run_at,
                "基準日": item.as_of_date or "N/A",
                "情境": item.scenario_label,
                "狀態": item.status,
                "已標記": f"{item.priced_position_count}/{item.total_position_count}",
                "基準市值": str(item.base_market_value) if item.base_market_value is not None else "N/A",
                "壓力後市值": (
                    str(item.stressed_market_value)
                    if item.stressed_market_value is not None
                    else "N/A"
                ),
                "變動": str(item.value_delta) if item.value_delta is not None else "N/A",
                "payload hash": item.payload_hash[:12],
            }
            for item in result.records
        ]
        if not rows:
            rows = [{"執行時間": "N/A", "基準日": "N/A", "情境": "N/A", "狀態": result.status}]
            columns = ["執行時間", "基準日", "情境", "狀態"]
        else:
            columns = [
                "執行時間",
                "基準日",
                "情境",
                "狀態",
                "已標記",
                "基準市值",
                "壓力後市值",
                "變動",
                "payload hash",
            ]
        self.stress_history_table.setModel(PandasTableModel(pd.DataFrame(rows, columns=columns)))
        self.stress_history_table.resizeColumnsToContents()

    def _save_stress_history(self) -> None:
        """二次確認後保存目前 Stress 結果；保存不會改變持倉或交易。"""
        result = getattr(self, "_stress_result", None)
        if result is None:
            QMessageBox.information(self, "尚無 Stress 結果", "請先執行情境，才可以保存研究快照。")
            return
        answer = QMessageBox.question(
            self,
            "確認保存 Stress 研究快照",
            "這會新增一筆 append-only 研究歷史。它不是正式績效、交易證據或交易指令；是否繼續？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            record = PortfolioStressHistoryRecord.from_payload(result.to_dict())
            PortfolioStressHistoryRepository(self.stress_history_db_path).append(record)
            self._load_stress_history()
            QMessageBox.information(
                self,
                "Stress 研究快照已保存",
                f"已保存 {record.record_id}\n資料庫：{self.stress_history_db_path}",
            )
        except Exception as exc:
            logger.error("Failed to save portfolio stress history: %s", exc)
            QMessageBox.warning(self, "Stress 研究快照未保存", str(exc))

    def _show_import_paper_fills_dialog(self) -> None:
        """預覽並在二次確認後匯入完整 Paper fill CSV；不修改正式 Portfolio。"""
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇 Paper 成交 CSV",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if not source_path:
            return
        try:
            preview = self.paper_trade_import_service.preview_csv(source_path)
        except Exception as exc:
            logger.error("Paper trade CSV preview failed: %s", exc)
            QMessageBox.warning(self, "Paper 成交匯入無法預覽", str(exc))
            return

        if not preview.ready_to_import:
            error_text = "; ".join(
                f"第 {row.row_number} 列：{', '.join(row.errors)}"
                for row in preview.invalid_rows[:5]
            ) or "沒有可匯入的 Paper fill 列。"
            QMessageBox.warning(
                self,
                "Paper 成交匯入被阻擋",
                f"預覽 {len(preview.rows)} 列，沒有全部通過 Paper fill 驗證。\n{error_text}",
            )
            return

        try:
            fills = self.paper_trade_import_service.build_fills(preview)
            total_cost = sum((fill.total_cost for fill in fills), Decimal("0.00"))
        except Exception as exc:
            logger.error("Paper trade CSV validation failed: %s", exc)
            QMessageBox.warning(self, "Paper 成交匯入被阻擋", str(exc))
            return

        ledger_path = self.paper_readiness_service.cost_ledger_db_path
        summary = (
            f"來源：{Path(source_path).name}\n"
            f"SHA-256：{preview.source_hash}\n"
            f"可匯入：{len(fills)} 筆｜總成本：TWD {total_cost}\n"
            f"目標 Ledger：{ledger_path}\n\n"
            "按『是』後只會 append Paper Trade Ledger；不會修改手動 Portfolio、Paper snapshot 或下單。"
        )
        if QMessageBox.question(
            self,
            "確認匯入 Paper 成交",
            summary,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            imported = self.paper_trade_import_service.commit(
                preview,
                ledger_path,
                confirm=True,
            )
        except Exception as exc:
            logger.error("Paper trade CSV commit failed: %s", exc)
            QMessageBox.warning(self, "Paper 成交匯入失敗", str(exc))
            return
        self._load_paper_readiness()
        self._load_paper_weekly_evidence()
        QMessageBox.information(
            self,
            "Paper 成交匯入完成",
            f"已匯入 {len(imported)} 筆 Paper fill；正式 Portfolio 未修改。",
        )

    def _export_paper_fills_template(self) -> None:
        """建立空白 Paper fills CSV 範本；不寫入任何 ledger 或正式資料。"""
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "匯出 Paper 成交 CSV 範本",
            "paper_fills_template.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not output_path:
            return
        try:
            path = self.paper_trade_import_service.write_template(output_path)
        except FileExistsError:
            QMessageBox.warning(
                self,
                "Paper 成交範本未覆寫",
                "目標檔案已存在；為避免覆蓋你已填寫的資料，請另存新檔。",
            )
            return
        except (OSError, ValueError) as exc:
            logger.error("Paper trade CSV template export failed: %s", exc)
            QMessageBox.warning(self, "Paper 成交範本匯出失敗", str(exc))
            return
        QMessageBox.information(
            self,
            "Paper 成交範本已建立",
            f"已建立空白欄位範本：\n{path}\n\n請填入真實成交後，再使用『匯入 Paper 成交 CSV』預覽與確認。",
        )

    def _show_import_trades_dialog(self) -> None:
        """預覽並在二次確認後匯入 Broker CSV；取消或失敗不寫入。"""
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇交易 CSV",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if not source_path:
            return
        try:
            existing_ids = tuple(
                str(trade.trade_id) for trade in self.portfolio_service.list_trades()
            )
            preview = self.trade_import_service.preview_csv(
                source_path,
                existing_trade_ids=existing_ids,
            )
        except Exception as exc:
            logger.error("Trade CSV preview failed: %s", exc)
            QMessageBox.warning(self, "交易匯入無法預覽", str(exc))
            return

        error_text = "; ".join(
            f"第 {row.row_number} 列：{', '.join(row.errors)}"
            for row in preview.invalid_rows[:5]
        )
        if not preview.ready_to_import:
            detail = error_text or "沒有可匯入的交易列。"
            QMessageBox.warning(
                self,
                "交易匯入被阻擋",
                f"預覽 {len(preview.rows)} 列，沒有全部通過驗證。\n{detail}",
            )
            return

        summary = (
            f"來源：{Path(source_path).name}\n"
            f"SHA-256：{preview.source_hash}\n"
            f"可匯入：{len(preview.valid_rows)} 列\n\n"
            "按『是』後才會寫入既有 Portfolio 交易紀錄；"
            "這不是券商下單。"
        )
        if QMessageBox.question(
            self,
            "確認匯入交易",
            summary,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            imported = self.trade_import_service.commit(
                preview,
                self.portfolio_service,
                confirm=True,
            )
        except Exception as exc:
            logger.error("Trade CSV commit failed: %s", exc)
            QMessageBox.warning(self, "交易匯入失敗", str(exc))
            return
        self.refresh_all()
        self.portfolioUpdated.emit()
        QMessageBox.information(
            self,
            "交易匯入完成",
            f"已匯入 {len(imported)} 筆交易；持倉已重新驗證。",
        )

    def _load_portfolio_summary(self, portfolio: PortfolioDTO | None = None):
        """讀取持倉摘要，並更新頂部卡片"""
        try:
            if portfolio is None:
                portfolio = self.portfolio_service.get_portfolio()
                if not isinstance(portfolio, PortfolioDTO):
                    raise TypeError("PortfolioService.get_portfolio must return PortfolioDTO")
            active_count = portfolio.active_positions
            total_invested = portfolio.total_invested_amount
            realized_pnl = portfolio.total_realized_pnl
            active_positions = [
                position
                for position in getattr(portfolio, "positions", [])
                if position.is_holding
            ]

            # 現金帳與資產負債尚未進入 Phase 4.1 MVP，不能把投入金額加上已實現損益冒充 NAV。
            # 這裡只顯示有可用最新價格的持倉市值；缺價格時明確保留 N/A。
            marked_value = Decimal("0")
            priced_count = 0
            unpriced_codes: list[str] = []
            price_dates: set[str] = set()
            for position in active_positions:
                raw_price = getattr(position, "current_price", None)
                try:
                    quantity = Decimal(str(position.quantity))
                    price = Decimal(str(raw_price)) if raw_price is not None else Decimal("NaN")
                except Exception:
                    price = Decimal("NaN")
                    quantity = Decimal("0")
                if not price.is_finite() or price <= 0 or not quantity.is_finite() or quantity < 0:
                    unpriced_codes.append(str(position.stock_code))
                    continue
                marked_value += quantity * price
                priced_count += 1
                source_summary = getattr(position, "source_summary", {}) or {}
                price_date = source_summary.get("current_price_date")
                if isinstance(price_date, str) and price_date:
                    price_dates.add(price_date)

            if priced_count:
                marked_value = marked_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                self.card_net_val.update_value(f"TWD {marked_value:,.2f}")
            else:
                self.card_net_val.update_value("N/A（缺最新價格）")
            self.card_invested.update_value(f"TWD {total_invested:,.2f}")

            # P&L 色彩區分
            pnl_text = f"TWD {realized_pnl:+,.2f}"
            self.card_pnl.update_value(pnl_text)
            if realized_pnl > 0:
                self.card_pnl.value_label.setStyleSheet("color: #48bb78;")
            elif realized_pnl < 0:
                self.card_pnl.value_label.setStyleSheet("color: #f56565;")
            else:
                self.card_pnl.value_label.setStyleSheet(
                    f"color: {MIDNIGHT_ANALYST.text_primary};"
                )

            self.card_positions.update_value(f"{active_count} 檔")
            top_symbols = "、".join(
                f"{position.stock_code} {position.stock_name}" for position in active_positions[:5]
            )
            suffix = f"｜{top_symbols}" if top_symbols else ""
            if len(active_positions) > 5:
                suffix += f" 等 {len(active_positions)} 檔"
            pricing_summary = ""
            if active_positions:
                pricing_summary = f"｜已標記市值 {priced_count}/{len(active_positions)} 檔"
                if unpriced_codes:
                    pricing_summary += f"｜缺最新價：{', '.join(unpriced_codes[:3])}"
                if len(unpriced_codes) > 3:
                    pricing_summary += f" 等 {len(unpriced_codes)} 檔"
                if price_dates:
                    pricing_summary += f"｜價格截至 {', '.join(sorted(price_dates))}"
            self.active_positions_summary_label.setText(
                f"活躍持倉：{active_count} 檔{suffix}{pricing_summary}"
            )
        except Exception as e:
            logger.error("Failed to load portfolio summary: %s", e)

    def _load_positions_table(self, portfolio: PortfolioDTO | None = None):
        """加載衍生持倉列表，並執行非同步推薦引擎 Monitor 檢查"""
        try:
            if portfolio is None:
                portfolio = self.portfolio_service.get_portfolio()
                if not isinstance(portfolio, PortfolioDTO):
                    raise TypeError("PortfolioService.get_portfolio must return PortfolioDTO")
            positions = list(portfolio.positions)

            if not positions:
                df = pd.DataFrame(columns=[
                    "證券代號", "證券名稱", "持有股數", "平均成本", "目前價格",
                    "投入金額", "未實現損益", "未實現損益%", "已實現損益",
                    "來源脈絡", "進場分數", "目前分數", "狀態監控", "監控原因"
                ])
            else:
                data = []
                for p in positions:
                    snapshot = self._current_snapshot_for_position(p.stock_code)
                    monitor_result = self.condition_monitor.evaluate(p, snapshot)
                    monitor_reason = "；".join(monitor_result.reasons)

                    pnl_pct_str = "-"
                    if p.unrealized_pnl_pct is not None:
                        pnl_pct_str = f"{p.unrealized_pnl_pct * 100:+.2f}%"

                    data.append({
                        "證券代號": p.stock_code,
                        "證券名稱": p.stock_name,
                        "持有股數": p.quantity,
                        "平均成本": p.average_cost,
                        "目前價格": p.current_price if p.current_price is not None else "-",
                        "投入金額": p.invested_amount,
                        "未實現損益": p.unrealized_pnl if p.unrealized_pnl is not None else "-",
                        "未實現損益%": pnl_pct_str,
                        "已實現損益": p.realized_pnl,
                        "來源脈絡": monitor_result.source_label,
                        "進場分數": monitor_result.entry_total_score,
                        "目前分數": monitor_result.current_total_score,
                        "狀態監控": monitor_result.label,
                        "監控原因": monitor_reason,
                        "_tooltip": monitor_reason,
                    })
                df = pd.DataFrame(data)

            self.positions_model = PandasTableModel(df)
            # 隱藏內部輔助用的 _tooltip 欄位
            if "_tooltip" in df.columns:
                self.positions_model.setVisibleColumns([col for col in df.columns if col != "_tooltip"])

            self.positions_table.setModel(self.positions_model)
            self.positions_table.resizeColumnsToContents()

            # 設定 Tooltip 提示以符合條件監控體驗
            # 這裡我們可以設置雙擊或滑鼠懸停 tooltip

        except Exception as e:
            logger.error("Failed to load positions table: %s", e)
            import traceback
            traceback.print_exc()

    def _current_snapshot_for_position(self, stock_code: str) -> Optional[PortfolioCurrentSnapshot]:
        """取得單一持倉的目前評分快照；取不到時交由 monitor 標示待更新。"""
        current_price = self.portfolio_service.get_current_price(stock_code)

        if not self.recommendation_service:
            return PortfolioCurrentSnapshot(current_price=current_price)
        try:
            if stock_code not in self.rec_cache:
                self._update_recommendation_cache_for_stock(stock_code)
            rec_info = self.rec_cache.get(stock_code)
            if not rec_info:
                return PortfolioCurrentSnapshot(current_price=current_price)
            return PortfolioCurrentSnapshot(
                current_regime=str(rec_info.get("regime", "")),
                current_total_score=rec_info.get("score"),
                current_price=current_price,
            )
        except Exception as exc:
            logger.debug("Current snapshot lookup failed for %s: %s", stock_code, exc)
            return PortfolioCurrentSnapshot(current_price=current_price)

    def _update_recommendation_cache_for_stock(self, stock_code: str):
        """背景快速獲取特定個股的推薦狀態，用以更新 Condition Monitor"""
        if not self.recommendation_service:
            return
        try:
            # 獲取最新大盤 Regime 與個股打分 (極簡快速模擬以防止卡頓)
            # 實際上可從 recommendation_service 的內部方法做快速單股 Scoring
            # 此處做安全緩存防禦
            engine = getattr(self.recommendation_service, 'screening_service', None)
            if engine:
                # 簡單查詢該股的分數快照
                df_score = engine.get_market_strength_score()  # 這會返回大表
                if not df_score.empty and '證券代號' in df_score.columns:
                    stock_row = df_score[df_score['證券代號'] == stock_code]
                    if not stock_row.empty:
                        # 獲取總技術分數
                        score = float(stock_row.iloc[0].get('綜合分數', 80.0))
                        self.rec_cache[stock_code] = {
                            "score": score,
                            "regime": "",
                            "why_not": "多空分數失衡" if score < 60 else ""
                        }
        except Exception as e:
            logger.debug("Failed to prefetch recommendation score for %s: %s", stock_code, e)

    def _load_trades_history(self):
        """加載交易明細，若有選定股票，則進行篩選"""
        try:
            self.selected_trade_id = ""
            trades = self.portfolio_service.list_trades()
            if self.selected_stock_code:
                trades = [t for t in trades if t.stock_code == self.selected_stock_code]

            if not trades:
                df = pd.DataFrame(columns=["交易日期", "證券代號", "證券名稱", "買賣", "交易股數", "單價", "手續費", "稅金", "策略來源", "備註", "_trade_id"])
            else:
                data = []
                for t in trades:
                    data.append({
                        "交易日期": t.trade_date,
                        "證券代號": t.stock_code,
                        "證券名稱": t.stock_name,
                        "買賣": "買入" if t.side.lower() == "buy" else "賣出",
                        "交易股數": t.quantity,
                        "單價": t.price,
                        "手續費": t.fees,
                        "稅金": t.taxes,
                        "策略來源": t.source_id or "手動",
                        "備註": t.notes,
                        "_trade_id": t.trade_id
                    })
                df = pd.DataFrame(data)

            self.trades_model = PandasTableModel(df)
            if "_trade_id" in df.columns:
                self.trades_model.setVisibleColumns([col for col in df.columns if col != "_trade_id"])
            self.trades_table.setModel(self.trades_model)
            self.trades_table.resizeColumnsToContents()
            selection_model = self.trades_table.selectionModel()
            if selection_model is not None:
                selection_model.selectionChanged.connect(self._sync_selected_trade_action)
            self._sync_selected_trade_action()
            if self.selected_stock_code:
                self.trade_filter_status_label.setText(f"目前只顯示：{self.selected_stock_code}")
                self.clear_trade_filter_button.setEnabled(True)
            else:
                self.trade_filter_status_label.setText("顯示全部交易歷史")
                self.clear_trade_filter_button.setEnabled(False)
        except Exception as e:
            logger.error("Failed to load trades history: %s", e)

    def _selected_trade_record(self) -> Optional[Dict[str, Any]]:
        """取得目前表格中選取的原始交易，避免將衍生持倉列當作可刪除紀錄。"""
        if not self.trades_model:
            return None
        selection_model = self.trades_table.selectionModel()
        if selection_model is None:
            return None
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return None

        row = selected_rows[0].row()
        df = self.trades_model.getDataFrame()
        if row < 0 or row >= len(df) or "_trade_id" not in df.columns:
            return None

        trade_id = str(df.iloc[row]["_trade_id"] or "").strip()
        if not trade_id:
            return None
        return {
            "trade_id": trade_id,
            "stock_code": str(df.iloc[row].get("證券代號", "")).strip(),
            "stock_name": str(df.iloc[row].get("證券名稱", "")).strip(),
            "side": str(df.iloc[row].get("買賣", "")).strip(),
            "quantity": df.iloc[row].get("交易股數", ""),
            "price": df.iloc[row].get("單價", ""),
        }

    def _sync_selected_trade_action(self, *_args) -> None:
        """同步單筆刪除按鈕，未選取交易時永遠不可按。"""
        record = self._selected_trade_record()
        self.selected_trade_id = str(record["trade_id"]) if record is not None else ""
        self.delete_selected_trade_button.setEnabled(record is not None)
        if record is None:
            self.trade_selection_hint_label.setText("選取一筆交易後，可安全刪除該筆紀錄。")
            return
        self.trade_selection_hint_label.setText(
            f"已選取：{record['stock_code']} {record['stock_name']}｜刪除後會重算持倉。"
        )

    def _delete_selected_trade(self) -> None:
        """以可見按鈕刪除單筆選取交易；實際寫入仍交由 service 驗證。"""
        record = self._selected_trade_record()
        if record is None:
            QMessageBox.information(self, "請先選取交易", "請先在交易歷史選取一筆交易紀錄。")
            return
        self._confirm_and_delete_trade(record)

    def _clear_trade_history_filter(self):
        self.selected_stock_code = ""
        self._load_trades_history()
        self._load_journal_entries()

    def _load_journal_entries(self):
        """加載交易日記列表"""
        try:
            self.journal_list.clear()
            entries = self.journal_service.list_journal_entries(
                stock_code=self.selected_stock_code
            )

            if not entries:
                item = QListWidgetItem("目前無相關的覆盤日記筆記。您可點擊下方「新增日記」開始記錄您的交易心法！")
                item.setFlags(Qt.NoItemFlags)
                self.journal_list.addItem(item)
                return

            for entry in entries:
                # 建立精美的卡片項目
                time_str = datetime.fromisoformat(entry.created_at).strftime("%Y-%m-%d %H:%M")
                display_text = f"【{entry.title}】 - {time_str}\n"
                if entry.stock_code:
                    display_text += f"關聯股票：{entry.stock_code}\n"
                display_text += f"{entry.body}\n"
                display_text += "-" * 40

                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, entry.journal_id)
                self.journal_list.addItem(item)
        except Exception as e:
            logger.error("Failed to load journal entries: %s", e)

    def _on_position_selected(self, index):
        """當使用者選中某個持倉部位時，連動右側明細"""
        if not self.positions_model:
            return

        df = self.positions_model.getDataFrame()
        row = index.row()
        if row < len(df):
            code = df.iloc[row]["證券代號"]
            # 如果是空占位符則不理會
            if code == "-":
                self.selected_stock_code = ""
            else:
                self.selected_stock_code = code

            logger.info("Selected position stock: %s", self.selected_stock_code)
            self._load_trades_history()
            self._load_journal_entries()
            self._update_monitoring_tab()

    def _show_position_context_menu(self, pos):
        """右鍵選單操作"""
        index = self.positions_table.indexAt(pos)
        if not index.isValid() or not self.positions_model:
            return

        df = self.positions_model.getDataFrame()
        row = index.row()
        stock_code = df.iloc[row]["證券代號"]
        stock_name = df.iloc[row]["證券名稱"]

        if stock_code == "-":
            return

        menu = QMenu(self)

        action_journal = menu.addAction("為此部位寫日記...")
        action_history = menu.addAction("只查看此股交易歷史")
        action_clear_filter = menu.addAction("顯示全部交易歷史")

        action = menu.exec(self.positions_table.viewport().mapToGlobal(pos))
        if action == action_journal:
            self._show_add_journal_dialog(stock_code)
        elif action == action_history:
            self.selected_stock_code = stock_code
            self._load_trades_history()
            self._load_journal_entries()
        elif action == action_clear_filter:
            self._clear_trade_history_filter()

    def _show_record_trade_dialog(self):
        """顯示手動記錄交易對話框"""
        dialog = AddTradeDialog(self.recommendation_service, self)
        # 如果當前有選中股票，則預填
        if self.selected_stock_code:
            dialog.code_input.setText(self.selected_stock_code)
            dialog._auto_query_stock_name()

        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_trade_data()
            try:
                self.portfolio_service.record_trade(
                    stock_code=data["stock_code"],
                    stock_name=data["stock_name"],
                    side=data["side"],
                    quantity=data["quantity"],
                    price=data["price"],
                    trade_date=data["trade_date"],
                    fees=data["fees"],
                    taxes=data["taxes"],
                    source_type=data["source_type"],
                    source_id=data["source_id"],
                    notes=data["notes"]
                )
                QMessageBox.information(self, "成功", f"成功記錄 {data['stock_name']} 的交易紀錄！")
                self.refresh_all()
                self.portfolioUpdated.emit()
            except Exception as e:
                QMessageBox.critical(self, "記錄交易失敗", f"無法記入交易，領域規則校驗失敗：\n{e}")

    def _show_add_journal_dialog(self, stock_code: str = ""):
        """顯示日記新增對話框"""
        dialog = AddJournalDialog(stock_code or self.selected_stock_code, self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_journal_data()
            try:
                self.journal_service.add_journal_entry(
                    title=data["title"],
                    body=data["body"],
                    stock_code=data["stock_code"]
                )
                QMessageBox.information(self, "成功", "日記筆記已成功記入覆盤歷史！")
                self._load_journal_entries()
            except Exception as e:
                QMessageBox.critical(self, "新增日記失敗", f"無法新增日記：\n{e}")

    def _show_trade_context_menu(self, pos):
        """交易歷史表格的右鍵刪除選單"""
        index = self.trades_table.indexAt(pos)
        if not index.isValid() or not self.trades_model:
            return

        self.trades_table.selectRow(index.row())
        record = self._selected_trade_record()
        if record is None:
            return

        menu = QMenu(self)
        action_delete = menu.addAction("刪除此交易紀錄")

        action = menu.exec(self.trades_table.viewport().mapToGlobal(pos))
        if action == action_delete:
            self._confirm_and_delete_trade(record)

    def _confirm_and_delete_trade(self, record: Dict[str, Any]) -> None:
        """二次確認後刪除一筆原始交易，並將合法性判斷留在 PortfolioService。"""
        confirm = QMessageBox.question(
            self,
            "確認刪除單筆交易",
            (
                f"確定刪除這筆 {record['stock_name']} 的 {record['side']} "
                f"({record['quantity']} 股，@{record['price']}) 紀錄嗎？\n\n"
                "系統會依剩餘交易重新計算持倉與平均成本；若會造成超賣或不合法持倉，刪除會被拒絕且原始資料會保留。"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            deleted = self.portfolio_service.delete_trade(str(record["trade_id"]))
            if not deleted:
                QMessageBox.warning(self, "交易已變更", "找不到這筆交易；請重新整理後再試一次。")
                self.refresh_all()
                return
            if self.selected_stock_code == record["stock_code"]:
                remaining_trades = self.portfolio_service.list_trades()
                if not any(trade.stock_code == record["stock_code"] for trade in remaining_trades):
                    self.selected_stock_code = ""
            QMessageBox.information(self, "已刪除", "交易紀錄已移除，持倉與平均成本已依剩餘交易重新計算。")
            self.refresh_all()
            self.portfolioUpdated.emit()
        except PortfolioValidationError as error:
            QMessageBox.critical(self, "刪除被保護", str(error))
        except Exception as error:
            QMessageBox.critical(self, "刪除失敗", f"發生非預期錯誤：\n{error}")

    def _show_journal_context_menu(self, pos):
        """日記列表的右鍵選單"""
        item = self.journal_list.itemAt(pos)
        if not item:
            return

        journal_id = item.data(Qt.UserRole)
        if not journal_id:
            return

        menu = QMenu(self)
        action_delete = menu.addAction("刪除此篇日記筆記")

        action = menu.exec(self.journal_list.viewport().mapToGlobal(pos))
        if action == action_delete:
            confirm = QMessageBox.question(
                self, "二次確認",
                "您確定要刪除這篇日記筆記嗎？此操作無法還原。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if confirm == QMessageBox.Yes:
                try:
                    self.journal_service.delete_journal_entry(journal_id)
                    QMessageBox.information(self, "成功", "日記已成功刪除！")
                    self._load_journal_entries()
                except Exception as e:
                    QMessageBox.critical(self, "刪除失敗", f"無法刪除日記：\n{e}")

    def _show_clear_all_dialog(self):
        """一鍵重置清空持倉與日記數據"""
        # 第一層確認
        confirm1 = QMessageBox.warning(
            self, "極度危險警告",
            "【注意】這將會永久清空您所有的手動交易紀錄與覆盤日記！\n此操作無法還原，您確定要清空嗎？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm1 != QMessageBox.Yes:
            return

        # 第二層確認以保證安全
        confirm2 = QMessageBox.warning(
            self, "最終確認",
            "為了您的資料安全，請進行最終確認：您真的要【刪除所有持倉數據與日記】嗎？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm2 == QMessageBox.Yes:
            try:
                self.portfolio_service.clear_all_data()
                self.journal_service.clear_all_journals()
                QMessageBox.information(self, "重置成功", "已成功清空所有的持倉交易紀錄與交易日記！現在是乾淨狀態。")
                self.selected_stock_code = ""
                self.refresh_all()
                self.portfolioUpdated.emit()
            except Exception as e:
                QMessageBox.critical(self, "清空失敗", f"發生錯誤：\n{e}")

    def _update_monitoring_tab(self, portfolio: PortfolioDTO | None = None):
        """連動並更新「策略與價格監控」分頁"""
        position_dto = None
        if self.selected_stock_code:
            try:
                source_positions = (
                    list(portfolio.positions)
                    if portfolio is not None
                    else list(self._last_portfolio_dto.positions)
                    if self._last_portfolio_dto is not None
                    else self.portfolio_service.list_positions()
                )
                for p in source_positions:
                    if p.stock_code == self.selected_stock_code:
                        position_dto = p
                        break
            except Exception as e:
                logger.error("Error retrieving position for monitoring: %s", e)

        if not position_dto:
            # 清空 labels
            self.lbl_mon_entry_price.setText("-")
            self.lbl_mon_current_price.setText("-")
            self.lbl_mon_pnl_pct.setText("-")
            self.lbl_mon_pnl_pct.setStyleSheet("color: white;")
            self.lbl_mon_stop_loss.setText("-")
            self.lbl_mon_stop_loss.setStyleSheet("color: white;")
            self.lbl_mon_take_profit.setText("-")
            self.lbl_mon_take_profit.setStyleSheet("color: white;")
            self.lbl_mon_status.setText("-")
            self.lbl_mon_status.setStyleSheet("color: white;")

            self.lbl_strat_id.setText("-")
            self.lbl_strat_version.setText("-")
            self.lbl_strat_params.setText("-")
            self.lbl_strat_perf.setText("-")

            self._clear_lifecycle_labels()

            # 清空籌碼監控
            self.lbl_chip_risk_level.setText("-")
            self.lbl_chip_risk_level.setStyleSheet("color: white;")
            self.lbl_chip_consecutive.setText("-")
            self.lbl_chip_consecutive.setStyleSheet("color: white;")
            self.lbl_chip_net_5d.setText("-")
            self.lbl_chip_net_5d.setStyleSheet("color: white;")
            self.lbl_chip_concentration.setText("-")
            self.lbl_chip_reasons.setText("-")
            self.chip_detail_table.setModel(None)
            return

        try:
            snapshot = self._current_snapshot_for_position(position_dto.stock_code)
            monitor_result = self.condition_monitor.evaluate(position_dto, snapshot)
            details = monitor_result.details
            self._update_lifecycle_review(position_dto, monitor_result)

            # 價格對照
            self.lbl_mon_entry_price.setText(f"TWD {position_dto.average_cost:,.2f}")
            if position_dto.current_price is not None:
                price_text = f"TWD {position_dto.current_price:,.2f}"
                price_date = self._position_price_date(position_dto)
                if price_date:
                    price_text += f"（價格日期：{price_date}）"
                self.lbl_mon_current_price.setText(price_text)
            else:
                self.lbl_mon_current_price.setText("-")

            if position_dto.unrealized_pnl_pct is not None:
                pnl_pct = position_dto.unrealized_pnl_pct * 100
                self.lbl_mon_pnl_pct.setText(f"{pnl_pct:+.2f}%")
                if pnl_pct > 0:
                    self.lbl_mon_pnl_pct.setStyleSheet("color: #48bb78; font-weight: bold;")
                elif pnl_pct < 0:
                    self.lbl_mon_pnl_pct.setStyleSheet("color: #f56565; font-weight: bold;")
                else:
                    self.lbl_mon_pnl_pct.setStyleSheet("color: white;")
            else:
                self.lbl_mon_pnl_pct.setText("-")
                self.lbl_mon_pnl_pct.setStyleSheet("color: white;")

            # 停損
            stop_loss_pct = details.get("stop_loss_pct")
            if stop_loss_pct is not None:
                sl_price = position_dto.average_cost * (1.0 - abs(stop_loss_pct))
                self.lbl_mon_stop_loss.setText(f"TWD {sl_price:,.2f} (-{stop_loss_pct * 100:.1f}%)")
                if details.get("stop_loss_triggered"):
                    self.lbl_mon_stop_loss.setStyleSheet("color: #f56565; font-weight: bold;")
                else:
                    self.lbl_mon_stop_loss.setStyleSheet("color: white;")
            else:
                self.lbl_mon_stop_loss.setText("- (未設定)")
                self.lbl_mon_stop_loss.setStyleSheet("color: white;")

            # 停利
            take_profit_pct = details.get("take_profit_pct")
            if take_profit_pct is not None:
                tp_price = position_dto.average_cost * (1.0 + abs(take_profit_pct))
                self.lbl_mon_take_profit.setText(f"TWD {tp_price:,.2f} (+{take_profit_pct * 100:.1f}%)")
                if details.get("take_profit_triggered"):
                    self.lbl_mon_take_profit.setStyleSheet("color: #48bb78; font-weight: bold;")
                else:
                    self.lbl_mon_take_profit.setStyleSheet("color: white;")
            else:
                self.lbl_mon_take_profit.setText("- (未設定)")
                self.lbl_mon_take_profit.setStyleSheet("color: white;")

            # 監控判定
            self.lbl_mon_status.setText(monitor_result.label)
            if monitor_result.status == "invalid":
                self.lbl_mon_status.setStyleSheet("background-color: #742a2a; color: #fff5f5; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
            elif monitor_result.status == "warning":
                self.lbl_mon_status.setStyleSheet("background-color: #7b341e; color: #fffff0; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
            elif monitor_result.status == "valid":
                self.lbl_mon_status.setStyleSheet("background-color: #22543d; color: #f0fff4; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
            else:
                self.lbl_mon_status.setStyleSheet("color: white;")

            # 策略版本詳情
            self.lbl_strat_id.setText("-")
            self.lbl_strat_version.setText("-")
            self.lbl_strat_params.setText("-")
            self.lbl_strat_perf.setText("-")

            source_type = position_dto.source_type
            source_id = position_dto.source_id

            version_id = None
            if source_type == "strategy_version":
                version_id = source_id
            elif source_type == "backtest_run":
                # 第一層：從 source_summary 讀取 promoted_version_id
                version_id = position_dto.source_summary.get("promoted_version_id")

                # 第二層：從 BacktestRunRepository 讀取 promoted_version_id
                if not version_id:
                    try:
                        from app_module.backtest_repository import BacktestRunRepository
                        run_repo = BacktestRunRepository(self.portfolio_service.config)
                        run_obj = run_repo.get_run(source_id)
                        if run_obj and run_obj.promoted_version_id:
                            version_id = run_obj.promoted_version_id
                    except Exception as ex:
                        logger.debug("Failed to lookup promoted_version_id from BacktestRunRepository for run_id %s: %s", source_id, ex)

                # 第三層：遍歷策略版本列表，比對 source_run_id == source_id
                if not version_id:
                    try:
                        versions = self.strategy_version_service.list_versions()
                        for v in versions:
                            if v.get("source_run_id") == source_id:
                                version_id = v.get("version_id")
                                break
                    except Exception as ex:
                        logger.debug("Failed to lookup version_id by source_run_id in StrategyVersionService: %s", ex)

            if version_id:
                version_obj = self.strategy_version_service.get_version(version_id)
                if version_obj:
                    self.lbl_strat_id.setText(f"{version_obj.strategy_id} (ID: {version_id})")
                    self.lbl_strat_version.setText(f"版本: {version_obj.strategy_version} / 升級時間: {version_obj.promoted_at[:16].replace('T', ' ')}")

                    param_lines = [f"{k}: {v}" for k, v in version_obj.params.items()]
                    self.lbl_strat_params.setText(", ".join(param_lines) if param_lines else "預設參數")

                    perf = version_obj.backtest_summary
                    total_ret = perf.get('total_return', 0.0)
                    mdd = perf.get('max_drawdown', 0.0)

                    ret_val = float(total_ret) * 100
                    mdd_val = float(mdd) * 100
                    perf_text = f"總報酬: {ret_val:+.1f}%, Sharpe: {float(perf.get('sharpe_ratio', 0.0)):.2f}, MaxDD: {mdd_val:.1f}%"
                    self.lbl_strat_perf.setText(perf_text)
                else:
                    self.lbl_strat_id.setText(f"策略版本來源 (ID: {version_id})")
                    self.lbl_strat_version.setText("未找到對應的策略版本資料")
            elif source_type == "backtest_run":
                # 雖是 backtest_run 但尚未升級為策略版本
                self.lbl_strat_id.setText(f"回測執行來源: {position_dto.source_summary.get('run_name') or '未命名'} (ID: {source_id})")
                self.lbl_strat_version.setText("該回測執行尚未升級為正式策略版本")
                self.lbl_strat_params.setText(f"策略: {position_dto.source_summary.get('strategy_id', '-')}")
                self.lbl_strat_perf.setText(f"回測狀態: {position_dto.source_summary.get('validation_status') or '未驗證'}")
            elif source_type == "recommendation_result":
                profile_id = position_dto.source_summary.get("profile_id", "")
                self.lbl_strat_id.setText(f"推薦引擎: {profile_id}")
                self.lbl_strat_version.setText(f"推薦批次 ID: {source_id}")
                self.lbl_strat_params.setText(f"進場分數: {position_dto.source_summary.get('total_score', '-')}")
                self.lbl_strat_perf.setText(f"適用市場體制 (Regime): {position_dto.source_summary.get('regime', '未指定')}")
            else:
                self.lbl_strat_id.setText("手動建立，無推薦 / 回測來源")
                self.lbl_strat_version.setText(f"來源類型: {source_type or '手動交易'}")
                if source_id:
                    self.lbl_strat_version.setText(self.lbl_strat_version.text() + f" (ID: {source_id})")

            # 更新籌碼監控
            try:
                chip_summary = self.chip_service.get_stock_chip_summary(position_dto.stock_code, period_days=5)
                
                # 籌碼評級
                risk_level = chip_summary.get('risk_level', 'neutral')
                self.lbl_chip_risk_level.setText(self._chip_risk_label(risk_level))
                self.lbl_chip_risk_level.setToolTip(f"raw risk_level: {risk_level}")
                if risk_level == 'bearish':
                    self.lbl_chip_risk_level.setStyleSheet("background-color: #742a2a; color: #fff5f5; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
                elif risk_level == 'bullish':
                    self.lbl_chip_risk_level.setStyleSheet("background-color: #22543d; color: #f0fff4; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
                else:
                    self.lbl_chip_risk_level.setStyleSheet("background-color: #2d3748; color: #e2e8f0; padding: 2px 6px; border-radius: 3px; font-weight: bold;")

                # 連續買賣超
                consecutive = chip_summary.get('consecutive_days', 0)
                if consecutive > 0:
                    self.lbl_chip_consecutive.setText(f"連續 {consecutive} 天淨買超")
                    self.lbl_chip_consecutive.setStyleSheet("color: #48bb78; font-weight: bold;")
                elif consecutive < 0:
                    self.lbl_chip_consecutive.setText(f"連續 {abs(consecutive)} 天淨賣超")
                    self.lbl_chip_consecutive.setStyleSheet("color: #f56565; font-weight: bold;")
                else:
                    self.lbl_chip_consecutive.setText("0 天")
                    self.lbl_chip_consecutive.setStyleSheet("color: white;")

                # 近 5 日累計淨買賣超
                net_qty = chip_summary.get('accumulated_net', 0)
                net_lots = net_qty / 1000.0
                self.lbl_chip_net_5d.setText(f"{net_lots:+.1f} 張")
                if net_qty > 0:
                    self.lbl_chip_net_5d.setStyleSheet("color: #48bb78; font-weight: bold;")
                elif net_qty < 0:
                    self.lbl_chip_net_5d.setStyleSheet("color: #f56565; font-weight: bold;")
                else:
                    self.lbl_chip_net_5d.setStyleSheet("color: white;")

                # 集中度
                concentration = chip_summary.get('concentration', 0.0)
                if chip_summary.get("concentration_status") == "unavailable":
                    self.lbl_chip_concentration.setText("資料不足")
                else:
                    self.lbl_chip_concentration.setText(f"{concentration:.2%}")
                quality = chip_summary.get("quality_counts") or {}
                self.lbl_chip_concentration.setToolTip(
                    "集中度以張數 / 股數等價 quantity 計算；不直接使用千元金額。"
                    f"\nobserved: {quality.get('observed', 0)}"
                    f"\nestimated: {quality.get('estimated', 0)}"
                    f"\nunavailable: {quality.get('unavailable', 0)}"
                )

                # 警示原因
                reasons = chip_summary.get('risk_reasons', [])
                self.lbl_chip_reasons.setText("；".join(reasons) if reasons else "正常")

                # 分點明細
                details = chip_summary.get('branch_details', [])
                detail_data = []
                for d in details:
                    detail_data.append({
                        '分點名稱': d['display_name'],
                        '買進張數': d['buy_qty'] / 1000.0,
                        '賣出張數': d['sell_qty'] / 1000.0,
                        '淨買賣超': d['net_qty'] / 1000.0
                    })
                df_detail = pd.DataFrame(detail_data) if detail_data else pd.DataFrame(columns=['分點名稱', '買進張數', '賣出張數', '淨買賣超'])
                detail_model = PandasTableModel(df_detail)
                self.chip_detail_table.setModel(detail_model)
                self.chip_detail_table.resizeColumnsToContents()
                
            except Exception as ce:
                logger.error("Failed to update chip monitoring UI values: %s", ce)

        except Exception as e:
            logger.error("Failed to update monitoring tab UI: %s", e)

    def _position_price_date(self, position_dto) -> str:
        summary = getattr(position_dto, "source_summary", {}) or {}
        for key in ("current_price_date", "price_as_of_date", "latest_price_date", "as_of_date"):
            value = summary.get(key)
            if value:
                return str(value)
        return str(getattr(position_dto, "last_trade_date", "") or "")

    def _chip_risk_label(self, raw_risk: Any) -> str:
        mapping = {
            "bearish": "偏空",
            "bullish": "偏多",
            "neutral": "中性",
            "low": "低",
            "medium": "中",
            "high": "高",
            "extreme": "極高",
        }
        return mapping.get(str(raw_risk).lower(), str(raw_risk))

    def _clear_lifecycle_labels(self) -> None:
        self.lbl_lifecycle_status.setText("-")
        self.lbl_lifecycle_status.setStyleSheet("color: white;")
        self.lbl_lifecycle_source.setText("-")
        self.lbl_lifecycle_execution.setText("-")
        self.lbl_lifecycle_signal.setText("-")
        self.lbl_lifecycle_market.setText("-")
        self.lbl_lifecycle_data_quality.setText("-")
        self.lbl_lifecycle_tokens.setText("-")

    def _update_lifecycle_review(self, position_dto, monitor_result) -> None:
        try:
            from app_module.portfolio_feedback_service import FeedbackCategory
            from app_module.strategy_lifecycle_service import GateStatus

            report = self.portfolio_feedback_service.build_position_feedback(
                position_dto,
                condition_result=monitor_result,
            )
            if report.thesis_status == GateStatus.FAIL:
                self.lbl_lifecycle_status.setText("假設失效 / 需要覆盤")
                self.lbl_lifecycle_status.setStyleSheet("background-color: #742a2a; color: #fff5f5; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
            elif report.thesis_status == GateStatus.DEGRADED:
                self.lbl_lifecycle_status.setText("證據降級 / 持續觀察")
                self.lbl_lifecycle_status.setStyleSheet("background-color: #7b341e; color: #fffff0; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
            else:
                self.lbl_lifecycle_status.setText("假設仍成立")
                self.lbl_lifecycle_status.setStyleSheet("background-color: #22543d; color: #f0fff4; padding: 2px 6px; border-radius: 3px; font-weight: bold;")

            self.lbl_lifecycle_source.setText(report.source_label)
            self.lbl_lifecycle_execution.setText(self._format_lifecycle_category(report.items, FeedbackCategory.EXECUTION))
            self.lbl_lifecycle_signal.setText(self._format_lifecycle_category(report.items, FeedbackCategory.SIGNAL))
            self.lbl_lifecycle_market.setText(self._format_lifecycle_category(report.items, FeedbackCategory.MARKET))
            self.lbl_lifecycle_data_quality.setText(self._format_lifecycle_category(report.items, FeedbackCategory.DATA_QUALITY))
            self.lbl_lifecycle_tokens.setText("；".join(report.summary_tokens) if report.summary_tokens else "-")
        except Exception as exc:
            logger.error("Failed to update lifecycle review: %s", exc)
            self.lbl_lifecycle_status.setText("生命週期回顧不可用")
            self.lbl_lifecycle_status.setStyleSheet("background-color: #7b341e; color: #fffff0; padding: 2px 6px; border-radius: 3px; font-weight: bold;")

    def _format_lifecycle_category(self, items, category) -> str:
        matched = [item for item in items if item.category == category]
        if not matched:
            return "-"
        parts = []
        for item in matched:
            evidence = ", ".join(f"{key}={value}" for key, value in item.evidence.items())
            parts.append(f"{item.status.value}: {item.reason}" + (f" ({evidence})" if evidence else ""))
        return "；".join(parts)

    def _on_drill_down_chip_clicked(self):
        """下鑽詳細主力流向"""
        if not self.selected_stock_code:
            QMessageBox.warning(self, "提示", "請先選擇要下鑽的持倉個股")
            return
            
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'show_smart_money_flow_for_stock'):
                parent.show_smart_money_flow_for_stock(self.selected_stock_code)
                return
            parent = parent.parent()
            
        QMessageBox.warning(self, "提示", "未找到 MainWindow 主視圖，無法完成下鑽")

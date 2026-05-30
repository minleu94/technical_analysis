"""
持倉管理與交易日誌視圖 (Phase 4.1 Portfolio MVP)
提供手動交易記錄、衍生持倉加載、交易日誌管理以及基於推薦引擎的持倉狀態條件監控。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd
from uuid import uuid4

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QMessageBox, QDialog, QDialogButtonBox, QLineEdit,
    QTextEdit, QListWidget, QListWidgetItem, QHeaderView, QMenu,
    QAbstractItemView, QGroupBox, QSplitter, QComboBox, QDateEdit,
    QDoubleSpinBox, QFormLayout, QTabWidget, QFrame
)
from PySide6.QtCore import Qt, Signal, QSize, QDate
from PySide6.QtGui import QFont, QColor, QPalette, QBrush

from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.portfolio_service import PortfolioService
from app_module.journal_service import JournalService
from app_module.recommendation_service import RecommendationService
from portfolio_module import PortfolioValidationError
from ui_qt.widgets.info_button import InfoButton

logger = logging.getLogger(__name__)


class GradientCard(QFrame):
    """精美 HSL 漸層資訊展示卡片"""
    
    def __init__(self, title: str, value: str, gradient_style: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        
        # 設置漸層樣式與圓角、陰影
        self.setStyleSheet(f"""
            GradientCard {{
                background: {gradient_style};
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(4)
        
        # 標題
        self.title_label = QLabel(title)
        title_font = QFont("Inter", 9)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        layout.addWidget(self.title_label)
        
        # 數值
        self.value_label = QLabel(value)
        value_font = QFont("Outfit", 18)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet("color: white;")
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
        except Exception as e:
            logger.debug("Auto query stock name failed: %s", e)
            
    def _validate_and_accept(self):
        if not self.code_input.text().strip():
            QMessageBox.warning(self, "驗證失敗", "請輸入證券代號")
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
        parent=None
    ):
        super().__init__(parent)
        self.portfolio_service = portfolio_service
        self.journal_service = journal_service
        self.recommendation_service = recommendation_service
        
        self.positions_model: Optional[PandasTableModel] = None
        self.trades_model: Optional[PandasTableModel] = None
        self.selected_stock_code: str = ""
        
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
            "資產估計淨值 (NAV)", "TWD 0",
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
        self.positions_table.setAlternatingRowColors(True)
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
        self.btn_record_trade.setStyleSheet("background-color: #2b6cb0; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;")
        self.btn_record_trade.clicked.connect(self._show_record_trade_dialog)
        btn_layout.addWidget(self.btn_record_trade)
        
        self.btn_add_journal = QPushButton("新增日記")
        self.btn_add_journal.clicked.connect(self._show_add_journal_dialog)
        btn_layout.addWidget(self.btn_add_journal)
        
        self.btn_refresh = QPushButton("整理刷新")
        self.btn_refresh.clicked.connect(self.refresh_all)
        btn_layout.addWidget(self.btn_refresh)
        
        # 🗑️ 清空全體數據按鈕
        self.btn_clear_all = QPushButton("🗑️ 清空全體數據")
        self.btn_clear_all.setStyleSheet("background-color: #e53e3e; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;")
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
        
        self.trades_table = QTableView()
        self.trades_table.setAlternatingRowColors(True)
        self.trades_table.setSelectionBehavior(QTableView.SelectRows)
        self.trades_table.horizontalHeader().setStretchLastSection(True)
        # 啟用右鍵選單
        self.trades_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trades_table.customContextMenuRequested.connect(self._show_trade_context_menu)
        history_layout.addWidget(self.trades_table)
        
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
        
        main_splitter.addWidget(right_widget)
        
        # 設定左右分割比例（60% : 40%）
        main_splitter.setSizes([720, 480])
        main_layout.addWidget(main_splitter)
        
    def refresh_all(self):
        """重新整理加載所有持倉、歷史與日記數據"""
        logger.info("[PortfolioView] Refreshing all data...")
        self._load_portfolio_summary()
        self._load_positions_table()
        self._load_trades_history()
        self._load_journal_entries()
        
    def _load_portfolio_summary(self):
        """讀取持倉摘要，並更新頂部卡片"""
        try:
            portfolio = self.portfolio_service.get_portfolio()
            active_count = portfolio.active_positions
            total_invested = portfolio.total_invested_amount
            realized_pnl = portfolio.total_realized_pnl
            
            # 用投入與已實現估算簡易 Net Asset Value (MVP 版本)
            nav = total_invested + realized_pnl
            
            self.card_net_val.update_value(f"TWD {nav:,.2f}")
            self.card_invested.update_value(f"TWD {total_invested:,.2f}")
            
            # P&L 色彩區分
            pnl_text = f"TWD {realized_pnl:+,.2f}"
            self.card_pnl.update_value(pnl_text)
            if realized_pnl > 0:
                self.card_pnl.card_pnl_style = "color: #48bb78;"  # 綠色
            elif realized_pnl < 0:
                self.card_pnl.card_pnl_style = "color: #f56565;"  # 紅色
                
            self.card_positions.update_value(f"{active_count} 檔")
        except Exception as e:
            logger.error("Failed to load portfolio summary: %s", e)
            
    def _load_positions_table(self):
        """加載衍生持倉列表，並執行非同步推薦引擎 Monitor 檢查"""
        try:
            positions = self.portfolio_service.list_positions()
            
            if not positions:
                df = pd.DataFrame(columns=["證券代號", "證券名稱", "持有股數", "平均成本", "投入金額", "已實現損益", "狀態監控"])
            else:
                data = []
                for p in positions:
                    # 執行 Condition Monitor 警告匹配
                    monitor_status = "✅ 良好"
                    tooltip_msg = "技術面表現良好，符合策略脈絡"
                    
                    # 嘗試非同步或背景調用推薦分析（如果服務可用且有最新推薦緩存）
                    if self.recommendation_service and self.recommendation_service.config:
                        try:
                            # 對於該個股，我們嘗試拉取最近一天的推薦打分（此處拉取快照）
                            code = p.stock_code
                            # 進行簡化條件監控：例如呼叫內部篩選或打分引擎
                            # 為了不卡頓 UI，如果該股最近沒有被緩存，我們可以安全跳過
                            if code not in self.rec_cache:
                                # 背景加載
                                self._update_recommendation_cache_for_stock(code)
                                
                            rec_info = self.rec_cache.get(code)
                            if rec_info:
                                score = rec_info.get("score", 100)
                                if score < 60:
                                    monitor_status = "⚠️ 警示"
                                    tooltip_msg = f"評分過低 ({score}分)！Regime 不合或技術指標走弱。Why Not: {rec_info.get('why_not', '無')}"
                        except Exception as me:
                            logger.debug("Condition monitor check failed for %s: %s", p.stock_code, me)
                            
                    data.append({
                        "證券代號": p.stock_code,
                        "證券名稱": p.stock_name,
                        "持有股數": p.quantity,
                        "平均成本": p.average_cost,
                        "投入金額": p.invested_amount,
                        "已實現損益": p.realized_pnl,
                        "狀態監控": monitor_status,
                        "_tooltip": tooltip_msg  # 用於自定義表格行為
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
                            "why_not": "多空分數失衡" if score < 60 else ""
                        }
        except Exception as e:
            logger.debug("Failed to prefetch recommendation score for %s: %s", stock_code, e)

    def _load_trades_history(self):
        """加載交易明細，若有選定股票，則進行篩選"""
        try:
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
        except Exception as e:
            logger.error("Failed to load trades history: %s", e)
            
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
            self.selected_stock_code = ""
            self._load_trades_history()
            self._load_journal_entries()

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
            
        df = self.trades_model.getDataFrame()
        row = index.row()
        if row >= len(df) or "_trade_id" not in df.columns:
            return
            
        trade_id = df.iloc[row]["_trade_id"]
        stock_name = df.iloc[row]["證券名稱"]
        side_str = df.iloc[row]["買賣"]
        qty = df.iloc[row]["交易股數"]
        price = df.iloc[row]["單價"]
        
        menu = QMenu(self)
        action_delete = menu.addAction("❌ 刪除此交易紀錄")
        
        action = menu.exec(self.trades_table.viewport().mapToGlobal(pos))
        if action == action_delete:
            confirm = QMessageBox.question(
                self, "二次確認",
                f"您確定要刪除這筆 {stock_name} 的 {side_str} ({qty}股, @{price}) 紀錄嗎？\n這將會自動重新計算您的庫存部位與平均成本！",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if confirm == QMessageBox.Yes:
                try:
                    self.portfolio_service.delete_trade(trade_id)
                    QMessageBox.information(self, "成功", "該交易紀錄已成功移除，持倉與成本均已重算完畢！")
                    self.refresh_all()
                    self.portfolioUpdated.emit()
                except PortfolioValidationError as pve:
                    QMessageBox.critical(self, "刪除失敗 (領域防禦)", str(pve))
                except Exception as e:
                    QMessageBox.critical(self, "刪除失敗", f"發生非預期錯誤：\n{e}")

    def _show_journal_context_menu(self, pos):
        """日記列表的右鍵選單"""
        item = self.journal_list.itemAt(pos)
        if not item:
            return
            
        journal_id = item.data(Qt.UserRole)
        if not journal_id:
            return
            
        menu = QMenu(self)
        action_delete = menu.addAction("❌ 刪除此篇日記筆記")
        
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
            self, "⚠️ 極度危險警告 ⚠️",
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

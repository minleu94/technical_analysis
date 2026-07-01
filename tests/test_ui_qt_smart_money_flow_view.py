import os
import sys
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView
import pandas as pd

from app_module.dtos.broker_flow_dtos import BranchFlowAggregation, BrokerFlowEvent, StockFlowAggregation
from app_module.dtos.flow_signal_dtos import FlowSignalDTO
from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.views.smart_money.smart_money_flow_view import SmartMoneyFlowView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class FakeSmartMoneyService:
    def __init__(self, stock_details=None):
        self.stock_details = stock_details or []

    def get_stock_flow_signals(self, period="week"):
        return []

    def get_market_flow_summary(self, signals=None, period="week"):
        from app_module.dtos.flow_signal_dtos import SmartMoneySummaryDTO

        return SmartMoneySummaryDTO()

    def get_tracked_branches(self):
        return [
            {"display_name": "凱基-台北", "system_key": "kgi_taipei"},
            {"display_name": "富邦-仁愛", "system_key": "fubon_renai"},
        ]

    def get_branch_flow_details(self, period="week"):
        return []

    def get_stock_detail_by_branches(self, stock_code, period):
        return self.stock_details


class FakeSemanticService:
    def build_stock_semantics(self, stock_code, decision_date):
        from app_module.dtos.smart_money_semantic_dtos import SmartMoneySemanticSummary, SmartMoneyWindowStats

        window = SmartMoneyWindowStats(
            window_days=5,
            net_qty=500,
            buy_qty=700,
            sell_qty=200,
            direction="buy",
            continuous_buy_days=2,
            continuous_sell_days=0,
            top_n=3,
            top_concentration_bp=7000,
            observed_count=3,
            estimated_count=0,
            unavailable_count=0,
            usable_coverage_bp=10000,
        )
        return SmartMoneySemanticSummary(
            stock_code=stock_code,
            stock_name=f"股票{stock_code}",
            decision_date=decision_date,
            primary_state="初轉買",
            semantic_flags=("分點集中異常",),
            confidence_bp=10000,
            quality="observed",
            warnings=(),
            evidence_lines=("5 日轉為買超",),
            window_5=window,
            window_20=window,
            window_60=window,
        )


def _signal(code: str, score: float, net_qty: int) -> FlowSignalDTO:
    aggregation = StockFlowAggregation(
        stock_code=code,
        stock_name=f"股票{code}",
        total_buy_qty=max(net_qty, 0),
        total_sell_qty=abs(min(net_qty, 0)),
        total_net_qty=net_qty,
        lots_coverage_ratio=Decimal("1"),
    )
    return FlowSignalDTO(
        stock_code=code,
        stock_name=f"股票{code}",
        aggregation=aggregation,
        smart_money_score=score,
        branch_concentration=0.5,
    )


def _branch_detail(name: str, buy_qty: int, sell_qty: int, net_qty: int) -> BranchFlowAggregation:
    return BranchFlowAggregation(
        branch_system_key=name,
        branch_display_name=name,
        stock_code="2330",
        stock_name="股票2330",
        total_buy_qty=buy_qty,
        total_sell_qty=sell_qty,
        total_net_qty=net_qty,
        usable_event_count=1,
    )


def test_smart_money_flow_defaults_to_top_and_bottom_50_scope():
    app()
    view = SmartMoneyFlowView(FakeSmartMoneyService())
    signals = [
        *[_signal(f"P{i:04d}", 100 - i, 1000 - i) for i in range(60)],
        *[_signal(f"N{i:04d}", i, -1000 - i) for i in range(60)],
    ]

    filtered = view._filter_scanner_signals(signals)

    assert view.scope_combo.currentData() == "top_bottom_50"
    assert len(filtered) == 100
    assert sum(1 for signal in filtered if signal.aggregation.total_net_qty > 0) == 50
    assert sum(1 for signal in filtered if signal.aggregation.total_net_qty < 0) == 50

    view.scope_combo.setCurrentIndex(view.scope_combo.findData("all"))
    assert len(view._filter_scanner_signals(signals)) == 120


def test_smart_money_flow_detail_double_click_switches_to_branch_tracker():
    app()
    view = SmartMoneyFlowView(FakeSmartMoneyService())
    branches = view.flow_service.get_tracked_branches()
    for branch in branches:
        view.branch_combo.addItem(branch["display_name"], branch["system_key"])

    view.detail_table.setModel(PandasTableModel(pd.DataFrame([{
        "分點名稱": "富邦-仁愛",
        "買進張數": "100",
        "賣出張數": "20",
        "淨買賣超": "+80",
    }])))

    index = view.detail_table.model().index(0, 0)
    view._drill_down_branch_from_detail(index)

    assert view.tab_widget.currentIndex() == 1
    assert view.branch_combo.currentText() == "富邦-仁愛"


def test_smart_money_table_model_renders_semantic_state_and_diagnostics():
    qt_app = app()
    signal = _signal("2330", 88, 500)
    view = SmartMoneyFlowView(
        FakeSmartMoneyService(),
        smart_money_semantic_service=FakeSemanticService(),
    )
    view.resize(1600, 800)
    view.show()

    view._apply_scanner_signals([signal])
    qt_app.processEvents()

    model = view.scanner_table.model()
    headers = [model.headerData(i, Qt.Horizontal) for i in range(model.columnCount())]
    assert "語意狀態" in headers
    assert "5/20/60 日診斷" in headers
    semantic_col = headers.index("語意狀態")
    concentration_col = headers.index("集中度")
    diagnostic_col = headers.index("5/20/60 日診斷")
    assert "初轉買" in model.data(model.index(0, semantic_col), Qt.DisplayRole)
    assert "5D" in model.data(model.index(0, diagnostic_col), Qt.DisplayRole)
    assert view.scanner_table.columnWidth(concentration_col) <= 70
    assert view.scanner_table.columnWidth(semantic_col) <= 86
    header = view.scanner_table.horizontalHeader()
    trend_col = headers.index("近期趨勢 (Trend)")
    badges_col = headers.index("信號 (Badges)")
    assert header.sectionResizeMode(diagnostic_col) == QHeaderView.ResizeMode.Interactive
    assert header.sectionResizeMode(trend_col) == QHeaderView.ResizeMode.Interactive
    assert view.scanner_table.columnWidth(trend_col) == 190
    assert view.scanner_table.columnWidth(diagnostic_col) <= 420
    assert view.scanner_table.columnWidth(badges_col) <= 280
    total_column_width = sum(
        view.scanner_table.columnWidth(col)
        for col in range(model.columnCount())
    )
    assert total_column_width <= view.scanner_table.maximumWidth()
    assert view.scanner_table.horizontalScrollBar().maximum() == 0


def test_smart_money_detail_table_fits_columns_without_horizontal_scroll():
    qt_app = app()
    service = FakeSmartMoneyService(stock_details=[
        _branch_detail("元大證券", 54622, 9742, 44880),
        _branch_detail("永豐金-板新", 10000, 37, 9963),
        _branch_detail("凱基", 681, 401, 280),
    ])
    view = SmartMoneyFlowView(
        service,
        smart_money_semantic_service=FakeSemanticService(),
    )
    view.resize(1600, 800)
    view.show()

    view._apply_scanner_signals([_signal("2330", 88, 500)])
    view.scanner_table.selectRow(0)
    view._on_scanner_selection_changed()
    qt_app.processEvents()

    model = view.detail_table.model()
    headers = [model.headerData(i, Qt.Horizontal) for i in range(model.columnCount())]
    net_col = headers.index("淨買賣超")
    sell_col = headers.index("賣出張數")
    total_column_width = sum(
        view.detail_table.columnWidth(col)
        for col in range(model.columnCount())
    )
    viewport_width = view.detail_table.viewport().width()

    assert total_column_width <= viewport_width
    assert viewport_width - total_column_width <= 24
    assert view.detail_table.columnWidth(net_col) >= 128
    assert view.detail_table.columnWidth(sell_col) < view.detail_table.columnWidth(net_col)
    assert view.detail_table.horizontalScrollBar().maximum() == 0

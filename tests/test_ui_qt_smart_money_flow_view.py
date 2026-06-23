import os
import sys
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
import pandas as pd

from app_module.dtos.broker_flow_dtos import BrokerFlowEvent, StockFlowAggregation
from app_module.dtos.flow_signal_dtos import FlowSignalDTO
from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.views.smart_money.smart_money_flow_view import SmartMoneyFlowView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class FakeSmartMoneyService:
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
        return []


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
    app()
    signal = _signal("2330", 88, 500)
    view = SmartMoneyFlowView(
        FakeSmartMoneyService(),
        smart_money_semantic_service=FakeSemanticService(),
    )

    view._apply_scanner_signals([signal])

    model = view.scanner_table.model()
    headers = [model.headerData(i, Qt.Horizontal) for i in range(model.columnCount())]
    assert "語意狀態" in headers
    assert "5/20/60 日診斷" in headers
    semantic_col = headers.index("語意狀態")
    diagnostic_col = headers.index("5/20/60 日診斷")
    assert "初轉買" in model.data(model.index(0, semantic_col), Qt.DisplayRole)
    assert "5日" in model.data(model.index(0, diagnostic_col), Qt.DisplayRole)

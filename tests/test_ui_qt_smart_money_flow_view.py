import os
import sys
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.dtos.portfolio_dtos import PortfolioDTO, PositionDTO
from app_module.portfolio_condition_monitor import PortfolioConditionResult
from ui_qt.views.portfolio_view import PortfolioView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class FakePortfolioService:
    def __init__(self):
        from data_module.config import TWStockConfig
        self.config = TWStockConfig()

    def get_portfolio(self):
        return PortfolioDTO(
            portfolio_id="default",
            portfolio_name="Default Portfolio",
            total_positions=1,
            active_positions=1,
            positions=self.list_positions(),
            total_invested_amount=900000,
            total_realized_pnl=0,
        )

    def list_positions(self):
        return [
            PositionDTO(
                position_id="default:2330",
                portfolio_id="default",
                stock_code="2330",
                stock_name="台積電",
                quantity=1000,
                average_cost=900,
                invested_amount=900000,
                source_type="recommendation_result",
                source_id="rec_001",
                source_summary={
                    "profile_id": "aggressive_short",
                    "regime": "trend",
                    "total_score": 85.0,
                },
                trade_ids=["trade_001"],
            )
        ]

    def list_trades(self):
        return []

    def get_current_price(self, stock_code):
        from decimal import Decimal
        return Decimal("950.0")


class FakeJournalService:
    def list_journal_entries(self, stock_code=""):
        return []


class FakeConditionMonitor:
    def evaluate(self, position, current_snapshot=None):
        return PortfolioConditionResult(
            stock_code=position.stock_code,
            status="warning",
            label="需要留意",
            source_label="推薦：aggressive_short",
            entry_regime="trend",
            current_regime="trend",
            entry_total_score="85.0",
            current_total_score="62.0",
            reasons=["評分下降 23.0 分"],
            details={"score_degraded": True},
        )


def test_portfolio_view_displays_condition_monitor_result_in_positions_table():
    app()
    view = PortfolioView(
        portfolio_service=FakePortfolioService(),
        journal_service=FakeJournalService(),
        condition_monitor=FakeConditionMonitor(),
    )

    df = view.positions_model.getDataFrame()

    assert df.iloc[0]["狀態監控"] == "需要留意"
    assert df.iloc[0]["來源脈絡"] == "推薦：aggressive_short"
    assert df.iloc[0]["監控原因"] == "評分下降 23.0 分"
    assert df.iloc[0]["進場分數"] == "85.0"
    assert df.iloc[0]["目前分數"] == "62.0"

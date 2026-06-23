import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from app_module.dtos.portfolio_dtos import PortfolioDTO, PositionDTO, TradeDTO
from ui_qt.views.portfolio_view import AddTradeDialog, PortfolioView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class FakeIndustryMapper:
    def get_stock_name(self, code: str) -> str | None:
        return {"2330": "台積電", "2317": "鴻海"}.get(code)


class FakeRecommendationService:
    def __init__(self):
        self.industry_mapper = FakeIndustryMapper()


def test_add_trade_dialog_autofills_stock_name_and_rejects_unknown_code():
    app()
    dialog = AddTradeDialog(recommendation_service=FakeRecommendationService())

    dialog.code_input.setText("2330")
    assert dialog.name_input.text() == "台積電"
    assert dialog.code_error_label.text() == ""

    dialog.name_input.clear()
    dialog.code_input.setText("999999")
    assert "找不到正式股票代號" in dialog.code_error_label.text()


def test_add_trade_dialog_prefills_taiwan_fee_and_sell_tax():
    app()
    dialog = AddTradeDialog(recommendation_service=FakeRecommendationService())

    dialog.qty_input.setValue(1000)
    dialog.price_input.setValue(100)
    dialog.side_combo.setCurrentIndex(dialog.side_combo.findData("buy"))
    assert dialog.fees_input.value() == 143
    assert dialog.taxes_input.value() == 0

    dialog.side_combo.setCurrentIndex(dialog.side_combo.findData("sell"))
    assert dialog.fees_input.value() == 143
    assert dialog.taxes_input.value() == 300


@dataclass
class FakeConfig:
    output_root: Path

    @property
    def broker_branch_registry_file(self) -> Path:
        return self.output_root / "missing_broker_branch_registry.csv"

    @property
    def data_dir(self) -> Path:
        return self.output_root

    def resolve_output_path(self, relative_path: str) -> Path:
        return self.output_root / relative_path


class FakePortfolioService:
    def __init__(self, config: FakeConfig):
        self.config = config
        self.positions = [
            PositionDTO(
                position_id="default:2330",
                portfolio_id="default",
                stock_code="2330",
                stock_name="台積電",
                quantity=1000,
                average_cost=100,
                invested_amount=100000,
                current_price=110,
                unrealized_pnl=10000,
                unrealized_pnl_pct=0.1,
                source_type="",
                source_id="",
                source_summary={"current_price_date": "2026-06-22"},
            ),
            PositionDTO(
                position_id="default:2317",
                portfolio_id="default",
                stock_code="2317",
                stock_name="鴻海",
                quantity=1000,
                average_cost=150,
                invested_amount=150000,
                current_price=151,
                unrealized_pnl=1000,
                unrealized_pnl_pct=0.0067,
                source_type="recommendation_result",
                source_id="rec-1",
                source_summary={"profile_id": "balanced"},
            ),
        ]
        self.trades = [
            TradeDTO(
                trade_id="t1",
                portfolio_id="default",
                stock_code="2330",
                stock_name="台積電",
                side="buy",
                quantity=1000,
                price=100,
                trade_date="2026-06-20",
            ),
            TradeDTO(
                trade_id="t2",
                portfolio_id="default",
                stock_code="2317",
                stock_name="鴻海",
                side="buy",
                quantity=1000,
                price=150,
                trade_date="2026-06-20",
            ),
        ]

    def get_portfolio(self):
        return PortfolioDTO(
            portfolio_id="default",
            portfolio_name="Default",
            total_positions=2,
            active_positions=2,
            positions=self.positions,
            total_invested_amount=250000,
            total_realized_pnl=0,
        )

    def list_positions(self):
        return self.positions

    def list_trades(self):
        return self.trades

    def get_current_price(self, stock_code: str):
        for position in self.positions:
            if position.stock_code == stock_code:
                return position.current_price
        return None


class FakeJournalService:
    def list_journal_entries(self, stock_code: str = ""):
        return []


class FakeConditionResult:
    status = "valid"
    label = "假設仍成立"
    reasons: list[str] = []
    source_label = "手動建立"
    entry_total_score = "-"
    current_total_score = "-"
    details: dict[str, Any] = {}


class FakeConditionMonitor:
    def evaluate(self, _position, _snapshot):
        return FakeConditionResult()


class FakeChipService:
    def get_stock_chip_summary(self, _stock_code: str, period_days: int = 5):
        return {
            "risk_level": "bearish",
            "consecutive_days": -2,
            "accumulated_net": -3000,
            "concentration": 0.25,
            "risk_reasons": ["連續賣超"],
            "quality_counts": {"observed": 3, "estimated": 1, "unavailable": 2},
            "branch_details": [],
        }


def make_portfolio_view(tmp_path, parent=None):
    app()
    view = PortfolioView(
        portfolio_service=FakePortfolioService(FakeConfig(tmp_path)),
        journal_service=FakeJournalService(),
        condition_monitor=FakeConditionMonitor(),
        parent=parent,
    )
    view._update_lifecycle_review = lambda *_args, **_kwargs: None
    view.chip_service = FakeChipService()
    return view


def test_portfolio_active_summary_lists_position_count_and_top_symbols(tmp_path):
    view = make_portfolio_view(tmp_path)

    view.refresh_all()

    assert "活躍持倉：2 檔" in view.active_positions_summary_label.text()
    assert "2330 台積電" in view.active_positions_summary_label.text()


def test_trade_history_filter_label_and_clear_button(tmp_path):
    view = make_portfolio_view(tmp_path)

    view.selected_stock_code = "2330"
    view._load_trades_history()
    assert "目前只顯示：2330" in view.trade_filter_status_label.text()

    view.clear_trade_filter_button.click()
    assert view.selected_stock_code == ""
    assert "顯示全部交易歷史" in view.trade_filter_status_label.text()


def test_portfolio_monitoring_shows_price_as_of_manual_source_and_chinese_chip_risk(tmp_path):
    view = make_portfolio_view(tmp_path)
    view.selected_stock_code = "2330"

    view._update_monitoring_tab()

    assert "價格日期：2026-06-22" in view.lbl_mon_current_price.text()
    assert "手動建立，無推薦 / 回測來源" in view.lbl_strat_id.text()
    assert "偏空" in view.lbl_chip_risk_level.text()
    assert "bearish" in view.lbl_chip_risk_level.toolTip()
    assert "observed: 3" in view.lbl_chip_concentration.toolTip()


def test_portfolio_drill_down_passes_selected_stock_to_parent(tmp_path):
    class Parent(QWidget):
        def __init__(self):
            super().__init__()
            self.received = None

        def show_smart_money_flow_for_stock(self, stock_code: str):
            self.received = stock_code

    parent = Parent()
    view = make_portfolio_view(tmp_path, parent=parent)
    view.selected_stock_code = "2330"

    view._on_drill_down_chip_clicked()

    assert parent.received == "2330"

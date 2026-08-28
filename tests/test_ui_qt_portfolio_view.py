import os
import sqlite3
import sys
from dataclasses import dataclass, field
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from app_module.dtos.portfolio_dtos import PortfolioDTO, PositionDTO, TradeDTO
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from app_module.paper_trade_ledger import PaperTradeLedgerRepository
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
        self.deleted_trade_ids: list[str] = []

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

    def delete_trade(self, trade_id: str) -> bool:
        self.deleted_trade_ids.append(trade_id)
        remaining = [trade for trade in self.trades if trade.trade_id != trade_id]
        if len(remaining) == len(self.trades):
            return False
        self.trades = remaining
        return True


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
    assert view.card_net_val.title_label.text() == "持倉市值（未含現金）"
    assert view.card_net_val.value_label.text() == "TWD 261,000.00"
    assert "已標記市值 2/2 檔" in view.active_positions_summary_label.text()


def test_portfolio_stress_lab_is_visible_and_research_only(tmp_path):
    view = make_portfolio_view(tmp_path)

    view.stress_scenario_combo.setCurrentIndex(
        view.stress_scenario_combo.findData("concentration_event")
    )
    view.btn_run_stress.click()

    assert "最大持倉事件" in view.stress_summary_label.text()
    assert "可計算" in view.stress_summary_label.text()
    assert "研究用途" in view.stress_detail_label.text()
    assert view.stress_positions_table.model().rowCount() == 2
    assert view._stress_result.research_only is True
    assert view._stress_result.investment_effectiveness_claim is False


def test_portfolio_stress_history_is_read_only_when_not_configured(tmp_path):
    view = make_portfolio_view(tmp_path)

    view.refresh_all()

    assert "Stress 歷史" in view.stress_history_summary_label.text()
    assert "stress_history_not_configured" in view.stress_history_summary_label.text()
    assert view.stress_history_table.model().rowCount() == 1
    assert not (tmp_path / "portfolio").exists()


def test_portfolio_stress_history_requires_confirmation_and_renders_saved_row(tmp_path, monkeypatch):
    view = make_portfolio_view(tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    view.btn_save_stress_history.click()

    assert view.stress_history_db_path.exists()
    assert view.stress_history_table.model().rowCount() == 1
    assert "狀態：可用" in view.stress_history_summary_label.text()
    assert "writes_allowed=false" in view.stress_history_summary_label.text()


def test_paper_portfolio_readiness_tab_discloses_snapshot_and_missing_benchmark(tmp_path):
    state_db = tmp_path / "paper_portfolio" / "paper_portfolio.sqlite"
    status_path = tmp_path / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    snapshot = PaperPortfolioSnapshot(
        snapshot_id="paper-main-20260821",
        portfolio_id="paper-main",
        decision_date="2026-08-21",
        source_result_id="rec-1",
        cash=Decimal("100.00"),
        total_value=Decimal("1000.00"),
        positions=(
            PaperPortfolioPositionSnapshot(
                stock_code="2330",
                quantity=1,
                mark_price=Decimal("900.00"),
                market_value=Decimal("900.00"),
                weight_bp=9000,
            ),
        ),
    )
    PaperPortfolioSnapshotRepository(state_db).append(snapshot)
    status_path.parent.mkdir(parents=True)
    status_path.write_text(
        json.dumps(
            {
                "schema_version": "paper-portfolio-daily-status.v1",
                "status": "passed",
                "snapshot_id": snapshot.snapshot_id,
                "decision_date": snapshot.decision_date,
                "cash": "100.00",
                "total_value": "1000.00",
                "state_db": str(state_db.resolve()),
                "writes_market_db": False,
                "auto_rebalance_allowed": False,
                "changes_advice": False,
                "broker_execution": False,
            }
        ),
        encoding="utf-8",
    )

    view = make_portfolio_view(tmp_path)
    view.refresh_all()

    assert "最新可採用 snapshot：2026-08-21" in view.paper_readiness_summary_label.text()
    assert "raw 累積 1 筆" in view.paper_readiness_summary_label.text()
    assert "TWD 1,000.00" in view.paper_readiness_summary_label.text()
    assert "Equal Weight：尚無" in view.paper_readiness_summary_label.text()
    assert "equal_weight_benchmark_db_missing" in view.paper_readiness_detail_label.text()
    assert view.paper_snapshot_table.model().rowCount() == 1


def test_paper_portfolio_tab_discloses_weekly_evidence_gap_without_writing(tmp_path):
    view = make_portfolio_view(tmp_path)

    view.refresh_all()

    assert "最近週報" in view.paper_weekly_report_label.text()
    assert "paper_snapshot_db_missing" in view.paper_weekly_report_label.text()
    assert not (tmp_path / "paper_portfolio").exists()


def test_paper_equal_weight_button_previews_then_builds_new_ledger(tmp_path, monkeypatch):
    baseline_path = tmp_path / "paper_portfolio" / "baseline_20260712.json"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_text(
        json.dumps(
            {
                "decision_date": "2026-08-20",
                "residual_cash": "800.00",
                "research_only": True,
                "writes_positions_db": False,
                "broker_order_allowed": False,
                "auto_rebalance_allowed": False,
                "allocations": [
                    {
                        "stock_code": "2330",
                        "reference_price": "100.00",
                        "executable_shares": 1,
                        "executable_amount": "100.00",
                    },
                    {
                        "stock_code": "2317",
                        "reference_price": "50.00",
                        "executable_shares": 2,
                        "executable_amount": "100.00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    state_db = tmp_path / "paper_portfolio" / "paper_portfolio.sqlite"
    for snapshot_id, decision_date, total_value in (
        ("paper-main-20260820", "2026-08-20", "1000.00"),
        ("paper-main-20260821", "2026-08-21", "1010.00"),
    ):
        PaperPortfolioSnapshotRepository(state_db).append(
            PaperPortfolioSnapshot(
                snapshot_id=snapshot_id,
                portfolio_id="paper-main",
                decision_date=decision_date,
                source_result_id="recommendation-1",
                cash=Decimal("800.00"),
                total_value=Decimal(total_value),
                positions=(
                    PaperPortfolioPositionSnapshot(
                        stock_code="2330",
                        quantity=1,
                        mark_price=Decimal("100.00"),
                        market_value=Decimal("100.00"),
                        weight_bp=1000,
                    ),
                ),
            )
        )
    market_db = tmp_path / "sqlite" / "twstock.db"
    market_db.parent.mkdir(parents=True)
    with sqlite3.connect(market_db) as connection:
        connection.execute("CREATE TABLE daily_prices (證券代號 TEXT, 日期 TEXT, 收盤價 TEXT)")
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?)",
            (("2330", "20260820", "101.00"), ("2317", "20260820", "49.00")),
        )

    view = make_portfolio_view(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: messages.append(str(_args[2])))

    view.btn_build_paper_benchmark.click()

    benchmark_path = tmp_path / "paper_portfolio" / "paper_equal_weight_benchmark.sqlite"
    assert benchmark_path.exists()
    assert "已保存" in messages[-1]
    assert "Equal Weight：2 筆" in view.paper_readiness_summary_label.text()


def test_paper_fill_csv_import_requires_confirmation_and_only_writes_paper_ledger(
    tmp_path,
    monkeypatch,
):
    view = make_portfolio_view(tmp_path)
    csv_path = tmp_path / "paper_fills.csv"
    csv_path.write_text(
        "fill_id,order_id,portfolio_id,event_date,stock_code,side,requested_quantity,"
        "filled_quantity,reference_price,fill_price,commission,tax,slippage_cost,"
        "turnover_bp,execution_gap_bp,status,source_event_id,override_reason\n"
        "fill-1,order-1,paper-main,2026-08-27,2330,buy,1000,1000,100.00,100.08,"
        "15.00,0.00,8.00,120,8,filled,broker-1,\n",
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(csv_path), "CSV"))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    view.btn_import_paper_fills.click()

    ledger_path = tmp_path / "paper_portfolio" / "paper_trade_ledger.sqlite"
    assert [fill.fill_id for fill in PaperTradeLedgerRepository(ledger_path).list()] == ["fill-1"]
    assert [trade.trade_id for trade in view.portfolio_service.trades] == ["t1", "t2"]
    assert "成本帳：ready" in view.paper_readiness_summary_label.text()


def test_paper_fill_template_export_writes_headers_only_and_not_ledger(tmp_path, monkeypatch):
    view = make_portfolio_view(tmp_path)
    template = tmp_path / "paper_fills_template.csv"
    messages: list[str] = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(template), "CSV"))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: messages.append(str(_args[2])))

    view.btn_export_paper_template.click()

    assert template.read_text(encoding="utf-8-sig").startswith(
        "fill_id,order_id,portfolio_id,event_date"
    )
    assert not (tmp_path / "paper_portfolio" / "paper_trade_ledger.sqlite").exists()
    assert any("空白欄位範本" in message for message in messages)


def test_portfolio_trade_csv_import_requires_confirmation_and_passes_source_trace(tmp_path, monkeypatch):
    view = make_portfolio_view(tmp_path)
    csv_path = tmp_path / "broker.csv"
    csv_path.write_text(
        "stock_code,side,quantity,price,trade_date\n"
        "2330,buy,1000,100,2026-08-20\n",
        encoding="utf-8-sig",
    )
    imported = []
    view.portfolio_service.record_trades = lambda trades: imported.extend(trades) or trades
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(csv_path), "CSV"))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    view.btn_import_trades.click()

    assert len(imported) == 1
    assert imported[0].source_type == "broker_csv"
    assert imported[0].source_snapshot_hash.startswith("sha256:")


def test_trade_history_filter_label_and_clear_button(tmp_path):
    view = make_portfolio_view(tmp_path)

    view.selected_stock_code = "2330"
    view._load_trades_history()
    assert "目前只顯示：2330" in view.trade_filter_status_label.text()

    view.clear_trade_filter_button.click()
    assert view.selected_stock_code == ""
    assert "顯示全部交易歷史" in view.trade_filter_status_label.text()


def test_portfolio_trade_delete_button_requires_a_selected_transaction(tmp_path):
    view = make_portfolio_view(tmp_path)

    assert view.delete_selected_trade_button.text() == "刪除選取交易"
    assert not view.delete_selected_trade_button.isEnabled()

    view.trades_table.selectRow(0)
    app().processEvents()

    assert view.delete_selected_trade_button.isEnabled()
    assert view.selected_trade_id == "t1"
    assert "已選取：2330 台積電" in view.trade_selection_hint_label.text()


def test_portfolio_trade_delete_button_confirms_then_deletes_one_transaction(tmp_path, monkeypatch):
    view = make_portfolio_view(tmp_path)
    service = view.portfolio_service
    portfolio_updates: list[bool] = []
    view.portfolioUpdated.connect(lambda: portfolio_updates.append(True))
    view.trades_table.selectRow(0)
    app().processEvents()

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    view.delete_selected_trade_button.click()

    assert service.deleted_trade_ids == ["t1"]
    assert [trade.trade_id for trade in service.trades] == ["t2"]
    assert portfolio_updates == [True]
    assert not view.delete_selected_trade_button.isEnabled()


def test_portfolio_trade_delete_button_keeps_data_when_confirmation_is_cancelled(tmp_path, monkeypatch):
    view = make_portfolio_view(tmp_path)
    service = view.portfolio_service
    view.trades_table.selectRow(0)
    app().processEvents()

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)

    view.delete_selected_trade_button.click()

    assert service.deleted_trade_ids == []
    assert [trade.trade_id for trade in service.trades] == ["t1", "t2"]


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

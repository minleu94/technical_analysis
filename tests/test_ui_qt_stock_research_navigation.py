"""持倉與觀察清單共用同一個個股研究報告 context 入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from app_module.dtos.portfolio_dtos import PortfolioDTO, PositionDTO
from app_module.research_session import ResearchStockContextDTO
from ui_qt.views.portfolio_view import PortfolioView
from ui_qt.views.watchlist_view import WatchlistView


def _app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class WatchlistStub:
    def query_stock_names(self, codes):
        return {"2330": "台積電", "1101": "台泥"}

    def get_stocks(self):
        return [{"stock_code": "2330", "stock_name": "台積電"}]


@dataclass
class PortfolioConfig:
    output_root: Path

    @property
    def broker_branch_registry_file(self) -> Path:
        return self.output_root / "missing_registry.csv"

    @property
    def data_dir(self) -> Path:
        return self.output_root

    def resolve_output_path(self, relative_path: str) -> Path:
        return self.output_root / relative_path


class PortfolioStub:
    def __init__(self, config: PortfolioConfig):
        self.config = config
        self.position = PositionDTO(
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
        )

    def get_portfolio(self):
        return PortfolioDTO(
            portfolio_id="default",
            portfolio_name="Default",
            total_positions=1,
            active_positions=1,
            positions=[self.position],
            total_invested_amount=100000,
            total_realized_pnl=0,
        )

    def list_positions(self):
        return [self.position]

    def get_current_price(self, stock_code):
        return self.position.current_price if stock_code == "2330" else None

    def list_trades(self):
        return []


class JournalStub:
    def list_journal_entries(self, stock_code=""):
        return []


class ConditionStub:
    def evaluate(self, _position, _snapshot):
        return type(
            "Condition",
            (),
            {
                "status": "valid",
                "label": "仍符合",
                "source_label": "手動",
                "entry_total_score": "-",
                "current_total_score": "-",
                "reasons": [],
                "details": {},
            },
        )()


def test_watchlist_and_portfolio_emit_same_context_contract(tmp_path: Path) -> None:
    _app()
    watchlist = WatchlistView(WatchlistStub())
    portfolio = PortfolioView(
        portfolio_service=PortfolioStub(PortfolioConfig(tmp_path)),
        journal_service=JournalStub(),
        condition_monitor=ConditionStub(),
    )
    portfolio._update_lifecycle_review = lambda *_args, **_kwargs: None

    watch_contexts: list[object] = []
    portfolio_contexts: list[object] = []
    watchlist.stockResearchRequested.connect(watch_contexts.append)
    portfolio.stockResearchRequested.connect(portfolio_contexts.append)

    watchlist.stocks_table.selectRow(0)
    watchlist.stock_research_btn.click()
    portfolio.select_stock("2330")
    portfolio.btn_stock_research.click()

    assert len(watch_contexts) == 1
    assert len(portfolio_contexts) == 1
    assert isinstance(watch_contexts[0], ResearchStockContextDTO)
    assert isinstance(portfolio_contexts[0], ResearchStockContextDTO)
    assert watch_contexts[0].stock_code == portfolio_contexts[0].stock_code == "2330"
    assert watch_contexts[0].source_workspace == "watchlist"
    assert portfolio_contexts[0].source_workspace == "portfolio"
    assert watch_contexts[0].source_kind == "recommendation"
    assert portfolio_contexts[0].source_kind == "portfolio"

    # Returns use the existing model, so selection/filter state is not rebuilt.
    assert watchlist.select_stock("2330") is True
    assert portfolio.select_stock("2330") is True
    watchlist.close()
    portfolio.close()

import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from app_module.research_run_dtos import ResearchRunMetadataDTO
from ui_qt.views.backtest_view import BacktestView
from ui_qt.views.research_lab.run_registry_compare_widget import (
    RunRegistryCompareWidget,
)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qt_app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def _metadata(run_id: str, **overrides) -> ResearchRunMetadataDTO:
    values = {
        "run_id": run_id,
        "run_name": run_id,
        "run_type": "single_backtest",
        "strategy_id": "baseline_score",
        "universe": ["2330", "2317"],
        "start_date": "2026-01-02",
        "end_date": "2026-01-08",
        "data_fingerprint": "sha256:data",
        "capital_cents": 1_000_000_00,
        "fee_bp_x100": 1425,
        "slippage_bp_x100": 500,
        "execution_price": "next_open",
        "sizing_mode": "fixed_amount",
        "normalized_params": {"buy_score": 70, "sell_score": 40},
        "metrics": {"sharpe_ratio": 1.2},
        "regime_breakdown": {"trend": {"trades": 3}},
        "benchmark_results": {"taiex": {"excess_return_bp": 250}},
        "payload_hash": f"sha256:{run_id}",
        "created_at": "2026-06-14T12:00:00",
    }
    values.update(overrides)
    return ResearchRunMetadataDTO(**values)


class FakeResearchRunService:
    def __init__(self):
        self.runs = [
            _metadata("run-a"),
            _metadata("run-b", normalized_params={"buy_score": 80, "sell_score": 40}),
            _metadata("run-c", run_type="recommendation_portfolio", strategy_id="profile-a"),
        ]
        self.data = {
            "run-a": pd.DataFrame(
                {"日期": ["2026-01-02", "2026-01-05"], "portfolio_value": [1000, 1100]}
            ),
            "run-b": pd.DataFrame(
                {"日期": ["2026-01-02", "2026-01-05"], "portfolio_value": [2000, 2100]}
            ),
            "run-c": pd.DataFrame(
                {"日期": ["2026-01-02", "2026-01-05"], "portfolio_value": [1500, 1510]}
            ),
        }

    def list_runs(self, include_archived: bool = False):
        return self.runs

    def load_run_data(self, run_id: str):
        return SimpleNamespace(
            metadata=next(run for run in self.runs if run.run_id == run_id),
            equity=self.data[run_id],
            trades=pd.DataFrame(),
        )


def test_backtest_view_mounts_registry_compare_subtab(qt_app):
    view = BacktestView(backtest_service=None, config=None)
    view.research_run_service = FakeResearchRunService()
    widget = view.result_panel.add_registry_compare_tab()

    labels = [view.result_tabs.tabText(index) for index in range(view.result_tabs.count())]

    assert "Registry 比較" in labels
    assert widget is view.run_registry_compare_widget


def test_registry_compare_widget_filters_paginates_and_limits_selection(qt_app):
    widget = RunRegistryCompareWidget(FakeResearchRunService(), page_size=2)

    widget.refresh_runs()
    assert widget.run_list.count() == 2
    assert "第 1 / 2 頁" in widget.page_label.text()

    widget.next_page()
    assert widget.run_list.count() == 1
    assert "第 2 / 2 頁" in widget.page_label.text()

    widget.run_type_filter.setCurrentText("single_backtest")
    widget.refresh_runs()
    assert widget.run_list.count() == 2
    assert all("single_backtest" in widget.run_list.item(i).text() for i in range(2))

    widget.run_list.selectAll()
    assert widget.selected_run_ids() == ["run-a", "run-b"]


def test_registry_compare_widget_renders_badge_diff_metrics_and_saved_benchmark(qt_app):
    widget = RunRegistryCompareWidget(FakeResearchRunService(), page_size=10)
    widget.refresh_runs()
    widget.run_list.item(0).setSelected(True)
    widget.run_list.item(1).setSelected(True)

    widget.compare_selected_runs()

    assert "Comparable" in widget.comparability_badge.text()
    assert widget.params_diff_table.model().rowCount() >= 1
    assert widget.metrics_table.model().rowCount() == 2
    assert widget.regime_table.model().rowCount() == 2
    assert widget.benchmark_table.model().rowCount() == 2
    assert widget.normalized_equity_table.model().rowCount() == 4


def test_registry_compare_widget_discards_stale_run_list_response(qt_app):
    widget = RunRegistryCompareWidget(FakeResearchRunService(), page_size=10)

    stale_request = widget.begin_run_list_request()
    fresh_request = widget.begin_run_list_request()
    widget.apply_run_list_response(stale_request, [_metadata("stale")])
    widget.apply_run_list_response(fresh_request, [_metadata("fresh")])

    assert widget.run_list.count() == 1
    assert "fresh" in widget.run_list.item(0).text()

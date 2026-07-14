import os
import sys
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.broker_flow_dashboard_dtos import (
    BrokerFlowDashboardSnapshot,
    BrokerFlowStockDetailSnapshot,
)
from decision_module.flow_contracts import FlowSignalDTO, SmartMoneySummaryDTO, StockFlowAggregation
from ui_qt.views.smart_money.smart_money_flow_view import SmartMoneyFlowView


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in self.callbacks:
            callback(*args)


class ManualWorker:
    def __init__(self, task):
        self.task = task
        self.finished = _Signal()
        self.error = _Signal()
        self.cancelled = _Signal()
        self.cancel_calls = []
        self.started = False

    def start(self):
        self.started = True

    def cancel(self, *, cooperative, wait):
        self.cancel_calls.append((cooperative, wait))


class WorkerFactory:
    def __init__(self):
        self.workers = []

    def __call__(self, task):
        worker = ManualWorker(task)
        self.workers.append(worker)
        return worker


class AsyncService:
    def load_dashboard_snapshot(self, query):
        raise AssertionError("manual worker should not run in GUI thread")

    def load_stock_branch_detail(self, stock_code, period, as_of_date):
        raise AssertionError("manual worker should not run in GUI thread")

    def load_branch_tracker(self, branch_system_key, period, as_of_date):
        raise AssertionError("manual worker should not run in GUI thread")


def _app():
    return QApplication.instance() or QApplication(sys.argv)


def _signal(code):
    aggregation = StockFlowAggregation(
        stock_code=code,
        stock_name=code,
        total_buy_qty=10,
        total_net_qty=10,
        lots_coverage_ratio=Decimal("1"),
    )
    return FlowSignalDTO(stock_code=code, stock_name=code, aggregation=aggregation)


def _snapshot(code):
    return BrokerFlowDashboardSnapshot(
        as_of_date=date(2026, 7, 10),
        period="week",
        top_signals=(_signal(code),),
        bottom_signals=(),
        summary=SmartMoneySummaryDTO(),
        semantics_by_code={},
        tracked_branches=(("branch-a", "Branch A"),),
        quality="observed",
    )


def test_dashboard_refresh_cancels_cooperatively_and_discards_stale_result():
    _app()
    factory = WorkerFactory()
    view = SmartMoneyFlowView(AsyncService(), task_worker_factory=factory)

    view._refresh_data()
    first = factory.workers[-1]
    view._refresh_data()
    second = factory.workers[-1]

    assert first.cancel_calls == [(True, False)]
    first.finished.emit(_snapshot("OLD"))
    assert not hasattr(view, "scanner_model")

    second.finished.emit(_snapshot("NEW"))
    assert view.scanner_model.get_signal_at(0).stock_code == "NEW"
    assert view.refresh_btn.isEnabled()


def test_stock_detail_uses_worker_and_discards_previous_selection_result():
    _app()
    factory = WorkerFactory()
    view = SmartMoneyFlowView(AsyncService(), task_worker_factory=factory)
    view._apply_scanner_signals([_signal("2330")], semantics_by_code={})
    view.scanner_table.selectRow(0)
    view._on_scanner_selection_changed()

    worker = factory.workers[-1]
    assert worker.started
    assert view.detail_label.text().endswith("載入中…")
    worker.finished.emit(BrokerFlowStockDetailSnapshot(
        as_of_date=date(2026, 7, 10), period="week", stock_code="2330",
        rows=(), quality="observed",
    ))
    assert view.detail_table.model().rowCount() == 0


def test_close_event_only_requests_cooperative_cancellation():
    _app()
    factory = WorkerFactory()
    view = SmartMoneyFlowView(AsyncService(), task_worker_factory=factory)
    view._refresh_data()
    worker = factory.workers[-1]

    view.close()

    assert worker.cancel_calls == [(True, False)]

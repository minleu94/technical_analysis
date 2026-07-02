from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QDateEdit

from app_module.forward_performance_dashboard_dtos import (
    ForwardPerformanceDashboardCardSummary,
    ForwardPerformanceDashboardRequest,
    ForwardPerformanceDashboardResult,
    ForwardPerformanceDashboardRow,
)
from app_module.forward_performance_read_model import (
    SUMMARY_STATUS_INSUFFICIENT_SAMPLE,
    SUMMARY_STATUS_MISSING_BENCHMARK,
    SUMMARY_STATUS_READY,
)
from ui_qt.models.forward_performance_table_model import ForwardPerformanceTableModel
from ui_qt.views.forward_performance_view import ForwardPerformanceView
from ui_qt.widgets.date_filter_edit import date_filter_value


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class FakeDashboardService:
    def __init__(self, result: ForwardPerformanceDashboardResult):
        self.result = result
        self.calls: list[ForwardPerformanceDashboardRequest] = []

    def load_dashboard(self, request: ForwardPerformanceDashboardRequest):
        self.calls.append(request)
        return self.result


def _row(
    group_key: str = "recommendation_included",
    *,
    status: str = SUMMARY_STATUS_READY,
    sample_size: int = 12,
    warning_counts: dict[str, int] | None = None,
) -> ForwardPerformanceDashboardRow:
    return ForwardPerformanceDashboardRow(
        group_by="event_type",
        group_key=group_key,
        window_days=20,
        sample_size=sample_size,
        pending_count=1,
        missing_count=2,
        mean_forward_return_bp=123,
        median_forward_return_bp=100,
        mean_benchmark_excess_bp=45,
        median_benchmark_excess_bp=40,
        mean_industry_excess_bp=20,
        median_industry_excess_bp=10,
        positive_rate_bp=6500,
        win_vs_benchmark_rate_bp=5400,
        win_vs_industry_rate_bp=5100,
        mean_mae_bp=-80,
        mean_mfe_bp=210,
        summary_status=status,
        first_event_date="2026-07-01",
        last_event_date="2026-07-10",
        quality_counts={"observed": sample_size},
        warning_counts=warning_counts or {},
    )


def _result(rows: tuple[ForwardPerformanceDashboardRow, ...]) -> ForwardPerformanceDashboardResult:
    if not rows:
        message = "尚無足夠 forward evidence。請先 capture evidence events 並 calculate forward outcomes。"
    elif any(row.summary_status == SUMMARY_STATUS_MISSING_BENCHMARK for row in rows):
        message = "Benchmark 缺失，無法判斷相對大盤超額。"
    elif any(row.summary_status == SUMMARY_STATUS_INSUFFICIENT_SAMPLE for row in rows):
        message = "樣本不足，只能作資料品質檢查，不可作訊號有效性判斷。"
    else:
        message = ""
    return ForwardPerformanceDashboardResult(
        request=ForwardPerformanceDashboardRequest(),
        cards=ForwardPerformanceDashboardCardSummary(
            total_events=sum(row.sample_size + row.pending_count + row.missing_count for row in rows),
            ready_outcomes=sum(row.sample_size for row in rows),
            pending_outcomes=sum(row.pending_count for row in rows),
            missing_outcomes=sum(row.missing_count for row in rows),
            groups_ready=sum(1 for row in rows if row.summary_status == SUMMARY_STATUS_READY),
            groups_insufficient_sample=sum(
                1 for row in rows if row.summary_status == SUMMARY_STATUS_INSUFFICIENT_SAMPLE
            ),
            groups_degraded=sum(1 for row in rows if row.summary_status == SUMMARY_STATUS_MISSING_BENCHMARK),
            missing_benchmark_count=5,
            missing_industry_count=0,
            warnings_count=5,
        ),
        rows=rows,
        empty_state_message=message,
        limitations=(
            "這是 research evidence，不是買賣建議。",
            "Close-to-close forward return 不代表實盤可執行績效。",
        ),
    )


def test_table_model_formats_bp_without_changing_raw_values() -> None:
    app()
    model = ForwardPerformanceTableModel()
    model.set_rows((_row(),))

    col = model.column_index("mean_forward_return_bp")
    idx = model.index(0, col)

    assert model.data(idx) == "1.23%"
    assert model.raw_value(0, "mean_forward_return_bp") == 123


def test_forward_performance_view_renders_filters_cards_table_and_details() -> None:
    app()
    service = FakeDashboardService(_result((_row(),)))
    view = ForwardPerformanceView(service, auto_refresh=False, async_refresh=False)

    assert isinstance(view.start_date_input, QDateEdit)
    assert isinstance(view.end_date_input, QDateEdit)
    assert view.start_date_input.calendarPopup()
    assert view.end_date_input.calendarPopup()
    view.start_date_input.setDate(QDate(2026, 6, 1))
    view.end_date_input.setDate(QDate(2026, 6, 30))
    view.symbol_input.setText("2330")
    view.group_by_combo.setCurrentIndex(view.group_by_combo.findData("regime"))
    view.window_days_input.setValue(20)
    view.min_sample_size_input.setValue(10)
    view.refresh_dashboard()

    assert service.calls[-1].start_date == "2026-06-01"
    assert service.calls[-1].end_date == "2026-06-30"
    assert service.calls[-1].symbol == "2330"
    assert service.calls[-1].group_by == "regime"
    assert "事件總數" in view.total_events_card.text()
    assert "15" in view.total_events_card.text()
    assert view.table_model.rowCount() == 1
    assert "recommendation_included" in view.detail_panel.toPlainText()
    assert "Close-to-close" in view.detail_panel.toPlainText()
    assert "不是買賣建議" in view.boundary_label.text()


def test_forward_performance_date_filters_do_not_display_or_submit_sentinel() -> None:
    app()
    service = FakeDashboardService(_result(()))
    view = ForwardPerformanceView(service, auto_refresh=False, async_refresh=False)

    assert "1900" not in view.start_date_input.text()
    assert "1900" not in view.end_date_input.text()
    assert date_filter_value(view.start_date_input) is None
    assert date_filter_value(view.end_date_input) is None

    view.start_date_input.setDate(QDate(2026, 6, 30))
    assert date_filter_value(view.start_date_input) == "2026-06-30"

    view.start_date_input.clear()
    view.refresh_dashboard()

    assert "1900" not in view.start_date_input.text()
    assert service.calls[-1].start_date is None


def test_forward_performance_table_headers_are_chinese() -> None:
    app()
    model = ForwardPerformanceTableModel()

    assert model.headerData(model.column_index("group_key"), Qt.Horizontal) == "群組"
    assert model.headerData(model.column_index("mean_forward_return_bp"), Qt.Horizontal) == "平均前瞻報酬"
    assert model.headerData(model.column_index("summary_status"), Qt.Horizontal) == "狀態"


def test_forward_performance_view_empty_and_degraded_states() -> None:
    app()
    empty_view = ForwardPerformanceView(FakeDashboardService(_result(())), auto_refresh=False, async_refresh=False)
    empty_view.refresh_dashboard()

    assert "尚無足夠 forward evidence" in empty_view.empty_state_label.text()

    degraded = _row(
        "benchmark_gap",
        status=SUMMARY_STATUS_MISSING_BENCHMARK,
        warning_counts={"missing_benchmark": 5},
    )
    degraded_view = ForwardPerformanceView(
        FakeDashboardService(_result((degraded,))),
        auto_refresh=False,
        async_refresh=False,
    )
    degraded_view.refresh_dashboard()

    assert "Benchmark 缺失" in degraded_view.empty_state_label.text()


def test_forward_performance_view_ignores_stale_worker_result() -> None:
    app()
    latest = _result((_row("latest"),))
    stale = _result((_row("stale"),))
    view = ForwardPerformanceView(FakeDashboardService(latest), auto_refresh=False, async_refresh=False)

    view._active_request_id = 2
    view._on_dashboard_loaded(stale, request_id=1)

    assert view.table_model.rowCount() == 0

    view._on_dashboard_loaded(latest, request_id=2)

    assert view.table_model.raw_value(0, "group_key") == "latest"

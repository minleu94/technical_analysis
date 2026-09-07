import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from decision_module.flow_contracts import (
    BranchFlowAggregation,
    FlowSignalDTO,
    StockFlowAggregation,
)
from ui_qt.views.recommendation.execution_coordinator import (
    RecommendationExecutionRequest,
)
from ui_qt.views.recommendation_view import (
    format_execution_elapsed,
    recommendation_execution_stage,
)
from ui_qt.views.smart_money.terminal_table_model import (
    BranchTrackerTableModel,
    TerminalTableModel,
)
from ui_qt.widgets.fast_chart_widget import (
    _build_html,
    _numeric_alternative_text,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def _request() -> RecommendationExecutionRequest:
    return RecommendationExecutionRequest(
        {
            "patterns": {"selected": ["W底"]},
            "signals": {"technical_indicators": ["trend"]},
        }
    )


def test_recommendation_detailed_progress_is_opt_in_and_cancellable() -> None:
    class Service:
        def __init__(self) -> None:
            self.cancel_callback = None

        def run_recommendation(self, **kwargs):
            self.cancel_callback = kwargs.pop("cancel_callback", None)
            assert kwargs["max_stocks"] == 200
            return ["result"]

    service = Service()
    progress = []
    result = _request().execute(
        service,
        progress_callback=lambda message, percentage: progress.append((message, percentage)),
        cancellation_callback=lambda: False,
        detailed_progress=True,
    )

    assert result == ["result"]
    assert service.cancel_callback is not None
    assert progress == [
        ("讀取股票數據...", 10),
        ("建立分析範圍...", 25),
        ("執行推薦規則...", 35),
        ("整理推薦結果...", 90),
        ("分析完成", 100),
    ]


def test_recommendation_cancel_before_service_keeps_old_service_contract() -> None:
    class Service:
        def __init__(self) -> None:
            self.called = False

        def run_recommendation(self, **kwargs):
            self.called = True
            return ["unexpected"]

    service = Service()
    progress = []
    result = _request().execute(
        service,
        progress_callback=lambda message, percentage: progress.append((message, percentage)),
        cancellation_callback=lambda: True,
    )

    assert result == []
    assert service.called is False
    assert progress == [("讀取股票數據...", 10), ("已取消：推薦分析尚未開始", 10)]


def test_recommendation_status_helpers_expose_elapsed_and_stage() -> None:
    assert format_execution_elapsed(3661) == "01:01:01"
    assert recommendation_execution_stage("執行推薦規則...", 35) == (
        "執行推薦規則",
        3,
        4,
    )
    assert recommendation_execution_stage("分析完成", 100) == ("完成", 4, 4)


def test_recommendation_view_keeps_visible_status_through_safe_cancel() -> None:
    _app()

    from ui_qt.views.recommendation_view import RecommendationView

    view = RecommendationView(MagicMock(), MagicMock())
    view._begin_execution_status()
    view._on_progress("執行推薦規則...", 35)

    assert "階段：執行推薦規則（3/4）" in view.execution_status_label.text()
    assert "耗時：" in view.execution_status_label.text()
    assert "最後活動：" in view.execution_status_label.text()
    assert not view.cancel_execution_btn.isHidden()

    view._mark_execution_cancel_requested()
    assert "狀態：取消中" in view.execution_status_label.text()
    assert "取消請求已送出" in view.progress_label.text()
    view._on_recommendation_cancelled()
    assert "狀態：已取消" in view.execution_status_label.text()
    assert "安全取消" in view.execution_status_label.text()
    assert "未套用部分結果" in view.progress_label.text()


def test_fast_chart_has_keyboard_canvas_and_numeric_alternative() -> None:
    payload = {
        "kind": "lineArea",
        "title": "測試淨值",
        "series": [
            {"time": "2026-09-01", "value": 100.5},
            {"time": "2026-09-02", "value": 101.25},
        ],
        "markers": [{"label": "平均", "value": 100.875}],
    }

    alternative = _numeric_alternative_text(payload)
    html = _build_html(payload)

    assert "2026-09-01" in alternative
    assert "100.5" in alternative
    assert "tabindex=\"0\"" in html
    assert "aria-keyshortcuts=\"ArrowLeft ArrowRight Home End\"" in html
    assert "canvas.addEventListener('keydown'" in html


def test_terminal_models_expose_graphic_cells_as_accessible_text() -> None:
    aggregation = StockFlowAggregation(
        stock_code="2330",
        stock_name="台積電",
        total_net_qty=1234,
        lots_coverage_ratio=Decimal("1"),
    )
    signal = FlowSignalDTO(
        stock_code="2330",
        stock_name="台積電",
        aggregation=aggregation,
        smart_money_score=88.5,
        signal_tags=["買超", "集中"],
        sparkline_data=[1.0, -2.0],
        sparkline_details=[("2026-09-05", 12)],
    )
    model = TerminalTableModel([signal])

    badges_index = model.index(0, 6)
    trend_index = model.index(0, 7)
    assert model.data(badges_index, Qt.DisplayRole) == ""
    assert "買超" in model.data(badges_index, Qt.AccessibleTextRole)
    assert "2026-09-05" in model.data(trend_index, Qt.AccessibleTextRole)
    assert "+12" in model.data(trend_index, Qt.StatusTipRole)
    assert model.headerData(7, Qt.Horizontal, Qt.AccessibleTextRole) == "近期趨勢 (Trend)"

    aggregation_by_branch = BranchFlowAggregation(
        branch_system_key="branch",
        branch_display_name="測試分點",
        stock_code="2330",
        stock_name="台積電",
        total_buy_qty=20,
        total_sell_qty=8,
        total_net_qty=12,
        sparkline_data=[3.0, -1.0],
        sparkline_details=[("2026-09-05", 3)],
    )
    branch_model = BranchTrackerTableModel([aggregation_by_branch])
    branch_trend = branch_model.index(0, 5)
    assert branch_model.data(branch_trend, Qt.DisplayRole) == ""
    assert "2026-09-05" in branch_model.data(branch_trend, Qt.AccessibleTextRole)
    assert "+3" in branch_model.data(branch_trend, Qt.StatusTipRole)


def test_smart_money_tables_are_keyboard_focusable() -> None:
    _app()

    class Service:
        pass

    from ui_qt.views.smart_money.smart_money_flow_view import SmartMoneyFlowView

    view = SmartMoneyFlowView(Service())

    assert view.scanner_table.focusPolicy() == Qt.StrongFocus
    assert view.scanner_table.accessibleName() == "主力資金流向掃描結果"
    assert view.branch_table.focusPolicy() == Qt.StrongFocus
    assert view.branch_table.accessibleName() == "分點追蹤結果"

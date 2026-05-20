import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QPushButton, QStackedWidget

from ui_qt.views.update_view import UpdateView


class _TestableUpdateView(UpdateView):
    def _check_data_status(self):
        return None


class FakeUpdateService:
    def __init__(self):
        self.calls = []

    def check_data_status(self):
        self.calls.append(("check_data_status",))
        return {
            "daily_data": {"latest_date": "2026-05-19", "total_records": 100, "status": "ok"},
            "market_index": {"latest_date": "2026-05-19", "total_records": 10, "status": "ok"},
            "industry_index": {"latest_date": "2026-05-19", "total_records": 20, "status": "ok"},
            "broker_branch": {"latest_date": "2026-05-19", "total_records": 30, "status": "ok"},
        }

    def update_daily(self, start_date, end_date):
        self.calls.append(("update_daily", start_date, end_date))
        return {"success": True, "message": "daily ok"}

    def update_market(self, start_date, end_date):
        self.calls.append(("update_market", start_date, end_date))
        return {"success": True, "message": "market ok"}

    def update_industry(self, start_date, end_date):
        self.calls.append(("update_industry", start_date, end_date))
        return {"success": True, "message": "industry ok"}

    def update_broker_branch(self, start_date, end_date):
        self.calls.append(("update_broker_branch", start_date, end_date))
        return {"success": True, "message": "broker ok"}

    def merge_daily_data(self, force_all=False):
        self.calls.append(("merge_daily_data", force_all))
        return {"success": True, "message": "merge daily ok"}

    def merge_broker_branch_data(self):
        self.calls.append(("merge_broker_branch_data",))
        return {"success": True, "message": "merge broker ok"}

    def calculate_technical_indicators(
        self,
        target_stock=None,
        force_all=False,
        start_date=None,
        progress_callback=None,
    ):
        self.calls.append(("calculate_technical_indicators", target_stock, force_all, start_date))
        if progress_callback:
            progress_callback("technical indicators ok", 100)
        return {"success": True, "message": "technical ok"}


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def make_view():
    app()
    return _TestableUpdateView(FakeUpdateService())


def test_update_view_uses_workbench_navigation():
    view = make_view()

    assert isinstance(view.nav_list, QListWidget)
    assert isinstance(view.content_stack, QStackedWidget)
    assert [view.nav_list.item(i).text() for i in range(view.nav_list.count())] == [
        "全部資料",
        "每日股價",
        "大盤指數",
        "產業指數",
        "券商分點",
        "技術指標",
    ]
    assert view.content_stack.count() == 6
    assert view.nav_list.currentRow() == 0


def test_all_data_view_has_safe_update_primary_button():
    view = make_view()

    assert isinstance(view.safe_update_all_btn, QPushButton)
    assert view.safe_update_all_btn.text() == "安全更新所有數據"


def test_safe_update_all_runs_conservative_sequence():
    view = make_view()
    progress = []

    result = view._run_safe_update_all(
        progress_callback=lambda message, pct: progress.append((message, pct))
    )

    assert result["success"] is True
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_status",
        "update_daily",
        "update_market",
        "update_industry",
        "update_broker_branch",
        "merge_daily_data",
        "merge_broker_branch_data",
        "calculate_technical_indicators",
        "check_data_status",
    ]
    assert view.update_service.calls[-2] == (
        "calculate_technical_indicators",
        None,
        False,
        None,
    )
    assert progress[0][1] == 0
    assert progress[-1][1] == 100


class FailingMarketService(FakeUpdateService):
    def update_market(self, start_date, end_date):
        self.calls.append(("update_market", start_date, end_date))
        return {"success": False, "message": "market failed"}


def test_safe_update_all_stops_after_failed_core_step():
    app()
    view = _TestableUpdateView(FailingMarketService())

    result = view._run_safe_update_all(progress_callback=lambda message, pct: None)

    assert result["success"] is False
    assert result["failed_step"] == "大盤指數更新"
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_status",
        "update_daily",
        "update_market",
    ]

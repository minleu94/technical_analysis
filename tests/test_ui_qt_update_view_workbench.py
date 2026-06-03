import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QStackedWidget

from ui_qt.views.update_view import UpdateView


class _TestableUpdateView(UpdateView):
    def _check_data_status(self):
        return None


class FakeConfig:
    def __init__(self):
        self.use_sqlite = False
        self.data_root = Path(".")
        self.log_dir = Path(".")
        self.db_file = Path("test.db")

class FakeUpdateService:
    def __init__(self):
        self.calls = []
        self.config = FakeConfig()
        
    def export_table_to_csv(self, table_name, target_path, start_date=None, end_date=None):
        self.calls.append(("export_table_to_csv", table_name, target_path, start_date, end_date))
        return {"success": True, "message": "export ok"}

    def check_data_status(self):
        self.calls.append(("check_data_status",))
        return self.check_data_overview()

    def check_data_overview(self):
        self.calls.append(("check_data_overview",))
        return {
            "daily_data": {"latest_date": "2026-05-19", "total_records": 100, "status": "ok"},
            "market_index": {"latest_date": "2026-05-19", "total_records": 10, "status": "ok"},
            "industry_index": {"latest_date": "2026-05-19", "total_records": 20, "status": "ok"},
            "broker_branch": {"latest_date": "2026-05-19", "total_records": 30, "status": "ok"},
            "technical_indicators": {"latest_date": "2026-05-19", "total_records": 40, "status": "ok"},
        }

    def check_source_detail(self, source):
        self.calls.append(("check_source_detail", source))
        return {"latest_date": "2026-05-19", "total_records": 1, "status": "ok"}

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
        incremental_lookback_days=250,
    ):
        self.calls.append((
            "calculate_technical_indicators",
            target_stock,
            force_all,
            start_date,
            incremental_lookback_days,
        ))
        if progress_callback:
            progress_callback("technical indicators ok", 100)
        return {"success": True, "message": "technical ok"}

    def sync_source_to_sqlite(self, source, start_date=None, end_date=None):
        self.calls.append(("sync_source_to_sqlite", source, start_date, end_date))
        return {"success": True, "message": f"{source} sync ok"}


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
        "SQLite 資料檢視",
    ]
    assert view.content_stack.count() == 7
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
        "check_data_overview",
        "update_daily",
        "sync_source_to_sqlite",
        "update_market",
        "sync_source_to_sqlite",
        "update_industry",
        "sync_source_to_sqlite",
        "update_broker_branch",
        "merge_daily_data",
        "sync_source_to_sqlite",
        "merge_broker_branch_data",
        "sync_source_to_sqlite",
        "calculate_technical_indicators",
        "check_data_overview",
    ]
    daily_call = next(call for call in view.update_service.calls if call[0] == "update_daily")
    assert ("sync_source_to_sqlite", "daily_price_files", daily_call[1], daily_call[2]) in view.update_service.calls
    assert ("sync_source_to_sqlite", "market_index", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "industry_index", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "daily_data", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "broker_branch", None, None) in view.update_service.calls
    assert view.update_service.calls[-2] == (
        "calculate_technical_indicators",
        None,
        False,
        None,
        250,
    )
    assert progress[0][1] == 0
    assert progress[-1][1] == 100


def test_overview_check_uses_lightweight_service_contract():
    view = make_view()

    status = view._get_overview_status()

    assert status["daily_data"]["latest_date"] == "2026-05-19"
    assert view.update_service.calls == [("check_data_overview",)]


def test_source_detail_check_uses_detail_service_contract():
    view = make_view()

    detail = view._get_source_detail("broker_branch")

    assert detail == {"broker_branch": {"latest_date": "2026-05-19", "total_records": 1, "status": "ok"}}
    assert view.update_service.calls == [("check_source_detail", "broker_branch")]


def test_source_tabs_have_operational_content():
    view = make_view()

    # 排除最後一個 db_inspector 頁面，因為它的 layout 與 widgets 結構不同
    for row in range(1, view.content_stack.count() - 1):
        page = view.content_stack.widget(row)
        labels = page.findChildren(QLabel)
        buttons = page.findChildren(QPushButton)

        assert len(labels) >= 2
        assert buttons


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
        "check_data_overview",
        "update_daily",
        "sync_source_to_sqlite",
        "update_market",
    ]


def test_update_view_with_config_instantiates_inspector_widget(tmp_path):
    from data_module.config import TWStockConfig
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    
    # 建立臨時路徑
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    data_root.mkdir()
    output_root.mkdir()
    
    # 建立隔離的 config
    config = TWStockConfig(
        data_root=data_root,
        output_root=output_root,
        profile="test"
    )
    config.use_sqlite = True
    
    # 注入到 FakeUpdateService
    service = FakeUpdateService()
    service.config = config
    
    # 實例化 view
    app()
    view = _TestableUpdateView(service)
    
    # 驗證 sqlite_inspector_widget 是否被成功建立
    assert view.nav_list.count() == 7
    # 最後一頁應該是 SqliteInspectorWidget 的實例
    last_widget = view.content_stack.widget(6)
    assert isinstance(last_widget, SqliteInspectorWidget)

def test_safe_update_all_runs_conservative_sequence_sqlite():
    view = make_view()
    view.update_service.config.use_sqlite = True
    progress = []

    result = view._run_safe_update_all(
        progress_callback=lambda message, pct: progress.append((message, pct))
    )

    assert result["success"] is True
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_overview",
        "update_daily",
        "sync_source_to_sqlite",
        "update_market",
        "sync_source_to_sqlite",
        "update_industry",
        "sync_source_to_sqlite",
        "update_broker_branch",
        "sync_source_to_sqlite",  # broker_branch_files 同步
        "calculate_technical_indicators",
        "check_data_overview",
    ]
    # 驗證同步的來源為 broker_branch_files
    assert ("sync_source_to_sqlite", "broker_branch_files", "2026-05-23", "2026-06-02") in view.update_service.calls or any(
        call[0] == "sync_source_to_sqlite" and call[1] == "broker_branch_files" for call in view.update_service.calls
    )

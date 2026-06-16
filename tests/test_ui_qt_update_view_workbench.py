import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QStackedWidget, QMessageBox, QDateEdit
import pandas as pd

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

    assert isinstance(view.quick_update_all_btn, QPushButton)
    assert view.quick_update_all_btn.text() == "⚡ 快速更新 (僅 SQLite)"
    assert isinstance(view.safe_update_all_btn, QPushButton)
    assert view.safe_update_all_btn.text() == "🛡️ 安全更新 (完整 CSV + SQLite)"


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


class FakeInspectorService:
    def __init__(self, total=250):
        self.total = total
        self.last_query = {}
        
    def is_enabled(self):
        return True
        
    def get_tables(self):
        return ["daily_prices"]
        
    def get_table_info(self, table_name):
        return {
            "success": True,
            "table_name": table_name,
            "total_records": self.total,
            "columns_count": 5,
            "earliest_date": "2026-05-01",
            "latest_date": "2026-05-30"
        }
        
    def get_table_schema(self, table_name):
        return pd.DataFrame([{"cid": 0, "name": "日期", "type": "TEXT"}])
        
    def query_table_data_count(self, **kwargs):
        return self.total
        
    def query_table_data(self, table_name, **kwargs):
        self.last_query = kwargs
        limit = kwargs.get("limit", 100)
        return pd.DataFrame([{"日期": f"2026-05-{i:02d}", "證券代號": "2330"} for i in range(min(limit, 10))])


class SynchronousTaskWorker:
    def __init__(self, task_function, *args, **kwargs):
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs
        
        class DummySignal:
            def __init__(self, name):
                self.name = name
                self.slots = []
            def connect(self, slot):
                self.slots.append(slot)
            def emit(self, *args):
                print(f"[DummySignal] emitting {self.name}")
                for slot in self.slots:
                    slot(*args)
        
        self.started = DummySignal("started")
        self.finished = DummySignal("finished")
        self.error = DummySignal("error")
        self.progress = DummySignal("progress")
        self.cancelled = DummySignal("cancelled")

    def start(self):
        try:
            print("[SynchronousTaskWorker] start called")
            self.started.emit()
            print("[SynchronousTaskWorker] calling task_function")
            result = self.task_function(*self.args, **self.kwargs)
            print("[SynchronousTaskWorker] task_function finished, emitting finished")
            self.finished.emit(result)
            print("[SynchronousTaskWorker] finished emitted successfully")
        except Exception as e:
            print(f"[SynchronousTaskWorker] error: {e}")
            self.error.emit(str(e))

    def isRunning(self):
        return False

    def disconnect(self):
        pass

    def wait(self):
        pass


class DeferredTaskWorker:
    instances = []

    def __init__(self, task_function, *args, **kwargs):
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs

        class DummySignal:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def emit(self, *args):
                for slot in list(self.slots):
                    slot(*args)

        self.finished = DummySignal()
        self.error = DummySignal()
        self.cancelled = DummySignal()
        self._running = False
        DeferredTaskWorker.instances.append(self)

    def start(self):
        self._running = True

    def isRunning(self):
        return self._running

    def wait(self):
        self._running = False

    def disconnect(self):
        raise AssertionError("running workers must not be disconnected")


def test_update_view_detail_refresh_does_not_cancel_running_merge(monkeypatch):
    from ui_qt.views import update_view

    DeferredTaskWorker.instances = []
    monkeypatch.setattr(update_view, "TaskWorker", DeferredTaskWorker)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    view = make_view()
    view._execute_merge()
    merge_worker = DeferredTaskWorker.instances[-1]

    view._check_source_detail("market", force=True)

    assert merge_worker.isRunning()
    assert len(view._active_workers) == 2


def test_sqlite_inspector_rapid_requests_keep_running_workers_alive(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget

    DeferredTaskWorker.instances = []
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", DeferredTaskWorker)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    widget = SqliteInspectorWidget(FakeInspectorService(total=250))
    widget.current_table = "daily_prices"

    widget._request_page(load_schema=False)
    widget._request_page(load_schema=False)

    assert len(DeferredTaskWorker.instances) == 2
    assert len(widget._active_workers) == 2


def test_sqlite_inspector_next_page_uses_offset(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)
    
    app()
    print("[Test] app() initialized")
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"
    widget.page_size = 100
    widget.current_page = 2
    print("[Test] calling _request_page")
    widget._request_page(load_schema=False)
    print("[Test] _request_page returned")
    
    assert service.last_query.get("offset") == 100



def test_filter_reload_resets_to_first_page(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)
    
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"
    widget.current_page = 4
    widget.stock_code_input.setText("2330")
    widget._load_current_table_data()
    
    assert widget.current_page == 1


def test_sqlite_inspector_uses_calendar_date_filters(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"

    assert isinstance(widget.date_input, QDateEdit)
    assert widget.date_input.calendarPopup()

    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") is None

    widget.date_input.setDate(QDate(2026, 5, 29))
    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") == "2026-05-29"


def test_sqlite_inspector_header_sort_requests_server_order(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"
    widget._request_page(load_schema=False)

    widget._on_preview_header_clicked(0)

    assert service.last_query.get("sort_column") == "日期"
    assert service.last_query.get("sort_order") == "asc"
    assert widget.current_page == 1





def test_stale_worker_result_is_ignored():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    import pandas as pd
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._active_request_id = 2
    widget._on_table_data_loaded(
        {
            "request_id": 1,
            "table_name": "daily_prices",
            "load_schema": False,
            "info": None,
            "schema": None,
            "filtered_count": 0,
            "preview": pd.DataFrame(),
        }
    )
    assert widget.preview_model is None



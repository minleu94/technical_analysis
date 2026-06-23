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
        self.output_root = Path(".")
        self.profile = "test"
        self.log_dir = Path(".")
        self.db_file = Path("test.db")

class FakeUpdateService:
    def __init__(self):
        self.calls = []
        self.config = FakeConfig()
        self.scripts_dir = Path("scripts")
        
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
            "monthly_revenue": {"latest_date": "2026-05", "total_records": 244499, "status": "ok"},
        }

    def check_source_detail(self, source):
        self.calls.append(("check_source_detail", source))
        return {"latest_date": "2026-05-19", "total_records": 1, "status": "ok"}

    def update_daily(self, start_date, end_date):
        self.calls.append(("update_daily", start_date, end_date))
        return {"success": True, "message": "daily ok"}

    def update_tpex_daily_price(self, target_date):
        self.calls.append(("update_tpex_daily_price", target_date))
        return {
            "success": True,
            "message": "tpex ok",
            "tpex_rows": 1,
            "skipped_rows": 0,
            "source_date": target_date.replace("-", ""),
        }

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
        incremental_lookback_days=120,
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

    def dry_run_mops_monthly_revenue_backfill(
        self,
        snapshot_file=None,
        availability_file=None,
        source_version=None,
    ):
        self.calls.append((
            "dry_run_mops_monthly_revenue_backfill",
            str(snapshot_file) if snapshot_file else None,
            str(availability_file) if availability_file else None,
            source_version,
        ))
        return {
            "success": True,
            "ready_for_apply": True,
            "raw_row_count": 1848,
            "normalized_record_count": 1848,
            "diagnostic_count": 0,
            "message": "dry run ok",
        }

    def apply_mops_monthly_revenue_backfill(
        self,
        snapshot_file=None,
        availability_file=None,
        source_version=None,
    ):
        self.calls.append((
            "apply_mops_monthly_revenue_backfill",
            str(snapshot_file) if snapshot_file else None,
            str(availability_file) if availability_file else None,
            source_version,
        ))
        return {
            "success": True,
            "applied": True,
            "inserted_count": 1848,
            "backup_file": "backup.db",
            "message": "apply ok",
        }


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def make_view():
    app()
    return _TestableUpdateView(FakeUpdateService())


class StaleTechnicalUpdateService(FakeUpdateService):
    def check_data_overview(self):
        self.calls.append(("check_data_overview",))
        return {
            "daily_data": {"latest_date": "2026-05-20", "total_records": 100, "status": "ok"},
            "market_index": {"latest_date": "2026-05-19", "total_records": 10, "status": "ok"},
            "industry_index": {"latest_date": "2026-05-19", "total_records": 20, "status": "ok"},
            "broker_branch": {"latest_date": "2026-05-19", "total_records": 30, "status": "ok"},
            "technical_indicators": {"latest_date": "2026-05-19", "total_records": 40, "status": "ok"},
            "monthly_revenue": {"latest_date": "2026-05", "total_records": 244499, "status": "ok"},
        }


def make_view_with_service(service):
    app()
    return _TestableUpdateView(service)


def test_update_view_does_not_auto_scan_status_on_open():
    app()
    service = FakeUpdateService()

    view = UpdateView(service)

    assert service.calls == []
    assert view.check_status_btn.isEnabled()


def test_update_view_uses_workbench_navigation():
    view = make_view()

    assert isinstance(view.nav_list, QListWidget)
    assert isinstance(view.content_stack, QStackedWidget)
    assert [key for key, _label in view._nav_items] == [
        "all",
        "daily",
        "market",
        "industry",
        "broker_branch",
        "technical",
        "monthly_revenue",
        "db_inspector",
    ]
    assert view.content_stack.count() == 8
    assert view.nav_list.currentRow() == 0


def test_all_data_view_has_safe_update_primary_button():
    view = make_view()

    assert isinstance(view.quick_update_all_btn, QPushButton)
    assert view.quick_update_all_btn.text() == "⚡ 快速更新 (跳過大型合併)"
    assert isinstance(view.safe_update_all_btn, QPushButton)
    assert view.safe_update_all_btn.text() == "🛡️ 安全更新 (完整 CSV + SQLite)"


def test_all_data_view_has_monthly_revenue_status_card():
    view = make_view()

    assert hasattr(view, "monthly_revenue_status_text")

    view._on_status_checked({
        "monthly_revenue": {
            "latest_date": "2026-05",
            "total_records": 244499,
            "status": "ok",
        }
    })

    assert "2026-05" in view.monthly_revenue_status_text.toPlainText()
    assert "244,499" in view.monthly_revenue_status_text.toPlainText()


def test_safe_update_all_skips_technical_when_current():
    view = make_view()
    progress = []

    result = view._run_safe_update_all(
        progress_callback=lambda message, pct: progress.append((message, pct))
    )

    assert result["success"] is True
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_overview",
        "update_daily",
        "update_tpex_daily_price",
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
        "check_data_overview",
        "check_data_overview",
    ]
    daily_call = next(call for call in view.update_service.calls if call[0] == "update_daily")
    assert ("update_tpex_daily_price", daily_call[2]) in view.update_service.calls
    assert ("sync_source_to_sqlite", "daily_price_files", daily_call[1], daily_call[2]) in view.update_service.calls
    assert ("sync_source_to_sqlite", "market_index", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "industry_index", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "daily_data", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "broker_branch", None, None) in view.update_service.calls
    assert not any(call[0] == "calculate_technical_indicators" for call in view.update_service.calls)
    assert result["completed_steps"][-2]["result"]["skipped"] is True
    assert progress[0][1] == 0
    assert progress[-1][1] == 100


def test_safe_update_all_calculates_technical_when_stale():
    view = make_view_with_service(StaleTechnicalUpdateService())

    result = view._run_safe_update_all(progress_callback=lambda message, pct: None)

    assert result["success"] is True
    assert (
        "calculate_technical_indicators",
        None,
        False,
        None,
        120,
    ) in view.update_service.calls


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


def test_source_date_controls_use_clear_calendar_buttons():
    view = make_view()

    for key in ("daily", "market", "industry", "broker_branch"):
        date_edit = getattr(view, f"{key}_end_date")
        assert isinstance(date_edit, QDateEdit)
        assert not date_edit.calendarPopup()

    buttons = [button.text() for button in view.findChildren(QPushButton)]
    assert buttons.count("日曆") >= 4


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
        "update_tpex_daily_price",
        "sync_source_to_sqlite",
        "update_market",
    ]


class FailingTpexService(FakeUpdateService):
    def update_tpex_daily_price(self, target_date):
        self.calls.append(("update_tpex_daily_price", target_date))
        return {"success": False, "message": "tpex failed", "tpex_rows": 0}


def test_safe_update_all_continues_with_warning_when_tpex_fails_after_twse_success():
    app()
    view = _TestableUpdateView(FailingTpexService())

    result = view._run_safe_update_all(progress_callback=lambda message, pct: None)

    assert result["success"] is True
    assert result["warnings"] == ["TPEX 每日股價更新: tpex failed"]
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_overview",
        "update_daily",
        "update_tpex_daily_price",
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
        "check_data_overview",
        "check_data_overview",
    ]


def test_manual_daily_update_also_fetches_tpex_daily_price(monkeypatch):
    from ui_qt.views import update_view

    monkeypatch.setattr(update_view, "ProgressTaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view.daily_radio.setChecked(True)
    view.end_date.setDate(QDate(2026, 6, 16))
    view.lookback_days.setValue(10)

    view._execute_update()

    assert ("update_daily", "2026-06-06", "2026-06-16") in view.update_service.calls
    assert ("update_tpex_daily_price", "2026-06-16") in view.update_service.calls


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
    assert view.nav_list.count() == 8
    # 最後一頁應該是 SqliteInspectorWidget 的實例
    last_widget = view.content_stack.widget(7)
    assert isinstance(last_widget, SqliteInspectorWidget)


def test_background_tpex_refresh_does_not_force_technical_all(monkeypatch):
    from ui_qt.views import update_view

    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            self.pid = 12345

        def poll(self):
            return None

    monkeypatch.setattr(update_view.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view._execute_background_tpex_refresh()

    assert "--sync-sqlite" in captured["cmd"]
    assert "--technical-force-all" not in captured["cmd"]


def test_monthly_revenue_tab_runs_mops_dry_run(monkeypatch):
    from ui_qt.views import update_view

    monkeypatch.setattr(update_view, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view.monthly_revenue_snapshot_input.setText("snapshot.csv")
    view.monthly_revenue_availability_input.setText("availability.csv")

    view._execute_monthly_revenue_backfill(apply=False)

    assert view.update_service.calls[-1] == (
        "dry_run_mops_monthly_revenue_backfill",
        "snapshot.csv",
        "availability.csv",
        "mops-static-snapshot-monthly-revenue-2026-06-16",
    )


def test_monthly_revenue_tab_uses_user_facing_chinese_labels():
    view = make_view()

    labels = [label.text() for label in view.content_stack.widget(6).findChildren(QLabel)]
    buttons = [button.text() for button in view.content_stack.widget(6).findChildren(QPushButton)]

    assert "MOPS 月營收快照檔：" in labels
    assert "正式可得日對照檔：" in labels
    assert "本次寫入版本名稱：" in labels
    assert "先檢查，不寫入" in buttons
    assert "確認後寫入月營收" in buttons
    assert all("Dry-run" not in text for text in labels + buttons)
    assert all("SQLite" not in text for text in labels + buttons)
    assert all("source_version" not in text for text in labels + buttons)


def test_monthly_revenue_tab_requires_confirmation_before_apply(monkeypatch):
    from ui_qt.views import update_view

    monkeypatch.setattr(update_view, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view.monthly_revenue_snapshot_input.setText("snapshot.csv")
    view.monthly_revenue_availability_input.setText("availability.csv")

    view._execute_monthly_revenue_backfill(apply=True)

    assert any(call[0] == "apply_mops_monthly_revenue_backfill" for call in view.update_service.calls)

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
        "update_tpex_daily_price",
        "sync_source_to_sqlite",
        "update_market",
        "sync_source_to_sqlite",
        "update_industry",
        "sync_source_to_sqlite",
        "update_broker_branch",
        "sync_source_to_sqlite",  # broker_branch_files 同步
        "check_data_overview",
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
        return ["daily_prices", "broker_flows"]

    def get_distinct_column_values(self, table_name, column_name, limit=500):
        if table_name == "broker_flows" and column_name == "分點名稱":
            return ["凱基台北", "美商高盛"]
        return []
        
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
    assert not widget.date_input.calendarPopup()
    assert widget.date_input.text().strip() == ""

    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") is None

    widget._set_single_date_today()
    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") == QDate.currentDate().toString("yyyy-MM-dd")

    widget.date_input.setDate(QDate(2026, 5, 29))
    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") == "2026-05-29"


def test_sqlite_inspector_date_pickers_default_blank_but_calendar_opens_today():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    today = QDate.currentDate()

    assert widget._date_filter_value(widget.date_input) == ""
    assert widget._date_filter_value(widget.start_date_input) == ""
    assert widget._date_filter_value(widget.end_date_input) == ""
    assert widget.date_input.text().strip() == ""
    assert widget._calendar_page_date(widget.date_input) == today
    assert widget._calendar_page_date(widget.start_date_input) == today
    assert widget._calendar_page_date(widget.end_date_input) == today

    widget._set_single_date_today()
    widget.start_date_input.setDate(QDate(2026, 5, 1))
    widget.end_date_input.setDate(QDate(2026, 5, 29))
    widget._clear_all_dates()

    assert widget._date_filter_value(widget.date_input) == ""
    assert widget._date_filter_value(widget.start_date_input) == ""
    assert widget._date_filter_value(widget.end_date_input) == ""


def test_sqlite_inspector_date_pickers_have_enough_width_for_full_dates():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    widget = SqliteInspectorWidget(FakeInspectorService(total=250))

    assert widget.date_input.minimumWidth() >= 122
    assert widget.start_date_input.minimumWidth() >= 122
    assert widget.end_date_input.minimumWidth() >= 122
    assert widget.date_input.maximumWidth() <= 132
    assert widget.start_date_input.maximumWidth() <= 132
    assert widget.end_date_input.maximumWidth() <= 132
    calendar_button_texts = [button.text() for button in widget.findChildren(QPushButton)]
    assert calendar_button_texts.count("日曆") >= 3


def test_sqlite_inspector_stock_filters_are_wide_enough_for_placeholders():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    widget = SqliteInspectorWidget(FakeInspectorService(total=250))

    assert widget.stock_code_input.minimumWidth() >= 112
    assert widget.stock_code_input.maximumWidth() >= 112
    assert widget.stock_name_input.minimumWidth() >= 145
    assert widget.stock_name_input.maximumWidth() >= 145


def test_sqlite_inspector_broker_branch_filter_uses_dropdown(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None

    widget._on_table_changed("broker_flows")
    assert widget.broker_branch_combo.findText("凱基台北") >= 0
    assert widget.broker_branch_combo.maxVisibleItems() >= 20
    assert widget.broker_branch_dropdown_btn.text() == "展開"
    assert "#f8fafc" in widget.broker_branch_dropdown_btn.styleSheet()
    assert widget.broker_branch_dropdown_btn.minimumHeight() >= 26

    widget.broker_branch_combo.setCurrentText("凱基台北")
    widget._request_page(load_schema=False)

    assert service.last_query.get("broker_branch") == "凱基台北"


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





def test_pandas_table_model_handles_duplicate_display_columns_without_series_error():
    from ui_qt.models.pandas_table_model import PandasTableModel

    df = pd.DataFrame([[1, 2]], columns=["漲跌", "漲跌"])
    model = PandasTableModel(df)

    assert model.data(model.index(0, 0)) == "1"
    assert model.data(model.index(0, 1)) == "2"


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



from types import SimpleNamespace

from ui_qt.views.update.update_all_coordinator import run_update_all


class _Service:
    def __init__(self, *, use_sqlite: bool, daily_result=None) -> None:
        self.config = SimpleNamespace(use_sqlite=use_sqlite)
        self.calls: list[tuple] = []
        self.daily_result = daily_result or {"success": True}

    def __getattr__(self, name):
        def operation(*args, **kwargs):
            self.calls.append((name, *args))
            if name == "update_daily":
                return self.daily_result
            return {"success": True}

        return operation


def _run(mode: str, *, use_sqlite: bool = True, daily_result=None):
    service = _Service(use_sqlite=use_sqlite, daily_result=daily_result)
    progress: list[tuple[str, int]] = []
    result = run_update_all(
        mode=mode,
        start_date="2026-07-01",
        end_date="2026-07-10",
        update_service=service,
        get_overview_status=lambda: {"success": True},
        update_tpex_daily_prices=lambda start, end, skipped_dates=None: {"success": True},
        run_incremental_technical=lambda callback: {"success": True},
        tpex_warning_messages=lambda result: [],
        progress_callback=lambda message, pct: progress.append((message, pct)),
    )
    return service, progress, result


def test_quick_update_contract_skips_large_merges_and_syncs_source_files() -> None:
    service, progress, result = _run("quick")
    call_names = [call[0] for call in service.calls]

    assert result["success"] is True
    assert result["message"] == "快速更新所有數據完成"
    assert "merge_daily_data" not in call_names
    assert "merge_broker_branch_data" not in call_names
    assert ("sync_source_to_sqlite", "broker_branch_files", "2026-07-01", "2026-07-10") in service.calls
    assert progress[-1] == ("快速更新所有數據完成", 100)


def test_safe_update_contract_keeps_merge_and_sqlite_order() -> None:
    service, progress, result = _run("safe")
    call_names = [call[0] for call in service.calls]

    assert result["success"] is True
    assert call_names.index("merge_daily_data") < call_names.index("merge_broker_branch_data")
    assert result["message"] == "安全更新所有數據完成"
    assert progress[-1] == ("安全更新所有數據完成", 100)


def test_safe_update_maps_merge_progress_into_outer_range() -> None:
    service = _Service(use_sqlite=False)
    progress: list[tuple[str, int]] = []

    def merge_daily_data(*, force_all=False, progress_callback=None, cancel_callback=None):
        if progress_callback is not None:
            progress_callback("每日合併檔案", 0)
            progress_callback("每日合併檔案", 100)
        return {"success": True}

    def merge_broker_branch_data(*, progress_callback=None, cancel_callback=None):
        if progress_callback is not None:
            progress_callback("券商分點合併", 0)
            progress_callback("券商分點合併", 100)
        return {"success": True}

    service.merge_daily_data = merge_daily_data
    service.merge_broker_branch_data = merge_broker_branch_data

    result = run_update_all(
        mode="safe",
        start_date="2026-07-01",
        end_date="2026-07-10",
        update_service=service,
        get_overview_status=lambda: {"success": True},
        update_tpex_daily_prices=lambda start, end, skipped_dates=None: {"success": True},
        run_incremental_technical=lambda callback: {"success": True},
        tpex_warning_messages=lambda result: [],
        progress_callback=lambda message, pct: progress.append((message, pct)),
    )

    assert result["success"] is True
    assert ("每日合併檔案", 55) in progress
    assert ("每日合併檔案", 62) in progress
    assert ("券商分點合併", 69) in progress
    assert ("券商分點合併", 76) in progress
    percentages = [pct for _msg, pct in progress]
    assert all(earlier <= later for earlier, later in zip(percentages, percentages[1:]))


def test_quick_update_continues_after_twse_no_data_skip() -> None:
    service, _progress, result = _run(
        "quick",
        daily_result={"success": True, "no_data_skipped_dates": ["2026-07-10"]},
    )

    assert result["success"] is True
    assert any("TWSE 上游查無資料" in warning for warning in result["warnings"])
    assert ("sync_source_to_sqlite", "daily_price_files", "2026-07-01", "2026-07-10") in service.calls


def test_quick_update_does_not_label_existing_file_skip_as_twse_no_data() -> None:
    _service, _progress, result = _run(
        "quick",
        daily_result={"success": True, "skipped_dates": ["2026-07-10"]},
    )

    assert result["success"] is True
    assert result["warnings"] == []


def test_update_all_maps_nested_technical_progress_into_outer_range() -> None:
    service = _Service(use_sqlite=True)
    progress: list[tuple[str, int]] = []

    def run_technical(callback):
        callback("技術指標局部進度", 5)
        callback("技術指標局部進度", 100)
        return {"success": True}

    result = run_update_all(
        mode="quick",
        start_date="2026-07-01",
        end_date="2026-07-10",
        update_service=service,
        get_overview_status=lambda: {"success": True},
        update_tpex_daily_prices=lambda start, end, skipped_dates=None: {"success": True},
        run_incremental_technical=run_technical,
        tpex_warning_messages=lambda result: [],
        progress_callback=lambda message, pct: progress.append((message, pct)),
    )

    assert result["success"] is True
    assert ("技術指標局部進度", 89) in progress
    assert ("技術指標局部進度", 99) in progress
    percentages = [pct for _msg, pct in progress]
    assert all(earlier <= later for earlier, later in zip(percentages, percentages[1:]))


def test_update_all_rejects_nested_status_error_after_steps() -> None:
    service = _Service(use_sqlite=True)
    overview_results = iter(
        [
            {"success": True},
            {"daily_data": {"status": "error: no such table"}},
        ]
    )

    result = run_update_all(
        mode="quick",
        start_date="2026-07-01",
        end_date="2026-07-10",
        update_service=service,
        get_overview_status=lambda: next(overview_results),
        update_tpex_daily_prices=lambda start, end, skipped_dates=None: {"success": True},
        run_incremental_technical=lambda callback: {"success": True},
        tpex_warning_messages=lambda result: [],
    )

    assert result["success"] is False
    assert result["failed_step"] == "刷新資料狀態"
    assert result["status_failures"][0]["source"] == "daily_data"


def test_update_all_stops_before_writes_when_initial_status_has_nested_error() -> None:
    service = _Service(use_sqlite=True)
    calls: list[str] = []

    def overview_with_error():
        return {
            "success": True,
            "daily_data": {
                "status": "error: database is not readable",
                "message": "database is not readable",
            },
        }

    result = run_update_all(
        mode="quick",
        start_date="2026-07-01",
        end_date="2026-07-10",
        update_service=service,
        get_overview_status=overview_with_error,
        update_tpex_daily_prices=lambda start, end, skipped_dates=None: calls.append("tpex") or {"success": True},
        run_incremental_technical=lambda callback: calls.append("technical") or {"success": True},
        tpex_warning_messages=lambda result: [],
    )

    assert result["success"] is False
    assert result["failed_step"] == "檢查資料狀態"
    assert "已停止寫入" in result["message"]
    assert result["status_failures"][0]["source"] == "daily_data"
    assert calls == []
    assert service.calls == []

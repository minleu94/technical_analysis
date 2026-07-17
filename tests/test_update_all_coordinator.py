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

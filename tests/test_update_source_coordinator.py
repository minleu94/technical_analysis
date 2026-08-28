from types import SimpleNamespace

from ui_qt.views.update.source_update_coordinator import SourceUpdateRequest


class _Service:
    def __init__(self):
        self.config = SimpleNamespace()
        self.calls = []

    def update_daily(self, start, end):
        self.calls.append(("update_daily", start, end))
        return {"success": True, "message": "TWSE", "updated_dates": [start]}

    def sync_source_to_sqlite(self, source, start, end):
        self.calls.append(("sync", source, start, end))
        return {"success": True, "synced_records": 12}

    def calculate_technical_indicators(self, **kwargs):
        self.calls.append(("indicators", kwargs))
        return {"success": True}

    def update_market(self, start, end):
        self.calls.append(("market", start, end))
        return {"success": True}


class _FailedTWSEService(_Service):
    def update_daily(self, start, end):
        self.calls.append(("update_daily", start, end))
        return {
            "success": False,
            "message": "TWSE transport error",
            "failed_dates": [start],
        }


def test_daily_source_update_keeps_twse_tpex_sqlite_indicator_order() -> None:
    service = _Service()
    progress = []
    request = SourceUpdateRequest("daily", "2026-07-01", "2026-07-10")

    result = request.execute(
        service,
        update_tpex_daily_prices=lambda start, end: {
            "success": True,
            "message": "TPEX",
            "updated_dates": [end],
        },
        tpex_warning_messages=lambda result: [],
        progress_callback=lambda message, pct: progress.append((message, pct)),
    )

    assert [call[0] for call in service.calls] == ["update_daily", "sync", "indicators"]
    assert result["success"] is True
    assert result["updated_dates"] == ["2026-07-01", "2026-07-10"]
    assert result["synced_records"] == 12
    assert result["sqlite_sync"] == {
        "success": True,
        "synced_records": 12,
        "source": "daily_price_files",
        "table": "daily_prices",
    }
    assert progress[:3] == [
        ("更新 TWSE 每日股價", 15),
        ("更新 TPEX 每日收盤行情", 30),
        ("同步每日股價到 SQLite", 55),
    ]


def test_simple_source_update_maps_market_without_daily_side_effects() -> None:
    service = _Service()
    result = SourceUpdateRequest("market", "2026-07-01", "2026-07-10").execute(
        service,
        update_tpex_daily_prices=lambda *_: (_ for _ in ()).throw(AssertionError()),
        tpex_warning_messages=lambda _: [],
    )

    assert result == {"success": True}
    assert service.calls == [("market", "2026-07-01", "2026-07-10")]


def test_daily_source_update_maps_technical_progress_and_finishes_at_100() -> None:
    service = _Service()
    progress = []

    def calculate_technical_indicators(**kwargs):
        callback = kwargs.get("progress_callback")
        if callback:
            callback("technical inner", 5)
            callback("technical inner", 100)
        return {"success": True, "message": "technical ok"}

    service.calculate_technical_indicators = calculate_technical_indicators
    result = SourceUpdateRequest("daily", "2026-07-01", "2026-07-10").execute(
        service,
        update_tpex_daily_prices=lambda start, end: {"success": True, "message": "TPEX"},
        tpex_warning_messages=lambda result: [],
        progress_callback=lambda message, percentage: progress.append((message, percentage)),
    )

    assert result["success"] is True
    assert ("technical inner", 86) in progress
    assert ("technical inner", 99) in progress
    assert progress[-1] == ("每日資料更新完成", 100)


def test_daily_source_update_maps_twse_and_tpex_api_progress() -> None:
    service = _Service()
    progress = []

    def update_daily(start, end, progress_callback=None):
        service.calls.append(("update_daily", start, end))
        if progress_callback:
            progress_callback("TWSE API 下載 20260702（1/2）", 50)
        return {"success": True, "message": "TWSE"}

    def update_tpex(start, end, progress_callback=None):
        if progress_callback:
            progress_callback("TPEX API 下載 20260702（1/2）", 50)
        return {"success": True, "message": "TPEX"}

    service.update_daily = update_daily
    request = SourceUpdateRequest("daily", "2026-07-01", "2026-07-10")
    result = request.execute(
        service,
        update_tpex_daily_prices=update_tpex,
        tpex_warning_messages=lambda _result: [],
        progress_callback=lambda message, percentage: progress.append(
            (message, percentage)
        ),
    )

    assert result["success"] is True
    assert ("TWSE API 下載 20260702（1/2）", 23) in progress
    assert ("TPEX API 下載 20260702（1/2）", 40) in progress


def test_daily_source_update_stops_after_explicit_twse_failure() -> None:
    service = _FailedTWSEService()
    progress = []

    result = SourceUpdateRequest("daily", "2026-07-01", "2026-07-10").execute(
        service,
        update_tpex_daily_prices=lambda start, end: (_ for _ in ()).throw(
            AssertionError("TPEX must not run after TWSE failure")
        ),
        tpex_warning_messages=lambda result: [],
        progress_callback=lambda message, percentage: progress.append((message, percentage)),
    )

    assert result["success"] is False
    assert any("TWSE 每日股價缺少日期" in warning for warning in result["warnings"])
    assert [call[0] for call in service.calls] == ["update_daily"]
    assert progress == [
        ("更新 TWSE 每日股價", 15),
        ("TWSE 每日股價更新失敗，已停止後續寫入", 30),
    ]

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

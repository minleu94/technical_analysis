from types import SimpleNamespace

from scripts.run_tpex_full_refresh_and_technical import (
    _run_tpex_parallel,
    _should_skip_technical_indicators,
)


def test_background_refresh_skips_technical_when_indicator_is_current():
    status = {
        "daily_data": {"latest_date": "2026-06-18"},
        "technical_indicators": {"latest_date": "2026-06-18"},
    }

    should_skip, message = _should_skip_technical_indicators(status, force_all=False)

    assert should_skip is True
    assert "2026-06-18" in message


def test_background_refresh_calculates_technical_when_indicator_is_stale():
    status = {
        "daily_data": {"latest_date": "2026-06-18"},
        "technical_indicators": {"latest_date": "2026-06-17"},
    }

    should_skip, _message = _should_skip_technical_indicators(status, force_all=False)

    assert should_skip is False


def test_background_refresh_force_all_disables_technical_skip():
    status = {
        "daily_data": {"latest_date": "2026-06-18"},
        "technical_indicators": {"latest_date": "2026-06-18"},
    }

    should_skip, _message = _should_skip_technical_indicators(status, force_all=True)

    assert should_skip is False


def test_background_refresh_does_not_skip_when_technical_coverage_lags():
    status = {
        "daily_data": {"latest_date": "2026-07-06"},
        "technical_indicators": {"latest_date": "2026-07-06"},
    }

    should_skip, message = _should_skip_technical_indicators(
        status,
        force_all=False,
        technical_coverage={
            "success": True,
            "is_current": False,
            "daily_latest_date": "20260706",
            "eligible_stock_count": 2,
            "covered_stock_count": 1,
        },
    )

    assert should_skip is False
    assert "1/2" in message


def test_parallel_tpex_refresh_fails_when_pending_date_is_missing(tmp_path):
    (tmp_path / "20260703.csv").write_text(
        "日期,證券代號,證券名稱,收盤價\n20260703,3207,耀勝,42.5\n",
        encoding="utf-8-sig",
    )

    class FailingSource:
        def update_for_date(self, date_key):
            assert date_key == "20260706"
            return SimpleNamespace(
                success=False,
                source_date=None,
                row_count=0,
                skipped_count=0,
                message="remote disconnected",
            )

    class FakeService:
        def _iter_weekday_date_keys(self, start_date, end_date):
            return ["20260703", "20260706"]

        def _create_tpex_daily_price_source(self):
            return FailingSource()

    state = {"steps": {}}
    result = _run_tpex_parallel(
        FakeService(),
        SimpleNamespace(tpex_daily_price_dir=tmp_path),
        tmp_path / "state.json",
        state,
        start_date="2026-07-03",
        end_date="2026-07-06",
        workers=1,
    )

    assert result["success"] is False
    assert result["failed_dates"] == ["20260706"]
    assert result["warnings"] == ["TPEX 每日股價缺少日期：20260706"]

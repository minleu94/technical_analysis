from scripts.run_tpex_full_refresh_and_technical import _should_skip_technical_indicators


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

from datetime import date
import sqlite3
from unittest.mock import MagicMock, patch

from data_module.official_trading_calendar import OfficialTradingCalendar


def test_official_trading_calendar_uses_market_indices_evidence(tmp_path):
    db_path = tmp_path / "market.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE market_indices (trade_date TEXT, index_name TEXT)")
        conn.execute("INSERT INTO market_indices VALUES ('20240722', 'TAIEX')")

    is_td, reason = OfficialTradingCalendar(db_path).is_official_trading_day(
        date(2024, 7, 22), allow_online_probe=False
    )

    assert is_td is True
    assert reason == "twstock_db_market_indices_evidence"


def test_official_trading_calendar_missing_evidence_is_unknown(tmp_path):
    is_td, reason = OfficialTradingCalendar(tmp_path / "missing.db").is_official_trading_day(
        date(2024, 7, 22), allow_online_probe=False
    )

    assert is_td is None
    assert reason == "lacks_official_evidence"


def _official_response(rows: list[dict[str, str]]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = rows
    return response


def test_official_trading_calendar_weekend_is_closed_without_online_request(
    tmp_path,
):
    with patch("data_module.official_trading_calendar.safe_request") as mock_req:
        is_td, reason = OfficialTradingCalendar(tmp_path / "missing.db").is_official_trading_day(
            date(2026, 8, 1), allow_online_probe=True
        )

    assert is_td is False
    assert reason == "weekend_closed"
    mock_req.assert_not_called()


def test_weekday_absent_from_valid_official_schedule_is_open(tmp_path):
    with patch(
        "data_module.official_trading_calendar.safe_request",
        return_value=_official_response(
            [
                {
                    "Name": "中華民國開國紀念日",
                    "Date": "1150101",
                    "Description": "依規定放假一日。",
                }
            ]
        ),
    ) as request:
        is_td, reason = OfficialTradingCalendar(
            tmp_path / "missing.db"
        ).is_official_trading_day(date(2026, 7, 29))

    assert is_td is True
    assert reason == "twse_holiday_schedule_open"
    assert request.call_args.kwargs["params"] == {"queryYear": "115"}


def test_weekday_listed_as_holiday_is_closed(tmp_path):
    with patch(
        "data_module.official_trading_calendar.safe_request",
        return_value=_official_response(
            [
                {
                    "Name": "和平紀念日補假",
                    "Date": "1150302",
                    "Description": "停止交易。",
                }
            ]
        ),
    ):
        is_td, reason = OfficialTradingCalendar(
            tmp_path / "missing.db"
        ).is_official_trading_day(date(2026, 3, 2))

    assert is_td is False
    assert reason == "twse_holiday_schedule_closed"


def test_explicit_start_last_resume_or_normal_trading_row_is_open(tmp_path):
    calendar = OfficialTradingCalendar(tmp_path / "missing.db")
    with patch(
        "data_module.official_trading_calendar.safe_request",
        return_value=_official_response(
            [
                {
                    "Name": "農曆春節前最後交易日",
                    "Date": "1150211",
                    "Description": "農曆春節前最後交易。",
                },
                {
                    "Name": "農曆春節後開始交易日",
                    "Date": "1150223",
                    "Description": "恢復交易。",
                },
            ]
        ),
    ):
        before, before_reason = calendar.is_official_trading_day(
            date(2026, 2, 11)
        )
        after, after_reason = calendar.is_official_trading_day(
            date(2026, 2, 23)
        )

    assert before is True
    assert after is True
    assert before_reason == "twse_holiday_schedule_explicit_open"
    assert after_reason == "twse_holiday_schedule_explicit_open"


def test_official_trading_calendar_request_failure_is_unknown_and_cached(
    tmp_path,
):
    with patch(
        "data_module.official_trading_calendar.safe_request",
        side_effect=RuntimeError("service temporarily unavailable"),
    ) as request:
        calendar = OfficialTradingCalendar(tmp_path / "missing.db")
        first = calendar.is_official_trading_day(date(2026, 7, 29))
        second = calendar.is_official_trading_day(date(2026, 7, 30))

    assert first == (None, "twse_holiday_schedule_unavailable")
    assert second == (None, "twse_holiday_schedule_unavailable")
    assert request.call_count == 1


def test_malformed_official_schedule_fails_closed(tmp_path):
    with patch(
        "data_module.official_trading_calendar.safe_request",
        return_value=_official_response([{"unexpected": "payload"}]),
    ):
        result = OfficialTradingCalendar(
            tmp_path / "missing.db"
        ).is_official_trading_day(date(2026, 7, 29))

    assert result == (None, "twse_holiday_schedule_unavailable")

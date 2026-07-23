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
        date(2024, 7, 21), allow_online_probe=False
    )

    assert is_td is None
    assert reason == "lacks_official_evidence"


def test_official_trading_calendar_online_closed_probe(tmp_path):
    with patch("data_module.official_trading_calendar.safe_request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"stat": "很抱歉，沒有符合條件的資料！"}
        mock_req.return_value = mock_resp

        is_td, reason = OfficialTradingCalendar(tmp_path / "missing.db").is_official_trading_day(
            date(2099, 1, 1), allow_online_probe=True
        )

    assert is_td is False
    assert reason == "twse_official_closed_or_holiday"


def test_official_trading_calendar_unexpected_online_status_is_unknown(tmp_path):
    with patch("data_module.official_trading_calendar.safe_request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"stat": "service temporarily unavailable"}
        mock_req.return_value = mock_resp

        is_td, reason = OfficialTradingCalendar(tmp_path / "missing.db").is_official_trading_day(
            date(2099, 1, 1), allow_online_probe=True
        )

    assert is_td is None
    assert reason == "lacks_official_evidence"

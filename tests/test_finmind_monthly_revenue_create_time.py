from __future__ import annotations

import json
from datetime import date

from data_module.finmind_monthly_revenue_create_time import (
    decode_dpapi_hex_token,
    harvest_finmind_monthly_revenue_create_time,
    load_stock_codes_from_raw_monthly_revenue_dir,
)


def test_decode_dpapi_hex_token_supports_utf16le_payload() -> None:
    protected = b"cipher"
    plain = "token-abc".encode("utf-16le")

    token = decode_dpapi_hex_token(protected.hex(), unprotect=lambda payload: plain)

    assert token == "token-abc"


def test_load_stock_codes_from_raw_monthly_revenue_dir_reads_existing_csv_names(tmp_path) -> None:
    (tmp_path / "2330_monthly_revenue.csv").write_text("", encoding="utf-8")
    (tmp_path / "3207_monthly_revenue.csv").write_text("", encoding="utf-8")
    (tmp_path / "README.txt").write_text("", encoding="utf-8")

    assert load_stock_codes_from_raw_monthly_revenue_dir(tmp_path) == ("2330", "3207")


def test_harvest_finmind_create_time_groups_rows_and_never_prints_token(tmp_path) -> None:
    responses = {
        "2330": [
            {
                "stock_id": "2330",
                "date": "2026-04-01",
                "revenue_year": 2026,
                "revenue_month": 4,
                "revenue": 195211000,
                "create_time": "2026-05-08",
            }
        ],
        "3207": [
            {
                "stock_id": "3207",
                "date": "2026-04-01",
                "revenue_year": 2026,
                "revenue_month": 4,
                "revenue": 1234,
                "create_time": "2026-05-09",
            }
        ],
    }

    def fake_fetch(stock_code: str, start_date: str, end_date: str, token: str) -> list[dict]:
        assert token == "secret-token"
        return responses[stock_code]

    result = harvest_finmind_monthly_revenue_create_time(
        stock_codes=("2330", "3207"),
        start_date="2026-04-01",
        end_date="2026-05-31",
        token="secret-token",
        fetch_rows=fake_fetch,
        output_dir=tmp_path,
        fetch_date=date(2026, 6, 16),
        sleep_seconds=0,
    )

    assert len(result.rows) == 2
    assert result.rows[0]["period"] == "2026-04"
    assert result.rows[0]["available_date_candidate"] == "2026-05-09"
    assert result.group_rows == [
        {"create_time": "2026-05-08", "stock_count": "1", "stock_codes": "2330"},
        {"create_time": "2026-05-09", "stock_count": "1", "stock_codes": "3207"},
    ]
    assert result.state["completed_stock_codes"] == ["2330", "3207"]
    assert "secret-token" not in result.to_markdown()


def test_harvest_finmind_create_time_resume_skips_completed_codes(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps({"completed_stock_codes": ["2330"], "failed_stock_codes": []}),
        encoding="utf-8",
    )
    fetched: list[str] = []

    def fake_fetch(stock_code: str, start_date: str, end_date: str, token: str) -> list[dict]:
        fetched.append(stock_code)
        return []

    result = harvest_finmind_monthly_revenue_create_time(
        stock_codes=("2330", "3207"),
        start_date="2026-04-01",
        end_date="2026-05-31",
        token="secret-token",
        fetch_rows=fake_fetch,
        output_dir=tmp_path,
        state_file=state_file,
        resume=True,
        fetch_date=date(2026, 6, 16),
        sleep_seconds=0,
    )

    assert fetched == ["3207"]
    assert result.requested_stock_count == 2
    assert result.fetched_stock_count == 1

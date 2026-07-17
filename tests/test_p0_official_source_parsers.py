from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from data_module.p0_official_source_parsers import (
    RawFetchEnvelope,
    parse_tdcc_shareholding,
    parse_twse_credit,
    parse_twse_institutional,
)
from data_module.official_phase3c_fetcher import (
    fetch_credit_transactions,
    fetch_institutional_flows,
    fetch_tdcc_shareholding,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "p0_official_sources"
FETCHED_AT = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)


def _envelope(filename: str, *, source_id: str, source_version: str) -> RawFetchEnvelope:
    return RawFetchEnvelope(
        source_id=source_id,
        source_version=source_version,
        endpoint_id=source_id,
        request_parameters={"fixture": filename},
        fetched_at=FETCHED_AT,
        http_status=200,
        http_headers={"Content-Type": "application/json"},
        payload=(FIXTURE_ROOT / filename).read_bytes(),
    )


def test_twse_institutional_parser_normalizes_aliases_and_publication_evidence() -> None:
    result = parse_twse_institutional(
        _envelope(
            "twse_institutional.json",
            source_id="twse_institutional",
            source_version="twse-T86.v1",
        )
    )

    assert result.raw_row_count == 1
    assert result.accepted_row_count == 1
    row = result.accepted[0].to_dict()
    assert row["symbol"] == "2330"
    assert row["observation_date"] == "2026-07-10"
    assert row["available_at"] == "2026-07-10T17:30:00+08:00"
    assert row["quality"] == "verified"
    assert row["quantities"]["foreign_net_shares"] == 1200
    assert "stock_code" not in row
    assert "decision_date" not in row


def test_twse_credit_parser_preserves_missing_as_missing_not_zero() -> None:
    result = parse_twse_credit(
        _envelope(
            "twse_credit.json",
            source_id="twse_credit",
            source_version="twse-MI_MARGN.v1",
        )
    )

    assert result.accepted_row_count == 1
    quantities = result.accepted[0].to_dict()["quantities"]
    assert quantities["margin_balance_shares"] == 2500
    assert "short_balance_shares" not in quantities
    assert "missing_quantity:short_balance_shares" in result.accepted[0].warnings


def test_twse_credit_parser_accepts_current_duplicate_column_schema() -> None:
    payload = {
        "date": "20260716",
        "tables": [
            {
                "fields": [
                    "代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
                    "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額",
                    "次一營業日限額", "資券互抵", "註記",
                ],
                "data": [["2330", "台積電", "100", "20", "1", "400", "479", "999", "3", "4", "0", "20", "24", "999", "0", ""]],
            }
        ],
    }
    envelope = RawFetchEnvelope(
        source_id="twse_credit",
        source_version="twse-MI_MARGN.v1",
        endpoint_id="twse:MI_MARGN",
        request_parameters={"date": "20260716"},
        fetched_at=FETCHED_AT,
        http_status=200,
        http_headers={"Content-Type": "application/json"},
        payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )

    result = parse_twse_credit(envelope)

    assert result.raw_row_count == 1
    assert result.accepted_row_count == 1
    assert result.quarantine_row_count == 0
    assert result.accepted[0].to_dict()["quantities"] == {
        "margin_balance_shares": 479,
        "margin_purchase_shares": 100,
        "short_balance_shares": 24,
        "short_sale_shares": 4,
    }


def test_tdcc_period_end_is_not_promoted_to_publication_time() -> None:
    result = parse_tdcc_shareholding(
        _envelope(
            "tdcc_shareholding.csv",
            source_id="tdcc_shareholding",
            source_version="tdcc-1-5.v1",
        )
    )

    assert result.accepted_row_count == 1
    row = result.accepted[0].to_dict()
    assert row["observation_date"] == "2026-07-10"
    assert row["publication_at"] is None
    assert row["available_at"] == FETCHED_AT.isoformat()
    assert row["quality"] == "degraded"
    assert "official_publication_timestamp_missing" in row["warnings"]


def test_malformed_row_is_quarantined_and_conserved() -> None:
    result = parse_twse_institutional(
        _envelope(
            "twse_institutional_malformed.json",
            source_id="twse_institutional",
            source_version="twse-T86.v1",
        )
    )

    assert result.raw_row_count == 1
    assert result.accepted_row_count == 0
    assert result.quarantine_row_count == 1
    assert result.blocked_row_count == 0
    assert result.quarantine[0].reason_code == "malformed_required_quantity"


def test_legacy_institutional_fetcher_does_not_emit_decision_date_plus_one() -> None:
    twse_response = MagicMock()
    twse_response.json.return_value = {
        "stat": "OK",
        "fields": [
            "證券代號",
            "外陸資買進股數(不含外資自營商)",
            "外陸資賣出股數(不含外資自營商)",
            "外陸資買賣超股數(不含外資自營商)",
        ],
        "data": [["2330", "2,000", "800", "1,200"]],
    }
    tpex_response = MagicMock()
    tpex_response.json.return_value = {"aaData": []}

    with patch(
        "data_module.official_phase3c_fetcher.safe_request",
        side_effect=[twse_response, tpex_response],
    ), patch("data_module.official_phase3c_fetcher.time.sleep"):
        frame = fetch_institutional_flows(datetime(2026, 7, 10).date())

    row = frame.iloc[0].to_dict()
    assert row["available_date"] is None
    assert row["publication_at"] is None
    assert row["available_at"] == row["first_observed_at"]
    assert datetime.fromisoformat(row["available_at"]).tzinfo is not None
    assert row["quality"] == "degraded"


def test_legacy_tdcc_fetcher_does_not_emit_period_end_plus_three() -> None:
    response = MagicMock()
    response.text = (FIXTURE_ROOT / "tdcc_shareholding.csv").read_text(encoding="utf-8")

    with patch(
        "data_module.official_phase3c_fetcher.safe_request",
        return_value=response,
    ):
        frame = fetch_tdcc_shareholding(datetime(2026, 7, 10).date())

    row = frame.iloc[0].to_dict()
    assert row["available_date"] is None
    assert row["publication_at"] is None
    assert row["available_at"] == row["first_observed_at"]
    assert datetime.fromisoformat(row["available_at"]).tzinfo is not None
    assert row["quality"] == "degraded"


def test_legacy_credit_fetcher_does_not_emit_decision_date_plus_one() -> None:
    twse_response = MagicMock()
    twse_response.json.return_value = {
        "stat": "OK",
        "tables": [{
            "fields": ["證券代號", "融資買進", "融資今日餘額", "融券賣出", "融券今日餘額"],
            "data": [["2330", "100", "2,500", "20", "400"]],
        }],
    }
    tpex_response = MagicMock()
    tpex_response.json.return_value = {"aaData": []}

    with patch(
        "data_module.official_phase3c_fetcher.safe_request",
        side_effect=[twse_response, tpex_response],
    ), patch("data_module.official_phase3c_fetcher.time.sleep"):
        frame = fetch_credit_transactions(datetime(2026, 7, 10).date())

    row = frame.iloc[0].to_dict()
    assert row["available_date"] is None
    assert row["publication_at"] is None
    assert row["available_at"] == row["first_observed_at"]
    assert datetime.fromisoformat(row["available_at"]).tzinfo is not None
    assert row["quality"] == "degraded"

from datetime import date
from pathlib import Path
import json
import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_module.p0_candidate_repository import ProductionPathRejectedError
from data_module.phase3c_backfill_runner import APPLY_CONFIRM_TOKEN
from scripts.update_phase3c_candidates import (
    run_bounded_official_probe,
    update_phase3c_candidates,
)


@pytest.fixture
def mock_fetchers():
    with (
        patch(
            "scripts.update_phase3c_candidates.fetch_institutional_flows"
        ) as mock_inst,
        patch(
            "scripts.update_phase3c_candidates.fetch_credit_transactions"
        ) as mock_credit,
        patch(
            "scripts.update_phase3c_candidates.fetch_tdcc_shareholding"
        ) as mock_tdcc,
    ):
        mock_inst.return_value = pd.DataFrame(
            [
                {
                    "stock_code": "2330",
                    "decision_date": "2026-07-08",
                    "available_date": "2026-07-09",
                    "source_version": "twse-official-T86",
                    "quality": "degraded",
                    "foreign_investor_buy": 100,
                    "foreign_investor_sell": 50,
                    "foreign_investor_net": 50,
                    "investment_trust_buy": 0,
                    "investment_trust_sell": 0,
                    "investment_trust_net": 0,
                    "dealer_buy": 0,
                    "dealer_sell": 0,
                    "dealer_net": 0,
                }
            ]
        )
        mock_credit.return_value = pd.DataFrame(
            [
                {
                    "stock_code": "2330",
                    "decision_date": "2026-07-08",
                    "available_date": "2026-07-09",
                    "source_version": "twse-official-MI_MARGN",
                    "quality": "degraded",
                    "margin_purchase": 10,
                    "margin_balance": 100,
                    "short_sale": 5,
                    "short_balance": 50,
                    "financing": None,
                    "securities_lending": None,
                }
            ]
        )
        mock_tdcc.return_value = pd.DataFrame(
            [
                {
                    "stock_code": "2330",
                    "decision_date": "2026-07-08",
                    "available_date": "2026-07-11",
                    "source_version": "tdcc-official-od-1-5",
                    "quality": "observed",
                    "shareholding_tiers": "weekly_distribution_available",
                    "large_holder_ratio_bp": 8000,
                    "retail_holder_ratio_bp": 500,
                    "dispersion_index_bp": -7500,
                }
            ]
        )
        yield mock_inst, mock_credit, mock_tdcc


def test_dry_run_does_not_create_db(tmp_path, mock_fetchers):
    db_path = tmp_path / "test_twstock.db"

    with (
        patch("scripts.update_phase3c_candidates.DBManager") as mock_db_manager,
        patch("scripts.update_phase3c_candidates.TWStockConfig") as mock_config,
    ):
        update_phase3c_candidates(
            date(2026, 7, 8),
            dry_run=True,
            db_path=str(db_path),
            rate_limit_seconds=0,
        )

        assert not db_path.exists()
        mock_db_manager.assert_not_called()
        mock_config.assert_not_called()


def test_apply_rejects_data_root_descendant_before_initialization(
    tmp_path, mock_fetchers, monkeypatch
):
    data_root = tmp_path / "formal-data"
    db_path = data_root / "candidate" / "working.sqlite"
    db_path.parent.mkdir(parents=True)
    db_path.touch()
    monkeypatch.setenv("DATA_ROOT", str(data_root))

    with (
        patch("scripts.update_phase3c_candidates.DBManager") as mock_db_manager,
        patch("scripts.update_phase3c_candidates.TWStockConfig") as mock_config,
    ):
        with pytest.raises(ProductionPathRejectedError):
            update_phase3c_candidates(
                date(2026, 7, 8),
                dry_run=False,
                db_path=str(db_path),
                confirm_token=APPLY_CONFIRM_TOKEN,
                rate_limit_seconds=0,
            )

        mock_db_manager.assert_not_called()
        mock_config.assert_not_called()


def test_apply_without_confirm_token_aborts(tmp_path, mock_fetchers):
    db_path = tmp_path / "non_existent.db"

    with pytest.raises(ValueError, match="confirm token"):
        update_phase3c_candidates(
            date(2026, 7, 8),
            dry_run=False,
            db_path=str(db_path),
            rate_limit_seconds=0,
        )

    assert not db_path.exists()


def test_apply_with_explicit_confirm_token_writes_isolated_candidate_db(
    tmp_path, mock_fetchers
):
    db_path = tmp_path / "test_twstock.db"

    result = update_phase3c_candidates(
        date(2026, 7, 8),
        dry_run=False,
        db_path=str(db_path),
        rate_limit_seconds=0,
        confirm_token=APPLY_CONFIRM_TOKEN,
    )

    assert result is not None
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "institutional_flows",
        "credit_transactions",
        "tdcc_shareholding",
        "phase3c_backfill_checkpoints",
    }.issubset(tables)
    assert "phase3c_backfill_checkpoints" in tables


def test_optional_fields_are_none():
    mock_credit = pd.DataFrame(
        [{"stock_code": "2330", "financing": None, "securities_lending": None}]
    )
    assert mock_credit["financing"].iloc[0] is None
    assert mock_credit["securities_lending"].iloc[0] is None


def test_bounded_probe_reports_schema_timestamp_and_conservation_without_acceptance(
    tmp_path,
):
    fixture_root = Path(__file__).parent / "fixtures" / "p0_official_sources"
    responses = []
    for filename, content_type in (
        ("twse_institutional.json", "application/json"),
        ("twse_credit.json", "application/json"),
        ("tdcc_shareholding.csv", "text/csv"),
        ("twse_disposition.json", "application/json"),
        ("twse_disposition.json", "application/json"),
        ("twse_full_delivery.json", "application/json"),
        ("twse_halt_resume.json", "application/json"),
        ("twse_ex_dividend.json", "application/json"),
        ("twse_reduction.json", "application/json"),
        ("twse_monthly_revenue.json", "application/json"),
        ("tpex_monthly_revenue.json", "application/json"),
        ("twse_limit_lock.json", "application/json"),
        ("mops_quarterly_financials.json", "application/json"),
    ):
        response = MagicMock()
        response.content = (fixture_root / filename).read_bytes()
        response.headers = {"Content-Type": content_type}
        response.status_code = 200
        responses.append(response)

    before = tuple(tmp_path.rglob("*"))
    with patch(
        "scripts.update_phase3c_candidates.safe_request", side_effect=responses
    ):
        report = run_bounded_official_probe(date(2026, 7, 10))

    assert tuple(tmp_path.rglob("*")) == before
    assert report["license_accepted"] is False
    assert report["source_accepted"] is False
    assert report["downstream_eligibility"] == "none"
    assert report["production_scheduler_allowed"] is False
    assert {item["source_id"] for item in report["sources"]} == {
        "twse_institutional",
        "twse_credit",
        "tdcc_shareholding",
        "twse_disposition",
        "twse_periodic_call_auction",
        "twse_full_delivery",
        "twse_halt_resume",
        "twse_ex_dividend",
        "twse_reduction",
        "twse_monthly_revenue",
        "tpex_monthly_revenue",
        "twse_limit_lock",
    }
    for item in report["sources"]:
        assert item["raw_row_count"] == (
            item["accepted_row_count"]
            + item["duplicate_row_count"]
            + item["quarantine_row_count"]
            + item["blocked_row_count"]
        )
        assert item["schema_status"] == "matched"
        assert item["timestamp_evidence"] in {
            "official_publication_timestamp",
            "official_document_upload_timestamp",
            "first_observed_only",
        }


def test_bounded_probe_preserves_allowlisted_http_headers_as_transport_evidence():
    """Headers are visible to the owner packet but never become PIT proof."""

    fixture_root = Path(__file__).parent / "fixtures" / "p0_official_sources"

    def response_for(filename: str, content_type: str = "application/json"):
        response = MagicMock()
        response.content = (fixture_root / filename).read_bytes()
        response.headers = {
            "Date": "Fri, 10 Jul 2026 10:00:00 GMT",
            "Last-Modified": "Fri, 10 Jul 2026 09:59:00 GMT",
            "ETag": '"fixture-etag"',
            "Content-Type": content_type,
            # A secret-like header must never be copied to the artifact.
            "Authorization": "Bearer should-not-appear",
        }
        response.status_code = 200
        return response

    responses = [
        response_for("twse_institutional.json"),
        response_for("twse_credit.json"),
        response_for("tdcc_shareholding.csv", "text/csv"),
        response_for("twse_disposition.json"),
        response_for("twse_disposition.json"),
        response_for("twse_full_delivery.json"),
        response_for("twse_halt_resume.json"),
        response_for("twse_ex_dividend.json"),
        response_for("twse_reduction.json"),
        response_for("twse_monthly_revenue.json"),
        response_for("tpex_monthly_revenue.json"),
        response_for("twse_limit_lock.json"),
    ]

    with patch(
        "scripts.update_phase3c_candidates.safe_request", side_effect=responses
    ):
        report = run_bounded_official_probe(date(2026, 7, 10))

    institutional = next(
        item
        for item in report["sources"]
        if item["source_id"] == "twse_institutional"
    )
    assert institutional["http_date"] == "Fri, 10 Jul 2026 10:00:00 GMT"
    assert institutional["last_modified"] == "Fri, 10 Jul 2026 09:59:00 GMT"
    assert institutional["etag"] == '"fixture-etag"'
    assert institutional["content_type"] == "application/json"
    assert "Authorization" not in json.dumps(institutional, ensure_ascii=False)


def test_bounded_probe_uses_one_short_attempt_per_source() -> None:
    response = MagicMock()
    response.content = b'{"stat":"No data"}'
    response.headers = {"Content-Type": "application/json"}
    response.status_code = 200
    with patch(
        "scripts.update_phase3c_candidates.safe_request", return_value=response
    ) as request:
        run_bounded_official_probe(date(2026, 7, 10))

    # 季報僅能接收既有、可驗證的 MOPS artifact；不可把 HTML 頁面當成
    # JSON probe 端點。官方無資料時，對已登錄的替代路徑各做一次短 probe。
    assert request.call_count == 17
    for call in request.call_args_list:
        assert call.kwargs["timeout_seconds"] == 8
        assert call.kwargs["max_attempts"] == 1


def test_bounded_probe_preserves_raw_http_evidence_for_official_no_data():
    fixture_root = Path(__file__).parent / "fixtures" / "p0_official_sources"
    drifted = MagicMock()
    drifted.content = b'{"stat":"No data"}'
    drifted.headers = {"Content-Type": "application/json"}
    drifted.status_code = 200
    valid_credit = MagicMock()
    valid_credit.content = (fixture_root / "twse_credit.json").read_bytes()
    valid_credit.headers = {"Content-Type": "application/json"}
    valid_credit.status_code = 200
    valid_tdcc = MagicMock()
    valid_tdcc.content = (fixture_root / "tdcc_shareholding.csv").read_bytes()
    valid_tdcc.headers = {"Content-Type": "text/csv"}
    valid_tdcc.status_code = 200

    with patch(
        "scripts.update_phase3c_candidates.safe_request",
        side_effect=[drifted, drifted, valid_credit, valid_tdcc, *([drifted] * 11)],
    ):
        report = run_bounded_official_probe(date(2026, 7, 10))

    institutional = next(
        item
        for item in report["sources"]
        if item["source_id"] == "twse_institutional"
    )
    assert institutional["network_status"] == "reachable"
    assert institutional["http_status"] == 200
    assert institutional["payload_size_bytes"] == len(drifted.content)
    assert len(institutional["payload_sha256"]) == 64
    assert institutional["probe_outcome"] == "official_no_data"
    assert institutional["schema_status"] == "no_data"
    assert institutional["official_status"] == "No data"
    assert institutional["fallback_attempted"] is True
    assert institutional["fallback_probe_outcome"] == "official_no_data"


def test_bounded_probe_uses_tdcc_openapi_after_legacy_csv_network_failure():
    fixture_root = Path(__file__).parent / "fixtures" / "p0_official_sources"

    def response_for(filename: str, content_type: str = "application/json"):
        response = MagicMock()
        response.content = (fixture_root / filename).read_bytes()
        response.headers = {"Content-Type": content_type}
        response.status_code = 200
        return response

    tdcc_openapi = MagicMock()
    tdcc_openapi.content = (
        b'[{"\\ufeff\\u8cc7\\u6599\\u65e5\\u671f":"20260710",'
        b'"\\u8b49\\u5238\\u4ee3\\u865f":"2330",'
        b'"\\u6301\\u80a1\\u5206\\u7d1a":"15",'
        b'"\\u4eba\\u6578":"100","\\u80a1\\u6578":"600000",'
        b'"\\u5360\\u96c6\\u4fdd\\u5eab\\u5b58\\u6578\\u6bd4\\u4f8b%":"60.00"}]'
    )
    tdcc_openapi.headers = {"Content-Type": "application/json"}
    tdcc_openapi.status_code = 200
    no_data = MagicMock()
    no_data.content = b'{"stat":"No data"}'
    no_data.headers = {"Content-Type": "application/json"}
    no_data.status_code = 200
    responses = [
        response_for("twse_institutional.json"),
        response_for("twse_credit.json"),
        TimeoutError("legacy TDCC timeout"),
        tdcc_openapi,
        *([no_data] * 11),
    ]

    with patch(
        "scripts.update_phase3c_candidates.safe_request", side_effect=responses
    ) as request:
        report = run_bounded_official_probe(date(2026, 7, 10))

    tdcc = next(
        item for item in report["sources"] if item["source_id"] == "tdcc_shareholding"
    )
    assert request.call_count == 15
    assert tdcc["network_status"] == "reachable"
    assert tdcc["schema_status"] == "matched"
    assert tdcc["fallback_used"] is True
    assert tdcc["fallback_from_acquisition_route_id"] == "tdcc.legacy_1-5_csv"
    assert tdcc["acquisition_route_id"] == "tdcc.openapi_1-5"
    assert tdcc["accepted_row_count"] == 1


def test_bounded_probe_uses_tpex_institutional_fallback_after_official_no_data():
    tpex_payload = [
        {
            "Date": "1150710",
            "SecuritiesCompanyCode": "2330",
            "CompanyName": "台積電",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy": "2000",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell": "800",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "1200",
        }
    ]

    def response_for(url: str, *args, **kwargs):
        response = MagicMock()
        response.headers = {"Content-Type": "application/json"}
        response.status_code = 200
        if url.endswith("/fund/T86"):
            response.content = b'{"stat":"No data"}'
        elif url.endswith("/tpex_3insti_daily_trading"):
            response.content = json.dumps(tpex_payload).encode("utf-8")
        else:
            response.content = b'{"stat":"No data"}'
        return response

    with patch(
        "scripts.update_phase3c_candidates.safe_request",
        side_effect=response_for,
    ) as request:
        report = run_bounded_official_probe(date(2026, 7, 10))

    institutional = next(
        item
        for item in report["sources"]
        if item["source_id"] == "twse_institutional"
    )
    assert institutional["probe_outcome"] == "observed"
    assert institutional["schema_status"] == "matched"
    assert institutional["fallback_used"] is True
    assert institutional["fallback_from_endpoint_id"] == "twse:T86"
    assert institutional["fallback_from_acquisition_route_id"] == "twse.T86"
    assert institutional["endpoint_id"] == "tpex:openapi:tpex_3insti_daily_trading"
    assert institutional["acquisition_route_id"] == "tpex.tpex_3insti_daily_trading"
    assert institutional["accepted_row_count"] == 1
    assert request.call_count == 17


def test_bounded_probe_rejects_tpex_fallback_when_observation_date_is_not_requested_date():
    tpex_payload = [
        {
            "Date": "1150709",
            "SecuritiesCompanyCode": "2330",
            "CompanyName": "台積電",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy": "2000",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell": "800",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "1200",
        }
    ]

    def response_for(url: str, *args, **kwargs):
        response = MagicMock()
        response.headers = {"Content-Type": "application/json"}
        response.status_code = 200
        if url.endswith("/fund/T86"):
            response.content = b'{"stat":"No data"}'
        elif url.endswith("/tpex_3insti_daily_trading"):
            response.content = json.dumps(tpex_payload).encode("utf-8")
        else:
            response.content = b'{"stat":"No data"}'
        return response

    with patch(
        "scripts.update_phase3c_candidates.safe_request",
        side_effect=response_for,
    ):
        report = run_bounded_official_probe(date(2026, 7, 10))

    institutional = next(
        item
        for item in report["sources"]
        if item["source_id"] == "twse_institutional"
    )
    assert institutional["probe_outcome"] == "official_no_data"
    assert institutional["schema_status"] == "no_data"
    assert institutional["fallback_used"] is False
    assert institutional["fallback_probe_outcome"] == "date_mismatch"
    assert institutional["fallback_observation_dates"] == ["2026-07-09"]
    assert institutional["fallback_requested_date"] == "2026-07-10"

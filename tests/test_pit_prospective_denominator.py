from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

import data_module.pit_prospective_denominator as denominator
from data_module.pit_prospective_denominator import (
    DATA_GOV_LICENSE_URL,
    ProspectivePITDenominatorError,
    build_prospective_pit_denominator,
    validate_prospective_pit_denominator,
)


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 8, 1, 0, tzinfo=TAIPEI)


def _raw_json() -> dict[str, bytes]:
    return {
        "twse": json.dumps(
            [
                {"公司代號": "1101", "產業別": "01", "出表日期": "20260907"},
                {"公司代號": "1102", "產業別": "02", "出表日期": "20260907"},
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        "tpex": json.dumps(
            [
                {
                    "SecuritiesCompanyCode": "5501",
                    "SecuritiesIndustryCode": "03",
                    "Date": "2026-09-07",
                },
                {
                    "SecuritiesCompanyCode": "5502",
                    "SecuritiesIndustryCode": "05",
                    "Date": "2026-09-07",
                },
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    }


def _csv() -> dict[str, bytes]:
    twse = (
        "出表日期,公司代號,產業別,公司名稱\n"
        "1150907,1101,01,甲公司\n"
        "1150907,1102,02,乙公司\n"
    ).encode("utf-8-sig")
    tpex = (
        "出表日期,公司代號,產業別,公司名稱\n"
        "1150907,5501,03,丙公司\n"
        "1150907,5502,05,丁公司\n"
    ).encode("utf-8-sig")
    return {"twse": twse, "tpex": tpex}


def _metadata() -> dict[str, bytes]:
    return {
        "twse": _metadata_one(
            18419,
            "A45020000D-000353",
            "上市公司基本資料",
            "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv",
            "https://openapi.twse.com.tw/v1/swagger.json",
        ),
        "tpex": _metadata_one(
            25036,
            "A45020000D-000511",
            "上櫃公司基本資料",
            "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv",
            "https://www.tpex.org.tw/openapi/swagger.json",
        ),
    }


def _metadata_one(
    dataset_id: int,
    identifier: str,
    title: str,
    resource_url: str,
    swagger_url: str,
) -> bytes:
    payload = {
        "success": True,
        "result": {
            "datasetId": dataset_id,
            "identifier": identifier,
            "title": title,
            "dataProvider": "N121467221",
            "publisherOID": "2.16.886.101.20003.20052.20004",
            "license": "1",
            "notes": f"授權說明網址: {DATA_GOV_LICENSE_URL}\nOAS標準之API說明文件網址 {swagger_url}",
            "distribution": [
                {
                    "resourceFormat": "CSV",
                    "resourceDownloadUrl": resource_url,
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _swagger() -> dict[str, bytes]:
    return {
        "twse": json.dumps(
            {
                "swagger": "2.0",
                "info": {"title": "臺灣證券交易所 OpenAPI"},
                "host": "openapi.twse.com.tw",
                "basePath": "/v1",
                "paths": {"/opendata/t187ap03_L": {"get": {}}},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"),
        "tpex": json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "證券櫃檯買賣中心 OpenAPI"},
                "servers": [{"url": "https://www.tpex.org.tw/openapi/v1"}],
                "paths": {"/mopsfin_t187ap03_O": {"get": {}}},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"),
    }


def _http(url: str, captured_at: datetime) -> dict[str, object]:
    return {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "application/json; charset=utf-8",
        "http_date": "Mon, 07 Sep 2026 15:45:00 GMT",
        "http_last_modified": None,
        "captured_at": captured_at.isoformat(),
    }


def _inputs(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    fake_license = b"<html><head><title>test-license</title></head></html>"
    monkeypatch.setattr(denominator, "DATA_GOV_LICENSE_TITLE", "test-license")
    monkeypatch.setattr(
        denominator,
        "DATA_GOV_LICENSE_SHA256",
        "sha256:" + hashlib.sha256(fake_license).hexdigest(),
    )
    monkeypatch.setattr(denominator, "DATA_GOV_LICENSE_BYTES", len(fake_license))
    raw = _raw_json()
    csv_payloads = _csv()
    metadata = _metadata()
    swagger = _swagger()
    raw_http = {
        "twse": _http(
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
            NOW - timedelta(minutes=15),
        ),
        "tpex": _http(
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
            NOW - timedelta(minutes=14),
        ),
    }
    csv_http = {
        "twse": _http(
            "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv",
            NOW - timedelta(minutes=13),
        ),
        "tpex": _http(
            "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv",
            NOW - timedelta(minutes=12),
        ),
    }
    metadata_http = {
        "twse": _http(
            "https://data.gov.tw/api/v2/rest/dataset/18419",
            NOW - timedelta(minutes=11),
        ),
        "tpex": _http(
            "https://data.gov.tw/api/v2/rest/dataset/25036",
            NOW - timedelta(minutes=10),
        ),
    }
    swagger_http = {
        "twse": _http(
            "https://openapi.twse.com.tw/v1/swagger.json",
            NOW - timedelta(minutes=9),
        ),
        "tpex": _http(
            "https://www.tpex.org.tw/openapi/swagger.json",
            NOW - timedelta(minutes=8),
        ),
    }
    license_http = _http(DATA_GOV_LICENSE_URL, NOW - timedelta(minutes=7))
    license_http["content_type"] = "text/html; charset=utf-8"
    return {
        "raw_json_payloads": raw,
        "raw_json_http": raw_http,
        "csv_payloads": csv_payloads,
        "csv_http": csv_http,
        "metadata_payloads": metadata,
        "metadata_http": metadata_http,
        "swagger_payloads": swagger,
        "swagger_http": swagger_http,
        "license_payload": fake_license,
        "license_http": license_http,
        "coverage_start": date(2026, 9, 8),
        "now": NOW,
    }


def test_official_csv_metadata_builds_independent_prospective_denominator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _inputs(monkeypatch)
    arguments["output_dir"] = tmp_path / "denominator"
    result = build_prospective_pit_denominator(**arguments)

    assert result["status"] == "verified_prospective_denominator"
    assert result["symbols"] == ["1101", "1102", "5501", "5502"]
    assert result["symbol_count"] == 4
    assert result["source_independence"]["denominator_not_derived_from_archive"] is True
    assert result["license_scope"]["status"] == "machine_scope_verified"
    loaded = validate_prospective_pit_denominator(
        tmp_path / "denominator" / "denominator.json",
        now=NOW,
    )
    assert loaded["symbols_hash"] == result["symbols_hash"]
    assert (tmp_path / "denominator" / "twse_t187ap03.csv").is_file()


def test_denominator_rejects_csv_tampering_even_when_outer_payload_is_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _inputs(monkeypatch)
    output = tmp_path / "denominator"
    arguments["output_dir"] = output
    build_prospective_pit_denominator(**arguments)
    csv_path = output / "twse_t187ap03.csv"
    csv_path.write_bytes(csv_path.read_bytes().replace(b",01,", b",99,"))

    with pytest.raises(ProspectivePITDenominatorError, match="source CSV hash mismatch"):
        validate_prospective_pit_denominator(output / "denominator.json", now=NOW)


def test_denominator_rejects_license_document_that_only_contains_open_data_words(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _inputs(monkeypatch)
    bad_license = "政府資料開放授權條款，但這不是註冊版本".encode("utf-8")
    arguments["license_payload"] = bad_license
    arguments["output_dir"] = tmp_path / "denominator"

    with pytest.raises(ProspectivePITDenominatorError, match="license document fingerprint"):
        build_prospective_pit_denominator(**arguments)


def test_license_fingerprint_canonicalizes_only_one_cloudflare_email_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'<title>test-license</title><a data-cfemail="deadbeef">mail</a>'
    monkeypatch.setattr(denominator, "DATA_GOV_LICENSE_TITLE", "test-license")
    monkeypatch.setattr(denominator, "DATA_GOV_LICENSE_BYTES", len(payload))
    monkeypatch.setattr(
        denominator,
        "DATA_GOV_LICENSE_SHA256",
        "sha256:" + hashlib.sha256(
            payload.replace(b"deadbeef", b"<dynamic-email-token>")
        ).hexdigest(),
    )

    denominator._validate_license_document(payload)
    denominator._validate_license_document(payload.replace(b"deadbeef", b"01234567"))

    bad_payload = payload + b'<a data-cfemail="cafebabe">second</a>'
    monkeypatch.setattr(denominator, "DATA_GOV_LICENSE_BYTES", len(bad_payload))
    with pytest.raises(ProspectivePITDenominatorError, match="dynamic token"):
        denominator._validate_license_document(bad_payload)


def test_denominator_rejects_coverage_start_before_latest_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _inputs(monkeypatch)
    arguments["coverage_start"] = date(2026, 9, 7)
    arguments["output_dir"] = tmp_path / "denominator"

    with pytest.raises(ProspectivePITDenominatorError, match="coverage_start"):
        build_prospective_pit_denominator(**arguments)


def test_denominator_rejects_data_gov_resource_mapping_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _inputs(monkeypatch)
    metadata = _metadata()
    altered = json.loads(metadata["twse"].decode("utf-8"))
    altered["result"]["distribution"][0]["resourceDownloadUrl"] = (
        "https://example.invalid/t187ap03_L.csv"
    )
    arguments["metadata_payloads"] = {
        **metadata,
        "twse": json.dumps(altered, ensure_ascii=False).encode("utf-8"),
    }
    arguments["output_dir"] = tmp_path / "denominator"

    with pytest.raises(ProspectivePITDenominatorError, match="resource URL mismatch"):
        build_prospective_pit_denominator(**arguments)


def test_denominator_retains_but_allows_independent_source_date_cadence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _inputs(monkeypatch)
    csv_payloads = dict(arguments["csv_payloads"])
    csv_payloads["twse"] = csv_payloads["twse"].replace(b"1150907", b"1150906")
    arguments["csv_payloads"] = csv_payloads
    arguments["output_dir"] = tmp_path / "denominator"

    result = build_prospective_pit_denominator(**arguments)
    loaded = validate_prospective_pit_denominator(
        arguments["output_dir"] / "denominator.json",
        now=NOW,
    )

    twse = next(
        entry for entry in result["source_registry"] if entry["market"] == "twse"
    )
    assert twse["publication_date"] == "2026-09-07"
    assert twse["csv_publication_date"] == "2026-09-06"
    assert loaded["source_registry"] == result["source_registry"]

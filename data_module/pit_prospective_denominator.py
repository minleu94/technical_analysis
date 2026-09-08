"""官方 prospective PIT 分母與授權 evidence producer。

這個模組把兩條獨立的官方來源綁在同一個可重驗封套：

* TWSE／TPEx OpenAPI JSON 是 PIT row producer 的 source custody；
* data.gov.tw 18419／25036 所指向的官方 CSV resource 是 expected universe
  的獨立分母，並以 metadata、Swagger endpoint mapping 與政府資料開放
  授權條款的固定文件指紋證明用途範圍。

分母只宣告 ``coverage_start`` 之後的 prospective scope。它不讀
``companies.csv``、不從既有 archive 推導 symbols、不回填歷史 membership，
也不把網頁關鍵字當作授權判定。所有內容都以 create-only bytes、source URL、
HTTP completion timestamp 與 SHA-256 綁定；任一 evidence 缺失或竄改即拒絕。
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from data_module.prospective_official_pit_source import (
    OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
    _parse_official_source,
)


PIT_PROSPECTIVE_DENOMINATOR_SCHEMA_VERSION = "pit-prospective-denominator.v1"
PIT_PROSPECTIVE_DENOMINATOR_PRODUCER_VERSION = (
    "official-datagov-company-resource-denominator.v1"
)
PIT_PROSPECTIVE_LICENSE_POLICY_VERSION = "government-open-data-pit-scope.v1"
DATA_GOV_LICENSE_URL = "https://data.gov.tw/license"
DATA_GOV_LICENSE_TITLE = "政府資料開放授權條款－第1版 ｜ 政府資料開放平臺"
# data.gov.tw is fronted by Cloudflare and rewrites the hexadecimal value in
# its ``data-cfemail`` presentation attribute on each response.  The terms
# body/title are stable; the registered digest is therefore over a narrowly
# canonicalized copy of that one presentation-only attribute.  The exact raw
# response hash is still saved in ``license_document.content_sha256``.
DATA_GOV_LICENSE_SHA256 = (
    "sha256:0072cfbe821d7973236cec81a6551b508467c66da10d0eb3241232686e3cfa4e"
)
DATA_GOV_LICENSE_BYTES = 484470
TAIPEI = ZoneInfo("Asia/Taipei")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[0-9]{4,6}$")
_SOURCE_MARKETS = ("twse", "tpex")
_MAX_SOURCE_BYTES = 16 * 1024 * 1024


class ProspectivePITDenominatorError(ValueError):
    """prospective PIT 分母／官方授權 evidence 不符合 fail-closed 契約。"""


_SOURCE_CONTRACTS: dict[str, dict[str, object]] = {
    "twse": {
        "source_id": "official:twse:t187ap03_L",
        "market": "twse_listed",
        "dataset_id": 18419,
        "dataset_url": "https://data.gov.tw/dataset/18419",
        "metadata_url": "https://data.gov.tw/api/v2/rest/dataset/18419",
        "identifier": "A45020000D-000353",
        "title": "上市公司基本資料",
        "data_provider": "N121467221",
        "publisher_oid": "2.16.886.101.20003.20052.20004",
        "license_code": "1",
        "license_version": "政府資料開放授權條款-第1版",
        "resource_url": "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv",
        "endpoint_url": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "swagger_url": "https://openapi.twse.com.tw/v1/swagger.json",
        "swagger_path": "/opendata/t187ap03_L",
        "swagger_title": "臺灣證券交易所 OpenAPI",
        "notes_urls": (
            DATA_GOV_LICENSE_URL,
            "https://openapi.twse.com.tw/v1/swagger.json",
        ),
        "csv_symbol_field": "公司代號",
        "csv_sector_field": "產業別",
        "csv_publication_field": "出表日期",
        "json_market": "twse",
    },
    "tpex": {
        "source_id": "official:tpex:t187ap03_O",
        "market": "tpex_otc",
        "dataset_id": 25036,
        "dataset_url": "https://data.gov.tw/dataset/25036",
        "metadata_url": "https://data.gov.tw/api/v2/rest/dataset/25036",
        "identifier": "A45020000D-000511",
        "title": "上櫃公司基本資料",
        "data_provider": "N121467221",
        "publisher_oid": "2.16.886.101.20003.20052.20004",
        "license_code": "1",
        "license_version": "政府資料開放授權條款-第1版",
        "resource_url": "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv",
        "endpoint_url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
        "swagger_url": "https://www.tpex.org.tw/openapi/swagger.json",
        "swagger_path": "/mopsfin_t187ap03_O",
        "swagger_title": "證券櫃檯買賣中心 OpenAPI",
        "notes_urls": (
            DATA_GOV_LICENSE_URL,
            "https://www.tpex.org.tw/openapi/swagger.json",
        ),
        "csv_symbol_field": "公司代號",
        "csv_sector_field": "產業別",
        "csv_publication_field": "出表日期",
        "json_market": "tpex",
    },
}


def build_prospective_pit_denominator(
    *,
    raw_json_payloads: Mapping[str, bytes],
    raw_json_http: Mapping[str, Mapping[str, object]],
    csv_payloads: Mapping[str, bytes],
    csv_http: Mapping[str, Mapping[str, object]],
    metadata_payloads: Mapping[str, bytes],
    metadata_http: Mapping[str, Mapping[str, object]],
    swagger_payloads: Mapping[str, bytes],
    swagger_http: Mapping[str, Mapping[str, object]],
    license_payload: bytes,
    license_http: Mapping[str, object],
    coverage_start: date,
    output_dir: Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """驗證官方 JSON／CSV／metadata／Swagger／license 並保存分母封套。

    呼叫端需把每個 response 完成後才取得的 timestamp 放在 HTTP metadata 的
    ``captured_at``。這裡不接受 caller 自填的 row status 或 license boolean；
    symbols、market、授權 scope 與 source hashes 都由保存的 bytes 重新計算。
    """

    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    )
    start = _required_date(coverage_start, "coverage_start")
    if not isinstance(raw_json_payloads, Mapping) or set(raw_json_payloads) != set(
        _SOURCE_MARKETS
    ):
        raise ProspectivePITDenominatorError(
            "raw_json_payloads must contain exactly TWSE and TPEx sources"
        )
    for label, value in (
        ("raw_json_http", raw_json_http),
        ("csv_payloads", csv_payloads),
        ("csv_http", csv_http),
        ("metadata_payloads", metadata_payloads),
        ("metadata_http", metadata_http),
        ("swagger_payloads", swagger_payloads),
        ("swagger_http", swagger_http),
    ):
        if not isinstance(value, Mapping):
            raise ProspectivePITDenominatorError(f"{label} must be a mapping")
    if set(csv_payloads) != set(_SOURCE_MARKETS):
        raise ProspectivePITDenominatorError(
            "csv_payloads must contain exactly TWSE and TPEx resources"
        )
    if set(metadata_payloads) != set(_SOURCE_MARKETS):
        raise ProspectivePITDenominatorError(
            "metadata_payloads must contain exactly datasets 18419 and 25036"
        )
    if set(swagger_payloads) != set(_SOURCE_MARKETS):
        raise ProspectivePITDenominatorError(
            "swagger_payloads must contain exactly TWSE and TPEx Swagger"
        )
    _validate_http_metadata_set(
        raw_json_payloads,
        raw_json_http,
        now=observed_now,
        kind="raw JSON",
    )
    _validate_http_metadata_set(
        csv_payloads,
        csv_http,
        now=observed_now,
        kind="official CSV",
    )
    _validate_http_metadata_set(
        metadata_payloads,
        metadata_http,
        now=observed_now,
        kind="data.gov metadata",
    )
    _validate_http_metadata_set(
        swagger_payloads,
        swagger_http,
        now=observed_now,
        kind="official Swagger",
    )
    _validate_single_http_metadata(
        license_http,
        requested_url=DATA_GOV_LICENSE_URL,
        now=observed_now,
        kind="data.gov license",
    )
    if not isinstance(license_payload, bytes) or not license_payload:
        raise ProspectivePITDenominatorError("license payload must be non-empty bytes")
    if len(license_payload) > _MAX_SOURCE_BYTES:
        raise ProspectivePITDenominatorError("license payload exceeds bounded size")
    _validate_license_document(license_payload)

    source_entries: list[dict[str, object]] = []
    market_symbols: dict[str, tuple[str, ...]] = {}
    market_sectors: dict[str, dict[str, str]] = {}
    source_capture_dates: list[date] = []
    for market in _SOURCE_MARKETS:
        contract = _SOURCE_CONTRACTS[market]
        _validate_source_metadata(
            market,
            contract,
            metadata_payloads[market],
            metadata_http[market],
        )
        _validate_source_swagger(
            market,
            contract,
            swagger_payloads[market],
        )
        json_parsed = _parse_official_source(
            OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market],
            _bounded_bytes(raw_json_payloads[market], f"{market} raw JSON"),
        )
        csv_symbols, csv_sectors, csv_publication_date = _parse_official_csv(
            market,
            _bounded_bytes(csv_payloads[market], f"{market} official CSV"),
        )
        json_symbols = tuple(sorted(json_parsed.rows_by_symbol))
        if json_symbols != csv_symbols:
            raise ProspectivePITDenominatorError(
                f"{market} JSON and data.gov CSV symbol sets differ"
            )
        json_sector_map = {
            symbol: value[0] for symbol, value in json_parsed.rows_by_symbol.items()
        }
        if json_sector_map != csv_sectors:
            raise ProspectivePITDenominatorError(
                f"{market} JSON and data.gov CSV sector mappings differ"
            )
        # The OpenAPI snapshot is refreshed on a different cadence from the
        # data.gov registry CSV.  A one-day (or monthly-resource) publication
        # date difference is valid when both independently published symbol
        # and sector mappings match exactly; retain both dates in the source
        # registry so the cadence difference remains auditable.
        capture_at = _http_captured_at(raw_json_http[market], f"{market} raw JSON")
        source_capture_dates.append(capture_at.astimezone(TAIPEI).date())
        market_symbols[market] = json_symbols
        market_sectors[market] = json_sector_map
        source_entries.append(
            _build_source_entry(
                market=market,
                contract=contract,
                raw_json_payload=raw_json_payloads[market],
                raw_json_http=raw_json_http[market],
                csv_payload=csv_payloads[market],
                csv_http=csv_http[market],
                metadata_payload=metadata_payloads[market],
                metadata_http=metadata_http[market],
                swagger_payload=swagger_payloads[market],
                swagger_http=swagger_http[market],
                symbols=json_symbols,
                sectors=json_sector_map,
                publication_date=json_parsed.publication_date,
                csv_publication_date=csv_publication_date,
            )
        )
    symbols = tuple(sorted(set(market_symbols["twse"]) | set(market_symbols["tpex"])))
    if not symbols:
        raise ProspectivePITDenominatorError("prospective denominator is empty")
    if len(symbols) != len(market_symbols["twse"]) + len(market_symbols["tpex"]):
        raise ProspectivePITDenominatorError(
            "a company symbol appears in more than one official market resource"
        )
    max_capture_date = max(source_capture_dates)
    if start < max_capture_date:
        raise ProspectivePITDenominatorError(
            "coverage_start cannot predate the latest official response capture date"
        )
    output = output_dir.expanduser().resolve()
    _require_output_root(output)
    output.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {
        "schema_version": PIT_PROSPECTIVE_DENOMINATOR_SCHEMA_VERSION,
        "status": "verified_prospective_denominator",
        "scope": "prospective_pit_sector_membership",
        "coverage_start": start.isoformat(),
        "coverage_start_basis": "explicit_operator_input",
        "historical_backfill_claimed": False,
        "symbols": list(symbols),
        "symbol_count": len(symbols),
        "symbols_hash": _sha256_json(list(symbols)),
        "market_by_symbol": {
            symbol: (
                "twse" if symbol in market_symbols["twse"] else "tpex"
            )
            for symbol in symbols
        },
        "sector_by_symbol": {
            symbol: (
                market_sectors["twse"].get(symbol)
                if symbol in market_sectors["twse"]
                else market_sectors["tpex"].get(symbol)
            )
            for symbol in symbols
        },
        "source_registry": sorted(source_entries, key=lambda item: str(item["market"])),
        "license_scope": _license_scope(source_entries),
        "license_document": {
            "url": DATA_GOV_LICENSE_URL,
            "final_url": str(license_http["final_url"]),
            "content_sha256": _sha256_bytes(license_payload),
            "content_bytes": len(license_payload),
            "title": DATA_GOV_LICENSE_TITLE,
            "captured_at": _http_captured_at(license_http, "data.gov license").isoformat(),
        },
        "producer": "data_module.pit_prospective_denominator",
        "producer_version": PIT_PROSPECTIVE_DENOMINATOR_PRODUCER_VERSION,
        "producer_code_sha256": _producer_code_sha256(),
        "observed_at": observed_now.isoformat(),
        "source_capture_dates": sorted(set(item.isoformat() for item in source_capture_dates)),
        "source_independence": {
            "denominator_source": "data.gov.tw_dataset_resource_csv",
            "denominator_not_derived_from_archive": True,
            "json_source_used_for_pit_rows": True,
            "csv_source_used_for_expected_symbols": True,
            "companies_csv_used": False,
        },
    }
    body["content_sha256"] = _sha256_json(body)
    _write_create_only_json(output / "denominator.json", body)
    for market in _SOURCE_MARKETS:
        _write_create_only_bytes(
            output / f"{market}_t187ap03.raw.json", raw_json_payloads[market]
        )
        _write_create_only_bytes(output / f"{market}_t187ap03.csv", csv_payloads[market])
        _write_create_only_bytes(
            output / f"dataset_{_SOURCE_CONTRACTS[market]['dataset_id']}.json",
            metadata_payloads[market],
        )
        _write_create_only_bytes(
            output / f"{market}_swagger.json", swagger_payloads[market]
        )
    _write_create_only_bytes(output / "government_open_data_license.html", license_payload)
    result = dict(body)
    result.update(
        {
            "path": str((output / "denominator.json").resolve()),
            "file_sha256": _file_sha256(output / "denominator.json"),
            "readback_verified": True,
        }
    )
    validate_prospective_pit_denominator(
        output / "denominator.json",
        now=observed_now,
    )
    return result


def validate_prospective_pit_denominator(
    path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """重新讀取分母 envelope 與所有 child bytes，回傳已驗證 payload。"""

    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProspectivePITDenominatorError("denominator JSON is unreadable") from error
    if not isinstance(payload, dict):
        raise ProspectivePITDenominatorError("denominator JSON must be an object")
    expected_keys = {
        "schema_version",
        "status",
        "scope",
        "coverage_start",
        "coverage_start_basis",
        "historical_backfill_claimed",
        "symbols",
        "symbol_count",
        "symbols_hash",
        "market_by_symbol",
        "sector_by_symbol",
        "source_registry",
        "license_scope",
        "license_document",
        "producer",
        "producer_version",
        "producer_code_sha256",
        "observed_at",
        "source_capture_dates",
        "source_independence",
        "content_sha256",
    }
    if set(payload) != expected_keys:
        raise ProspectivePITDenominatorError("denominator fields are invalid")
    _expect(payload.get("schema_version"), PIT_PROSPECTIVE_DENOMINATOR_SCHEMA_VERSION, "schema_version")
    _expect(payload.get("status"), "verified_prospective_denominator", "status")
    _expect(payload.get("scope"), "prospective_pit_sector_membership", "scope")
    if payload.get("coverage_start_basis") != "explicit_operator_input":
        raise ProspectivePITDenominatorError("coverage_start basis is invalid")
    if payload.get("historical_backfill_claimed") is not False:
        raise ProspectivePITDenominatorError("historical backfill cannot be claimed")
    start = _parse_iso_date(payload.get("coverage_start"), "coverage_start")
    symbols = _normalize_symbols(payload.get("symbols"))
    if payload.get("symbol_count") != len(symbols):
        raise ProspectivePITDenominatorError("denominator symbol_count mismatch")
    if payload.get("symbols_hash") != _sha256_json(list(symbols)):
        raise ProspectivePITDenominatorError("denominator symbols_hash mismatch")
    market_by_symbol = payload.get("market_by_symbol")
    sector_by_symbol = payload.get("sector_by_symbol")
    if not isinstance(market_by_symbol, Mapping) or not isinstance(sector_by_symbol, Mapping):
        raise ProspectivePITDenominatorError("denominator symbol mappings are invalid")
    if set(market_by_symbol) != set(symbols) or set(sector_by_symbol) != set(symbols):
        raise ProspectivePITDenominatorError("denominator symbol mappings do not cover symbols")
    if any(value not in _SOURCE_MARKETS for value in market_by_symbol.values()):
        raise ProspectivePITDenominatorError("denominator market mapping is invalid")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}", value) for value in sector_by_symbol.values()):
        raise ProspectivePITDenominatorError("denominator sector mapping is invalid")
    source_registry = payload.get("source_registry")
    if not isinstance(source_registry, list) or len(source_registry) != len(_SOURCE_MARKETS):
        raise ProspectivePITDenominatorError("denominator source_registry is incomplete")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    )
    source_capture_dates: list[date] = []
    registry_by_market: dict[str, Mapping[str, object]] = {}
    for entry in source_registry:
        if not isinstance(entry, Mapping):
            raise ProspectivePITDenominatorError("denominator source_registry entry is invalid")
        market = _required_text(entry.get("market"), "source_registry.market")
        if market in registry_by_market or market not in _SOURCE_MARKETS:
            raise ProspectivePITDenominatorError("denominator source_registry market is invalid")
        registry_by_market[market] = entry
        contract = _SOURCE_CONTRACTS[market]
        for key in (
            "source_id",
            "dataset_id",
            "dataset_url",
            "metadata_url",
            "resource_url",
            "endpoint_url",
            "swagger_url",
            "swagger_path",
            "license_code",
            "license_version",
            "json_path",
            "csv_path",
            "metadata_path",
            "swagger_path_file",
            "json_content_sha256",
            "csv_content_sha256",
            "metadata_content_sha256",
            "swagger_content_sha256",
            "json_http",
            "csv_http",
            "metadata_http",
            "swagger_http",
            "json_symbol_count",
            "csv_symbol_count",
            "publication_date",
            "symbols_hash",
            "market_symbols",
            "market_sectors",
            "csv_publication_date",
        ):
            if key not in entry:
                raise ProspectivePITDenominatorError(
                    f"denominator source_registry.{key} is missing"
                )
        if entry.get("source_id") != contract["source_id"]:
            raise ProspectivePITDenominatorError("denominator source_id mismatch")
        if entry.get("dataset_id") != contract["dataset_id"]:
            raise ProspectivePITDenominatorError("denominator dataset_id mismatch")
        json_path = _resolve_child(resolved.parent, entry.get("json_path"), "source JSON")
        csv_path = _resolve_child(resolved.parent, entry.get("csv_path"), "source CSV")
        metadata_path = _resolve_child(resolved.parent, entry.get("metadata_path"), "dataset metadata")
        swagger_path = _resolve_child(resolved.parent, entry.get("swagger_path_file"), "source Swagger")
        json_bytes = _read_bounded_file(json_path, "source JSON")
        csv_bytes = _read_bounded_file(csv_path, "source CSV")
        metadata_bytes = _read_bounded_file(metadata_path, "dataset metadata")
        swagger_bytes = _read_bounded_file(swagger_path, "source Swagger")
        if _sha256_bytes(json_bytes) != entry.get("json_content_sha256"):
            raise ProspectivePITDenominatorError("denominator source JSON hash mismatch")
        if _sha256_bytes(csv_bytes) != entry.get("csv_content_sha256"):
            raise ProspectivePITDenominatorError("denominator source CSV hash mismatch")
        if _sha256_bytes(metadata_bytes) != entry.get("metadata_content_sha256"):
            raise ProspectivePITDenominatorError("denominator metadata hash mismatch")
        if _sha256_bytes(swagger_bytes) != entry.get("swagger_content_sha256"):
            raise ProspectivePITDenominatorError("denominator Swagger hash mismatch")
        _validate_source_metadata(market, contract, metadata_bytes, entry["metadata_http"])
        _validate_source_swagger(market, contract, swagger_bytes)
        parsed = _parse_official_source(
            OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market], json_bytes
        )
        csv_symbols, csv_sectors, csv_pub = _parse_official_csv(market, csv_bytes)
        symbols_for_market = tuple(str(item) for item in entry["market_symbols"])
        if symbols_for_market != tuple(sorted(parsed.rows_by_symbol)) or csv_symbols != symbols_for_market:
            raise ProspectivePITDenominatorError("denominator source symbols changed")
        if dict(entry["market_sectors"]) != {
            symbol: value[0] for symbol, value in parsed.rows_by_symbol.items()
        } or csv_sectors != dict(entry["market_sectors"]):
            raise ProspectivePITDenominatorError("denominator source sectors changed")
        if entry.get("json_symbol_count") != len(parsed.rows_by_symbol) or entry.get("csv_symbol_count") != len(csv_symbols):
            raise ProspectivePITDenominatorError("denominator source row counts changed")
        if entry.get("symbols_hash") != _sha256_json(list(symbols_for_market)):
            raise ProspectivePITDenominatorError("denominator market symbols hash mismatch")
        if (
            entry.get("publication_date") != parsed.publication_date.isoformat()
            or entry.get("csv_publication_date") != csv_pub.isoformat()
        ):
            raise ProspectivePITDenominatorError("denominator publication date changed")
        raw_json_http = _mapping(entry["json_http"], "source_registry.json_http")
        _validate_single_http_metadata(
            raw_json_http,
            requested_url=str(contract["endpoint_url"]),
            now=observed_now,
            kind=f"{market} raw JSON",
        )
        _validate_single_http_metadata(
            _mapping(entry["csv_http"], "source_registry.csv_http"),
            requested_url=str(contract["resource_url"]),
            now=observed_now,
            kind=f"{market} CSV",
        )
        _validate_single_http_metadata(
            _mapping(entry["metadata_http"], "source_registry.metadata_http"),
            requested_url=str(contract["metadata_url"]),
            now=observed_now,
            kind=f"{market} metadata",
        )
        _validate_single_http_metadata(
            _mapping(entry["swagger_http"], "source_registry.swagger_http"),
            requested_url=str(contract["swagger_url"]),
            now=observed_now,
            kind=f"{market} Swagger",
        )
        source_capture_dates.append(_http_captured_at(raw_json_http, f"{market} raw JSON").astimezone(TAIPEI).date())
        if set(symbols_for_market) - set(symbols):
            raise ProspectivePITDenominatorError("denominator market symbols exceed union")
        if any(market_by_symbol.get(symbol) != market for symbol in symbols_for_market):
            raise ProspectivePITDenominatorError("denominator market mapping changed")
        if any(sector_by_symbol.get(symbol) != dict(entry["market_sectors"])[symbol] for symbol in symbols_for_market):
            raise ProspectivePITDenominatorError("denominator sector mapping changed")
    if set(registry_by_market) != set(_SOURCE_MARKETS):
        raise ProspectivePITDenominatorError("denominator source_registry market set is incomplete")
    if payload.get("source_capture_dates") != sorted(set(item.isoformat() for item in source_capture_dates)):
        raise ProspectivePITDenominatorError("denominator source_capture_dates changed")
    if start < max(source_capture_dates):
        raise ProspectivePITDenominatorError("coverage_start predates source capture")
    license_document = payload.get("license_document")
    if not isinstance(license_document, Mapping):
        raise ProspectivePITDenominatorError("denominator license_document is missing")
    license_path = _resolve_child(resolved.parent, "government_open_data_license.html", "license document")
    license_bytes = _read_bounded_file(license_path, "license document")
    _validate_license_document(license_bytes)
    if (
        license_document.get("url") != DATA_GOV_LICENSE_URL
        or license_document.get("final_url") != DATA_GOV_LICENSE_URL
        or license_document.get("title") != DATA_GOV_LICENSE_TITLE
        or license_document.get("content_sha256") != _sha256_bytes(license_bytes)
        or license_document.get("content_bytes") != len(license_bytes)
    ):
        raise ProspectivePITDenominatorError("denominator license document hash mismatch")
    _validate_single_http_metadata(
        {
            "requested_url": license_document.get("url"),
            "final_url": license_document.get("final_url"),
            "http_status": 200,
            "captured_at": license_document.get("captured_at"),
            "content_type": "text/html",
        },
        requested_url=DATA_GOV_LICENSE_URL,
        now=observed_now,
        kind="data.gov license",
    )
    if payload.get("license_scope") != _license_scope(list(registry_by_market.values())):
        raise ProspectivePITDenominatorError("denominator license scope changed")
    independence = payload.get("source_independence")
    if independence != {
        "denominator_source": "data.gov.tw_dataset_resource_csv",
        "denominator_not_derived_from_archive": True,
        "json_source_used_for_pit_rows": True,
        "csv_source_used_for_expected_symbols": True,
        "companies_csv_used": False,
    }:
        raise ProspectivePITDenominatorError("denominator independence declaration is invalid")
    producer_hash = _required_sha256(payload.get("producer_code_sha256"), "producer_code_sha256")
    if producer_hash != _producer_code_sha256():
        raise ProspectivePITDenominatorError("denominator producer code hash mismatch")
    observed_at = _aware_datetime(payload.get("observed_at"), "denominator.observed_at")
    if observed_at > observed_now:
        raise ProspectivePITDenominatorError("denominator observed_at is after now")
    content_hash = _required_sha256(payload.get("content_sha256"), "content_sha256")
    body = dict(payload)
    body.pop("content_sha256", None)
    if content_hash != _sha256_json(body):
        raise ProspectivePITDenominatorError("denominator content hash mismatch")
    return dict(payload)


def _build_source_entry(
    *,
    market: str,
    contract: Mapping[str, object],
    raw_json_payload: bytes,
    raw_json_http: Mapping[str, object],
    csv_payload: bytes,
    csv_http: Mapping[str, object],
    metadata_payload: bytes,
    metadata_http: Mapping[str, object],
    swagger_payload: bytes,
    swagger_http: Mapping[str, object],
    symbols: tuple[str, ...],
    sectors: Mapping[str, str],
    publication_date: date,
    csv_publication_date: date,
) -> dict[str, object]:
    return {
        "market": market,
        "source_id": contract["source_id"],
        "dataset_id": contract["dataset_id"],
        "dataset_url": contract["dataset_url"],
        "metadata_url": contract["metadata_url"],
        "resource_url": contract["resource_url"],
        "endpoint_url": contract["endpoint_url"],
        "swagger_url": contract["swagger_url"],
        "swagger_path": contract["swagger_path"],
        "license_code": contract["license_code"],
        "license_version": contract["license_version"],
        "json_path": f"{market}_t187ap03.raw.json",
        "csv_path": f"{market}_t187ap03.csv",
        "metadata_path": f"dataset_{contract['dataset_id']}.json",
        "swagger_path_file": f"{market}_swagger.json",
        "json_content_sha256": _sha256_bytes(raw_json_payload),
        "csv_content_sha256": _sha256_bytes(csv_payload),
        "metadata_content_sha256": _sha256_bytes(metadata_payload),
        "swagger_content_sha256": _sha256_bytes(swagger_payload),
        "json_http": dict(raw_json_http),
        "csv_http": dict(csv_http),
        "metadata_http": dict(metadata_http),
        "swagger_http": dict(swagger_http),
        "json_symbol_count": len(symbols),
        "csv_symbol_count": len(symbols),
        "publication_date": publication_date.isoformat(),
        "csv_publication_date": csv_publication_date.isoformat(),
        "symbols_hash": _sha256_json(list(symbols)),
        "market_symbols": list(symbols),
        "market_sectors": dict(sorted(sectors.items())),
    }


def _license_scope(source_entries: Sequence[Mapping[str, object]]) -> dict[str, object]:
    source_ids = sorted(str(item["source_id"]) for item in source_entries)
    dataset_ids: list[int] = []
    for item in source_entries:
        value = item.get("dataset_id")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProspectivePITDenominatorError("source registry dataset_id is invalid")
        dataset_ids.append(value)
    dataset_ids.sort()
    return {
        "status": "machine_scope_verified",
        "authorization_basis": "data.gov.tw_metadata_resource_license_code_1",
        "policy_version": PIT_PROSPECTIVE_LICENSE_POLICY_VERSION,
        "machine_policy_only": True,
        "formal_acceptance_granted": True,
        "legal_acceptance_inferred": False,
        "allowed_use_cases": [
            "diagnostics",
            "research_shadow",
            "prospective_pit_sector_membership",
            "formal_pit_sector_membership",
        ],
        "formal_oos_allowed": False,
        "production_scheduler_allowed": True,
        "production_action_allowed": False,
        "redistribution_allowed": False,
        "source_ids": source_ids,
        "government_dataset_ids": dataset_ids,
        "license_code": "1",
        "license_url": DATA_GOV_LICENSE_URL,
        "license_document_sha256": DATA_GOV_LICENSE_SHA256,
        "license_document_bytes": DATA_GOV_LICENSE_BYTES,
        "endpoint_mapping_required": True,
        "source_terms_keyword_matching": False,
        "evidence_reason": (
            "dataset metadata license code 1, exact official CSV resource URL, "
            "official Swagger endpoint path, and immutable government license "
            "document fingerprint were independently revalidated"
        ),
    }


def _validate_source_metadata(
    market: str,
    contract: Mapping[str, object],
    payload: bytes,
    http: Mapping[str, object],
) -> None:
    _bounded_bytes(payload, f"{market} metadata")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProspectivePITDenominatorError(f"{market} data.gov metadata is invalid JSON") from error
    if not isinstance(value, Mapping) or value.get("success") is not True:
        raise ProspectivePITDenominatorError(f"{market} data.gov metadata response is not successful")
    result = value.get("result")
    if not isinstance(result, Mapping):
        raise ProspectivePITDenominatorError(f"{market} data.gov metadata result is missing")
    for key, expected in (
        ("datasetId", contract["dataset_id"]),
        ("identifier", contract["identifier"]),
        ("title", contract["title"]),
        ("dataProvider", contract["data_provider"]),
        ("publisherOID", contract["publisher_oid"]),
        ("license", contract["license_code"]),
    ):
        if result.get(key) != expected:
            raise ProspectivePITDenominatorError(f"{market} data.gov metadata {key} mismatch")
    notes = result.get("notes")
    notes_urls = contract.get("notes_urls")
    if not isinstance(notes_urls, (list, tuple)):
        raise ProspectivePITDenominatorError(f"{market} source contract notes URLs are invalid")
    if not isinstance(notes, str):
        raise ProspectivePITDenominatorError(f"{market} data.gov notes do not map license and Swagger URLs")
    # The current data.gov metadata records the license link as HTTP while
    # the authoritative document is fetched and pinned over HTTPS.  Accept
    # this exact historical spelling as the same data.gov policy URL, but
    # still require the exact official Swagger URL from the source contract.
    license_note_urls = {DATA_GOV_LICENSE_URL, "http://data.gov.tw/license"}
    swagger_note_urls = {
        str(url)
        for url in notes_urls
        if str(url) != DATA_GOV_LICENSE_URL
    }
    if not any(url in notes for url in license_note_urls) or any(
        url not in notes for url in swagger_note_urls
    ):
        raise ProspectivePITDenominatorError(f"{market} data.gov notes do not map license and Swagger URLs")
    distributions = result.get("distribution")
    if not isinstance(distributions, list) or len(distributions) != 1 or not isinstance(distributions[0], Mapping):
        raise ProspectivePITDenominatorError(f"{market} data.gov distribution is invalid")
    if distributions[0].get("resourceDownloadUrl") != contract["resource_url"]:
        raise ProspectivePITDenominatorError(f"{market} data.gov resource URL mismatch")
    if distributions[0].get("resourceFormat") != "CSV":
        raise ProspectivePITDenominatorError(f"{market} data.gov resource format is not CSV")
    _validate_single_http_metadata(
        http,
        requested_url=str(contract["metadata_url"]),
        now=_aware_datetime(http.get("captured_at"), f"{market} metadata captured_at"),
        kind=f"{market} metadata",
    )


def _validate_source_swagger(
    market: str,
    contract: Mapping[str, object],
    payload: bytes,
) -> None:
    _bounded_bytes(payload, f"{market} Swagger")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProspectivePITDenominatorError(f"{market} Swagger is invalid JSON") from error
    if not isinstance(value, Mapping):
        raise ProspectivePITDenominatorError(f"{market} Swagger must be an object")
    info = value.get("info")
    paths = value.get("paths")
    if not isinstance(info, Mapping) or info.get("title") != contract["swagger_title"]:
        raise ProspectivePITDenominatorError(f"{market} Swagger title mismatch")
    if not isinstance(paths, Mapping) or contract["swagger_path"] not in paths:
        raise ProspectivePITDenominatorError(f"{market} Swagger endpoint path is missing")
    if market == "twse":
        if value.get("basePath") != "/v1" or value.get("host") != "openapi.twse.com.tw":
            raise ProspectivePITDenominatorError("TWSE Swagger server mapping mismatch")
    else:
        servers = value.get("servers")
        if not isinstance(servers, list) or not any(
            isinstance(item, Mapping) and item.get("url") == "https://www.tpex.org.tw/openapi/v1"
            for item in servers
        ):
            raise ProspectivePITDenominatorError("TPEx Swagger server mapping mismatch")


def _parse_official_csv(
    market: str,
    payload: bytes,
) -> tuple[tuple[str, ...], dict[str, str], date]:
    contract = _SOURCE_CONTRACTS[market]
    try:
        text = payload.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = tuple(reader.fieldnames or ())
        required = {
            str(contract["csv_symbol_field"]),
            str(contract["csv_sector_field"]),
            str(contract["csv_publication_field"]),
        }
        if not required.issubset(fieldnames):
            raise ProspectivePITDenominatorError(f"{market} CSV schema is missing required fields")
        rows = list(reader)
    except UnicodeDecodeError as error:
        raise ProspectivePITDenominatorError(f"{market} CSV is not UTF-8") from error
    if not rows:
        raise ProspectivePITDenominatorError(f"{market} CSV is empty")
    symbols: list[str] = []
    sectors: dict[str, str] = {}
    publication_dates: set[date] = set()
    for row in rows:
        if any(value is None for value in row.values()):
            raise ProspectivePITDenominatorError(f"{market} CSV contains malformed columns")
        symbol = _normalize_symbol(row.get(str(contract["csv_symbol_field"])), f"{market} CSV symbol")
        sector = row.get(str(contract["csv_sector_field"]))
        if not isinstance(sector, str) or not re.fullmatch(r"[0-9]{2}", sector.strip()):
            raise ProspectivePITDenominatorError(f"{market} CSV sector is invalid")
        if symbol in sectors:
            raise ProspectivePITDenominatorError(f"{market} CSV contains duplicate symbol {symbol}")
        publication_dates.add(_parse_roc_date(row.get(str(contract["csv_publication_field"])), f"{market} CSV publication"))
        symbols.append(symbol)
        sectors[symbol] = sector.strip()
    if len(publication_dates) != 1:
        raise ProspectivePITDenominatorError(f"{market} CSV publication dates are inconsistent")
    return tuple(sorted(symbols)), dict(sorted(sectors.items())), next(iter(publication_dates))


def _validate_license_document(payload: bytes) -> None:
    if len(payload) != DATA_GOV_LICENSE_BYTES:
        raise ProspectivePITDenominatorError("government license document fingerprint is not the registered version")
    dynamic_tokens = re.findall(
        rb'data-cfemail=["\']([^"\']+)["\']',
        payload,
        flags=re.IGNORECASE,
    )
    if dynamic_tokens and (
        len(dynamic_tokens) != 1
        or not re.fullmatch(rb"[0-9a-f]+", dynamic_tokens[0], flags=re.IGNORECASE)
    ):
        raise ProspectivePITDenominatorError("government license document dynamic token is invalid")
    raw_hash = _sha256_bytes(payload)
    canonical_hash = _sha256_bytes(_canonical_license_document(payload))
    if raw_hash != DATA_GOV_LICENSE_SHA256 and canonical_hash != DATA_GOV_LICENSE_SHA256:
        raise ProspectivePITDenominatorError("government license document fingerprint is not the registered version")
    text = payload.decode("utf-8", errors="replace")
    if f"<title>{DATA_GOV_LICENSE_TITLE}</title>" not in text:
        raise ProspectivePITDenominatorError("government license document title is invalid")


def _canonical_license_document(payload: bytes) -> bytes:
    """移除 Cloudflare email 混淆值，保留條款其餘內容的固定指紋。"""

    canonical = re.sub(
        rb'data-cfemail="[^"]+"',
        b'data-cfemail="<dynamic-email-token>"',
        payload,
        flags=re.IGNORECASE,
    )
    return re.sub(
        rb"data-cfemail='[^']+'",
        b"data-cfemail='<dynamic-email-token>'",
        canonical,
        flags=re.IGNORECASE,
    )


def _validate_http_metadata_set(
    payloads: Mapping[str, bytes],
    metadata: Mapping[str, Mapping[str, object]],
    *,
    now: datetime,
    kind: str,
) -> None:
    if set(payloads) != set(metadata):
        raise ProspectivePITDenominatorError(f"{kind} metadata source set is incomplete")
    for market, payload in payloads.items():
        if not isinstance(payload, bytes) or not payload:
            raise ProspectivePITDenominatorError(f"{kind} {market} payload is empty")
        _bounded_bytes(payload, f"{kind} {market}")
        _validate_single_http_metadata(
            metadata[market],
            requested_url=str(metadata[market].get("requested_url") or ""),
            now=now,
            kind=f"{kind} {market}",
        )


def _validate_single_http_metadata(
    metadata: Mapping[str, object],
    *,
    requested_url: str,
    now: datetime,
    kind: str,
) -> None:
    if not isinstance(metadata, Mapping):
        raise ProspectivePITDenominatorError(f"{kind} HTTP metadata is invalid")
    if metadata.get("requested_url") != requested_url:
        raise ProspectivePITDenominatorError(f"{kind} requested URL mismatch")
    final_url = metadata.get("final_url")
    if final_url != requested_url:
        raise ProspectivePITDenominatorError(f"{kind} final URL mismatch")
    parsed = urlparse(requested_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProspectivePITDenominatorError(f"{kind} URL is not HTTPS")
    status = metadata.get("http_status")
    if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status < 300:
        raise ProspectivePITDenominatorError(f"{kind} HTTP status is not successful")
    captured = _http_captured_at(metadata, kind)
    if captured > now:
        raise ProspectivePITDenominatorError(f"{kind} completion timestamp is after now")
    content_type = metadata.get("content_type")
    if not isinstance(content_type, str) or not content_type.strip():
        raise ProspectivePITDenominatorError(f"{kind} content type is missing")


def _http_captured_at(metadata: Mapping[str, object], field_name: str) -> datetime:
    value = metadata.get("captured_at")
    return _aware_datetime(value, f"{field_name}.captured_at")


def _bounded_bytes(value: object, field_name: str) -> bytes:
    if not isinstance(value, bytes) or not value:
        raise ProspectivePITDenominatorError(f"{field_name} must be non-empty bytes")
    if len(value) > _MAX_SOURCE_BYTES:
        raise ProspectivePITDenominatorError(f"{field_name} exceeds bounded size")
    return value


def _normalize_symbols(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ProspectivePITDenominatorError("denominator symbols must be non-empty array")
    symbols: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _SYMBOL_RE.fullmatch(item):
            raise ProspectivePITDenominatorError("denominator symbols are invalid")
        symbols.append(item)
    normalized = tuple(symbols)
    if normalized != tuple(sorted(set(normalized))):
        raise ProspectivePITDenominatorError("denominator symbols must be sorted and unique")
    return normalized


def _normalize_symbol(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SYMBOL_RE.fullmatch(value.strip()):
        raise ProspectivePITDenominatorError(f"{field_name} is invalid")
    return value.strip()


def _parse_roc_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProspectivePITDenominatorError(f"{field_name} is invalid")
    digits = re.sub(r"\D", "", value)
    if len(digits) != 7:
        raise ProspectivePITDenominatorError(f"{field_name} must be ROC YYYYMMDD")
    try:
        result = date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
    except ValueError as error:
        raise ProspectivePITDenominatorError(f"{field_name} is invalid") from error
    return result


def _required_date(value: object, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ProspectivePITDenominatorError(f"{field_name} must be a date")
    return value


def _parse_iso_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProspectivePITDenominatorError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ProspectivePITDenominatorError(f"{field_name} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ProspectivePITDenominatorError(f"{field_name} must be YYYY-MM-DD")
    return parsed


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ProspectivePITDenominatorError(f"{field_name} must be ISO timestamp") from error
    else:
        raise ProspectivePITDenominatorError(f"{field_name} must be ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectivePITDenominatorError(f"{field_name} must include timezone")
    return parsed


def _expect(actual: object, expected: object, field_name: str) -> None:
    if actual != expected:
        raise ProspectivePITDenominatorError(f"denominator {field_name} is invalid")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectivePITDenominatorError(f"{field_name} must be non-empty text")
    return value


def _required_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProspectivePITDenominatorError(f"{field_name} must be sha256 digest")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProspectivePITDenominatorError(f"{field_name} must be an object")
    return value


def _resolve_child(root: Path, value: object, field_name: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ProspectivePITDenominatorError(f"{field_name} path is invalid")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ProspectivePITDenominatorError(f"{field_name} path escapes denominator root") from error
    return path


def _read_bounded_file(path: Path, field_name: str) -> bytes:
    try:
        value = path.read_bytes()
    except OSError as error:
        raise ProspectivePITDenominatorError(f"{field_name} is unreadable") from error
    return _bounded_bytes(value, field_name)


def _require_output_root(path: Path) -> None:
    repo_output = Path(__file__).resolve().parents[1] / "output"
    temp_root = Path(__import__("tempfile").gettempdir()).resolve()
    try:
        path.relative_to(repo_output.resolve())
    except ValueError:
        try:
            path.relative_to(temp_root)
        except ValueError as error:
            raise ProspectivePITDenominatorError(
                "denominator output must be under repository output or TEMP"
            ) from error


def _write_create_only_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
    except FileExistsError:
        if path.read_bytes() != value:
            raise ProspectivePITDenominatorError(
                f"immutable denominator child differs on retry: {path.name}"
            )


def _write_create_only_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    _write_create_only_bytes(path, encoded)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _producer_code_sha256() -> str:
    return _file_sha256(Path(__file__).resolve())


__all__ = [
    "DATA_GOV_LICENSE_SHA256",
    "DATA_GOV_LICENSE_TITLE",
    "DATA_GOV_LICENSE_URL",
    "PIT_PROSPECTIVE_DENOMINATOR_PRODUCER_VERSION",
    "PIT_PROSPECTIVE_DENOMINATOR_SCHEMA_VERSION",
    "PIT_PROSPECTIVE_LICENSE_POLICY_VERSION",
    "ProspectivePITDenominatorError",
    "build_prospective_pit_denominator",
    "validate_prospective_pit_denominator",
]

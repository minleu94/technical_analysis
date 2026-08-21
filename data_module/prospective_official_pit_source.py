"""TWSE／TPEX 官方公司基本資料的 prospective PIT producer。

這個 producer 只接受呼叫端明確提供的官方 OpenAPI raw bytes；它不讀取
``companies.csv``、不把 current snapshot 改名成 Formal，也不回填歷史產業
歸屬。raw bytes、官方出表日期、抓取可得時間、clock／universe lineage 與
canonical rows hash 會一起進入 source registry，後續再交給既有的
prospective PIT sidecar validator 做 clock-bound create-only 寫入。

網路抓取刻意不放在這裡。這讓 HTTP transport、授權與 raw bytes custody
可以由受控入口注入，並使 fixture／staging 不會意外啟動 legacy watcher 或
修改任何既有資料。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo


OFFICIAL_PROSPECTIVE_PIT_SOURCE_SCHEMA_VERSION = (
    "prospective-official-company-basic-pit-source.v1"
)
OFFICIAL_PROSPECTIVE_PIT_RESULT_SCHEMA_VERSION = (
    "prospective-official-company-basic-pit-capture.v1"
)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[0-9]{4,6}$")
_SECTOR_RE = re.compile(r"^[0-9]{2}$")


class ProspectiveOfficialPITSourceError(ValueError):
    """官方 prospective PIT source 不符合 fail-closed 契約。"""


@dataclass(frozen=True)
class OfficialCompanySourceDefinition:
    """一個被明確允許的官方公司基本資料 endpoint。"""

    market: str
    source_id: str
    dataset_id: str
    endpoint: str
    symbol_field: str
    sector_field: str
    publication_field: str


OFFICIAL_COMPANY_SOURCE_DEFINITIONS: dict[str, OfficialCompanySourceDefinition] = {
    "twse": OfficialCompanySourceDefinition(
        market="twse_listed",
        source_id="official:twse:t187ap03_L",
        dataset_id="t187ap03_L",
        endpoint="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        symbol_field="公司代號",
        sector_field="產業別",
        publication_field="出表日期",
    ),
    "tpex": OfficialCompanySourceDefinition(
        market="tpex_otc",
        source_id="official:tpex:t187ap03_O",
        dataset_id="t187ap03_O",
        endpoint="https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
        symbol_field="SecuritiesCompanyCode",
        sector_field="SecuritiesIndustryCode",
        publication_field="Date",
    ),
    "emerging": OfficialCompanySourceDefinition(
        market="tpex_emerging",
        source_id="official:tpex:t187ap03_R",
        dataset_id="t187ap03_R",
        endpoint="https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R",
        symbol_field="SecuritiesCompanyCode",
        sector_field="SecuritiesIndustryCode",
        publication_field="Date",
    ),
}


@dataclass(frozen=True)
class OfficialProspectivePITCapture:
    """供既有 PIT sidecar writer 消費的 rows 與 source registry。"""

    rows: tuple[dict[str, object], ...]
    source_registry: tuple[dict[str, object], ...]
    expected_symbols: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """只輸出 lineage 摘要與 rows；不輸出 raw bytes 以外的秘密。"""

        return {
            "schema_version": OFFICIAL_PROSPECTIVE_PIT_RESULT_SCHEMA_VERSION,
            "status": "accepted",
            "row_count": len(self.rows),
            "source_ids": [str(item["source_id"]) for item in self.source_registry],
            "source_hashes": [str(item["source_hash"]) for item in self.source_registry],
            "canonical_rows_hashes": [
                str(item["canonical_rows_hash"])
                for item in self.source_registry
            ],
            "clock_ids": sorted(
                {str(item["clock_id"]) for item in self.source_registry}
            ),
            "universe_hashes": sorted(
                {str(item["universe_hash"]) for item in self.source_registry}
            ),
            "expected_symbol_count": len(self.expected_symbols),
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "secret_values_emitted": False,
        }


@dataclass(frozen=True)
class _ParsedOfficialSource:
    definition: OfficialCompanySourceDefinition
    publication_date: date
    schema_fields: tuple[str, ...]
    rows: tuple[tuple[str, str, date], ...]
    rows_by_symbol: Mapping[str, tuple[str, date]]


def build_official_first_seen_capture(
    *,
    raw_payloads: Mapping[str, bytes],
    license_ids: Mapping[str, str],
    license_urls: Mapping[str, str],
    publication_at: Mapping[str, datetime],
    expected_symbols: Sequence[str],
    clock_id: str,
    clock_manifest_hash: str,
    universe_hash: str,
    available_at: datetime,
    effective_from: date,
    now: datetime,
) -> OfficialProspectivePITCapture:
    """建立官方 first-seen prospective PIT rows。

    ``raw_payloads`` 的 bytes 必須是 HTTP response 的原始 UTF-8 JSON bytes；
    producer 不接受已由 ``companies.csv`` 或其他 current snapshot 轉換的 rows。
    ``emerging`` 只有在 expected universe 確實只能由 R endpoint 覆蓋時才可
    使用；若 L/O 已可覆蓋全部 universe，傳入 R 會直接 fail closed。
    """

    expected = _normalize_expected_symbols(expected_symbols)
    _require_text(clock_id, "clock_id")
    _require_sha256(clock_manifest_hash, "clock_manifest_hash")
    _require_sha256(universe_hash, "universe_hash")
    now_taipei = _normalize_aware(now, "now")
    available_taipei = _normalize_aware(available_at, "available_at")
    if available_taipei > now_taipei:
        raise ProspectiveOfficialPITSourceError(
            "available_at cannot be after capture now"
        )
    if effective_from < now_taipei.date():
        raise ProspectiveOfficialPITSourceError(
            "effective_from cannot be before the prospective first-seen capture date"
        )
    if not raw_payloads:
        raise ProspectiveOfficialPITSourceError("at least one official raw payload is required")

    unknown_markets = set(raw_payloads) - set(OFFICIAL_COMPANY_SOURCE_DEFINITIONS)
    if unknown_markets:
        raise ProspectiveOfficialPITSourceError(
            "unknown official company source market: "
            + ", ".join(sorted(unknown_markets))
        )
    parsed_sources: dict[str, _ParsedOfficialSource] = {}
    for market, raw_payload in raw_payloads.items():
        definition = OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market]
        parsed_sources[market] = _parse_official_source(
            definition,
            raw_payload,
        )

    matches: dict[str, list[str]] = {symbol: [] for symbol in expected}
    for market, parsed in parsed_sources.items():
        for symbol in expected:
            if symbol in parsed.rows_by_symbol:
                matches[symbol].append(market)
    missing = sorted(symbol for symbol, markets in matches.items() if not markets)
    if missing:
        raise ProspectiveOfficialPITSourceError(
            "official company source is missing expected symbols: "
            + ", ".join(missing[:12])
        )
    duplicated = sorted(symbol for symbol, markets in matches.items() if len(markets) > 1)
    if duplicated:
        raise ProspectiveOfficialPITSourceError(
            "official company symbol appears in multiple market sources: "
            + ", ".join(duplicated[:12])
        )

    emerging_symbols = [
        symbol for symbol, markets in matches.items() if markets == ["emerging"]
    ]
    if "emerging" in parsed_sources and not emerging_symbols:
        raise ProspectiveOfficialPITSourceError(
            "t187ap03_R is allowed only when the clock universe contains emerging symbols"
        )
    required_markets = {markets[0] for markets in matches.values()}
    unused_markets = set(parsed_sources) - required_markets
    if unused_markets:
        raise ProspectiveOfficialPITSourceError(
            "official source supplied for a market outside the clock universe: "
            + ", ".join(sorted(unused_markets))
        )

    rows: list[dict[str, object]] = []
    source_registry: list[dict[str, object]] = []
    for market in sorted(required_markets):
        parsed = parsed_sources[market]
        license_id = _required_license(license_ids.get(market), market)
        license_url = _required_url(license_urls.get(market), market)
        source_publication_at = _normalize_aware(
            publication_at.get(market),
            f"publication_at[{market}]",
        )
        if source_publication_at.date() != parsed.publication_date:
            raise ProspectiveOfficialPITSourceError(
                f"publication_at[{market}] does not match official publication date"
            )
        if source_publication_at > available_taipei:
            raise ProspectiveOfficialPITSourceError(
                f"publication_at[{market}] is after available_at"
            )
        raw_hash = _sha256_bytes(raw_payloads[market])
        canonical_rows_hash = _sha256_json(
            {
                "schema_version": OFFICIAL_PROSPECTIVE_PIT_SOURCE_SCHEMA_VERSION,
                "dataset_id": parsed.definition.dataset_id,
                "rows": [
                    {
                        "symbol": symbol,
                        "sector_id": sector_id,
                        "publication_date": publication.isoformat(),
                    }
                    for symbol, sector_id, publication in parsed.rows
                ],
            }
        )
        source_entry: dict[str, object] = {
            "source_id": parsed.definition.source_id,
            "license_id": license_id,
            "source_hash": raw_hash,
            "source_version": (
                f"{parsed.definition.dataset_id}:{parsed.publication_date.isoformat()}"
            ),
            "publication_at": source_publication_at.isoformat(),
            "allowed_use": ["prospective_pit_sector_membership"],
            "source_kind": "official_company_basic_first_seen",
            "dataset_id": parsed.definition.dataset_id,
            "market": parsed.definition.market,
            "endpoint": parsed.definition.endpoint,
            "license_url": license_url,
            "raw_hash": raw_hash,
            "canonical_rows_hash": canonical_rows_hash,
            "publication_date": parsed.publication_date.isoformat(),
            "available_at": available_taipei.isoformat(),
            "effective_from": effective_from.isoformat(),
            "clock_id": clock_id,
            "clock_manifest_hash": clock_manifest_hash,
            "universe_hash": universe_hash,
            "schema_fields": list(parsed.schema_fields),
        }
        source_entry["source_registry_hash"] = _sha256_json(source_entry)
        source_registry.append(source_entry)

        for symbol in expected:
            if matches[symbol][0] != market:
                continue
            sector_id, _ = parsed.rows_by_symbol[symbol]
            rows.append(
                {
                    "symbol": symbol,
                    "sector_id": sector_id,
                    "available_at": available_taipei.isoformat(),
                    "effective_from": effective_from.isoformat(),
                    "effective_to": None,
                    "status": "accepted",
                    "source_id": parsed.definition.source_id,
                    "license_id": license_id,
                    "source_hash": raw_hash,
                }
            )

    rows.sort(
        key=lambda row: (
            str(row["symbol"]),
            str(row["effective_from"]),
            str(row["available_at"]),
            str(row["sector_id"]),
        )
    )
    source_registry.sort(key=lambda item: str(item["source_id"]))
    return OfficialProspectivePITCapture(
        rows=tuple(rows),
        source_registry=tuple(source_registry),
        expected_symbols=expected,
    )


def _parse_official_source(
    definition: OfficialCompanySourceDefinition,
    raw_payload: bytes,
) -> _ParsedOfficialSource:
    if not isinstance(raw_payload, bytes) or not raw_payload:
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} raw payload must be non-empty bytes"
        )
    try:
        decoded = raw_payload.decode("utf-8-sig")
        value: Any = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} raw payload is not valid UTF-8 JSON"
        ) from error
    if not isinstance(value, list) or not value:
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} raw payload must be a non-empty array"
        )
    if any(not isinstance(item, dict) for item in value):
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} raw payload rows must be objects"
        )

    first = value[0]
    if not isinstance(first, dict):  # pragma: no cover - guarded above
        raise AssertionError("official source row must be a dict")
    schema_fields = tuple(sorted(str(key) for key in first))
    required_fields = {
        definition.symbol_field,
        definition.sector_field,
        definition.publication_field,
    }
    if not required_fields.issubset(schema_fields):
        missing = sorted(required_fields - set(schema_fields))
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} raw schema is missing fields: {', '.join(missing)}"
        )

    normalized_rows: list[tuple[str, str, date]] = []
    rows_by_symbol: dict[str, tuple[str, date]] = {}
    for item in value:
        if not isinstance(item, dict):  # pragma: no cover - guarded above
            raise AssertionError("official source row must be a dict")
        if tuple(sorted(str(key) for key in item)) != schema_fields:
            raise ProspectiveOfficialPITSourceError(
                f"{definition.dataset_id} raw rows do not share one schema"
            )
        symbol = _normalize_symbol(item.get(definition.symbol_field), definition)
        sector_id = _normalize_sector(item.get(definition.sector_field), definition)
        publication_date = _parse_official_date(
            item.get(definition.publication_field),
            definition,
        )
        if symbol in rows_by_symbol:
            raise ProspectiveOfficialPITSourceError(
                f"{definition.dataset_id} contains duplicate company symbol {symbol}"
            )
        rows_by_symbol[symbol] = (sector_id, publication_date)
        normalized_rows.append((symbol, sector_id, publication_date))

    publication_dates = {row[2] for row in normalized_rows}
    if len(publication_dates) != 1:
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} contains inconsistent official publication dates"
        )
    return _ParsedOfficialSource(
        definition=definition,
        publication_date=next(iter(publication_dates)),
        schema_fields=schema_fields,
        rows=tuple(sorted(normalized_rows)),
        rows_by_symbol=rows_by_symbol,
    )


def _normalize_expected_symbols(value: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ProspectiveOfficialPITSourceError(
            "expected_symbols must be a non-empty array"
        )
    normalized = tuple(_require_text(item, "expected_symbols") for item in value)
    if any(not _SYMBOL_RE.fullmatch(item) for item in normalized):
        raise ProspectiveOfficialPITSourceError(
            "expected_symbols must contain 4-6 digit symbols"
        )
    if normalized != tuple(sorted(set(normalized))):
        raise ProspectiveOfficialPITSourceError(
            "expected_symbols must be unique and sorted"
        )
    return normalized


def _normalize_symbol(
    value: object,
    definition: OfficialCompanySourceDefinition,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} company symbol must preserve text leading zeros"
        )
    symbol = value.strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} company symbol is invalid"
        )
    return symbol


def _normalize_sector(
    value: object,
    definition: OfficialCompanySourceDefinition,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} industry code must be text"
        )
    sector_id = value.strip()
    if not _SECTOR_RE.fullmatch(sector_id) or sector_id == "00":
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} industry code is unknown or invalid"
        )
    known_codes = {
        "01", "02", "03", "04", "05", "06", "08", "09", "10", "11",
        "12", "14", "15", "16", "17", "18", "20", "21", "22", "23",
        "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
        "34", "35", "36", "37", "38", "80", "91",
    }
    if sector_id not in known_codes:
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} industry code is unknown or invalid"
        )
    return sector_id


def _parse_official_date(
    value: object,
    definition: OfficialCompanySourceDefinition,
) -> date:
    if not isinstance(value, str):
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} publication date must be text"
        )
    text = value.strip().replace("/", "-")
    if re.fullmatch(r"[0-9]{7}", text):
        text = f"{int(text[:3]) + 1911:04d}-{text[3:5]}-{text[5:7]}"
    elif re.fullmatch(r"[0-9]{3}-[0-9]{2}-[0-9]{2}", text):
        text = f"{int(text[:3]) + 1911:04d}-{text[4:6]}-{text[7:9]}"
    elif re.fullmatch(r"[0-9]{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ProspectiveOfficialPITSourceError(
            f"{definition.dataset_id} publication date is invalid"
        ) from error
    return parsed


def _normalize_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveOfficialPITSourceError(
            f"{field_name} must be timezone-aware datetime"
        )
    return value.astimezone(TAIPEI_TIMEZONE)


def _required_license(value: object, market: str) -> str:
    license_id = _require_text(value, f"license_id[{market}]")
    if license_id.casefold() in {"unknown", "unlicensed", "none", "not_provided"}:
        raise ProspectiveOfficialPITSourceError(
            f"license_id[{market}] is not an authorized license identity"
        )
    return license_id


def _required_url(value: object, market: str) -> str:
    url = _require_text(value, f"license_url[{market}]")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ProspectiveOfficialPITSourceError(
            f"license_url[{market}] must be an HTTP(S) URL"
        )
    return url


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveOfficialPITSourceError(f"{field_name} must be non-empty text")
    return value.strip()


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ProspectiveOfficialPITSourceError(f"{field_name} must be sha256")
    return value


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result

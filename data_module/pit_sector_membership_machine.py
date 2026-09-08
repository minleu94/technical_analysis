"""官方公司基本資料的 current natural-day PIT sector machine producer。

本模組提供一條可重驗的 source producer／consumer 鏈：producer 只接受官方
TWSE/TPEx OpenAPI 的原始 JSON bytes，保存 raw custody、first-seen rows、來源
版本與 hash；consumer 重新讀取 raw bytes 並重建相同 rows，才會簽發
``machine_verified`` receipt。

這條鏈是 candidate evidence。``effective_from`` 只代表本次實際抓取的
自然日，沒有歷史 PIT backfill、prospective clock、Formal OOS 或 promotion
權限。正式輸入仍須由 owner-controlled publisher 在正式路徑發布。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from data_module.prospective_official_pit_source import (
    OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
    _parse_official_source,
    build_official_first_seen_capture,
)


MACHINE_PIT_PUBLICATION_SCHEMA_VERSION = (
    "pit-sector-membership-machine-publication.v1"
)
MACHINE_PIT_RECEIPT_SCHEMA_VERSION = "pit-sector-membership-machine-receipt.v1"
MACHINE_PIT_INPUT_SCHEMA_VERSION = "pit-sector-membership-sidecar-v1"
MACHINE_PIT_PRODUCER_VERSION = "official-company-basic-first-seen.v1"
MACHINE_PIT_CONSUMER_VERSION = "pit-sector-membership-machine-consumer.v1"
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")

DEFAULT_LICENSE_IDS: dict[str, str] = {
    "twse": "twse-open-data-license-v1",
    "tpex": "tpex-open-data-license-v1",
}
DEFAULT_LICENSE_URLS: dict[str, str] = {
    "twse": "https://openapi.twse.com.tw/",
    "tpex": "https://www.tpex.org.tw/openapi/",
}
_SOURCE_MARKETS = ("twse", "tpex")
_SHA256_PREFIX = "sha256:"


class MachinePITSourceError(ValueError):
    """官方 PIT machine source 或 receipt 不符合契約。"""


@dataclass(frozen=True)
class MachinePITPublicationResult:
    publication_path: Path
    publication_file_hash: str
    publication_content_hash: str
    capture_id: str
    captured_at: str
    effective_from: str
    row_count: int
    source_ids: tuple[str, ...]
    producer_code_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MACHINE_PIT_PUBLICATION_SCHEMA_VERSION,
            "status": "machine_verified_candidate",
            "publication_path": str(self.publication_path),
            "publication_file_hash": self.publication_file_hash,
            "publication_content_hash": self.publication_content_hash,
            "capture_id": self.capture_id,
            "captured_at": self.captured_at,
            "effective_from": self.effective_from,
            "row_count": self.row_count,
            "source_ids": list(self.source_ids),
            "producer_code_sha256": self.producer_code_sha256,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
        }


@dataclass(frozen=True)
class MachinePITValidation:
    publication_path: Path
    publication_file_hash: str
    publication_content_hash: str
    capture_id: str
    captured_at: str
    effective_from: str
    row_count: int
    source_ids: tuple[str, ...]
    producer_code_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "machine_verified",
            "input": "pit_sector_membership",
            "input_schema_version": MACHINE_PIT_INPUT_SCHEMA_VERSION,
            "source_lane": "current_natural_day_machine_capture",
            "publication_path": str(self.publication_path),
            "publication_file_hash": self.publication_file_hash,
            "publication_content_hash": self.publication_content_hash,
            "capture_id": self.capture_id,
            "captured_at": self.captured_at,
            "effective_from": self.effective_from,
            "row_count": self.row_count,
            "source_ids": list(self.source_ids),
            "producer_code_sha256": self.producer_code_sha256,
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "historical_backfill_claimed": False,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "production_action_allowed": False,
        }


def build_machine_pit_publication(
    *,
    raw_payloads: Mapping[str, bytes],
    output_dir: Path,
    captured_at: datetime,
    now: datetime | None = None,
    expected_symbols: Sequence[str] | None = None,
    license_ids: Mapping[str, str] | None = None,
    license_urls: Mapping[str, str] | None = None,
    http_metadata: Mapping[str, Mapping[str, object]] | None = None,
) -> MachinePITPublicationResult:
    """將官方 raw response 封裝成 current-day machine publication。

    ``expected_symbols`` 若省略，僅使用本次兩個官方市場 endpoint 的 union，
    並在 manifest 標明此 denominator 非獨立歷史 universe。這使 live capture
    可以先完成 source custody；Formal PIT 仍不會因這個觀測而自動通過。
    """

    captured = _aware_datetime(captured_at, "captured_at")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    )
    if captured > observed_now:
        raise MachinePITSourceError("captured_at cannot be after now")
    if not isinstance(raw_payloads, Mapping) or not raw_payloads:
        raise MachinePITSourceError("raw_payloads must be a non-empty mapping")
    unknown_markets = set(raw_payloads) - set(_SOURCE_MARKETS)
    if unknown_markets:
        raise MachinePITSourceError(
            "unknown official PIT market: " + ", ".join(sorted(unknown_markets))
        )
    if set(raw_payloads) != set(_SOURCE_MARKETS):
        raise MachinePITSourceError(
            "current PIT capture requires both TWSE listed and TPEx OTC sources"
        )

    normalized_http = _normalize_http_metadata(
        raw_payloads=raw_payloads,
        captured_at=captured,
        now=observed_now,
        metadata=http_metadata,
    )

    parsed = {}
    for market in _SOURCE_MARKETS:
        raw = raw_payloads.get(market)
        if not isinstance(raw, bytes) or not raw:
            raise MachinePITSourceError(
                f"{market} raw payload must be non-empty bytes"
            )
        definition = OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market]
        parsed[market] = _parse_official_source(definition, raw)

    observed_symbols = sorted(
        {
            str(symbol)
            for parsed_source in parsed.values()
            for symbol in parsed_source.rows_by_symbol
        }
    )
    if expected_symbols is None:
        expected = tuple(observed_symbols)
        universe_basis = "official_source_union_current_observation"
    else:
        expected = _normalize_symbols(expected_symbols)
        universe_basis = "explicit_current_capture_scope"
    if not expected:
        raise MachinePITSourceError("expected current PIT symbol universe is empty")

    licenses = dict(DEFAULT_LICENSE_IDS)
    if license_ids is not None:
        licenses.update(_text_mapping(license_ids, "license_ids"))
    urls = dict(DEFAULT_LICENSE_URLS)
    if license_urls is not None:
        urls.update(_text_mapping(license_urls, "license_urls"))
    publication_at = {
        market: datetime.combine(
            parsed[market].publication_date,
            time.min,
            tzinfo=TAIPEI_TIMEZONE,
        )
        for market in _SOURCE_MARKETS
    }
    capture_date = captured.astimezone(TAIPEI_TIMEZONE).date()
    universe_hash = _sha256_json(list(expected))
    machine_clock_id = f"machine:natural-day:{capture_date.isoformat()}"
    machine_clock_hash = _sha256_json(
        {
            "schema_version": "machine-natural-day-capture.v1",
            "clock_id": machine_clock_id,
            "captured_at": captured.isoformat(),
            "effective_from": capture_date.isoformat(),
            "universe_hash": universe_hash,
        }
    )
    try:
        capture = build_official_first_seen_capture(
            raw_payloads=raw_payloads,
            license_ids=licenses,
            license_urls=urls,
            publication_at=publication_at,
            expected_symbols=expected,
            clock_id=machine_clock_id,
            clock_manifest_hash=machine_clock_hash,
            universe_hash=universe_hash,
            available_at=captured,
            effective_from=capture_date,
            now=observed_now,
        )
    except (TypeError, ValueError) as error:
        raise MachinePITSourceError(str(error)) from error

    output = output_dir.expanduser().resolve()
    _require_temp_directory(output)
    if not output.is_dir():
        raise MachinePITSourceError("machine PIT output directory must exist")
    raw_input_entries: list[dict[str, object]] = []
    source_registry: list[dict[str, object]] = []
    source_by_id = {
        str(source["source_id"]): dict(source)
        for source in capture.source_registry
    }
    for market in _SOURCE_MARKETS:
        raw_name = f"{market}_t187ap03.raw.json"
        raw_path = output / raw_name
        raw = raw_payloads[market]
        _create_bytes(raw_path, raw)
        source_id = OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].source_id
        source = source_by_id.get(source_id)
        if source is None:  # pragma: no cover - guarded by capture
            raise MachinePITSourceError("machine source registry is incomplete")
        source["raw_path"] = raw_name
        source["publication_time_precision"] = "date_only"
        source["capture_scope"] = "current_natural_day"
        source_registry.append(source)
        raw_input_entries.append(
            {
                "market": market,
                "source_id": source_id,
                "path": raw_name,
                "content_sha256": _sha256_bytes(raw),
                "content_bytes": len(raw),
                "http": normalized_http[market],
            }
        )

    source_registry.sort(key=lambda item: str(item["source_id"]))
    raw_input_entries.sort(key=lambda item: str(item["source_id"]))
    capture_identity = {
        "schema_version": MACHINE_PIT_PUBLICATION_SCHEMA_VERSION,
        "producer_version": MACHINE_PIT_PRODUCER_VERSION,
        "captured_at": captured.isoformat(),
        "effective_from": capture_date.isoformat(),
        "universe_hash": universe_hash,
        "source_hashes": [
            str(item["source_hash"]) for item in source_registry
        ],
    }
    capture_id = "pit-machine:" + _sha256_json(capture_identity)[7:27]
    publication_body: dict[str, object] = {
        "schema_version": MACHINE_PIT_PUBLICATION_SCHEMA_VERSION,
        "status": "complete",
        "producer": "data_module.pit_sector_membership_machine",
        "producer_version": MACHINE_PIT_PRODUCER_VERSION,
        "producer_code_sha256": _producer_code_sha256(),
        "input_schema_version": MACHINE_PIT_INPUT_SCHEMA_VERSION,
        "capture_id": capture_id,
        "captured_at": captured.isoformat(),
        "effective_from": capture_date.isoformat(),
        "scope": "current_natural_day",
        "historical_backfill_claimed": False,
        "formal_source_only": True,
        "formal_consumer_compatible": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
        "candidate_only": True,
        "universe": {
            "symbols": list(expected),
            "symbol_count": len(expected),
            "hash": universe_hash,
            "basis": universe_basis,
        },
        "source_registry": source_registry,
        "raw_inputs": raw_input_entries,
        "rows": [dict(row) for row in capture.rows],
        "row_count": len(capture.rows),
        "first_seen_policy": {
            "name": "official_source_first_observed_only",
            "effective_from_is_capture_date": True,
            "historical_pit_credit": False,
            "official_publication_time_claimed": False,
        },
        "license_scope": {
            "status": "declared_official_open_api_identity",
            "formal_acceptance_granted": False,
            "allowed_use_cases": ["research_shadow", "diagnostics"],
            "redistribution_allowed": False,
        },
    }
    content_hash = _sha256_json(publication_body)
    publication = {**publication_body, "content_sha256": content_hash}
    publication_path = output / "pit-sector-membership-machine.json"
    _create_json(publication_path, publication)
    return MachinePITPublicationResult(
        publication_path=publication_path,
        publication_file_hash=_file_sha256(publication_path),
        publication_content_hash=content_hash,
        capture_id=capture_id,
        captured_at=captured.isoformat(),
        effective_from=capture_date.isoformat(),
        row_count=len(capture.rows),
        source_ids=tuple(sorted(source_by_id)),
        producer_code_sha256=str(publication_body["producer_code_sha256"]),
    )


def validate_machine_pit_publication(
    publication_path: Path,
    *,
    now: datetime | None = None,
) -> MachinePITValidation:
    """重新讀取 publication 與每一個 raw source，驗證完整 custody。"""

    path = publication_path.expanduser().resolve()
    if not path.is_file():
        raise MachinePITSourceError("machine PIT publication is missing")
    payload = _read_json_object(path, "machine PIT publication")
    content_hash = _required_sha256(payload.get("content_sha256"), "content_sha256")
    body = dict(payload)
    body.pop("content_sha256", None)
    if _sha256_json(body) != content_hash:
        raise MachinePITSourceError("machine PIT publication content hash mismatch")
    _require_exact(
        payload,
        {
            "schema_version", "status", "producer", "producer_version",
            "producer_code_sha256", "input_schema_version", "capture_id",
            "captured_at", "effective_from", "scope",
            "historical_backfill_claimed", "formal_source_only",
            "formal_consumer_compatible", "formal_oos_allowed",
            "promotion_eligible", "production_action_allowed", "candidate_only",
            "universe", "source_registry", "raw_inputs", "rows", "row_count",
            "first_seen_policy", "license_scope", "content_sha256",
        },
        "machine PIT publication",
    )
    if payload.get("schema_version") != MACHINE_PIT_PUBLICATION_SCHEMA_VERSION:
        raise MachinePITSourceError("machine PIT publication schema is unsupported")
    if payload.get("status") != "complete":
        raise MachinePITSourceError("machine PIT publication is incomplete")
    if payload.get("producer") != "data_module.pit_sector_membership_machine":
        raise MachinePITSourceError("machine PIT producer identity is invalid")
    if payload.get("producer_version") != MACHINE_PIT_PRODUCER_VERSION:
        raise MachinePITSourceError("machine PIT producer version is invalid")
    producer_code = _required_sha256(
        payload.get("producer_code_sha256"), "producer_code_sha256"
    )
    if producer_code != _producer_code_sha256():
        raise MachinePITSourceError("machine PIT producer code hash mismatch")
    if payload.get("input_schema_version") != MACHINE_PIT_INPUT_SCHEMA_VERSION:
        raise MachinePITSourceError("machine PIT input schema is invalid")
    for field_name, expected in (
        ("scope", "current_natural_day"),
        ("historical_backfill_claimed", False),
        ("formal_source_only", True),
        ("formal_consumer_compatible", False),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("production_action_allowed", False),
        ("candidate_only", True),
    ):
        actual = payload.get(field_name)
        if (
            actual is not expected
            if isinstance(expected, bool)
            else actual != expected
        ):
            raise MachinePITSourceError(
                f"machine PIT publication {field_name} is invalid"
            )
    captured = _aware_datetime(payload.get("captured_at"), "captured_at")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    )
    if captured > observed_now:
        raise MachinePITSourceError("machine PIT captured_at is after validation now")
    effective_from = payload.get("effective_from")
    if not isinstance(effective_from, str):
        raise MachinePITSourceError("machine PIT effective_from is invalid")
    if effective_from != captured.astimezone(TAIPEI_TIMEZONE).date().isoformat():
        raise MachinePITSourceError(
            "machine PIT effective_from must equal captured natural date"
        )
    capture_id = _required_text(payload.get("capture_id"), "capture_id")
    universe = _mapping(payload.get("universe"), "universe")
    symbols = _normalize_symbols(universe.get("symbols"))
    if universe.get("symbol_count") != len(symbols):
        raise MachinePITSourceError("machine PIT universe symbol_count mismatch")
    universe_hash = _required_sha256(universe.get("hash"), "universe.hash")
    if universe_hash != _sha256_json(list(symbols)):
        raise MachinePITSourceError("machine PIT universe hash mismatch")
    if universe.get("basis") not in {
        "official_source_union_current_observation",
        "explicit_current_capture_scope",
    }:
        raise MachinePITSourceError("machine PIT universe basis is invalid")

    raw_inputs = _mapping_sequence(payload.get("raw_inputs"), "raw_inputs")
    source_registry = _mapping_sequence(
        payload.get("source_registry"), "source_registry"
    )
    if len(raw_inputs) != len(_SOURCE_MARKETS) or len(source_registry) != len(_SOURCE_MARKETS):
        raise MachinePITSourceError("machine PIT must contain both official sources")
    raw_by_source: dict[str, bytes] = {}
    observed_http_by_market: dict[str, Mapping[str, object]] = {}
    input_by_source: dict[str, Mapping[str, object]] = {}
    for item in raw_inputs:
        source_id = _required_text(item.get("source_id"), "raw_inputs.source_id")
        if source_id in input_by_source:
            raise MachinePITSourceError("machine PIT raw input source ids must be unique")
        market = _required_text(item.get("market"), "raw_inputs.market")
        if market not in _SOURCE_MARKETS:
            raise MachinePITSourceError("machine PIT raw input market is invalid")
        _require_exact(
            item,
            {
                "market",
                "source_id",
                "path",
                "content_sha256",
                "content_bytes",
                "http",
            },
            "machine PIT raw input",
        )
        relative = _required_text(item.get("path"), "raw_inputs.path")
        raw_path = _resolve_child(path.parent, relative)
        try:
            raw = raw_path.read_bytes()
        except OSError as error:
            raise MachinePITSourceError("machine PIT raw custody is unreadable") from error
        expected_hash = _required_sha256(
            item.get("content_sha256"), "raw_inputs.content_sha256"
        )
        if _sha256_bytes(raw) != expected_hash:
            raise MachinePITSourceError("machine PIT raw custody hash mismatch")
        if item.get("content_bytes") != len(raw):
            raise MachinePITSourceError("machine PIT raw custody byte count mismatch")
        expected_definition = OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market]
        if source_id != expected_definition.source_id:
            raise MachinePITSourceError("machine PIT raw source identity mismatch")
        market_http = _mapping(item.get("http"), "raw_inputs.http")
        observed_http_by_market[market] = market_http
        input_by_source[source_id] = item
        raw_by_source[market] = raw
    expected_source_ids = {
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].source_id
        for market in _SOURCE_MARKETS
    }
    if set(input_by_source) != expected_source_ids:
        raise MachinePITSourceError("machine PIT raw source set is incomplete")
    normalized_http = _normalize_http_metadata(
        raw_payloads=raw_by_source,
        captured_at=captured,
        now=observed_now,
        metadata={
            market: dict(value)
            for market, value in observed_http_by_market.items()
        },
    )
    for market, observed in observed_http_by_market.items():
        if dict(observed) != normalized_http[market]:
            raise MachinePITSourceError(
                f"machine PIT HTTP capture metadata mismatch: {market}"
            )

    parsed = {}
    for market in _SOURCE_MARKETS:
        parsed[market] = _parse_official_source(
            OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market], raw_by_source[market]
        )
    capture_date = captured.astimezone(TAIPEI_TIMEZONE).date()
    machine_clock_id = f"machine:natural-day:{capture_date.isoformat()}"
    machine_clock_hash = _sha256_json(
        {
            "schema_version": "machine-natural-day-capture.v1",
            "clock_id": machine_clock_id,
            "captured_at": captured.isoformat(),
            "effective_from": capture_date.isoformat(),
            "universe_hash": universe_hash,
        }
    )
    try:
        generated = build_official_first_seen_capture(
            raw_payloads=raw_by_source,
            license_ids=DEFAULT_LICENSE_IDS,
            license_urls=DEFAULT_LICENSE_URLS,
            publication_at={
                market: datetime.combine(
                    parsed[market].publication_date,
                    time.min,
                    tzinfo=TAIPEI_TIMEZONE,
                )
                for market in _SOURCE_MARKETS
            },
            expected_symbols=symbols,
            clock_id=machine_clock_id,
            clock_manifest_hash=machine_clock_hash,
            universe_hash=universe_hash,
            available_at=captured,
            effective_from=capture_date,
            now=observed_now,
        )
    except (TypeError, ValueError) as error:
        raise MachinePITSourceError(str(error)) from error
    generated_source_map = {
        str(item["source_id"]): dict(item)
        for item in generated.source_registry
    }
    observed_source_map = {
        _required_text(item.get("source_id"), "source_registry.source_id"): dict(item)
        for item in source_registry
    }
    if set(observed_source_map) != expected_source_ids:
        raise MachinePITSourceError("machine PIT source registry set is incomplete")
    for source_id, observed in observed_source_map.items():
        relative_raw_path = _required_text(
            observed.get("raw_path"), "source_registry.raw_path"
        )
        _resolve_child(path.parent, relative_raw_path)
        if observed.get("publication_time_precision") != "date_only":
            raise MachinePITSourceError("machine PIT publication precision is invalid")
        if observed.get("capture_scope") != "current_natural_day":
            raise MachinePITSourceError("machine PIT source capture scope is invalid")
        generated_source = generated_source_map[source_id]
        for key, expected_value in generated_source.items():
            if observed.get(key) != expected_value:
                raise MachinePITSourceError(
                    f"machine PIT source registry mismatch: {source_id}:{key}"
                )
    rows = _mapping_sequence(payload.get("rows"), "rows")
    if payload.get("row_count") != len(rows):
        raise MachinePITSourceError("machine PIT row_count mismatch")
    generated_rows = [dict(row) for row in generated.rows]
    if rows != generated_rows:
        raise MachinePITSourceError("machine PIT rows do not match official raw source")
    if set(str(row.get("symbol")) for row in rows) != set(symbols):
        raise MachinePITSourceError("machine PIT rows do not cover declared universe")
    first_seen_policy = _mapping(payload.get("first_seen_policy"), "first_seen_policy")
    for key, expected_value in (
        ("name", "official_source_first_observed_only"),
        ("effective_from_is_capture_date", True),
        ("historical_pit_credit", False),
        ("official_publication_time_claimed", False),
    ):
        actual = first_seen_policy.get(key)
        if (
            actual is not expected_value
            if isinstance(expected_value, bool)
            else actual != expected_value
        ):
            raise MachinePITSourceError("machine PIT first-seen policy is invalid")
    license_scope = _mapping(payload.get("license_scope"), "license_scope")
    if license_scope.get("status") != "declared_official_open_api_identity":
        raise MachinePITSourceError("machine PIT license scope is invalid")
    if license_scope.get("formal_acceptance_granted") is not False:
        raise MachinePITSourceError("machine PIT license acceptance cannot be inferred")
    if license_scope.get("allowed_use_cases") != ["research_shadow", "diagnostics"]:
        raise MachinePITSourceError("machine PIT allowed use scope is invalid")
    if license_scope.get("redistribution_allowed") is not False:
        raise MachinePITSourceError("machine PIT redistribution scope is invalid")
    expected_capture_id = _sha256_json(
        {
            "schema_version": MACHINE_PIT_PUBLICATION_SCHEMA_VERSION,
            "producer_version": MACHINE_PIT_PRODUCER_VERSION,
            "captured_at": captured.isoformat(),
            "effective_from": capture_date.isoformat(),
            "universe_hash": universe_hash,
            "source_hashes": [
                str(item["source_hash"]) for item in sorted(
                    generated.source_registry,
                    key=lambda item: str(item["source_id"]),
                )
            ],
        }
    )
    if capture_id != "pit-machine:" + expected_capture_id[7:27]:
        raise MachinePITSourceError("machine PIT capture_id mismatch")
    return MachinePITValidation(
        publication_path=path,
        publication_file_hash=_file_sha256(path),
        publication_content_hash=content_hash,
        capture_id=capture_id,
        captured_at=captured.isoformat(),
        effective_from=capture_date.isoformat(),
        row_count=len(rows),
        source_ids=tuple(sorted(expected_source_ids)),
        producer_code_sha256=producer_code,
    )


def write_machine_pit_receipt(
    publication_path: Path,
    *,
    receipt_path: Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """驗證 publication 並以 create-only 方式保存 machine receipt。"""

    validation = validate_machine_pit_publication(publication_path, now=now)
    receipt_output = receipt_path.expanduser().resolve()
    _require_temp_directory(receipt_output)
    if receipt_output == validation.publication_path:
        raise MachinePITSourceError("receipt must not overwrite publication")
    evaluated = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    )
    body: dict[str, object] = {
        "schema_version": MACHINE_PIT_RECEIPT_SCHEMA_VERSION,
        "status": "machine_verified",
        "input": "pit_sector_membership",
        "input_schema_version": MACHINE_PIT_INPUT_SCHEMA_VERSION,
        "consumer": "data_module.pit_sector_membership_machine",
        "consumer_version": MACHINE_PIT_CONSUMER_VERSION,
        "consumer_code_sha256": _consumer_code_sha256(),
        "evaluated_at": evaluated.isoformat(),
        "publication_path": str(validation.publication_path),
        "publication_file_hash": validation.publication_file_hash,
        "publication_content_hash": validation.publication_content_hash,
        "capture_id": validation.capture_id,
        "captured_at": validation.captured_at,
        "effective_from": validation.effective_from,
        "row_count": validation.row_count,
        "source_ids": list(validation.source_ids),
        "source_custody_verified": True,
        "rows_rebuilt_from_raw": True,
        "historical_backfill_claimed": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
        "decision_reason": (
            "official TWSE/TPEx raw custody re-read and first-seen rows rebuilt; "
            "current natural-day candidate only; formal owner publication remains pending"
        ),
    }
    content_hash = _sha256_json(body)
    payload = {**body, "content_sha256": content_hash}
    _create_json(receipt_output, payload)
    return {
        **payload,
        "receipt_file_hash": _file_sha256(receipt_output),
    }


def validate_machine_pit_receipt(
    receipt_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """驗證 receipt、自身 hash 與其 publication 的完整 source custody。"""

    path = receipt_path.expanduser().resolve()
    payload = _read_json_object(path, "machine PIT receipt")
    content_hash = _required_sha256(payload.get("content_sha256"), "receipt.content_sha256")
    body = dict(payload)
    body.pop("content_sha256", None)
    if _sha256_json(body) != content_hash:
        raise MachinePITSourceError("machine PIT receipt content hash mismatch")
    _require_exact(
        payload,
        {
            "schema_version", "status", "input", "input_schema_version",
            "consumer", "consumer_version", "consumer_code_sha256",
            "evaluated_at", "publication_path", "publication_file_hash",
            "publication_content_hash", "capture_id", "captured_at",
            "effective_from", "row_count", "source_ids",
            "source_custody_verified", "rows_rebuilt_from_raw",
            "historical_backfill_claimed", "formal_consumer_compatible",
            "candidate_only", "formal_oos_allowed", "promotion_eligible",
            "production_action_allowed", "decision_reason", "content_sha256",
        },
        "machine PIT receipt",
    )
    if payload.get("schema_version") != MACHINE_PIT_RECEIPT_SCHEMA_VERSION:
        raise MachinePITSourceError("machine PIT receipt schema is unsupported")
    if payload.get("status") != "machine_verified":
        raise MachinePITSourceError("machine PIT receipt status is invalid")
    if payload.get("input") != "pit_sector_membership":
        raise MachinePITSourceError("machine PIT receipt input is invalid")
    if payload.get("input_schema_version") != MACHINE_PIT_INPUT_SCHEMA_VERSION:
        raise MachinePITSourceError("machine PIT receipt input schema is invalid")
    if payload.get("consumer") != "data_module.pit_sector_membership_machine":
        raise MachinePITSourceError("machine PIT receipt consumer is invalid")
    if payload.get("consumer_version") != MACHINE_PIT_CONSUMER_VERSION:
        raise MachinePITSourceError("machine PIT receipt consumer version is invalid")
    consumer_code = _required_sha256(
        payload.get("consumer_code_sha256"), "receipt.consumer_code_sha256"
    )
    if consumer_code != _consumer_code_sha256():
        raise MachinePITSourceError("machine PIT consumer code hash mismatch")
    evaluated = _aware_datetime(payload.get("evaluated_at"), "receipt.evaluated_at")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    )
    if evaluated > observed_now:
        raise MachinePITSourceError("machine PIT receipt evaluated_at is after now")
    publication_path_value = _required_text(
        payload.get("publication_path"), "receipt.publication_path"
    )
    publication_path = Path(publication_path_value).expanduser().resolve()
    validation = validate_machine_pit_publication(publication_path, now=evaluated)
    for key, expected in (
        ("publication_file_hash", validation.publication_file_hash),
        ("publication_content_hash", validation.publication_content_hash),
        ("capture_id", validation.capture_id),
        ("captured_at", validation.captured_at),
        ("effective_from", validation.effective_from),
        ("row_count", validation.row_count),
        ("source_ids", list(validation.source_ids)),
    ):
        if payload.get(key) != expected:
            raise MachinePITSourceError(f"machine PIT receipt {key} mismatch")
    captured_at = _aware_datetime(
        validation.captured_at,
        "publication.captured_at",
    )
    if captured_at > evaluated:
        raise MachinePITSourceError("machine PIT receipt precedes source capture")
    for key, expected in (
        ("source_custody_verified", True),
        ("rows_rebuilt_from_raw", True),
        ("historical_backfill_claimed", False),
        ("formal_consumer_compatible", False),
        ("candidate_only", True),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("production_action_allowed", False),
    ):
        if payload.get(key) is not expected:
            raise MachinePITSourceError(f"machine PIT receipt {key} is invalid")
    _required_text(payload.get("decision_reason"), "receipt.decision_reason")
    return {
        **payload,
        "receipt_file_hash": _file_sha256(path),
        "publication": validation.to_dict(),
    }


def _normalize_symbols(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise MachinePITSourceError("machine PIT symbols must be a non-empty array")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MachinePITSourceError("machine PIT symbols must be text")
        text = item.strip()
        if not text.isdigit() or not 4 <= len(text) <= 6:
            raise MachinePITSourceError("machine PIT symbols must contain 4-6 digits")
        normalized.append(text)
    result = tuple(sorted(set(normalized)))
    if result != tuple(normalized):
        raise MachinePITSourceError("machine PIT symbols must be sorted and unique")
    return result


def _normalize_http_metadata(
    *,
    raw_payloads: Mapping[str, bytes],
    captured_at: datetime,
    now: datetime,
    metadata: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, dict[str, object]]:
    """驗證每個 response 的 URL、status、header 與完成時間。"""

    normalized: dict[str, dict[str, object]] = {}
    for market in _SOURCE_MARKETS:
        definition = OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market]
        supplied = None if metadata is None else metadata.get(market)
        if supplied is None:
            supplied = {
                "requested_url": definition.endpoint,
                "final_url": definition.endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": captured_at.isoformat(),
            }
        _require_exact(
            supplied,
            {
                "requested_url",
                "final_url",
                "http_status",
                "content_type",
                "http_date",
                "http_last_modified",
                "captured_at",
            },
            "machine PIT HTTP metadata",
        )
        requested_url = _required_text(
            supplied.get("requested_url"),
            "http.requested_url",
        )
        final_url = _required_text(
            supplied.get("final_url"),
            "http.final_url",
        )
        if requested_url != definition.endpoint:
            raise MachinePITSourceError(
                f"machine PIT HTTP requested URL mismatch: {market}"
            )
        if final_url != definition.endpoint:
            raise MachinePITSourceError(
                f"machine PIT HTTP final URL mismatch: {market}"
            )
        status = supplied.get("http_status")
        if isinstance(status, bool) or not isinstance(status, int) or status != 200:
            raise MachinePITSourceError(
                f"machine PIT HTTP status is not 200: {market}"
            )
        content_type = _required_text(
            supplied.get("content_type"),
            "http.content_type",
        )
        response_captured = _aware_datetime(
            supplied.get("captured_at"),
            "http.captured_at",
        )
        if response_captured > now:
            raise MachinePITSourceError(
                f"machine PIT HTTP captured_at is after now: {market}"
            )
        if response_captured > captured_at:
            raise MachinePITSourceError(
                f"machine PIT HTTP captured_at exceeds bundle captured_at: {market}"
            )
        headers: dict[str, object] = {}
        for field_name in ("http_date", "http_last_modified"):
            value = supplied.get(field_name)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise MachinePITSourceError(
                        f"machine PIT HTTP {field_name} is invalid: {market}"
                    )
                headers[field_name] = value.strip()
            else:
                headers[field_name] = None
        normalized[market] = {
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": status,
            "content_type": content_type,
            "http_date": headers["http_date"],
            "http_last_modified": headers["http_last_modified"],
            "captured_at": response_captured.isoformat(),
        }
    if max(
        _aware_datetime(item["captured_at"], "http.captured_at")
        for item in normalized.values()
    ) != captured_at:
        raise MachinePITSourceError(
            "bundle captured_at must equal latest HTTP response completion time"
        )
    return normalized


def _text_mapping(value: Mapping[str, str], field_name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        if key not in _SOURCE_MARKETS:
            raise MachinePITSourceError(f"{field_name} contains unknown market")
        if not isinstance(item, str) or not item.strip():
            raise MachinePITSourceError(f"{field_name}[{key}] must be text")
        result[key] = item.strip()
    return result


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise MachinePITSourceError(
                f"{field_name} must be timezone-aware datetime"
            ) from error
    if not isinstance(value, datetime):
        raise MachinePITSourceError(f"{field_name} must be timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MachinePITSourceError(f"{field_name} must be timezone-aware datetime")
    return value.astimezone(TAIPEI_TIMEZONE)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MachinePITSourceError(f"{field_name} must be an object")
    return value


def _mapping_sequence(value: object, field_name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise MachinePITSourceError(f"{field_name} must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise MachinePITSourceError(f"{field_name} entries must be objects")
        result.append(item)
    return result


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MachinePITSourceError(f"{field_name} must be non-empty text")
    return value.strip()


def _required_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith(_SHA256_PREFIX):
        raise MachinePITSourceError(f"{field_name} must be sha256")
    if len(value) != len(_SHA256_PREFIX) + 64:
        raise MachinePITSourceError(f"{field_name} must be sha256")
    try:
        int(value[len(_SHA256_PREFIX):], 16)
    except ValueError as error:
        raise MachinePITSourceError(f"{field_name} must be sha256") from error
    return value


def _require_exact(
    payload: Mapping[str, object],
    fields: set[str],
    field_name: str,
) -> None:
    if set(payload) != fields:
        raise MachinePITSourceError(f"{field_name} fields are invalid")


def _sha256_bytes(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _producer_code_sha256() -> str:
    return _file_sha256(Path(__file__).resolve())


def _consumer_code_sha256() -> str:
    return _producer_code_sha256()


def _read_json_object(path: Path, field_name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MachinePITSourceError(f"{field_name} is unreadable") from error
    if not isinstance(value, dict):
        raise MachinePITSourceError(f"{field_name} must be an object")
    return value


def _create_bytes(path: Path, value: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise MachinePITSourceError(
            f"machine PIT custody output already exists: {path.name}"
        ) from error
    except OSError as error:
        raise MachinePITSourceError("machine PIT custody output is not writable") from error


def _create_json(path: Path, value: Mapping[str, object]) -> None:
    _create_bytes(path, _canonical_json(value) + b"\n")


def _resolve_child(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise MachinePITSourceError("machine PIT custody path escapes publication root") from error
    if candidate == root.resolve():
        raise MachinePITSourceError("machine PIT custody path must name a file")
    return candidate


def _require_temp_directory(path: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        path.relative_to(temp_root)
    except ValueError as error:
        raise MachinePITSourceError(
            "machine PIT output must be under the operating-system TEMP directory"
        ) from error


__all__ = [
    "DEFAULT_LICENSE_IDS",
    "DEFAULT_LICENSE_URLS",
    "MACHINE_PIT_CONSUMER_VERSION",
    "MACHINE_PIT_INPUT_SCHEMA_VERSION",
    "MACHINE_PIT_PRODUCER_VERSION",
    "MACHINE_PIT_PUBLICATION_SCHEMA_VERSION",
    "MACHINE_PIT_RECEIPT_SCHEMA_VERSION",
    "MachinePITPublicationResult",
    "MachinePITSourceError",
    "MachinePITValidation",
    "build_machine_pit_publication",
    "validate_machine_pit_publication",
    "validate_machine_pit_receipt",
    "write_machine_pit_receipt",
]

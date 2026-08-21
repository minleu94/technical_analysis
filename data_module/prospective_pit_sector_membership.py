"""Prospective-only PIT sector membership sidecar custody.

本模組只驗證呼叫端提供的合法來源資料；它不下載 T97/T30、不讀
``companies.csv``、不從產業指數或 research output 推導 membership。每一列都
必須有 accepted status、source／license／publication lineage、available/effective
時間與 canonical source hash，且 manifest 明確綁定 prospective clock。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    canonical_json,
    file_sha256,
)


PIT_SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION = "pit-sector-membership-sidecar-v1"
PIT_SECTOR_MEMBERSHIP_PROSPECTIVE_MANIFEST_SCHEMA_VERSION = (
    "pit-sector-membership-prospective-manifest-v1"
)
PIT_SECTOR_MEMBERSHIP_RESULT_SCHEMA_VERSION = (
    "prospective-pit-sector-membership-capture-result.v1"
)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")

_ROW_REQUIRED_FIELDS = frozenset(
    {
        "symbol",
        "sector_id",
        "available_at",
        "effective_from",
        "status",
        "source_id",
        "license_id",
        "source_hash",
    }
)
_ROW_FIELDS = _ROW_REQUIRED_FIELDS | {"effective_to"}
_SOURCE_FIELDS = frozenset(
    {
        "source_id",
        "license_id",
        "source_hash",
        "source_version",
        "publication_at",
        "allowed_use",
    }
)
_OFFICIAL_SOURCE_FIELDS = frozenset(
    {
        "source_kind",
        "dataset_id",
        "market",
        "endpoint",
        "license_url",
        "raw_hash",
        "canonical_rows_hash",
        "publication_date",
        "available_at",
        "effective_from",
        "clock_id",
        "clock_manifest_hash",
        "universe_hash",
        "source_registry_hash",
        "schema_fields",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "formal_source_only",
        "research_only",
        "formal_consumer_compatible",
        "promotion_eligible",
        "scope",
        "historical_backfill_claimed",
        "clock_id",
        "clock_manifest_hash",
        "coverage_start",
        "coverage_end",
        "universe_hash",
        "row_count",
        "rows_hash",
        "source_registry",
        "canonical_hash",
    }
)


class ProspectivePitSectorMembershipError(ValueError):
    """Prospective PIT sidecar 不符合來源／時間／hash 契約。"""


@dataclass(frozen=True)
class ProspectivePitCaptureResult:
    sidecar_path: Path
    sidecar_file_hash: str
    canonical_hash: str
    rows_hash: str
    clock_id: str
    coverage_start: str
    coverage_end: str
    row_count: int
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PIT_SECTOR_MEMBERSHIP_RESULT_SCHEMA_VERSION,
            "status": "accepted",
            "sidecar_path": str(self.sidecar_path),
            "sidecar_file_hash": self.sidecar_file_hash,
            "canonical_hash": self.canonical_hash,
            "rows_hash": self.rows_hash,
            "clock_id": self.clock_id,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "row_count": self.row_count,
            "source_ids": list(self.source_ids),
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
            "secret_values_emitted": False,
        }


def capture_prospective_pit_sector_membership(
    *,
    clock: ProspectiveFormalClock,
    output_path: Path,
    decision_timestamp: str,
    now: datetime,
    rows: Sequence[Mapping[str, object]],
    source_registry: Sequence[Mapping[str, object]],
    expected_symbols: Sequence[str],
) -> ProspectivePitCaptureResult:
    """驗證呼叫端提供的 PIT rows 並以 immutable bytes 保存 sidecar。"""

    decision = _decision_timestamp(decision_timestamp, clock)
    _validate_now(now)
    if decision > now.astimezone(TAIPEI_TIMEZONE):
        raise ProspectivePitSectorMembershipError(
            "decision_timestamp is after capture now"
        )
    normalized_rows, normalized_sources, source_ids = _validate_content(
        clock=clock,
        decision=decision,
        rows=rows,
        source_registry=source_registry,
        expected_symbols=expected_symbols,
    )
    coverage_start = clock.activation_trading_day.isoformat()
    coverage_end = decision.date().isoformat()
    rows_hash = _sha256_json(normalized_rows)
    manifest_body: dict[str, object] = {
        "schema_version": PIT_SECTOR_MEMBERSHIP_PROSPECTIVE_MANIFEST_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "scope": "prospective_only",
        "historical_backfill_claimed": False,
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "universe_hash": str(clock.payload["universe_hash"]),
        "row_count": len(normalized_rows),
        "rows_hash": rows_hash,
        "source_registry": normalized_sources,
    }
    canonical_hash = _sha256_json(
        {
            "sidecar_schema_version": PIT_SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
            "manifest": manifest_body,
        }
    )
    manifest = {**manifest_body, "canonical_hash": canonical_hash}
    envelope = {
        "schema_version": PIT_SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
        "manifest": manifest,
        "rows": normalized_rows,
    }
    _validate_envelope(
        envelope,
        clock=clock,
        decision=decision,
        expected_symbols=expected_symbols,
    )
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectivePitSectorMembershipError(
            "sidecar output parent directory must already exist"
        )
    _write_sidecar(output, envelope)
    return ProspectivePitCaptureResult(
        sidecar_path=output,
        sidecar_file_hash=file_sha256(output),
        canonical_hash=canonical_hash,
        rows_hash=rows_hash,
        clock_id=clock.clock_id,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        row_count=len(normalized_rows),
        source_ids=source_ids,
    )


def validate_prospective_pit_sector_membership(
    *,
    sidecar_path: Path,
    clock: ProspectiveFormalClock,
    decision_timestamp: str,
    now: datetime,
    expected_symbols: Sequence[str],
) -> ProspectivePitCaptureResult:
    """唯讀驗證 `.json`／`.jsonl`／`.jsonl.gz` prospective sidecar。"""

    decision = _decision_timestamp(decision_timestamp, clock)
    _validate_now(now)
    if decision > now.astimezone(TAIPEI_TIMEZONE):
        raise ProspectivePitSectorMembershipError(
            "decision_timestamp is after capture now"
        )
    path = sidecar_path.expanduser().resolve()
    if not path.is_file():
        raise ProspectivePitSectorMembershipError("PIT sector sidecar is missing")
    envelope = _read_sidecar(path)
    normalized_rows, normalized_sources, source_ids = _validate_envelope(
        envelope,
        clock=clock,
        decision=decision,
        expected_symbols=expected_symbols,
    )
    manifest = envelope["manifest"]
    if not isinstance(manifest, Mapping):  # pragma: no cover - guarded above
        raise AssertionError("manifest must be a mapping")
    return ProspectivePitCaptureResult(
        sidecar_path=path,
        sidecar_file_hash=file_sha256(path),
        canonical_hash=str(manifest["canonical_hash"]),
        rows_hash=_sha256_json(normalized_rows),
        clock_id=clock.clock_id,
        coverage_start=str(manifest["coverage_start"]),
        coverage_end=str(manifest["coverage_end"]),
        row_count=len(normalized_rows),
        source_ids=source_ids,
    )


def _validate_envelope(
    envelope: Mapping[str, object],
    *,
    clock: ProspectiveFormalClock,
    decision: datetime,
    expected_symbols: Sequence[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], tuple[str, ...]]:
    if set(envelope) != {"schema_version", "manifest", "rows"}:
        raise ProspectivePitSectorMembershipError(
            "PIT sidecar envelope fields are invalid"
        )
    if envelope.get("schema_version") != PIT_SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION:
        raise ProspectivePitSectorMembershipError(
            "PIT sidecar schema_version is invalid"
        )
    manifest_value = envelope.get("manifest")
    if not isinstance(manifest_value, Mapping):
        raise ProspectivePitSectorMembershipError("PIT sidecar manifest is invalid")
    manifest = dict(manifest_value)
    if set(manifest) != _MANIFEST_FIELDS:
        raise ProspectivePitSectorMembershipError(
            "prospective PIT manifest fields are invalid"
        )
    if manifest.get("schema_version") != PIT_SECTOR_MEMBERSHIP_PROSPECTIVE_MANIFEST_SCHEMA_VERSION:
        raise ProspectivePitSectorMembershipError(
            "prospective PIT manifest schema_version is invalid"
        )
    if manifest.get("status") != "complete":
        raise ProspectivePitSectorMembershipError("prospective PIT manifest is incomplete")
    for field_name, expected_value in (
        ("formal_source_only", True),
        ("research_only", False),
        ("formal_consumer_compatible", True),
        ("promotion_eligible", False),
        ("historical_backfill_claimed", False),
    ):
        if manifest.get(field_name) is not expected_value:
            raise ProspectivePitSectorMembershipError(
                f"prospective PIT manifest {field_name} is invalid"
            )
    if manifest.get("scope") != "prospective_only":
        raise ProspectivePitSectorMembershipError("prospective PIT scope is invalid")
    if manifest.get("clock_id") != clock.clock_id:
        raise ProspectivePitSectorMembershipError("PIT sidecar clock_id mismatch")
    if manifest.get("clock_manifest_hash") != clock.manifest_hash:
        raise ProspectivePitSectorMembershipError(
            "PIT sidecar clock manifest hash mismatch"
        )
    if manifest.get("universe_hash") != str(clock.payload["universe_hash"]):
        raise ProspectivePitSectorMembershipError("PIT sidecar universe hash mismatch")
    coverage_start = _parse_date(manifest.get("coverage_start"), "coverage_start")
    coverage_end = _parse_date(manifest.get("coverage_end"), "coverage_end")
    if coverage_start != clock.activation_trading_day:
        raise ProspectivePitSectorMembershipError(
            "prospective PIT coverage_start must equal clock activation"
        )
    if coverage_end != decision.date() or coverage_end < coverage_start:
        raise ProspectivePitSectorMembershipError(
            "prospective PIT coverage_end does not match decision timestamp"
        )
    rows_value = envelope.get("rows")
    if not isinstance(rows_value, list) or not rows_value:
        raise ProspectivePitSectorMembershipError("PIT sidecar rows are required")
    normalized_sources = _normalize_source_registry(manifest.get("source_registry"))
    _validate_official_source_bindings(
        normalized_sources,
        clock=clock,
        decision=decision,
        coverage_start=coverage_start,
    )
    normalized_rows, source_ids = _normalize_rows(
        rows_value,
        normalized_sources,
        decision=decision,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    expected = _normalize_symbols(expected_symbols)
    if set(row["symbol"] for row in normalized_rows) != set(expected):
        raise ProspectivePitSectorMembershipError(
            "prospective PIT sidecar does not cover the required symbol universe"
        )
    if manifest.get("row_count") != len(normalized_rows):
        raise ProspectivePitSectorMembershipError("PIT sidecar row_count mismatch")
    rows_hash = _sha256_json(normalized_rows)
    if manifest.get("rows_hash") != rows_hash:
        raise ProspectivePitSectorMembershipError("PIT sidecar rows_hash mismatch")
    canonical_hash = manifest.get("canonical_hash")
    if not _is_sha256(canonical_hash):
        raise ProspectivePitSectorMembershipError("PIT sidecar canonical_hash is invalid")
    manifest_without_hash = dict(manifest)
    manifest_without_hash.pop("canonical_hash", None)
    expected_canonical = _sha256_json(
        {
            "sidecar_schema_version": PIT_SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
            "manifest": manifest_without_hash,
        }
    )
    if canonical_hash != expected_canonical:
        raise ProspectivePitSectorMembershipError("PIT sidecar canonical hash mismatch")
    return normalized_rows, normalized_sources, source_ids


def _validate_content(
    *,
    clock: ProspectiveFormalClock,
    decision: datetime,
    rows: Sequence[Mapping[str, object]],
    source_registry: Sequence[Mapping[str, object]],
    expected_symbols: Sequence[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], tuple[str, ...]]:
    normalized_sources = _normalize_source_registry(source_registry)
    _validate_official_source_bindings(
        normalized_sources,
        clock=clock,
        decision=decision,
        coverage_start=clock.activation_trading_day,
    )
    normalized_rows, source_ids = _normalize_rows(
        list(rows),
        normalized_sources,
        decision=decision,
        coverage_start=clock.activation_trading_day,
        coverage_end=decision.date(),
    )
    expected = _normalize_symbols(expected_symbols)
    if set(row["symbol"] for row in normalized_rows) != set(expected):
        raise ProspectivePitSectorMembershipError(
            "prospective PIT sidecar does not cover the required symbol universe"
        )
    return normalized_rows, normalized_sources, source_ids


def _normalize_source_registry(value: object) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ProspectivePitSectorMembershipError(
            "prospective PIT source_registry must be a non-empty array"
        )
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ProspectivePitSectorMembershipError(
                "prospective PIT source_registry entry fields are invalid"
            )
        item_fields = set(item)
        is_official = item_fields == _SOURCE_FIELDS | _OFFICIAL_SOURCE_FIELDS
        if item_fields != _SOURCE_FIELDS and not is_official:
            raise ProspectivePitSectorMembershipError(
                "prospective PIT source_registry entry fields are invalid"
            )
        source_id = _source_text(item.get("source_id"), "source_id")
        license_id = _source_text(item.get("license_id"), "license_id")
        source_version = _source_text(item.get("source_version"), "source_version")
        source_hash = item.get("source_hash")
        _require_sha256(source_hash, "source_registry.source_hash")
        publication = _parse_aware(
            item.get("publication_at"), "source_registry.publication_at"
        )
        allowed_use = item.get("allowed_use")
        if not isinstance(allowed_use, list) or any(
            not isinstance(entry, str) or not entry.strip() for entry in allowed_use
        ):
            raise ProspectivePitSectorMembershipError(
                "source_registry.allowed_use must be a text array"
            )
        if "prospective_pit_sector_membership" not in allowed_use:
            raise ProspectivePitSectorMembershipError(
                "source_registry does not authorize prospective PIT membership"
            )
        if _looks_like_unlicensed_source(license_id):
            raise ProspectivePitSectorMembershipError(
                "source_registry license_id is not an authorized license identity"
            )
        key = (source_id, license_id, str(source_hash))
        if key in seen:
            raise ProspectivePitSectorMembershipError(
                "source_registry entries must be unique"
            )
        seen.add(key)
        normalized_entry: dict[str, object] = {
            "source_id": source_id,
            "license_id": license_id,
            "source_hash": str(source_hash),
            "source_version": source_version,
            "publication_at": publication.isoformat(),
            "allowed_use": sorted(set(allowed_use)),
        }
        if is_official:
            normalized_entry.update(
                _normalize_official_source_fields(
                    item,
                    publication=publication,
                )
            )
        normalized.append(normalized_entry)
    return sorted(
        normalized,
        key=lambda item: (
            str(item["source_id"]),
            str(item["source_version"]),
            str(item["source_hash"]),
        ),
    )


def _normalize_official_source_fields(
    item: Mapping[str, object],
    *,
    publication: datetime,
) -> dict[str, object]:
    """Normalize and validate official source registry provenance fields."""

    source_kind = _source_text(item.get("source_kind"), "source_kind")
    if source_kind != "official_company_basic_first_seen":
        raise ProspectivePitSectorMembershipError(
            "official source_registry source_kind is invalid"
        )
    dataset_id = _source_text(item.get("dataset_id"), "dataset_id")
    market = _source_text(item.get("market"), "market")
    endpoint = _source_text(item.get("endpoint"), "endpoint")
    license_url = _source_text(item.get("license_url"), "license_url")
    if not (endpoint.startswith("https://") or endpoint.startswith("http://")):
        raise ProspectivePitSectorMembershipError(
            "official source_registry endpoint must be an HTTP(S) URL"
        )
    if not (license_url.startswith("https://") or license_url.startswith("http://")):
        raise ProspectivePitSectorMembershipError(
            "official source_registry license_url must be an HTTP(S) URL"
        )
    raw_hash = item.get("raw_hash")
    canonical_rows_hash = item.get("canonical_rows_hash")
    _require_sha256(raw_hash, "source_registry.raw_hash")
    _require_sha256(canonical_rows_hash, "source_registry.canonical_rows_hash")
    if raw_hash != item.get("source_hash"):
        raise ProspectivePitSectorMembershipError(
            "official source_registry raw_hash must equal source_hash"
        )
    publication_date = _parse_date(
        item.get("publication_date"),
        "source_registry.publication_date",
    )
    if publication.date() != publication_date:
        raise ProspectivePitSectorMembershipError(
            "official source_registry publication_date mismatch"
        )
    available_at = _parse_aware(
        item.get("available_at"),
        "source_registry.available_at",
    )
    effective_from = _parse_date(
        item.get("effective_from"),
        "source_registry.effective_from",
    )
    clock_id = _source_text(item.get("clock_id"), "source_registry.clock_id")
    clock_manifest_hash = item.get("clock_manifest_hash")
    universe_hash = item.get("universe_hash")
    _require_sha256(clock_manifest_hash, "source_registry.clock_manifest_hash")
    _require_sha256(universe_hash, "source_registry.universe_hash")
    schema_fields = item.get("schema_fields")
    if not isinstance(schema_fields, list) or not schema_fields:
        raise ProspectivePitSectorMembershipError(
            "official source_registry.schema_fields must be a non-empty array"
        )
    if any(not isinstance(field, str) or not field.strip() for field in schema_fields):
        raise ProspectivePitSectorMembershipError(
            "official source_registry.schema_fields must contain text"
        )
    normalized_schema_fields = sorted(set(schema_fields))
    if normalized_schema_fields != schema_fields:
        raise ProspectivePitSectorMembershipError(
            "official source_registry.schema_fields must be sorted and unique"
        )
    source_registry_hash = item.get("source_registry_hash")
    _require_sha256(source_registry_hash, "source_registry.source_registry_hash")
    source_without_hash = dict(item)
    source_without_hash.pop("source_registry_hash", None)
    if source_registry_hash != _sha256_json(source_without_hash):
        raise ProspectivePitSectorMembershipError(
            "official source_registry source_registry_hash mismatch"
        )
    return {
        "source_kind": source_kind,
        "dataset_id": dataset_id,
        "market": market,
        "endpoint": endpoint,
        "license_url": license_url,
        "raw_hash": str(raw_hash),
        "canonical_rows_hash": str(canonical_rows_hash),
        "publication_date": publication_date.isoformat(),
        "available_at": available_at.isoformat(),
        "effective_from": effective_from.isoformat(),
        "clock_id": clock_id,
        "clock_manifest_hash": str(clock_manifest_hash),
        "universe_hash": str(universe_hash),
        "source_registry_hash": str(source_registry_hash),
        "schema_fields": normalized_schema_fields,
    }


def _validate_official_source_bindings(
    sources: Sequence[Mapping[str, object]],
    *,
    clock: ProspectiveFormalClock,
    decision: datetime,
    coverage_start: date,
) -> None:
    official_sources = [
        source
        for source in sources
        if source.get("source_kind") == "official_company_basic_first_seen"
    ]
    for source in official_sources:
        if source.get("clock_id") != clock.clock_id:
            raise ProspectivePitSectorMembershipError(
                "official source_registry clock_id mismatch"
            )
        if source.get("clock_manifest_hash") != clock.manifest_hash:
            raise ProspectivePitSectorMembershipError(
                "official source_registry clock manifest hash mismatch"
            )
        if source.get("universe_hash") != str(clock.payload["universe_hash"]):
            raise ProspectivePitSectorMembershipError(
                "official source_registry universe hash mismatch"
            )
        available_at = _parse_aware(
            source.get("available_at"),
            "source_registry.available_at",
        )
        if available_at > decision:
            raise ProspectivePitSectorMembershipError(
                "official source_registry available_at is after decision timestamp"
            )
        effective_from = _parse_date(
            source.get("effective_from"),
            "source_registry.effective_from",
        )
        if effective_from != coverage_start:
            raise ProspectivePitSectorMembershipError(
                "official source_registry effective_from must equal coverage start"
            )


def _normalize_rows(
    rows: Sequence[object],
    sources: Sequence[Mapping[str, object]],
    *,
    decision: datetime,
    coverage_start: date,
    coverage_end: date,
) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    source_map = {
        (str(item["source_id"]), str(item["license_id"]), str(item["source_hash"])): item
        for item in sources
    }
    normalized: list[dict[str, object]] = []
    natural_keys: set[tuple[str, str, str, str]] = set()
    source_ids: set[str] = set()
    for value in rows:
        if not isinstance(value, Mapping):
            raise ProspectivePitSectorMembershipError("PIT membership row must be an object")
        if set(value) - _ROW_FIELDS or _ROW_REQUIRED_FIELDS - set(value):
            raise ProspectivePitSectorMembershipError("PIT membership row fields are invalid")
        symbol = _source_text(value.get("symbol"), "symbol")
        sector_id = _source_text(value.get("sector_id"), "sector_id")
        status = _source_text(value.get("status"), "status")
        if status != "accepted":
            raise ProspectivePitSectorMembershipError(
                "PIT membership row status must be accepted"
            )
        available = _parse_aware(value.get("available_at"), "available_at")
        if available > decision:
            raise ProspectivePitSectorMembershipError(
                "PIT membership available_at is after decision timestamp"
            )
        effective_from = _parse_date(value.get("effective_from"), "effective_from")
        effective_to_value = value.get("effective_to")
        effective_to = (
            None
            if effective_to_value in (None, "")
            else _parse_date(effective_to_value, "effective_to")
        )
        if effective_from < coverage_start or effective_from > coverage_end:
            raise ProspectivePitSectorMembershipError(
                "PIT membership effective_from is outside prospective coverage"
            )
        if effective_to is not None and effective_to < effective_from:
            raise ProspectivePitSectorMembershipError(
                "PIT membership effective_to precedes effective_from"
            )
        if effective_to is not None and effective_to < coverage_end:
            raise ProspectivePitSectorMembershipError(
                "PIT membership effective interval does not cover decision date"
            )
        source_id = _source_text(value.get("source_id"), "source_id")
        license_id = _source_text(value.get("license_id"), "license_id")
        source_hash = value.get("source_hash")
        _require_sha256(source_hash, "source_hash")
        source_key = (source_id, license_id, str(source_hash))
        source = source_map.get(source_key)
        if source is None:
            raise ProspectivePitSectorMembershipError(
                "PIT membership source/license/hash lineage is incomplete"
            )
        publication = _parse_aware(source["publication_at"], "publication_at")
        if publication > available:
            raise ProspectivePitSectorMembershipError(
                "source publication_at is after row available_at"
            )
        if source.get("source_kind") == "official_company_basic_first_seen":
            source_available = _parse_aware(
                source.get("available_at"),
                "source_registry.available_at",
            )
            source_effective = _parse_date(
                source.get("effective_from"),
                "source_registry.effective_from",
            )
            if available != source_available:
                raise ProspectivePitSectorMembershipError(
                    "official PIT row available_at does not match source registry"
                )
            if effective_from != source_effective:
                raise ProspectivePitSectorMembershipError(
                    "official PIT row effective_from does not match source registry"
                )
        if _looks_like_current_snapshot_source(source_id):
            raise ProspectivePitSectorMembershipError(
                "current company snapshot cannot be a prospective PIT source"
            )
        key = (symbol, str(available), effective_from.isoformat(), sector_id)
        if key in natural_keys:
            raise ProspectivePitSectorMembershipError(
                "PIT membership natural keys must be unique"
            )
        natural_keys.add(key)
        source_ids.add(source_id)
        normalized.append(
            {
                "symbol": symbol,
                "sector_id": sector_id,
                "available_at": available.isoformat(),
                "effective_from": effective_from.isoformat(),
                "effective_to": None if effective_to is None else effective_to.isoformat(),
                "status": status,
                "source_id": source_id,
                "license_id": license_id,
                "source_hash": str(source_hash),
            }
        )
    normalized.sort(
        key=lambda item: (
            str(item["symbol"]),
            str(item["effective_from"]),
            str(item["available_at"]),
            str(item["sector_id"]),
        )
    )
    return normalized, tuple(sorted(source_ids))


def _read_sidecar(path: Path) -> dict[str, object]:
    suffix = path.name.casefold()
    try:
        if suffix.endswith(".json"):
            raw = path.read_text(encoding="utf-8")
            value: Any = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
            )
            if not isinstance(value, dict):
                raise ProspectivePitSectorMembershipError("PIT JSON sidecar must be an object")
            if canonical_json(value) != raw:
                raise ProspectivePitSectorMembershipError(
                    "PIT JSON sidecar must use canonical JSON"
                )
            return value
        opener = gzip.open if suffix.endswith(".jsonl.gz") else open
        if not suffix.endswith(".jsonl") and not suffix.endswith(".jsonl.gz"):
            raise ProspectivePitSectorMembershipError(
                "PIT sidecar format must be .json, .jsonl or .jsonl.gz"
            )
        with opener(path, "rt", encoding="utf-8") as stream:
            records = []
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(
                    line,
                    object_pairs_hook=_reject_duplicate_keys,
                )
                if canonical_json(record) != line.strip():
                    raise ProspectivePitSectorMembershipError(
                        "PIT JSONL record must use canonical JSON"
                    )
                records.append(record)
    except ProspectivePitSectorMembershipError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProspectivePitSectorMembershipError("PIT sidecar is unreadable") from error
    if not records:
        raise ProspectivePitSectorMembershipError("PIT JSONL sidecar is empty")
    header = records[0]
    if not isinstance(header, dict) or set(header) != {
        "record_type",
        "schema_version",
        "manifest",
    } or header.get("record_type") != "manifest":
        raise ProspectivePitSectorMembershipError("PIT JSONL manifest header is invalid")
    rows: list[object] = []
    for record in records[1:]:
        if not isinstance(record, dict) or set(record) != {"record_type", "row"}:
            raise ProspectivePitSectorMembershipError("PIT JSONL membership record is invalid")
        if record.get("record_type") != "membership":
            raise ProspectivePitSectorMembershipError("PIT JSONL record type is invalid")
        rows.append(record.get("row"))
    return {
        "schema_version": header.get("schema_version"),
        "manifest": header.get("manifest"),
        "rows": rows,
    }


def _write_sidecar(path: Path, envelope: Mapping[str, object]) -> None:
    suffix = path.name.casefold()
    if suffix.endswith(".json"):
        encoded = canonical_json(envelope).encode("utf-8")
    elif suffix.endswith(".jsonl") or suffix.endswith(".jsonl.gz"):
        manifest_record = {
            "record_type": "manifest",
            "schema_version": envelope["schema_version"],
            "manifest": envelope["manifest"],
        }
        rows = envelope["rows"]
        if not isinstance(rows, list):  # pragma: no cover - constructed above
            raise AssertionError("rows must be a list")
        encoded = (
            "\n".join(
                [
                    canonical_json(manifest_record),
                    *[
                        canonical_json({"record_type": "membership", "row": row})
                        for row in rows
                    ],
                ]
            )
            + "\n"
        ).encode("utf-8")
        if suffix.endswith(".gz"):
            encoded = gzip.compress(encoded, mtime=0)
    else:
        raise ProspectivePitSectorMembershipError(
            "PIT sidecar format must be .json, .jsonl or .jsonl.gz"
        )
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectivePitSectorMembershipError(
            "PIT sidecar output already exists"
        ) from error


def _normalize_symbols(value: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ProspectivePitSectorMembershipError(
            "expected_symbols must be a non-empty array"
        )
    symbols = tuple(_source_text(item, "expected_symbols") for item in value)
    if symbols != tuple(sorted(set(symbols))):
        raise ProspectivePitSectorMembershipError(
            "expected_symbols must be unique and sorted"
        )
    return symbols


def _source_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectivePitSectorMembershipError(
            f"{field_name} must be non-empty text"
        )
    return value


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProspectivePitSectorMembershipError(f"{field_name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ProspectivePitSectorMembershipError(
            f"{field_name} must be an ISO date"
        ) from error
    if parsed.isoformat() != value:
        raise ProspectivePitSectorMembershipError(
            f"{field_name} must use YYYY-MM-DD"
        )
    return parsed


def _parse_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ProspectivePitSectorMembershipError(
            f"{field_name} must be timezone-aware ISO datetime"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProspectivePitSectorMembershipError(
            f"{field_name} is invalid"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectivePitSectorMembershipError(
            f"{field_name} must include timezone"
        )
    return parsed.astimezone(TAIPEI_TIMEZONE)


def _decision_timestamp(value: str, clock: ProspectiveFormalClock) -> datetime:
    decision = _parse_aware(value, "decision_timestamp")
    if decision.date() < clock.activation_trading_day:
        raise ProspectivePitSectorMembershipError(
            "decision_timestamp precedes prospective activation"
        )
    raw_time = clock.payload.get("decision_time")
    if not isinstance(raw_time, str):
        raise ProspectivePitSectorMembershipError("clock decision_time is invalid")
    try:
        expected = time.fromisoformat(raw_time)
    except ValueError as error:
        raise ProspectivePitSectorMembershipError("clock decision_time is invalid") from error
    if decision.timetz().replace(tzinfo=None) != expected:
        raise ProspectivePitSectorMembershipError(
            "decision_timestamp does not match clock decision_time"
        )
    return decision


def _validate_now(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectivePitSectorMembershipError("now must include timezone")


def _require_sha256(value: object, field_name: str) -> None:
    if not _is_sha256(value):
        raise ProspectivePitSectorMembershipError(f"{field_name} must be sha256")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _sha256_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _looks_like_current_snapshot_source(value: str) -> bool:
    normalized = value.casefold().replace("\\", "/")
    return any(
        token in normalized
        for token in (
            "companies.csv",
            "company_snapshot",
            "current_company",
            "industry_index",
            "research",
        )
    )


def _looks_like_unlicensed_source(value: str) -> bool:
    normalized = value.casefold()
    return normalized in {"unknown", "unlicensed", "none", "", "not_provided"}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result

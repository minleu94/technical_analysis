"""受控 machine publisher／consumer 的 current-day PIT sector candidate。

``pit_sector_membership_machine`` 負責保存官方 raw custody 與重建 rows；本模組
再把已驗證 receipt 包成一個由受控 runtime HMAC 簽章的 operational candidate。
consumer 每次仍以呼叫端明確提供的 ``decision_at`` 重驗 receipt、source capture
與時間界線，不會把 current snapshot 當成歷史 PIT，也不會寫入 Formal path。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from data_module.pit_sector_membership_machine import (
    MACHINE_PIT_INPUT_SCHEMA_VERSION,
    MachinePITSourceError,
    validate_machine_pit_receipt,
)


MACHINE_PIT_OPERATIONAL_PUBLICATION_SCHEMA_VERSION = (
    "pit-sector-membership-machine-operational-publication.v1"
)
MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION = (
    "controlled-current-day-pit-publisher.v1"
)
MACHINE_PIT_OPERATIONAL_CONSUMER_VERSION = (
    "controlled-current-day-pit-consumer.v1"
)
MACHINE_PIT_PUBLISHER_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
MACHINE_PIT_ATTESTATION_DOMAIN = "pit-sector-membership.machine-publisher.v1"
_SHA256_PREFIX = "sha256:"
_HMAC_PREFIX = "hmac-sha256:"
_TAIPEI = ZoneInfo("Asia/Taipei")


def publish_machine_pit_operational_candidate(
    receipt_path: Path,
    *,
    output_path: Path,
    decision_at: datetime,
    now: datetime | None = None,
) -> dict[str, object]:
    """以受控 machine identity 發布一份 current-day operational candidate。

    呼叫端必須提供明確、含時區的 ``decision_at``。publisher 只接受在該
    instant 已經完成 source capture 與 receipt evaluation 的 candidate；簽章
    secret 只能由受控 runtime environment 取得，不能由 caller 傳入。
    """

    decision = _aware_datetime(decision_at, "decision_at")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    )
    if decision > observed_now:
        raise MachinePITSourceError("decision_at cannot be after now")
    key, publisher_id = _runtime_attestation_config()
    receipt = validate_machine_pit_receipt(receipt_path, now=decision)
    captured = _aware_datetime(receipt.get("captured_at"), "receipt.captured_at")
    evaluated = _aware_datetime(
        receipt.get("evaluated_at"),
        "receipt.evaluated_at",
    )
    if captured > decision:
        raise MachinePITSourceError(
            "operational decision_at is before source capture completion"
        )
    if evaluated > decision:
        raise MachinePITSourceError(
            "operational decision_at is before receipt evaluation"
        )
    effective_from = _required_text(receipt.get("effective_from"), "receipt.effective_from")
    capture_date = captured.astimezone(_TAIPEI).date().isoformat()
    if effective_from != capture_date:
        raise MachinePITSourceError(
            "operational PIT effective_from must equal source capture date"
        )
    receipt_file_hash = _required_sha256(
        receipt.get("receipt_file_hash"),
        "receipt.receipt_file_hash",
    )
    receipt_content_hash = _required_sha256(
        receipt.get("content_sha256"),
        "receipt.content_sha256",
    )
    publication_path = _required_text(
        receipt.get("publication_path"),
        "receipt.publication_path",
    )
    publication_file_hash = _required_sha256(
        receipt.get("publication_file_hash"),
        "receipt.publication_file_hash",
    )
    publication_content_hash = _required_sha256(
        receipt.get("publication_content_hash"),
        "receipt.publication_content_hash",
    )
    source_ids = _text_list(receipt.get("source_ids"), "receipt.source_ids")
    row_count = _required_nonnegative_int(receipt.get("row_count"), "receipt.row_count")
    receipt_resolved = receipt_path.expanduser().resolve()
    output = output_path.expanduser().resolve()
    _require_temp_path(receipt_resolved, field_name="receipt")
    _require_temp_path(output, field_name="operational publication")
    if output == receipt_resolved:
        raise MachinePITSourceError("operational publication must not overwrite receipt")
    body: dict[str, object] = {
        "schema_version": MACHINE_PIT_OPERATIONAL_PUBLICATION_SCHEMA_VERSION,
        "status": "published_candidate",
        "input": "pit_sector_membership",
        "input_schema_version": MACHINE_PIT_INPUT_SCHEMA_VERSION,
        "publisher": "data_module.pit_sector_machine_publisher",
        "publisher_version": MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION,
        "publisher_code_sha256": _publisher_code_sha256(),
        "publisher_id": publisher_id,
        "attestation_domain": MACHINE_PIT_ATTESTATION_DOMAIN,
        "decision_at": decision.isoformat(),
        "available_at": captured.isoformat(),
        "available_date": capture_date,
        "effective_from": effective_from,
        "receipt_path": str(receipt_resolved),
        "receipt_file_hash": receipt_file_hash,
        "receipt_content_hash": receipt_content_hash,
        "publication_path": publication_path,
        "publication_file_hash": publication_file_hash,
        "publication_content_hash": publication_content_hash,
        "capture_id": _required_text(receipt.get("capture_id"), "receipt.capture_id"),
        "row_count": row_count,
        "source_ids": source_ids,
        "source_custody_verified": receipt.get("source_custody_verified") is True,
        "rows_rebuilt_from_raw": receipt.get("rows_rebuilt_from_raw") is True,
        "availability_policy": {
            "name": "response-completion-timestamp-gated",
            "date_only_consumer_allowed": False,
            "decision_must_be_at_or_after_available_at": True,
        },
        "scope": "current_natural_day",
        "historical_backfill_claimed": False,
        "formal_consumer_compatible": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
        "candidate_only": True,
        "decision_reason": (
            "controlled machine publisher attested a receipt whose official TWSE/TPEx "
            "raw custody was re-read; timestamp-gated current natural-day candidate only"
        ),
    }
    if body["source_custody_verified"] is not True or body["rows_rebuilt_from_raw"] is not True:
        raise MachinePITSourceError("receipt custody evidence is incomplete")
    signature = _hmac_signature(body, key)
    signed = {**body, "attestation_signature": signature}
    payload = {**signed, "content_sha256": _sha256_json(signed)}
    _create_json(output, payload)
    return {
        **payload,
        "publication_file_path": str(output),
        "operational_file_hash": _file_sha256(output),
    }


def validate_machine_pit_operational_candidate(
    publication_path: Path,
    *,
    decision_at: datetime,
    now: datetime | None = None,
) -> dict[str, object]:
    """驗證 machine publisher 簽章並重驗其 receipt custody。"""

    requested_decision = _aware_datetime(decision_at, "decision_at")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    )
    if requested_decision > observed_now:
        raise MachinePITSourceError("consumer decision_at cannot be after now")
    path = publication_path.expanduser().resolve()
    _require_temp_path(path, field_name="operational publication")
    payload = _read_json_object(path, "operational PIT publication")
    expected_fields = {
        "schema_version",
        "status",
        "input",
        "input_schema_version",
        "publisher",
        "publisher_version",
        "publisher_code_sha256",
        "publisher_id",
        "attestation_domain",
        "attestation_signature",
        "content_sha256",
        "decision_at",
        "available_at",
        "available_date",
        "effective_from",
        "receipt_path",
        "receipt_file_hash",
        "receipt_content_hash",
        "publication_path",
        "publication_file_hash",
        "publication_content_hash",
        "capture_id",
        "row_count",
        "source_ids",
        "source_custody_verified",
        "rows_rebuilt_from_raw",
        "availability_policy",
        "scope",
        "historical_backfill_claimed",
        "formal_consumer_compatible",
        "formal_oos_allowed",
        "promotion_eligible",
        "production_action_allowed",
        "candidate_only",
        "decision_reason",
    }
    if set(payload) != expected_fields:
        raise MachinePITSourceError("operational PIT publication fields are invalid")
    if payload.get("schema_version") != MACHINE_PIT_OPERATIONAL_PUBLICATION_SCHEMA_VERSION:
        raise MachinePITSourceError("operational PIT publication schema is unsupported")
    if payload.get("status") != "published_candidate":
        raise MachinePITSourceError("operational PIT publication status is invalid")
    if payload.get("input") != "pit_sector_membership":
        raise MachinePITSourceError("operational PIT publication input is invalid")
    if payload.get("input_schema_version") != MACHINE_PIT_INPUT_SCHEMA_VERSION:
        raise MachinePITSourceError("operational PIT input schema is invalid")
    if payload.get("publisher") != "data_module.pit_sector_machine_publisher":
        raise MachinePITSourceError("operational PIT publisher identity is invalid")
    if payload.get("publisher_version") != MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION:
        raise MachinePITSourceError("operational PIT publisher version is invalid")
    publisher_code = _required_sha256(
        payload.get("publisher_code_sha256"),
        "publisher_code_sha256",
    )
    if publisher_code != _publisher_code_sha256():
        raise MachinePITSourceError("operational PIT publisher code hash mismatch")
    if payload.get("attestation_domain") != MACHINE_PIT_ATTESTATION_DOMAIN:
        raise MachinePITSourceError("operational PIT attestation domain is invalid")
    key, publisher_id = _runtime_attestation_config()
    if payload.get("publisher_id") != publisher_id:
        raise MachinePITSourceError("operational PIT publisher identity does not match runtime")
    content_hash = _required_sha256(payload.get("content_sha256"), "content_sha256")
    signed_body = {
        key_name: value
        for key_name, value in payload.items()
        if key_name not in {"attestation_signature", "content_sha256"}
    }
    if _sha256_json({**signed_body, "attestation_signature": payload.get("attestation_signature")}) != content_hash:
        raise MachinePITSourceError("operational PIT publication content hash mismatch")
    supplied_signature = payload.get("attestation_signature")
    expected_signature = _hmac_signature(signed_body, key)
    if supplied_signature != expected_signature:
        raise MachinePITSourceError("operational PIT publisher attestation mismatch")
    published_decision = _aware_datetime(payload.get("decision_at"), "published decision_at")
    available_at = _aware_datetime(payload.get("available_at"), "available_at")
    if published_decision > observed_now:
        raise MachinePITSourceError("published decision_at is after now")
    if published_decision > requested_decision:
        raise MachinePITSourceError("consumer decision_at is before published decision")
    if available_at > requested_decision:
        raise MachinePITSourceError("consumer decision_at is before source availability")
    available_date = available_at.astimezone(_TAIPEI).date().isoformat()
    if payload.get("available_date") != available_date:
        raise MachinePITSourceError("operational PIT available_date is invalid")
    if payload.get("effective_from") != available_date:
        raise MachinePITSourceError("operational PIT effective_from is invalid")
    policy = payload.get("availability_policy")
    if policy != {
        "name": "response-completion-timestamp-gated",
        "date_only_consumer_allowed": False,
        "decision_must_be_at_or_after_available_at": True,
    }:
        raise MachinePITSourceError("operational PIT availability policy is invalid")
    for field_name, expected in (
        ("scope", "current_natural_day"),
        ("historical_backfill_claimed", False),
        ("formal_consumer_compatible", False),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("production_action_allowed", False),
        ("candidate_only", True),
        ("source_custody_verified", True),
        ("rows_rebuilt_from_raw", True),
    ):
        if payload.get(field_name) is not expected if isinstance(expected, bool) else payload.get(field_name) != expected:
            raise MachinePITSourceError(f"operational PIT {field_name} is invalid")
    receipt_path = Path(_required_text(payload.get("receipt_path"), "receipt_path"))
    receipt = validate_machine_pit_receipt(receipt_path, now=requested_decision)
    receipt_evaluated = _aware_datetime(receipt.get("evaluated_at"), "receipt.evaluated_at")
    if receipt_evaluated > requested_decision:
        raise MachinePITSourceError("consumer decision_at is before receipt evaluation")
    for field_name, receipt_field in (
        ("receipt_file_hash", "receipt_file_hash"),
        ("receipt_content_hash", "content_sha256"),
        ("publication_path", "publication_path"),
        ("publication_file_hash", "publication_file_hash"),
        ("publication_content_hash", "publication_content_hash"),
        ("capture_id", "capture_id"),
        ("effective_from", "effective_from"),
        ("row_count", "row_count"),
    ):
        if payload.get(field_name) != receipt.get(receipt_field):
            raise MachinePITSourceError(f"operational PIT {field_name} does not match receipt")
    source_ids = _text_list(receipt.get("source_ids"), "receipt.source_ids")
    if payload.get("source_ids") != source_ids:
        raise MachinePITSourceError("operational PIT source_ids do not match receipt")
    _required_text(payload.get("decision_reason"), "decision_reason")
    return {
        **payload,
        "operational_file_hash": _file_sha256(path),
        "consumer_decision_at": requested_decision.isoformat(),
        "receipt": receipt,
    }


def consume_machine_pit_operational_candidate(
    publication_path: Path,
    *,
    decision_at: datetime,
    now: datetime | None = None,
) -> dict[str, object]:
    """以明確 decision time 重驗並回傳可供 shadow 使用的 rows。"""

    validated = validate_machine_pit_operational_candidate(
        publication_path,
        decision_at=decision_at,
        now=now,
    )
    receipt = validated["receipt"]
    if not isinstance(receipt, Mapping):  # pragma: no cover - validator guard
        raise MachinePITSourceError("operational PIT receipt projection is invalid")
    source_publication_path = Path(
        _required_text(receipt.get("publication_path"), "receipt.publication_path")
    )
    publication = _read_json_object(source_publication_path, "machine PIT publication")
    expected_publication_file_hash = _required_sha256(
        validated.get("publication_file_hash"),
        "validated.publication_file_hash",
    )
    if _file_sha256(source_publication_path) != expected_publication_file_hash:
        raise MachinePITSourceError(
            "operational PIT source publication file hash changed during read"
        )
    observed_content_hash = _required_sha256(
        publication.get("content_sha256"),
        "machine PIT publication.content_sha256",
    )
    publication_body = dict(publication)
    publication_body.pop("content_sha256", None)
    if _sha256_json(publication_body) != observed_content_hash:
        raise MachinePITSourceError(
            "operational PIT source publication content hash mismatch"
        )
    if observed_content_hash != _required_sha256(
        validated.get("publication_content_hash"),
        "validated.publication_content_hash",
    ):
        raise MachinePITSourceError(
            "operational PIT source publication content hash changed during read"
        )
    rows = publication.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise MachinePITSourceError("operational PIT consumer rows are invalid")
    if len(rows) != validated.get("row_count"):
        raise MachinePITSourceError("operational PIT consumer row_count mismatch")
    source_ids = _text_list(validated.get("source_ids"), "validated.source_ids")
    return {
        "status": "machine_verified",
        "input": "pit_sector_membership",
        "consumer": "data_module.pit_sector_machine_publisher",
        "consumer_version": MACHINE_PIT_OPERATIONAL_CONSUMER_VERSION,
        "consumer_decision_at": validated["consumer_decision_at"],
        "published_decision_at": validated["decision_at"],
        "available_at": validated["available_at"],
        "effective_from": validated["effective_from"],
        "capture_id": validated["capture_id"],
        "row_count": len(rows),
        "rows": [dict(row) for row in rows],
        "source_ids": source_ids,
        "operational_file_hash": validated["operational_file_hash"],
        "publisher_code_sha256": validated["publisher_code_sha256"],
        "publisher_id": validated["publisher_id"],
        "attestation_signature": validated["attestation_signature"],
        "receipt_path": validated["receipt_path"],
        "receipt_file_hash": validated["receipt_file_hash"],
        "receipt_content_hash": validated["receipt_content_hash"],
        "publication_path": validated["publication_path"],
        "publication_file_hash": validated["publication_file_hash"],
        "publication_content_hash": validated["publication_content_hash"],
        "source_custody_verified": True,
        "rows_rebuilt_from_raw": True,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "decision_reason": validated["decision_reason"],
    }


def _runtime_attestation_config() -> tuple[bytes, str]:
    key = os.environ.get(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, "")
    publisher_id = os.environ.get(MACHINE_PIT_PUBLISHER_ID_ENV, "")
    if not key.strip():
        raise MachinePITSourceError(
            f"{MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV} is not configured"
        )
    if not publisher_id.strip() or len(publisher_id.strip()) > 128:
        raise MachinePITSourceError(
            f"{MACHINE_PIT_PUBLISHER_ID_ENV} is not configured"
        )
    return key.encode("utf-8"), publisher_id.strip()


def _hmac_signature(payload: Mapping[str, object], key: bytes) -> str:
    signing_payload = {"attestation_domain": MACHINE_PIT_ATTESTATION_DOMAIN, **payload}
    digest = hmac.new(key, _canonical_json(signing_payload), hashlib.sha256).hexdigest()
    return _HMAC_PREFIX + digest


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise MachinePITSourceError(
                f"{field_name} must be timezone-aware datetime"
            ) from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MachinePITSourceError(f"{field_name} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MachinePITSourceError(f"{field_name} must be non-empty text")
    return value.strip()


def _required_sha256(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    if len(text) != len(_SHA256_PREFIX) + 64 or not text.startswith(_SHA256_PREFIX):
        raise MachinePITSourceError(f"{field_name} must be sha256")
    try:
        int(text[len(_SHA256_PREFIX) :], 16)
    except ValueError as error:
        raise MachinePITSourceError(f"{field_name} must be sha256") from error
    return text


def _required_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MachinePITSourceError(f"{field_name} must be a non-negative integer")
    return value


def _text_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise MachinePITSourceError(f"{field_name} must be a non-empty array")
    result: list[str] = []
    for item in value:
        result.append(_required_text(item, field_name))
    if result != sorted(set(result)):
        raise MachinePITSourceError(f"{field_name} must be sorted and unique")
    return result


def _read_json_object(path: Path, field_name: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise MachinePITSourceError(f"{field_name} is unreadable") from error
    if not isinstance(value, dict):
        raise MachinePITSourceError(f"{field_name} must be an object")
    if raw != _canonical_json(value) + b"\n":
        raise MachinePITSourceError(f"{field_name} is not canonical JSON")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _publisher_code_sha256() -> str:
    return _file_sha256(Path(__file__).resolve())


def _create_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(_canonical_json(payload) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise MachinePITSourceError(
            f"operational PIT publication already exists: {path}"
        ) from error
    except OSError as error:
        raise MachinePITSourceError("operational PIT publication is not writable") from error


def _require_temp_path(path: Path, *, field_name: str) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        path.relative_to(temp_root)
    except ValueError as error:
        raise MachinePITSourceError(
            f"{field_name} must be under operating-system TEMP"
        ) from error


__all__ = [
    "MACHINE_PIT_ATTESTATION_DOMAIN",
    "MACHINE_PIT_OPERATIONAL_CONSUMER_VERSION",
    "MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION",
    "MACHINE_PIT_OPERATIONAL_PUBLICATION_SCHEMA_VERSION",
    "MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV",
    "MACHINE_PIT_PUBLISHER_ID_ENV",
    "MachinePITSourceError",
    "consume_machine_pit_operational_candidate",
    "publish_machine_pit_operational_candidate",
    "validate_machine_pit_operational_candidate",
]

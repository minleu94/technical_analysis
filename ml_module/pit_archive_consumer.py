"""讀取 Formal 已持久化的 PIT candidate archive。

這個 consumer 只接受呼叫端同時提供的受控 archive root 與精確
``archive_manifest.json``。它重用 Formal archive readback 驗證 archive 內的
官方 TWSE／TPEx raw bytes、publication、receipt、operational envelope 與 rows，
再驗證目前 machine publisher 的簽章與可用時間。archive 是 immutable
candidate evidence；它不會把 archive 檔案複製回 TEMP，也不會把 candidate
提升成 Formal OOS、promotion 或 production input。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from data_module.pit_sector_machine_publisher import (
    MACHINE_PIT_ATTESTATION_DOMAIN,
    MACHINE_PIT_OPERATIONAL_PUBLICATION_SCHEMA_VERSION,
    MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION,
    MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV,
    MACHINE_PIT_PUBLISHER_ID_ENV,
    _publisher_code_sha256,
)
from data_module.pit_sector_membership_machine import (
    MACHINE_PIT_CONSUMER_VERSION,
    MACHINE_PIT_INPUT_SCHEMA_VERSION,
    MACHINE_PIT_PRODUCER_VERSION,
    MACHINE_PIT_PUBLICATION_SCHEMA_VERSION,
    MACHINE_PIT_RECEIPT_SCHEMA_VERSION,
    _machine_code_hash_mode,
)


PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION = "formal-input-pit-candidate-archive.v1"
PIT_ARCHIVE_CONSUMER_SCHEMA_VERSION = "ml-pit-candidate-archive-consumer.v1"
_SHA256_PREFIX = "sha256:"
_HMAC_PREFIX = "hmac-sha256:"
_TAIPEI = ZoneInfo("Asia/Taipei")
_ARCHIVE_BASENAME = "pit_candidate_archive"
_MANIFEST_BASENAME = "archive_manifest.json"
_EXPECTED_SOURCE_IDS = (
    "official:tpex:t187ap03_O",
    "official:twse:t187ap03_L",
)


class PITArchiveConsumerError(ValueError):
    """持久 PIT archive 不符合 ML consumer 契約。"""


def consume_pit_candidate_archive(
    *,
    archive_root: Path,
    manifest_path: Path,
    expected_manifest_file_hash: str,
    decision_at: datetime,
    now: datetime | None = None,
) -> dict[str, object]:
    """從受控 durable archive 讀取一份可供 shadow 的 PIT rows。

    ``manifest_path`` 必須是 caller 已選定並凍結 hash 的 exact manifest；本
    函式不掃描或挑選最新 archive。archive 的 capture 可以在前一日收盤後
    完成，只要 archive 已在本次 model ``decision_at`` 前持久化可讀。
    """

    requested_decision = _aware_datetime(decision_at, "decision_at")
    observed_now, now_source = _read_now(now)
    if requested_decision > observed_now:
        raise PITArchiveConsumerError(
            "archive consumer decision_at cannot be after consumer now"
        )
    root = _resolve_controlled_archive_root(archive_root)
    manifest = _resolve_exact_manifest(root, manifest_path)
    expected_hash = _required_sha256(
        expected_manifest_file_hash,
        "expected_manifest_file_hash",
    )
    observed_manifest_hash = _file_sha256(manifest)
    if observed_manifest_hash != expected_hash:
        raise PITArchiveConsumerError("archive manifest file hash mismatch")
    manifest_payload = _read_canonical_json(manifest, "archive manifest")
    _validate_archive_manifest_shape(manifest_payload)
    _validate_archive_files_have_no_reparse(root, manifest, manifest_payload)
    # First prove the immutable archive was persisted no later than the real
    # consumer clock.  The shared Formal validator compares first-seen
    # ``effective_from`` with immutable ``captured_at`` for historical
    # readback, while the checks below continue to use the actual consumer
    # clock and requested decision.
    archive_archived_at = _aware_datetime(
        manifest_payload.get("archived_at"),
        "archive.archived_at",
    )
    if archive_archived_at > observed_now:
        raise PITArchiveConsumerError("archive archived_at is after consumer now")

    try:
        # Formal owns archive creation and this readback. Keeping this call as
        # the single raw/row custody oracle avoids a second parser that could
        # drift from the producer's official TWSE/TPEx contract.
        from data_module.formal_daily_input_producer import (  # noqa: PLC0415
            _readback_pit_candidate_archive,
        )

        readback = _readback_pit_candidate_archive(manifest, now=observed_now)
    except Exception as error:  # noqa: BLE001 - archive boundary is fail closed
        raise PITArchiveConsumerError(
            "formal PIT archive readback failed: " + type(error).__name__
        ) from error

    _validate_archive_times(
        manifest_payload,
        readback,
        decision_at=requested_decision,
        now=observed_now,
    )
    publication_path, receipt_path, operational_path = _archive_role_paths(
        root,
        manifest,
        manifest_payload,
    )
    publication, publication_file_hash, publication_content_hash = (
        _read_hashed_canonical_json(
            publication_path,
            "archived publication",
            expected_file_hash=readback.get("publication_file_hash"),
            expected_content_hash=readback.get("publication_content_hash"),
        )
    )
    receipt, receipt_file_hash, receipt_content_hash = _read_hashed_canonical_json(
        receipt_path,
        "archived receipt",
        expected_file_hash=readback.get("receipt_file_hash"),
    )
    operational, operational_file_hash, operational_content_hash = (
        _read_hashed_canonical_json(
            operational_path,
            "archived operational publication",
            expected_file_hash=readback.get("operational_file_hash"),
        )
    )
    if receipt_content_hash != operational.get("receipt_content_hash"):
        raise PITArchiveConsumerError(
            "archived receipt content hash changed during read"
        )
    if operational_content_hash != operational.get("content_sha256"):
        raise PITArchiveConsumerError(
            "archived operational content hash changed during read"
        )
    _validate_current_publisher_attestation(operational)
    code_hash_mode = _validate_archive_identity(
        manifest_payload,
        publication=publication,
        receipt=receipt,
        operational=operational,
        readback=readback,
    )

    # Formal's readback is intentionally the first custody read.  Re-read the
    # manifest and bind every returned envelope to that readback before rows
    # leave this boundary.  This closes a TOCTOU window in which a second read
    # could otherwise return changed rows while retaining the old declarations.
    final_manifest, final_manifest_file_hash, _ = _read_hashed_canonical_json(
        manifest,
        "archive manifest",
        expected_file_hash=expected_hash,
        content_hash_field=None,
    )
    final_manifest_hash = _required_sha256(
        final_manifest.get("manifest_hash"),
        "archive.manifest_hash",
    )
    manifest_body = dict(final_manifest)
    manifest_body.pop("manifest_hash", None)
    if _sha256_json(manifest_body) != final_manifest_hash:
        raise PITArchiveConsumerError("archive manifest content hash mismatch")
    if final_manifest_hash != _required_sha256(
        readback.get("manifest_hash"),
        "archive.readback.manifest_hash",
    ):
        raise PITArchiveConsumerError("archive manifest changed during read")

    rows = publication.get("rows")
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise PITArchiveConsumerError("archived publication rows are invalid")
    row_count = readback.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int):
        raise PITArchiveConsumerError("archived PIT row_count is invalid")
    if len(rows) != row_count:
        raise PITArchiveConsumerError("archived PIT row_count mismatch")

    captured_at = _aware_datetime(readback.get("captured_at"), "captured_at")
    archived_at = _aware_datetime(
        manifest_payload.get("archived_at"),
        "archive.archived_at",
    )
    effective_from = _required_date(
        readback.get("effective_from"),
        "effective_from",
    )
    return {
        "status": "machine_verified_archive_candidate",
        "schema_version": PIT_ARCHIVE_CONSUMER_SCHEMA_VERSION,
        "archive_schema_version": PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION,
        "archive_root": str(root),
        "archive_manifest_path": str(manifest),
        "archive_manifest_file_hash": final_manifest_file_hash,
        "archive_manifest_hash": final_manifest_hash,
        "archive_id": manifest_payload.get("archive_id"),
        "publication_path": str(publication_path),
        "publication_file_hash": publication_file_hash,
        "publication_content_hash": publication_content_hash,
        "receipt_path": str(receipt_path),
        "receipt_file_hash": receipt_file_hash,
        "receipt_content_hash": receipt_content_hash,
        "operational_path": str(operational_path),
        "operational_file_hash": operational_file_hash,
        "capture_id": readback.get("capture_id"),
        "captured_at": captured_at.isoformat(),
        "available_at": operational["available_at"],
        "archived_at": archived_at.isoformat(),
        "archive_decision_at": _aware_datetime(
            manifest_payload.get("decision_at"),
            "archive.decision_at",
        ).isoformat(),
        "consumer_decision_at": requested_decision.isoformat(),
        "effective_from": effective_from.isoformat(),
        "row_count": row_count,
        "source_ids": list(_EXPECTED_SOURCE_IDS),
        "rows": [dict(row) for row in rows],
        "producer_code_sha256": publication.get("producer_code_sha256"),
        "publisher_code_sha256": operational.get("publisher_code_sha256"),
        "publisher_id": operational.get("publisher_id"),
        "current_code_hash_match": code_hash_mode == "current",
        "code_hash_compatibility": code_hash_mode,
        "legacy_code_hash_compatibility_verified": (
            code_hash_mode == "audited_legacy"
        ),
        "source_custody_verified": True,
        "rows_rebuilt_from_raw": True,
        "candidate_only": True,
        "formal_consumer_compatible": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
        "historical_backfill_claimed": False,
        "consumer_now": observed_now.isoformat(),
        "consumer_now_source": now_source,
        "decision_reason": (
            "accepted-code Formal PIT archive readback verified publication, receipt, "
            "operational attestation, official raw source hashes and rebuilt rows; "
            "candidate-only shadow input"
        ),
    }


def _read_now(now: datetime | None) -> tuple[datetime, str]:
    wall_now = datetime.now(timezone.utc)
    if now is None:
        return wall_now, "runtime_clock"
    observed = _aware_datetime(now, "now")
    # An injected clock is useful for deterministic isolated tests, but a
    # production caller must never use a future timestamp to manufacture
    # archive availability.  Tests should inject a timestamp that has already
    # elapsed; the consumer deliberately grants no clock-skew allowance.
    if observed > wall_now:
        raise PITArchiveConsumerError("consumer now cannot be future-dated")
    return observed, "caller_clock_for_isolated_readback"


def _resolve_controlled_archive_root(value: Path) -> Path:
    requested = value.expanduser()
    _reject_reparse_chain(requested, "archive root")
    if not requested.exists() or not requested.is_dir():
        raise PITArchiveConsumerError("archive root is not a directory")
    root = requested.resolve()
    if root.name != _ARCHIVE_BASENAME:
        raise PITArchiveConsumerError(
            "archive root must be the controlled pit_candidate_archive directory"
        )
    _reject_reparse_chain(root, "archive root")
    return root


def _resolve_exact_manifest(root: Path, value: Path) -> Path:
    requested = value.expanduser()
    _reject_reparse_chain(requested, "archive manifest")
    if not requested.is_file():
        raise PITArchiveConsumerError("archive manifest is missing")
    manifest = requested.resolve()
    try:
        relative = manifest.relative_to(root)
    except ValueError as error:
        raise PITArchiveConsumerError(
            "archive manifest escapes controlled archive root"
        ) from error
    if (
        len(relative.parts) != 3
        or relative.name != _MANIFEST_BASENAME
        or not _is_iso_date(relative.parts[0])
        or not relative.parts[1].strip()
    ):
        raise PITArchiveConsumerError(
            "archive manifest must be an exact natural-day archive entry"
        )
    _reject_reparse_chain(manifest, "archive manifest")
    return manifest


def _validate_archive_manifest_shape(payload: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "status",
        "input",
        "archive_id",
        "archived_at",
        "captured_at",
        "decision_at",
        "effective_from",
        "capture_id",
        "publication_content_hash",
        "row_count",
        "source_ids",
        "producer",
        "producer_version",
        "producer_code_sha256",
        "consumer",
        "consumer_verified_at_capture",
        "archive_independent_of_temp",
        "candidate_only",
        "formal_consumer_compatible",
        "historical_backfill_claimed",
        "formal_oos_allowed",
        "promotion_eligible",
        "broker_order_allowed",
        "archive_reason",
        "files",
        "manifest_hash",
    }
    if set(payload) != required:
        raise PITArchiveConsumerError("archive manifest fields are invalid")
    for key, expected in (
        ("schema_version", PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION),
        ("status", "archived_candidate"),
        ("input", "pit_sector_membership"),
        ("producer", "data_module.pit_sector_membership_machine"),
        ("producer_version", MACHINE_PIT_PRODUCER_VERSION),
        ("consumer_verified_at_capture", True),
        ("archive_independent_of_temp", True),
        ("candidate_only", True),
        ("formal_consumer_compatible", False),
        ("historical_backfill_claimed", False),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
    ):
        if payload.get(key) is not expected if isinstance(expected, bool) else payload.get(key) != expected:
            raise PITArchiveConsumerError(f"archive manifest {key} is invalid")
    _required_sha256(payload.get("manifest_hash"), "archive.manifest_hash")
    _required_sha256(
        payload.get("publication_content_hash"),
        "archive.publication_content_hash",
    )
    _required_sha256(
        payload.get("producer_code_sha256"),
        "archive.producer_code_sha256",
    )
    source_ids = payload.get("source_ids")
    if source_ids != list(_EXPECTED_SOURCE_IDS):
        raise PITArchiveConsumerError("archive manifest source identity is invalid")
    row_count = payload.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
        raise PITArchiveConsumerError("archive manifest row_count is invalid")


def _validate_archive_times(
    manifest: Mapping[str, object],
    readback: Mapping[str, object],
    *,
    decision_at: datetime,
    now: datetime,
) -> None:
    captured = _aware_datetime(readback.get("captured_at"), "archive.captured_at")
    archived = _aware_datetime(manifest.get("archived_at"), "archive.archived_at")
    archive_decision = _aware_datetime(
        manifest.get("decision_at"),
        "archive.decision_at",
    )
    if captured > archived:
        raise PITArchiveConsumerError("archive persistence precedes source capture")
    if archived > now:
        raise PITArchiveConsumerError("archive archived_at is after consumer now")
    if captured > decision_at or archived > decision_at:
        raise PITArchiveConsumerError(
            "archive was not persisted before consumer decision"
        )
    if archive_decision > decision_at:
        raise PITArchiveConsumerError(
            "archive attestation decision is after consumer decision"
        )
    effective = _required_date(readback.get("effective_from"), "effective_from")
    if effective != captured.astimezone(_TAIPEI).date():
        raise PITArchiveConsumerError(
            "archive effective_from does not equal capture natural date"
        )


def _archive_role_paths(
    root: Path,
    manifest: Path,
    payload: Mapping[str, object],
) -> tuple[Path, Path, Path]:
    files = payload.get("files")
    if not isinstance(files, list):
        raise PITArchiveConsumerError("archive files are invalid")
    by_role: dict[str, Path] = {}
    for item in files:
        if not isinstance(item, Mapping):
            raise PITArchiveConsumerError("archive file entry is invalid")
        role = item.get("role")
        relative = item.get("relative_path")
        if not isinstance(role, str) or not role.strip():
            raise PITArchiveConsumerError("archive file role is invalid")
        if not isinstance(relative, str) or not relative.strip():
            raise PITArchiveConsumerError("archive file path is invalid")
        target = (manifest.parent / Path(relative)).resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise PITArchiveConsumerError(
                "archive file escapes controlled archive root"
            ) from error
        _reject_reparse_chain(target, f"archive file:{role}")
        if role in by_role:
            raise PITArchiveConsumerError("archive file roles are duplicated")
        by_role[role] = target
    try:
        return by_role["publication"], by_role["receipt"], by_role["operational"]
    except KeyError as error:
        raise PITArchiveConsumerError("archive envelope files are incomplete") from error


def _validate_current_publisher_attestation(
    payload: Mapping[str, object],
) -> None:
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
        raise PITArchiveConsumerError("archived operational fields are invalid")
    for key, expected in (
        ("schema_version", MACHINE_PIT_OPERATIONAL_PUBLICATION_SCHEMA_VERSION),
        ("status", "published_candidate"),
        ("input", "pit_sector_membership"),
        ("input_schema_version", MACHINE_PIT_INPUT_SCHEMA_VERSION),
        ("publisher", "data_module.pit_sector_machine_publisher"),
        ("publisher_version", MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION),
        ("attestation_domain", MACHINE_PIT_ATTESTATION_DOMAIN),
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
        if payload.get(key) is not expected if isinstance(expected, bool) else payload.get(key) != expected:
            raise PITArchiveConsumerError(f"archived operational {key} is invalid")
    publisher_code = _required_sha256(
        payload.get("publisher_code_sha256"),
        "operational.publisher_code_sha256",
    )
    if publisher_code != _publisher_code_sha256():
        raise PITArchiveConsumerError(
            "archived operational publisher code hash is not current"
        )
    key = os.environ.get(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, "")
    publisher_id = os.environ.get(MACHINE_PIT_PUBLISHER_ID_ENV, "")
    if not key.strip() or not publisher_id.strip():
        raise PITArchiveConsumerError("machine publisher attestation is not configured")
    if payload.get("publisher_id") != publisher_id.strip():
        raise PITArchiveConsumerError("archived operational publisher identity mismatch")
    content_hash = _required_sha256(
        payload.get("content_sha256"),
        "operational.content_sha256",
    )
    signed_body = {
        name: value
        for name, value in payload.items()
        if name not in {"attestation_signature", "content_sha256"}
    }
    if _sha256_json({**signed_body, "attestation_signature": payload.get("attestation_signature")}) != content_hash:
        raise PITArchiveConsumerError("archived operational content hash mismatch")
    signing_payload = {
        "attestation_domain": MACHINE_PIT_ATTESTATION_DOMAIN,
        **signed_body,
    }
    expected_signature = _HMAC_PREFIX + hmac.new(
        key.strip().encode("utf-8"),
        _canonical_json(signing_payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if payload.get("attestation_signature") != expected_signature:
        raise PITArchiveConsumerError("archived operational attestation mismatch")
    policy = payload.get("availability_policy")
    if policy != {
        "name": "response-completion-timestamp-gated",
        "date_only_consumer_allowed": False,
        "decision_must_be_at_or_after_available_at": True,
    }:
        raise PITArchiveConsumerError("archived operational availability policy is invalid")
    _aware_datetime(payload.get("decision_at"), "operational.decision_at")
    _aware_datetime(payload.get("available_at"), "operational.available_at")
    if payload.get("source_ids") != list(_EXPECTED_SOURCE_IDS):
        raise PITArchiveConsumerError("archived operational source identity is invalid")


def _validate_archive_identity(
    manifest: Mapping[str, object],
    *,
    publication: Mapping[str, object],
    receipt: Mapping[str, object],
    operational: Mapping[str, object],
    readback: Mapping[str, object],
) -> str:
    producer_code = _required_sha256(
        manifest.get("producer_code_sha256"),
        "archive.producer_code_sha256",
    )
    try:
        code_hash_mode = _machine_code_hash_mode(
            producer_code,
            "archive.producer_code_sha256",
        )
    except Exception as error:  # noqa: BLE001 - archive boundary is fail closed
        raise PITArchiveConsumerError(str(error)) from error
    if publication.get("producer_code_sha256") != producer_code:
        raise PITArchiveConsumerError("archived publication producer code mismatch")
    if publication.get("schema_version") != MACHINE_PIT_PUBLICATION_SCHEMA_VERSION:
        raise PITArchiveConsumerError("archived publication schema is incompatible")
    if publication.get("producer_version") != MACHINE_PIT_PRODUCER_VERSION:
        raise PITArchiveConsumerError("archived publication producer version is incompatible")
    receipt_code = _required_sha256(
        receipt.get("consumer_code_sha256"),
        "archive.receipt.consumer_code_sha256",
    )
    try:
        receipt_code_mode = _machine_code_hash_mode(
            receipt_code,
            "archive.receipt.consumer_code_sha256",
        )
    except Exception as error:  # noqa: BLE001 - archive boundary is fail closed
        raise PITArchiveConsumerError(str(error)) from error
    if receipt_code != producer_code or receipt_code_mode != code_hash_mode:
        raise PITArchiveConsumerError(
            "archive producer and receipt code hashes are incompatible"
        )
    if receipt.get("schema_version") != MACHINE_PIT_RECEIPT_SCHEMA_VERSION:
        raise PITArchiveConsumerError("archived receipt schema is incompatible")
    if receipt.get("consumer") != "data_module.pit_sector_membership_machine":
        raise PITArchiveConsumerError("archived receipt consumer is incompatible")
    if receipt.get("consumer_version") != MACHINE_PIT_CONSUMER_VERSION:
        raise PITArchiveConsumerError("archived receipt consumer version is incompatible")
    for source_ids in (
        readback.get("source_ids"),
        receipt.get("source_ids"),
        operational.get("source_ids"),
    ):
        if source_ids != list(_EXPECTED_SOURCE_IDS):
            raise PITArchiveConsumerError("archive source identity mismatch")
    for name, value in (
        ("capture_id", readback.get("capture_id")),
        ("receipt.capture_id", receipt.get("capture_id")),
        ("operational.capture_id", operational.get("capture_id")),
        ("manifest.capture_id", manifest.get("capture_id")),
    ):
        if value != readback.get("capture_id"):
            raise PITArchiveConsumerError(f"archive {name} mismatch")
    for name, value in (
        ("publication_content_hash", publication.get("content_sha256")),
        ("receipt.publication_content_hash", receipt.get("publication_content_hash")),
        ("operational.publication_content_hash", operational.get("publication_content_hash")),
        ("manifest.publication_content_hash", manifest.get("publication_content_hash")),
    ):
        if value != readback.get("publication_content_hash"):
            raise PITArchiveConsumerError(f"archive {name} mismatch")
    captured = _aware_datetime(readback.get("captured_at"), "archive.captured_at")
    available = _aware_datetime(operational.get("available_at"), "operational.available_at")
    receipt_captured = _aware_datetime(receipt.get("captured_at"), "receipt.captured_at")
    evaluated = _aware_datetime(receipt.get("evaluated_at"), "receipt.evaluated_at")
    if available != captured or receipt_captured != captured:
        raise PITArchiveConsumerError("archive available_at/captured_at mismatch")
    if evaluated < captured:
        raise PITArchiveConsumerError("archive receipt evaluation precedes capture")
    if operational.get("effective_from") != readback.get("effective_from"):
        raise PITArchiveConsumerError("archive effective_from mismatch")
    if operational.get("row_count") != readback.get("row_count"):
        raise PITArchiveConsumerError("archive operational row_count mismatch")
    return code_hash_mode


def _validate_archive_files_have_no_reparse(
    root: Path,
    manifest: Path,
    payload: Mapping[str, object],
) -> None:
    _reject_reparse_chain(manifest, "archive manifest")
    files = payload.get("files")
    if not isinstance(files, list):
        raise PITArchiveConsumerError("archive files are invalid")
    for item in files:
        if not isinstance(item, Mapping):
            raise PITArchiveConsumerError("archive file entry is invalid")
        relative = item.get("relative_path")
        role = item.get("role")
        if not isinstance(relative, str) or not relative.strip():
            raise PITArchiveConsumerError("archive file path is invalid")
        target = (manifest.parent / Path(relative)).resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise PITArchiveConsumerError("archive file escapes root") from error
        _reject_reparse_chain(target, f"archive file:{role}")
        if not target.is_file():
            raise PITArchiveConsumerError(f"archive file is missing:{role}")


def _reject_reparse_chain(path: Path, field_name: str) -> None:
    current = path
    while True:
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            raise PITArchiveConsumerError(
                f"{field_name} cannot be inspected"
            ) from error
        if stat.S_ISLNK(info.st_mode) or _is_reparse_point(info):
            raise PITArchiveConsumerError(f"{field_name} contains symlink or junction")
        if current.parent == current:
            break
        current = current.parent


def _is_reparse_point(info: os.stat_result) -> bool:
    return bool(int(getattr(info, "st_file_attributes", 0)) & 0x400)


def _read_hashed_canonical_json(
    path: Path,
    field_name: str,
    *,
    expected_file_hash: object | None = None,
    expected_content_hash: object | None = None,
    content_hash_field: str | None = "content_sha256",
) -> tuple[dict[str, object], str, str]:
    """Read one canonical JSON object and bind it to both hash layers.

    ``expected_file_hash`` binds the bytes to Formal's first readback.  The
    content hash is then recomputed from the parsed body, so a second read
    cannot replace rows while retaining a stale declaration.  The manifest
    uses ``manifest_hash`` rather than ``content_sha256`` and is checked by
    the caller after this helper returns.
    """

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise PITArchiveConsumerError(f"{field_name} is unreadable") from error
    observed_file_hash = _sha256_bytes(raw)
    if expected_file_hash is not None:
        expected = _required_sha256(
            expected_file_hash,
            f"{field_name}.expected_file_hash",
        )
        if observed_file_hash != expected:
            raise PITArchiveConsumerError(
                f"{field_name} file hash changed during read"
            )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PITArchiveConsumerError(f"{field_name} JSON is invalid") from error
    if not isinstance(value, dict):
        raise PITArchiveConsumerError(f"{field_name} JSON must be an object")
    canonical = (_canonical_json(value) + "\n").encode("utf-8")
    if raw != canonical:
        raise PITArchiveConsumerError(f"{field_name} JSON is not canonical")
    payload = {str(key): item for key, item in value.items()}
    if content_hash_field is None:
        observed_content_hash = ""
    else:
        declared_content_hash = _required_sha256(
            payload.get(content_hash_field),
            f"{field_name}.{content_hash_field}",
        )
        content_body = dict(payload)
        content_body.pop(content_hash_field, None)
        observed_content_hash = _sha256_json(content_body)
        if observed_content_hash != declared_content_hash:
            raise PITArchiveConsumerError(
                f"{field_name} content hash mismatch during read"
            )
        if expected_content_hash is not None:
            expected_content = _required_sha256(
                expected_content_hash,
                f"{field_name}.expected_content_hash",
            )
            if observed_content_hash != expected_content:
                raise PITArchiveConsumerError(
                    f"{field_name} content hash changed during read"
                )
    return payload, observed_file_hash, observed_content_hash


def _read_canonical_json(path: Path, field_name: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise PITArchiveConsumerError(f"{field_name} is unreadable") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PITArchiveConsumerError(f"{field_name} JSON is invalid") from error
    if not isinstance(value, dict):
        raise PITArchiveConsumerError(f"{field_name} JSON must be an object")
    canonical = (_canonical_json(value) + "\n").encode("utf-8")
    if raw != canonical:
        raise PITArchiveConsumerError(f"{field_name} JSON is not canonical")
    return {str(key): item for key, item in value.items()}


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PITArchiveConsumerError(
                f"{field_name} must be timezone-aware datetime"
            ) from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PITArchiveConsumerError(f"{field_name} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _required_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise PITArchiveConsumerError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise PITArchiveConsumerError(f"{field_name} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise PITArchiveConsumerError(f"{field_name} must be canonical YYYY-MM-DD")
    return parsed


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _required_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != len(_SHA256_PREFIX) + 64:
        raise PITArchiveConsumerError(f"{field_name} must be sha256")
    if not value.startswith(_SHA256_PREFIX):
        raise PITArchiveConsumerError(f"{field_name} must be sha256")
    try:
        int(value[len(_SHA256_PREFIX) :], 16)
    except ValueError as error:
        raise PITArchiveConsumerError(f"{field_name} must be sha256") from error
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return _sha256_bytes((_canonical_json(value)).encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
    except OSError as error:
        raise PITArchiveConsumerError("archive file hash read failed") from error
    return _SHA256_PREFIX + digest.hexdigest()


__all__ = [
    "PIT_ARCHIVE_CONSUMER_SCHEMA_VERSION",
    "PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION",
    "PITArchiveConsumerError",
    "consume_pit_candidate_archive",
]

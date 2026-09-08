"""由已驗證 PIT handoff 發布正式 sector sidecar 並交給既有 assembler。

此 publisher 是 input-level 的 machine publication。它只在同時具備獨立
data.gov 分母、明確 prospective coverage、台北 08:30 cutoff、archive
custody 與機器授權 scope 時發布；Rule／causal ledger 仍由各自 producer
決定，這個 sidecar 不會把整體三項 Formal input 標成 ready。

publication 採 create-only。receipt 寫入中斷時，下一次執行會重新驗證既有
sidecar、重新跑 assembler 的 in-memory consumer，再補上相同 receipt；不
會覆寫原始 archive、公司資料、SQLite 或交易資料。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from data_module.formal_pit_history_handoff import (
    PIT_DECISION_TIME,
    read_pit_candidate_history_handoff,
)
from data_module.pit_prospective_denominator import (
    validate_prospective_pit_denominator,
)


FORMAL_PIT_SECTOR_SIDECAR_SCHEMA_VERSION = "formal-pit-sector-sidecar.v1"
FORMAL_PIT_SECTOR_RECEIPT_SCHEMA_VERSION = "formal-pit-sector-receipt.v1"
FORMAL_PIT_SECTOR_PUBLISHER_VERSION = "machine-pit-handoff-publisher.v1"
FORMAL_PIT_SECTOR_CONSUMER_VERSION = "assembler-sector-membership-consumer.v1"
FORMAL_PIT_SECTOR_PUBLISHER_ID = "machine:formal-pit-sector-publisher"
SIDECAR_SCHEMA_VERSION = "pit-sector-membership-sidecar-v1"
MANIFEST_SCHEMA_VERSION = "pit-sector-membership-manifest-v1"
TAIPEI = ZoneInfo("Asia/Taipei")
_SHA256_RE = __import__("re").compile(r"^sha256:[0-9a-f]{64}$")


class FormalPITSectorPublisherError(ValueError):
    """正式 PIT sector sidecar 不符合 machine publication 契約。"""


def publish_formal_pit_sector_sidecar(
    *,
    handoff_path: Path,
    denominator_path: Path,
    publication_root: Path,
    decision_at: datetime,
    now: datetime | None = None,
) -> dict[str, object]:
    """驗證 handoff／分母後 create-only 發布 sidecar，再執行 assembler readback。"""

    decision = _aware_datetime(decision_at, "decision_at")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    )
    if decision > observed_now:
        raise FormalPITSectorPublisherError("decision_at cannot be after now")
    handoff_resolved = handoff_path.expanduser().resolve()
    denominator_resolved = denominator_path.expanduser().resolve()
    try:
        handoff = read_pit_candidate_history_handoff(handoff_resolved)
    except Exception as error:  # noqa: BLE001 - retain a bounded publication receipt
        return _write_blocked_receipt(
            publication_root=publication_root,
            decision=decision,
            blockers=["pit_formal_handoff_invalid:" + _safe_error(error)],
            handoff_path=handoff_resolved,
            denominator_path=denominator_resolved,
        )
    try:
        denominator = validate_prospective_pit_denominator(
            denominator_resolved,
            now=decision,
        )
    except (Exception,) as error:  # noqa: BLE001 - report source-specific blocker
        return _write_blocked_receipt(
            publication_root=publication_root,
            decision=decision,
            blockers=["pit_formal_denominator_invalid:" + _safe_error(error)],
            handoff_path=handoff_resolved,
            denominator_path=denominator_resolved,
        )

    projection = handoff.get("projection")
    if not isinstance(projection, Mapping):
        return _write_blocked_receipt(
            publication_root=publication_root,
            decision=decision,
            blockers=["pit_formal_handoff_projection_missing"],
            handoff_path=handoff_resolved,
            denominator_path=denominator_resolved,
        )
    blockers = [str(item) for item in projection.get("blockers", []) if isinstance(item, str)]
    allowed_boundary = {"pit_formal_sidecar_publication_required"}
    blockers = sorted(set(item for item in blockers if item not in allowed_boundary))
    blockers.extend(
        _validate_projection_scope(
            projection,
            denominator,
            denominator_path=denominator_resolved,
            decision=decision,
        )
    )
    if blockers:
        return _write_blocked_receipt(
            publication_root=publication_root,
            decision=decision,
            blockers=sorted(set(blockers)),
            handoff_path=handoff_resolved,
            denominator_path=denominator_resolved,
        )
    try:
        rows, selected_archives, covered_dates = _rows_from_handoff(
            projection,
            denominator,
            decision=decision,
        )
        sidecar_path, receipt_path = _publication_paths(
            publication_root,
            decision.astimezone(TAIPEI).date(),
        )
        sidecar_payload = _build_sidecar(
            rows=rows,
            projection=projection,
            denominator=denominator,
            selected_archives=selected_archives,
            covered_dates=covered_dates,
            decision=decision,
        )
        _write_create_only_json(sidecar_path, sidecar_payload)
        consumer = _consume_sidecar_bytes(
            sidecar_path,
            decision_at=decision,
        )
        sidecar_file_hash = _file_sha256(sidecar_path)
        sidecar_manifest = sidecar_payload.get("manifest")
        if not isinstance(sidecar_manifest, Mapping):  # pragma: no cover - local guard
            raise FormalPITSectorPublisherError("formal PIT sidecar manifest is invalid")
        raw_license_scope = denominator.get("license_scope")
        if not isinstance(raw_license_scope, Mapping):
            raise FormalPITSectorPublisherError("denominator license scope is invalid")
        receipt_body: dict[str, object] = {
            "schema_version": FORMAL_PIT_SECTOR_RECEIPT_SCHEMA_VERSION,
            "status": "formal_source_publication",
            "input": "pit_sector_membership",
            "publisher": "data_module.formal_pit_sector_publisher",
            "publisher_version": FORMAL_PIT_SECTOR_PUBLISHER_VERSION,
            "publisher_id": FORMAL_PIT_SECTOR_PUBLISHER_ID,
            "publisher_code_sha256": _publisher_code_sha256(),
            "consumer": "data_module.portfolio_ml_dataset_assembler._spool_sector_memberships",
            "consumer_version": FORMAL_PIT_SECTOR_CONSUMER_VERSION,
            "consumer_verified": consumer["consumer_verified"],
            "consumer_readback": consumer,
            "decision_at": decision.isoformat(),
            "coverage_start": projection["coverage"]["coverage_start"],
            "coverage_end": projection["coverage"]["coverage_end"],
            "covered_trading_dates": covered_dates,
            "selected_archive_ids": selected_archives,
            "sidecar_path": str(sidecar_path.resolve()),
            "sidecar_file_hash": sidecar_file_hash,
            "sidecar_content_hash": sidecar_manifest["canonical_hash"],
            "rows_hash": sidecar_manifest["rows_hash"],
            "row_count": sidecar_manifest["row_count"],
            "handoff_path": str(handoff_resolved),
            "handoff_file_hash": _file_sha256(handoff_resolved),
            "handoff_content_hash": projection["handoff_content_hash"],
            "denominator_path": str(denominator_resolved),
            "denominator_file_hash": _file_sha256(denominator_resolved),
            "denominator_content_hash": denominator["content_sha256"],
            "universe_hash": denominator["symbols_hash"],
            "source_ids": _source_ids(denominator),
            "license_scope": dict(raw_license_scope),
            "formal_source_only": True,
            "formal_ready": True,
            "formal_consumer_compatible": True,
            "candidate_only": False,
            "scope": "prospective_pit_sector_membership",
            "historical_backfill_claimed": False,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "production_action_allowed": False,
            "decision_reason": (
                "machine verified denominator, official source custody, Taipei "
                "cutoff coverage and assembler readback; input-level PIT sidecar "
                "only, with Rule and causal ledger readiness evaluated separately"
            ),
        }
        receipt_payload = {
            **receipt_body,
            "receipt_hash": _payload_hash(receipt_body),
        }
        _write_create_only_json(receipt_path, receipt_payload)
        readback = read_formal_pit_sector_receipt(
            receipt_path,
            sidecar_path=sidecar_path,
            decision_at=decision,
        )
        return {
            "status": "formal_source_publication",
            "formal_ready": True,
            "formal_consumer_compatible": True,
            "candidate_only": False,
            "sidecar_path": str(sidecar_path.resolve()),
            "receipt_path": str(receipt_path.resolve()),
            "sidecar_file_hash": sidecar_file_hash,
            "receipt_file_hash": _file_sha256(receipt_path),
            "receipt_hash": readback["receipt_hash"],
            "row_count": len(rows),
            "covered_trading_dates": covered_dates,
            "consumer_verified": True,
            "selected_archive_ids": selected_archives,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "production_action_allowed": False,
        }
    except Exception as error:  # noqa: BLE001 - publication remains candidate/blocked
        return _write_blocked_receipt(
            publication_root=publication_root,
            decision=decision,
            blockers=["pit_formal_sidecar_publication_failed:" + _safe_error(error)],
            handoff_path=handoff_resolved,
            denominator_path=denominator_resolved,
        )


def consume_formal_pit_sector_sidecar(
    sidecar_path: Path,
    *,
    receipt_path: Path,
    decision_at: datetime,
    now: datetime | None = None,
) -> dict[str, object]:
    """由既有 assembler spool／consumer 讀回已發布 sidecar。"""

    decision = _aware_datetime(decision_at, "decision_at")
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    )
    if decision > observed_now:
        raise FormalPITSectorPublisherError("decision_at cannot be after now")
    receipt = read_formal_pit_sector_receipt(
        receipt_path,
        sidecar_path=sidecar_path,
        decision_at=decision,
    )
    consumed = _consume_sidecar_bytes(sidecar_path, decision_at=decision)
    if consumed["consumer_verified"] is not True:
        raise FormalPITSectorPublisherError("formal PIT sidecar consumer readback failed")
    return {**receipt, "consumer_readback": consumed}


def read_formal_pit_sector_receipt(
    receipt_path: Path,
    *,
    sidecar_path: Path,
    decision_at: datetime,
) -> dict[str, object]:
    """驗證 receipt、sidecar file hash、canonical hash 與時間界線。"""

    decision = _aware_datetime(decision_at, "decision_at")
    path = receipt_path.expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalPITSectorPublisherError("formal PIT receipt is unreadable") from error
    if not isinstance(payload, Mapping):
        raise FormalPITSectorPublisherError("formal PIT receipt must be an object")
    if payload.get("schema_version") != FORMAL_PIT_SECTOR_RECEIPT_SCHEMA_VERSION:
        raise FormalPITSectorPublisherError("formal PIT receipt schema is invalid")
    if payload.get("status") != "formal_source_publication":
        raise FormalPITSectorPublisherError("formal PIT receipt status is invalid")
    if payload.get("input") != "pit_sector_membership":
        raise FormalPITSectorPublisherError("formal PIT receipt input is invalid")
    for field, expected in (
        ("publisher", "data_module.formal_pit_sector_publisher"),
        ("publisher_version", FORMAL_PIT_SECTOR_PUBLISHER_VERSION),
        ("publisher_id", FORMAL_PIT_SECTOR_PUBLISHER_ID),
        ("consumer", "data_module.portfolio_ml_dataset_assembler._spool_sector_memberships"),
        ("consumer_version", FORMAL_PIT_SECTOR_CONSUMER_VERSION),
        ("formal_source_only", True),
        ("formal_ready", True),
        ("formal_consumer_compatible", True),
        ("candidate_only", False),
        ("historical_backfill_claimed", False),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("production_action_allowed", False),
        ("consumer_verified", True),
    ):
        if payload.get(field) != expected:
            raise FormalPITSectorPublisherError(f"formal PIT receipt {field} is invalid")
    published_decision = _aware_datetime(payload.get("decision_at"), "receipt.decision_at")
    if published_decision > decision:
        raise FormalPITSectorPublisherError("consumer decision is before publication decision")
    publisher_hash = _required_sha256(payload.get("publisher_code_sha256"), "publisher_code_sha256")
    if publisher_hash != _publisher_code_sha256():
        raise FormalPITSectorPublisherError("formal PIT publisher code hash mismatch")
    sidecar = sidecar_path.expanduser().resolve()
    if str(sidecar) != payload.get("sidecar_path"):
        raise FormalPITSectorPublisherError("formal PIT receipt sidecar path mismatch")
    expected_file_hash = _required_sha256(payload.get("sidecar_file_hash"), "sidecar_file_hash")
    if _file_sha256(sidecar) != expected_file_hash:
        raise FormalPITSectorPublisherError("formal PIT sidecar file hash mismatch")
    try:
        from data_module.portfolio_ml_dataset_assembler import (  # noqa: PLC0415
            _load_sector_membership_sidecar,
        )

        rows, canonical_hash = _load_sector_membership_sidecar(sidecar)
    except Exception as error:  # noqa: BLE001 - surface assembler rejection
        raise FormalPITSectorPublisherError("formal PIT sidecar assembler validation failed") from error
    if canonical_hash != payload.get("sidecar_content_hash"):
        raise FormalPITSectorPublisherError("formal PIT sidecar canonical hash mismatch")
    rows_hash = _payload_hash([dict(row) for row in rows])
    if rows_hash != payload.get("rows_hash"):
        raise FormalPITSectorPublisherError("formal PIT sidecar rows hash mismatch")
    if payload.get("row_count") != len(rows):
        raise FormalPITSectorPublisherError("formal PIT receipt row_count mismatch")
    receipt_hash = _required_sha256(payload.get("receipt_hash"), "receipt_hash")
    body = dict(payload)
    body.pop("receipt_hash", None)
    if receipt_hash != _payload_hash(body):
        raise FormalPITSectorPublisherError("formal PIT receipt hash mismatch")
    return {
        **dict(payload),
        "receipt_file_hash": _file_sha256(path),
        "row_count": len(rows),
    }


def _validate_projection_scope(
    projection: Mapping[str, object],
    denominator: Mapping[str, object],
    *,
    denominator_path: Path,
    decision: datetime,
) -> list[str]:
    blockers: list[str] = []
    if projection.get("status") != "candidate_history_verified":
        blockers.append("pit_formal_handoff_not_candidate_history_verified")
    if projection.get("candidate_only") is not True:
        blockers.append("pit_formal_handoff_candidate_flag_invalid")
    coverage = projection.get("coverage")
    if not isinstance(coverage, Mapping):
        return ["pit_formal_handoff_coverage_missing"]
    required = coverage.get("required_trading_dates")
    covered = coverage.get("covered_trading_dates")
    missing = coverage.get("missing_trading_dates")
    required_dates, required_valid = _strict_date_list(
        required,
        "required_trading_dates",
    )
    if not required_dates:
        blockers.append("pit_formal_required_trading_dates_empty")
    covered_dates, covered_valid = _strict_date_list(
        covered,
        "covered_trading_dates",
    )
    missing_dates, missing_valid = _strict_date_list(
        missing,
        "missing_trading_dates",
    )
    if not required_valid or not covered_valid or not missing_valid:
        blockers.append("pit_formal_handoff_coverage_shape_invalid")
    elif sorted(covered_dates) != sorted(required_dates) or missing_dates:
        blockers.append("pit_formal_handoff_coverage_incomplete")
    coverage_start = coverage.get("coverage_start")
    if coverage_start != denominator.get("coverage_start"):
        blockers.append("pit_formal_handoff_denominator_coverage_start_mismatch")
    local = decision.astimezone(TAIPEI)
    if local.time() < PIT_DECISION_TIME and local.date().isoformat() in required_dates:
        blockers.append("pit_formal_decision_before_current_day_cutoff:" + local.date().isoformat())
    universe = projection.get("independent_universe")
    if not isinstance(universe, Mapping) or universe.get("state") != "verified":
        blockers.append("pit_formal_independent_expected_universe_not_verified")
    elif universe.get("content_hash") != denominator.get("symbols_hash"):
        blockers.append("pit_formal_denominator_hash_not_bound")
    if isinstance(universe, Mapping):
        if universe.get("file_hash") != _file_sha256(denominator_path):
            blockers.append("pit_formal_denominator_file_hash_not_bound")
        if universe.get("denominator_content_hash") != denominator.get("content_sha256"):
            blockers.append("pit_formal_denominator_content_hash_not_bound")
    scope = projection.get("license_scope")
    if not isinstance(scope, Mapping) or scope.get("status") != "machine_scope_verified":
        blockers.append("pit_formal_license_scope_not_machine_verified")
    else:
        if scope.get("formal_acceptance_granted") is not True or scope.get("machine_policy_only") is not True:
            blockers.append("pit_formal_license_scope_not_formally_accepted")
        allowed_use_cases = scope.get("allowed_use_cases")
        if not isinstance(allowed_use_cases, list) or "formal_pit_sector_membership" not in allowed_use_cases:
            blockers.append("pit_formal_license_use_scope_missing")
        if not _license_scope_matches(scope, denominator.get("license_scope")):
            blockers.append("pit_formal_license_scope_projection_mismatch")
    if projection.get("formal_ready") is not False or projection.get("formal_consumer_compatible") is not False:
        blockers.append("pit_formal_handoff_candidate_flags_invalid")
    return blockers


def _strict_date_list(
    value: object,
    field_name: str,
) -> tuple[list[str], bool]:
    """只接受 canonical YYYY-MM-DD 清單，拒絕日期字串排序捷徑。"""

    del field_name  # retained for call-site readability and future diagnostics
    if not isinstance(value, list):
        return [], False
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return [], False
        try:
            parsed = date.fromisoformat(item)
        except ValueError:
            return [], False
        if parsed.isoformat() != item:
            return [], False
        normalized.append(item)
    if normalized != sorted(set(normalized)):
        return [], False
    return normalized, True


def _license_scope_matches(
    projected: Mapping[str, object],
    expected: object,
) -> bool:
    """比較授權封套的值，允許 handoff 加入 lineage source diagnostics。"""

    if not isinstance(expected, Mapping):
        return False
    projected_body = dict(projected)
    projected_body.pop("lineage_source_ids", None)
    expected_body = dict(expected)
    for body in (projected_body, expected_body):
        for key in ("allowed_use_cases", "source_ids", "government_dataset_ids"):
            value = body.get(key)
            if isinstance(value, list):
                body[key] = sorted(value, key=str)
    return projected_body == expected_body


def _rows_from_handoff(
    projection: Mapping[str, object],
    denominator: Mapping[str, object],
    *,
    decision: datetime,
) -> tuple[list[dict[str, object]], list[str], list[str]]:
    coverage = projection["coverage"]
    if not isinstance(coverage, Mapping):  # pragma: no cover - guarded above
        raise FormalPITSectorPublisherError("handoff coverage is invalid")
    required_dates = [str(item) for item in coverage["required_trading_dates"]]
    covered_dates = [str(item) for item in coverage["covered_trading_dates"]]
    coverage_start = _required_text(coverage.get("coverage_start"), "coverage.coverage_start")
    lineage = projection.get("lineage")
    if not isinstance(lineage, list) or not lineage:
        raise FormalPITSectorPublisherError("handoff lineage is empty")
    selected: dict[str, Mapping[str, object]] = {}
    for target in required_dates:
        cutoff = _taipei_cutoff(target)
        candidates = [
            item
            for item in lineage
            if isinstance(item, Mapping)
            and str(item.get("effective_from", "")) >= coverage_start
            and str(item.get("effective_from", "")) <= target
            and _aware_datetime(item.get("available_at"), "lineage.available_at") <= cutoff
            and _aware_datetime(item.get("archived_at"), "lineage.archived_at") <= cutoff
        ]
        if not candidates:
            raise FormalPITSectorPublisherError(
                "handoff covered date has no custody archive:" + target
            )
        chosen = max(
            candidates,
            key=lambda item: (
                str(item.get("effective_from")),
                str(item.get("available_at")),
                str(item.get("publication_content_hash")),
            ),
        )
        archive_id = _required_text(chosen.get("archive_id"), "lineage.archive_id")
        selected[archive_id] = chosen
    raw_expected_symbols = denominator.get("symbols")
    if not isinstance(raw_expected_symbols, list):
        raise FormalPITSectorPublisherError("denominator symbols are invalid")
    expected_symbols = tuple(str(item) for item in raw_expected_symbols)
    rows_by_key: dict[tuple[str, str, str, str], dict[str, object]] = {}
    selected_ids: list[str] = []
    for archive_id, lineage_item in sorted(selected.items()):
        archive_rows = _read_archive_rows(lineage_item, decision=decision)
        if tuple(sorted(str(row.get("symbol")) for row in archive_rows)) != expected_symbols:
            raise FormalPITSectorPublisherError(
                "archive rows do not match verified denominator:" + archive_id
            )
        for row in archive_rows:
            normalized = dict(row)
            key = (
                _required_text(normalized.get("symbol"), "row.symbol"),
                _required_text(normalized.get("available_at"), "row.available_at"),
                _required_text(normalized.get("effective_from"), "row.effective_from"),
                _required_text(normalized.get("sector_id"), "row.sector_id"),
            )
            rows_by_key[key] = normalized
        selected_ids.append(archive_id)
    if not rows_by_key:
        raise FormalPITSectorPublisherError("formal PIT sidecar rows are empty")
    return list(rows_by_key.values()), selected_ids, sorted(set(covered_dates))


def _read_archive_rows(
    lineage: Mapping[str, object],
    *,
    decision: datetime,
) -> list[dict[str, object]]:
    manifest_path = Path(_required_text(lineage.get("archive_manifest_path"), "lineage.archive_manifest_path"))
    from data_module.formal_daily_input_producer import (  # noqa: PLC0415
        _pit_candidate_json_file,
        _readback_pit_candidate_archive,
    )

    readback = _readback_pit_candidate_archive(manifest_path, now=decision)
    if readback.get("publication_content_hash") != lineage.get("publication_content_hash"):
        raise FormalPITSectorPublisherError("archive publication content hash changed")
    manifest = _pit_candidate_json_file(manifest_path, "PIT archive manifest")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise FormalPITSectorPublisherError("archive files are missing")
    publication_entry = next(
        (item for item in files if isinstance(item, Mapping) and item.get("role") == "publication"),
        None,
    )
    if not isinstance(publication_entry, Mapping):
        raise FormalPITSectorPublisherError("archive publication file is missing")
    relative = publication_entry.get("relative_path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise FormalPITSectorPublisherError("archive publication path is invalid")
    publication_path = (manifest_path.parent / relative).resolve()
    try:
        publication_path.relative_to(manifest_path.parent.resolve())
    except ValueError as error:
        raise FormalPITSectorPublisherError("archive publication path escapes archive") from error
    publication = _pit_candidate_json_file(publication_path, "archived PIT publication")
    body = dict(publication)
    content_hash = _required_sha256(body.pop("content_sha256", None), "publication.content_sha256")
    if content_hash != lineage.get("publication_content_hash") or content_hash != _payload_hash(body):
        raise FormalPITSectorPublisherError("archived PIT publication content hash mismatch")
    rows = publication.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise FormalPITSectorPublisherError("archived PIT publication rows are invalid")
    return [dict(row) for row in rows]


def _build_sidecar(
    *,
    rows: Sequence[Mapping[str, object]],
    projection: Mapping[str, object],
    denominator: Mapping[str, object],
    selected_archives: Sequence[str],
    covered_dates: Sequence[str],
    decision: datetime,
) -> dict[str, object]:
    normalized_rows = [dict(row) for row in rows]
    rows_hash = _payload_hash(normalized_rows)
    coverage = projection["coverage"]
    if not isinstance(coverage, Mapping):  # pragma: no cover
        raise FormalPITSectorPublisherError("sidecar coverage is invalid")
    source_registry = denominator.get("source_registry")
    if not isinstance(source_registry, list):
        raise FormalPITSectorPublisherError("denominator source registry is invalid")
    manifest_body: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "formal_source_publication",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "scope": "prospective_pit_sector_membership",
        "historical_backfill_claimed": False,
        "clock_id": "formal-pit-handoff:" + str(projection["handoff_content_hash"])[7:23],
        "clock_manifest_hash": str(projection["handoff_content_hash"]),
        "coverage_start": coverage.get("coverage_start"),
        "coverage_end": coverage.get("coverage_end"),
        "covered_trading_dates": list(covered_dates),
        "universe_hash": denominator["symbols_hash"],
        "row_count": len(normalized_rows),
        "rows_hash": rows_hash,
        "source_registry": source_registry,
        "selected_archive_ids": list(selected_archives),
        "denominator_content_hash": denominator["content_sha256"],
        "license_scope": denominator["license_scope"],
        "publisher": "data_module.formal_pit_sector_publisher",
        "publisher_version": FORMAL_PIT_SECTOR_PUBLISHER_VERSION,
        "publisher_code_sha256": _publisher_code_sha256(),
        "decision_at": decision.isoformat(),
        "availability_policy": "archive_available_at_must_be_lte_taipei_0830_cutoff",
    }
    canonical_hash = _payload_hash(
        {
            "sidecar_schema_version": SIDECAR_SCHEMA_VERSION,
            "manifest": manifest_body,
        }
    )
    envelope: dict[str, object] = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "manifest": {**manifest_body, "canonical_hash": canonical_hash},
        "rows": normalized_rows,
    }
    return envelope


def _consume_sidecar_bytes(
    sidecar_path: Path,
    *,
    decision_at: datetime,
) -> dict[str, object]:
    from data_module.portfolio_ml_dataset_assembler import (  # noqa: PLC0415
        _initialize_spool,
        _load_sector_membership_sidecar,
        _spool_sector_memberships,
    )

    sidecar = sidecar_path.expanduser().resolve()
    before = _file_sha256(sidecar)
    payloads, canonical_hash = _load_sector_membership_sidecar(sidecar)
    with sqlite3.connect(":memory:") as connection:
        _initialize_spool(connection)
        observed_hash, row_count = _spool_sector_memberships(
            connection,
            sidecar,
            training_as_of=decision_at,
        )
        stored_count = int(
            connection.execute("SELECT COUNT(*) FROM sector_memberships").fetchone()[0]
        )
    after = _file_sha256(sidecar)
    if before != after:
        raise FormalPITSectorPublisherError("formal PIT sidecar changed during assembler read")
    if observed_hash != canonical_hash or row_count != len(payloads) or stored_count != len(payloads):
        raise FormalPITSectorPublisherError("assembler sidecar readback count/hash mismatch")
    return {
        "consumer": "data_module.portfolio_ml_dataset_assembler._spool_sector_memberships",
        "consumer_verified": True,
        "sidecar_file_hash": after,
        "sidecar_content_hash": canonical_hash,
        "row_count": len(payloads),
        "spooled_row_count": stored_count,
    }


def _validate_sidecar_manifest_for_receipt(
    sidecar_path: Path,
) -> tuple[tuple[Mapping[str, Any], ...], str]:
    from data_module.portfolio_ml_dataset_assembler import (  # noqa: PLC0415
        _load_sector_membership_sidecar,
    )

    return _load_sector_membership_sidecar(sidecar_path.expanduser().resolve())


def _publication_paths(root: Path, natural_date: date) -> tuple[Path, Path]:
    output_root = root.expanduser().resolve()
    _require_output_root(output_root)
    directory = output_root / "pit_sector_membership_formal" / natural_date.isoformat()
    return directory / "sidecar.json", directory / "receipt.json"


def _write_blocked_receipt(
    *,
    publication_root: Path,
    decision: datetime,
    blockers: Sequence[str],
    handoff_path: Path,
    denominator_path: Path,
) -> dict[str, object]:
    sidecar_path, receipt_path = _publication_paths(
        publication_root,
        decision.astimezone(TAIPEI).date(),
    )
    body: dict[str, object] = {
        "schema_version": FORMAL_PIT_SECTOR_RECEIPT_SCHEMA_VERSION,
        "status": "blocked",
        "input": "pit_sector_membership",
        "publisher": "data_module.formal_pit_sector_publisher",
        "publisher_version": FORMAL_PIT_SECTOR_PUBLISHER_VERSION,
        "publisher_id": FORMAL_PIT_SECTOR_PUBLISHER_ID,
        "publisher_code_sha256": _publisher_code_sha256(),
        "decision_at": decision.isoformat(),
        "blockers": sorted(set(str(item) for item in blockers)),
        "sidecar_path": str(sidecar_path.resolve()),
        "handoff_path": str(handoff_path),
        "denominator_path": str(denominator_path),
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
        "historical_backfill_claimed": False,
        "decision_reason": "formal sidecar was withheld because objective evidence is incomplete",
    }
    # Include the actual decision instant, source paths and current publisher
    # code hash in the immutable identity.  A later retry on the same natural
    # day may observe a different clock or code revision; it must append a new
    # diagnostic receipt rather than collide with an older blocked receipt or
    # overwrite it.
    blocked_path = receipt_path.with_name(
        "blocked-receipt-" + _payload_hash(body)[7:23] + ".json"
    )
    _write_create_only_json(blocked_path, {**body, "receipt_hash": _payload_hash(body)})
    return {
        "status": "blocked",
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "blockers": body["blockers"],
        "blocked_receipt_path": str(blocked_path.resolve()),
        "sidecar_path": str(sidecar_path.resolve()),
    }


def _write_create_only_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise FormalPITSectorPublisherError("immutable formal PIT publication differs on retry")


def _require_output_root(path: Path) -> None:
    repository_output = Path(__file__).resolve().parents[1] / "output"
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        path.relative_to(repository_output.resolve())
    except ValueError:
        try:
            path.relative_to(temp_root)
        except ValueError as error:
            raise FormalPITSectorPublisherError(
                "formal PIT publication root must be under repository output or TEMP"
            ) from error


def _source_ids(denominator: Mapping[str, object]) -> list[str]:
    raw = denominator.get("source_registry")
    if not isinstance(raw, list):
        raise FormalPITSectorPublisherError("denominator source registry is invalid")
    return sorted(
        _required_text(item.get("source_id"), "source_registry.source_id")
        for item in raw
        if isinstance(item, Mapping)
    )


def _taipei_cutoff(value: str) -> datetime:
    try:
        target = date.fromisoformat(value)
    except ValueError as error:
        raise FormalPITSectorPublisherError("coverage date is invalid") from error
    return datetime.combine(target, PIT_DECISION_TIME, tzinfo=TAIPEI).astimezone(timezone.utc)


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise FormalPITSectorPublisherError(f"{field_name} must be ISO timestamp") from error
    else:
        raise FormalPITSectorPublisherError(f"{field_name} must be ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FormalPITSectorPublisherError(f"{field_name} must include timezone")
    return parsed


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalPITSectorPublisherError(f"{field_name} must be non-empty text")
    return value


def _required_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise FormalPITSectorPublisherError(f"{field_name} must be sha256 digest")
    return value


def _payload_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _publisher_code_sha256() -> str:
    return _file_sha256(Path(__file__).resolve())


def _safe_error(error: Exception) -> str:
    return (str(error).splitlines()[0].strip() or type(error).__name__)[:220].replace("\x00", "?")


__all__ = [
    "FORMAL_PIT_SECTOR_CONSUMER_VERSION",
    "FORMAL_PIT_SECTOR_PUBLISHER_ID",
    "FORMAL_PIT_SECTOR_PUBLISHER_VERSION",
    "FORMAL_PIT_SECTOR_RECEIPT_SCHEMA_VERSION",
    "FORMAL_PIT_SECTOR_SIDECAR_SCHEMA_VERSION",
    "FormalPITSectorPublisherError",
    "consume_formal_pit_sector_sidecar",
    "publish_formal_pit_sector_sidecar",
    "read_formal_pit_sector_receipt",
]

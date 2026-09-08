"""Build a fail-closed, evidence-driven packet for the three Formal inputs.

The candidate inventory deliberately does not discover or wire Formal inputs.
This module keeps its bounded candidate metadata, then optionally invokes the
explicit production consumers for ledger, Rule history and PIT membership.
Owner/reviewer names are metadata only.  The packet never selects a candidate,
renames a manifest, writes a controlled path, or grants Formal/OOS credit.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from data_module.formal_portfolio_ledger import (
    load_formal_portfolio_state_ledger,
)
from data_module.pit_sector_membership_machine import (
    MachinePITSourceError,
    validate_machine_pit_receipt,
)
from data_module.pit_sector_machine_publisher import (
    consume_machine_pit_operational_candidate,
)
from data_module.rule_champion_snapshot_service import (
    load_verified_rule_champion_snapshot_history,
)
from scripts.continue_ml_direct_ooc_after_store import (
    _validate_sector_sidecar,
    discover_valid_sector_membership,
)


FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION = "formal-input-owner-review.v1"
INVENTORY_SCHEMA_VERSION = "ml-formal-input-candidate-inventory.v1"
EXPECTED_INPUTS: tuple[tuple[str, str, str], ...] = (
    (
        "causal_non_cash_portfolio_ledger",
        "causal-portfolio-ledger.v1",
        "由 owner 發布 append-only non-cash state ledger，逐日綁定 T-1、row hash、chain hash 與 custody。",
    ),
    (
        "formal_rule_champion_snapshot_history",
        "rule-champion-snapshot-history.v1",
        "由 owner 發布正式 Rule Champion snapshot history，綁定決策日、版本、hash 與可重建輸入。",
    ),
    (
        "pit_sector_membership",
        "pit-sector-membership-sidecar-v1",
        "由 owner 提供歷史 PIT sector membership sidecar，逐日綁定來源 publication、as-of 與 coverage。",
    ),
)
_EXPECTED_INPUT_NAMES = frozenset(item[0] for item in EXPECTED_INPUTS)
MACHINE_PIT_RECEIPT_ENV = "BALDR_ML_PIT_SECTOR_MEMBERSHIP_MACHINE_RECEIPT_PATH"
MACHINE_PIT_PUBLICATION_ENV = (
    "BALDR_ML_PIT_SECTOR_MEMBERSHIP_MACHINE_PUBLICATION_PATH"
)
FORMAL_LEDGER_ENV = "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"
FORMAL_RULE_HISTORY_ENV = "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"
FORMAL_SECTOR_ENV = "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"
FORMAL_INPUT_NAMES = tuple(item[0] for item in EXPECTED_INPUTS)
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_inventory(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"formal candidate inventory is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("formal candidate inventory must be a JSON object")
    if payload.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise ValueError("formal candidate inventory schema is unsupported")
    if payload.get("formal_oos_allowed") is not False:
        raise ValueError("formal candidate inventory must remain formal_oos_allowed=false")
    if payload.get("broker_order_allowed") is not False:
        raise ValueError("formal candidate inventory must remain broker_order_allowed=false")
    if payload.get("promotion_eligible") is not False:
        raise ValueError("formal candidate inventory must remain promotion_eligible=false")
    if payload.get("formal_ready_input_count", 0) not in (0, None):
        raise ValueError("formal candidate inventory must report formal_ready_input_count=0")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("formal candidate inventory candidates must be a list")
    candidate_root = str(payload.get("candidate_root") or "").strip()
    if not candidate_root:
        raise ValueError("formal candidate inventory candidate_root is required")
    return payload, _sha256_file(path)


def _candidate_projection(item: Mapping[str, object]) -> dict[str, object]:
    path = str(item.get("path") or "").strip()
    manifest_hash = str(item.get("manifest_sha256") or "").strip()
    lane = str(item.get("lane") or "").strip()
    reason = str(item.get("reason") or "").strip()
    if not path or not manifest_hash.startswith("sha256:") or not lane or not reason:
        raise ValueError("formal candidate inventory row is missing safe identity fields")
    raw_safe_projection = item.get("safe_projection")
    safe_projection: dict[str, object] = {}
    if isinstance(raw_safe_projection, Mapping):
        safe_projection = {str(key): value for key, value in raw_safe_projection.items()}
    return {
        "path": path,
        "manifest_sha256": manifest_hash,
        "lane": lane,
        "reason": reason,
        "formal_consumer_compatible": (
            item.get("formal_consumer_compatible")
            if isinstance(item.get("formal_consumer_compatible"), bool)
            else None
        ),
        "formal_oos_allowed": (
            item.get("formal_oos_allowed")
            if isinstance(item.get("formal_oos_allowed"), bool)
            else None
        ),
        "safe_projection": safe_projection,
    }


def _training_as_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("formal_training_as_of must be valid ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("formal_training_as_of must include timezone")
    return parsed.astimezone(timezone.utc)


def _formal_missing_projection(
    *,
    input_name: str,
    reason: str,
    path: Path | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "input": input_name,
        "state": "missing",
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "reason": reason,
    }
    if path is not None:
        result["path"] = str(path)
    return result


def _formal_unknown_projection(
    *,
    input_name: str,
    reason: str,
    path: Path | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "input": input_name,
        "state": "unknown",
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "reason": reason,
    }
    if path is not None:
        result["path"] = str(path)
    return result


def _formal_invalid_projection(
    *,
    input_name: str,
    path: Path,
    error: Exception,
) -> dict[str, object]:
    detail = str(error).splitlines()[0].strip()
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return {
        "input": input_name,
        "state": "invalid",
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "path": str(path),
        "reason": "formal_consumer_validation_failed",
        "error_type": type(error).__name__,
        "detail": detail,
    }


def _validated_formal_ledger(
    path: Path,
    *,
    training_as_of: str,
) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return _formal_missing_projection(
            input_name="causal_non_cash_portfolio_ledger",
            reason="configured_path_is_not_a_file",
            path=resolved,
        )
    # Ledger decisions are date-only.  Use the Taiwan trading date rather
    # than the UTC date, while Rule/PIT consumers below retain the full
    # timezone-aware cutoff timestamp for same-day availability checks.
    cutoff = _training_as_datetime(training_as_of).astimezone(_TAIPEI_TZ).date()
    ledger = load_formal_portfolio_state_ledger(resolved)
    decision_dates = tuple(date.fromisoformat(value) for value in ledger.decision_dates)
    if any(value >= cutoff for value in decision_dates):
        raise ValueError(
            "ledger date-only transition requires a later Taiwan calendar-day "
            "formal_training_as_of; intraday same-day availability is unproven"
        )
    return {
        "input": "causal_non_cash_portfolio_ledger",
        "state": "ready",
        "formal_ready": True,
        "formal_consumer_compatible": True,
        "candidate_only": False,
        "path": str(resolved),
        "file_hash": _sha256_file(resolved),
        "manifest_hash": ledger.ledger_manifest_hash,
        "transition_chain_hash": ledger.transition_chain_hash,
        "decision_date_count": len(ledger.decision_dates),
        "non_cash_state_day_count": ledger.non_cash_state_day_count,
        "consumer": "data_module.formal_portfolio_ledger.load_formal_portfolio_state_ledger",
        "cutoff_semantics": "taipei_calendar_date_after_date_only_transition",
        "reason": "formal ledger consumer validated custody and a later Taiwan cutoff date",
    }


def _validated_formal_rule_history(
    path: Path,
    *,
    training_as_of: str,
) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return _formal_missing_projection(
            input_name="formal_rule_champion_snapshot_history",
            reason="configured_path_is_not_a_file",
            path=resolved,
        )
    history = load_verified_rule_champion_snapshot_history(
        resolved,
        training_as_of=training_as_of,
    )
    return {
        "input": "formal_rule_champion_snapshot_history",
        "state": "ready",
        "formal_ready": True,
        "formal_consumer_compatible": True,
        "candidate_only": False,
        "path": str(resolved),
        "file_hash": history.manifest_file_hash,
        "manifest_hash": history.manifest_hash,
        "registered_store_id": history.registered_store_id,
        "decision_date_count": len(history.decision_dates),
        "snapshot_count": len(history.snapshots),
        "consumer": "data_module.rule_champion_snapshot_service.load_verified_rule_champion_snapshot_history",
        "reason": "formal Rule history consumer validated custody, HMAC and cutoff",
    }


def _validated_formal_sector(
    path: Path,
    *,
    training_as_of: str,
) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return _formal_missing_projection(
            input_name="pit_sector_membership",
            reason="configured_path_is_not_a_file",
            path=resolved,
        )
    file_hash = _sha256_file(resolved)
    # The production discovery function performs the same canonical assembler
    # validation used by readiness.  The direct helper is a bounded fallback
    # for an explicit file name that is not one of the discovery aliases.
    candidate = discover_valid_sector_membership(
        output_root=resolved.parent,
        training_as_of=training_as_of,
        expected_file_hash=file_hash,
    )
    if candidate is None:
        _validate_sector_sidecar(resolved, training_as_of=training_as_of)
        candidate = resolved
    if candidate.resolve() != resolved:
        raise ValueError("configured PIT sector path was not the validated candidate")
    return {
        "input": "pit_sector_membership",
        "state": "ready",
        "formal_ready": True,
        "formal_consumer_compatible": True,
        "candidate_only": False,
        "path": str(resolved),
        "file_hash": file_hash,
        "consumer": "scripts.continue_ml_direct_ooc_after_store.discover_valid_sector_membership",
        "reason": "formal PIT sector assembler validated source, custody and cutoff",
    }


def _load_formal_input_projections(
    *,
    ledger_path: str | Path | None,
    rule_history_path: str | Path | None,
    sector_path: str | Path | None,
    training_as_of: str | None,
) -> dict[str, dict[str, object]]:
    paths: dict[str, str | Path | None] = {
        "causal_non_cash_portfolio_ledger": ledger_path,
        "formal_rule_champion_snapshot_history": rule_history_path,
        "pit_sector_membership": sector_path,
    }
    if training_as_of is None or not str(training_as_of).strip():
        return {
            input_name: (
                _formal_unknown_projection(
                    input_name=input_name,
                    reason="formal_training_as_of_required",
                )
                if path is not None
                else _formal_missing_projection(
                    input_name=input_name,
                    reason="formal_source_path_not_provided",
                )
            )
            for input_name, path in paths.items()
        }
    # Validate the cutoff once before invoking any loader.  An invalid cutoff
    # is an unknown evidence state, rather than an owner/reviewer task.
    try:
        _training_as_datetime(str(training_as_of))
    except (TypeError, ValueError) as error:
        return {
            input_name: (
                _formal_unknown_projection(
                    input_name=input_name,
                    reason="formal_training_as_of_invalid",
                )
                if path is not None
                else _formal_missing_projection(
                    input_name=input_name,
                    reason="formal_source_path_not_provided",
                )
            )
            for input_name, path in paths.items()
        }

    loaders = {
        "causal_non_cash_portfolio_ledger": _validated_formal_ledger,
        "formal_rule_champion_snapshot_history": _validated_formal_rule_history,
        "pit_sector_membership": _validated_formal_sector,
    }
    result: dict[str, dict[str, object]] = {}
    for input_name, raw_path in paths.items():
        if raw_path is None or not str(raw_path).strip():
            result[input_name] = _formal_missing_projection(
                input_name=input_name,
                reason="formal_source_path_not_provided",
            )
            continue
        resolved = Path(raw_path).expanduser().resolve()
        try:
            result[input_name] = loaders[input_name](
                resolved,
                training_as_of=str(training_as_of),
            )
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            result[input_name] = _formal_invalid_projection(
                input_name=input_name,
                path=resolved,
                error=error,
            )
    return result


def build_formal_input_owner_packet(
    inventory_path: str | Path,
    *,
    owner_role: str = "",
    reviewer_role: str = "",
    max_candidates_per_input: int = 8,
    pit_machine_receipt_path: str | Path | None = None,
    pit_machine_publication_path: str | Path | None = None,
    pit_machine_decision_at: datetime | None = None,
    formal_ledger_path: str | Path | None = None,
    formal_rule_history_path: str | Path | None = None,
    formal_sector_path: str | Path | None = None,
    formal_training_as_of: str | None = None,
) -> dict[str, Any]:
    """Build an evidence-driven, non-authorizing owner packet.

    Candidate inventory rows remain metadata only.  A formal-ready decision is
    emitted only after the explicit production consumers validate the supplied
    ledger, Rule history and PIT sidecar.  Owner/reviewer names are retained as
    packet metadata and never affect the state decision.
    """

    resolved_inventory = Path(inventory_path).expanduser().resolve()
    if (
        isinstance(max_candidates_per_input, bool)
        or not isinstance(max_candidates_per_input, int)
        or not 1 <= max_candidates_per_input <= 32
    ):
        raise ValueError("max_candidates_per_input must be between 1 and 32")
    inventory, inventory_hash = _load_inventory(resolved_inventory)
    candidate_rows: dict[str, list[dict[str, object]]] = {
        input_name: [] for input_name in _EXPECTED_INPUT_NAMES
    }
    for raw_item in inventory["candidates"]:
        if not isinstance(raw_item, Mapping):
            raise ValueError("formal candidate inventory row must be an object")
        input_name = raw_item.get("candidate_input")
        if not isinstance(input_name, str) or input_name not in _EXPECTED_INPUT_NAMES:
            continue
        projected = _candidate_projection(raw_item)
        bucket = candidate_rows[str(input_name)]
        if len(bucket) < max_candidates_per_input:
            bucket.append(projected)

    normalized_owner = owner_role.strip()
    normalized_reviewer = reviewer_role.strip()
    machine_decision = pit_machine_decision_at or datetime.now(timezone.utc)
    machine_projection = _load_machine_pit_candidate(
        receipt_path=pit_machine_receipt_path,
        publication_path=pit_machine_publication_path,
        decision_at=machine_decision,
    )
    formal_projections = _load_formal_input_projections(
        ledger_path=formal_ledger_path,
        rule_history_path=formal_rule_history_path,
        sector_path=formal_sector_path,
        training_as_of=formal_training_as_of,
    )
    review_records: list[dict[str, Any]] = []
    for input_name, expected_schema, requirement in EXPECTED_INPUTS:
        candidates = candidate_rows[input_name]
        formal_projection = formal_projections[input_name]
        formal_ready = formal_projection.get("state") == "ready"
        input_machine_projection: dict[str, object] | None
        if formal_ready:
            input_machine_projection = formal_projection
        elif input_name == "pit_sector_membership":
            input_machine_projection = machine_projection
        else:
            input_machine_projection = None
        evidence_state = str(formal_projection.get("state") or "unknown")
        if formal_ready:
            owner_decision = "machine_verified"
        elif evidence_state == "invalid":
            owner_decision = "input_evidence_invalid"
        elif evidence_state == "unknown":
            owner_decision = "unknown"
        elif input_machine_projection is not None:
            owner_decision = "machine_candidate"
        else:
            owner_decision = "needs_input_evidence"
        review_records.append(
            {
                "input": input_name,
                "expected_schema": expected_schema,
                "requirement": requirement,
                "candidate_count_in_packet": len(candidates),
                "candidate_count_observed": int(
                    (inventory.get("candidate_input_counts") or {}).get(input_name, 0)
                ),
                "candidates": candidates,
                "owner_decision": owner_decision,
                "evidence_state": evidence_state,
                "evidence_required": not formal_ready,
                "formal_ready": formal_ready,
                "formal_consumer_compatible": formal_ready,
                "selected_candidate_path": "",
                "published_formal_path": "",
                "custody_id": "",
                "reviewed_at": "",
                "review_note": "",
                # 缺證據是資料狀態，不是人工審核請求；保留欄位以相容
                # 舊 packet，但永遠不由 owner/reviewer 名字推導。
                "machine_review_required": False,
                "machine_verification": input_machine_projection,
                "formal_consumer_evidence": formal_projection,
            }
        )

    machine_verified_count = sum(
        1
        for record in review_records
        if record.get("machine_verification") is not None
    )
    formal_ready_count = sum(
        1 for record in review_records if record.get("formal_ready") is True
    )
    machine_candidate_count = sum(
        1
        for record in review_records
        if isinstance(record.get("machine_verification"), Mapping)
        and record.get("formal_ready") is not True
    )
    evidence_state_counts = {
        state: sum(
            1 for record in review_records if record.get("evidence_state") == state
        )
        for state in ("missing", "unknown", "invalid", "ready")
    }
    if formal_ready_count == len(review_records):
        packet_status = "machine_verified"
    elif evidence_state_counts["invalid"]:
        packet_status = "input_evidence_invalid"
    elif evidence_state_counts["unknown"]:
        packet_status = "unknown_input_evidence"
    elif evidence_state_counts["missing"]:
        packet_status = "needs_input_evidence"
    elif machine_candidate_count:
        packet_status = "machine_verified_candidate"
    else:  # pragma: no cover - defensive if a new state is introduced
        packet_status = "unknown_input_evidence"
    return {
        "schema_version": FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "packet_status": packet_status,
        "inventory_path": str(resolved_inventory),
        "inventory_sha256": inventory_hash,
        "candidate_root": str(Path(str(inventory["candidate_root"])).expanduser().resolve()),
        "inventory_manifest_count": inventory.get("manifest_count", 0),
        "inventory_skipped_count": inventory.get("skipped_count", 0),
        "inventory_truncated": inventory.get("truncated", False),
        "inventory_lane_counts": inventory.get("lane_counts", {}),
        "owner_role": normalized_owner,
        "reviewer_role": normalized_reviewer,
        "owner_reviewer_required": False,
        "human_review_required": False,
        "owner_reviewer_metadata_only": True,
        "formal_ready_input_count": formal_ready_count,
        "machine_verified_input_count": machine_verified_count,
        "machine_candidate_input_count": machine_candidate_count,
        "formal_consumer_compatible_count": formal_ready_count,
        "missing_input_count": evidence_state_counts["missing"],
        "unknown_input_count": evidence_state_counts["unknown"],
        "invalid_input_count": evidence_state_counts["invalid"],
        "evidence_required": formal_ready_count != len(review_records),
        "formal_input_count": len(review_records),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "promotion_eligible": False,
        "candidate_only": True,
        "write_performed": False,
        "publication_emitted": False,
        "review_records": review_records,
        "limitations": [
            "候選 inventory 只保留 bounded manifest metadata，不代表 underlying data rows 已通過 loader、PIT、cutoff 或 custody。",
            "research／prospective artifact 不得改名、複製或直接接到正式 BALDR_ML_FORMAL_* path。",
            "必須由 owner-controlled publisher 產生三份 expected schema manifest，再由正式 readiness inspector 重新驗證 hash、cutoff、chain 與來源。",
            "本 packet 不會選擇 candidate、不會填入 published_formal_path、不會授予 Formal OOS、promotion 或 broker 資格。",
            "owner_role／reviewer_role 只保存 metadata；缺少來源證據時狀態是 needs_input_evidence、unknown 或 invalid，不會轉成具名人工審核門檻。",
            "machine PIT receipt 若驗證成功，只表示官方 raw custody 可由 consumer 重建 current natural-day candidate；它不等於正式 PIT input，也不計入 formal ready。",
            "只有三個明確路徑都由正式 consumer 驗證成功，才會將相應 input 標為 machine_verified；本 packet 仍維持 read-only、formal_oos_allowed=false。",
        ],
    }


def _load_machine_pit_candidate(
    *,
    receipt_path: str | Path | None,
    publication_path: str | Path | None,
    decision_at: datetime,
) -> dict[str, object] | None:
    """讀取明確指定的 machine publication／receipt，絕不自動掃描 TEMP。"""

    if publication_path is not None:
        return _load_machine_pit_publication(publication_path, decision_at=decision_at)
    return _load_machine_pit_receipt(receipt_path, decision_at=decision_at)


def _load_machine_pit_publication(
    publication_path: str | Path,
    *,
    decision_at: datetime,
) -> dict[str, object]:
    resolved = Path(publication_path).expanduser().resolve()
    try:
        resolved.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as error:
        raise ValueError("machine PIT publication must be under OS TEMP") from error
    try:
        consumed = consume_machine_pit_operational_candidate(
            resolved,
            decision_at=decision_at,
        )
    except (MachinePITSourceError, OSError, TypeError, ValueError) as error:
        raise ValueError(
            "machine PIT operational publication validation failed: "
            f"{type(error).__name__}:{str(error).splitlines()[0]}"
        ) from error
    source_ids = consumed.get("source_ids")
    if not isinstance(source_ids, list):
        raise ValueError("machine PIT operational publication source_ids are invalid")
    return {
        "status": "machine_verified",
        "operational_publication_path": str(resolved),
        "operational_file_hash": str(consumed.get("operational_file_hash") or ""),
        "publisher_id": str(consumed.get("publisher_id") or ""),
        "publisher_code_sha256": str(consumed.get("publisher_code_sha256") or ""),
        "attestation_signature": str(consumed.get("attestation_signature") or ""),
        "consumer_decision_at": str(consumed.get("consumer_decision_at") or ""),
        "published_decision_at": str(consumed.get("published_decision_at") or ""),
        "available_at": str(consumed.get("available_at") or ""),
        "effective_from": str(consumed.get("effective_from") or ""),
        "capture_id": str(consumed.get("capture_id") or ""),
        "row_count": consumed.get("row_count"),
        "source_ids": list(source_ids),
        "source_custody_verified": consumed.get("source_custody_verified") is True,
        "rows_rebuilt_from_raw": consumed.get("rows_rebuilt_from_raw") is True,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "reason": str(consumed.get("decision_reason") or ""),
    }


def _load_machine_pit_receipt(
    receipt_path: str | Path | None,
    *,
    decision_at: datetime,
) -> dict[str, object] | None:
    """讀取明確指定的 PIT machine receipt，絕不自動掃描 TEMP。"""

    if receipt_path is None:
        return None
    resolved = Path(receipt_path).expanduser().resolve()
    try:
        resolved.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as error:
        raise ValueError("machine PIT receipt must be under OS TEMP") from error
    try:
        receipt = validate_machine_pit_receipt(resolved, now=decision_at)
    except (MachinePITSourceError, OSError, TypeError, ValueError) as error:
        raise ValueError(
            "machine PIT receipt validation failed: "
            f"{type(error).__name__}:{str(error).splitlines()[0]}"
        ) from error
    source_ids = receipt.get("source_ids")
    if not isinstance(source_ids, list):
        raise ValueError("machine PIT receipt source_ids are invalid")
    return {
        "status": "machine_verified",
        "receipt_path": str(resolved),
        "receipt_file_hash": str(receipt.get("receipt_file_hash") or ""),
        "publication_file_hash": str(
            receipt.get("publication_file_hash") or ""
        ),
        "publication_content_hash": str(
            receipt.get("publication_content_hash") or ""
        ),
        "capture_id": str(receipt.get("capture_id") or ""),
        "captured_at": str(receipt.get("captured_at") or ""),
        "effective_from": str(receipt.get("effective_from") or ""),
        "consumer_decision_at": decision_at.isoformat(),
        "row_count": receipt.get("row_count"),
        "source_ids": list(source_ids),
        "source_custody_verified": receipt.get("source_custody_verified") is True,
        "rows_rebuilt_from_raw": receipt.get("rows_rebuilt_from_raw") is True,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "reason": str(receipt.get("decision_reason") or ""),
    }


def validate_output_path(output_path: str | Path, *, inventory_path: str | Path) -> Path:
    """Reject overwriting inventory or writing a packet into the candidate tree."""

    output = Path(output_path).expanduser().resolve()
    inventory = Path(inventory_path).expanduser().resolve()
    if output == inventory:
        raise ValueError("owner packet output must not overwrite the inventory")
    if output.parent == inventory.parent and output.name.lower() == "inventory.json":
        raise ValueError("owner packet output must not replace inventory.json")
    if not output.parent.exists():
        raise ValueError("owner packet output parent must already exist")
    try:
        candidate_root_value = json.loads(inventory.read_text(encoding="utf-8")).get("candidate_root")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        candidate_root_value = None
    if isinstance(candidate_root_value, str) and candidate_root_value.strip():
        candidate_root = Path(candidate_root_value).expanduser().resolve()
        if output == candidate_root or output.is_relative_to(candidate_root):
            raise ValueError("owner packet output must be outside candidate_root")
    return output


def render_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# Formal Input Owner Review Packet (Candidate)",
        "",
        f"- Packet status: `{packet.get('packet_status', '')}`",
        f"- Inventory: `{packet.get('inventory_path', '')}`",
        f"- Inventory SHA-256: `{packet.get('inventory_sha256', '')}`",
        f"- Candidate root: `{packet.get('candidate_root', '')}`",
        f"- Manifest count / skipped / truncated: `{packet.get('inventory_manifest_count', 0)}` / `{packet.get('inventory_skipped_count', 0)}` / `{str(bool(packet.get('inventory_truncated'))).lower()}`",
        f"- Owner role metadata: `{packet.get('owner_role', '') or '未提供（僅 metadata）'}`",
        f"- Reviewer role metadata: `{packet.get('reviewer_role', '') or '未提供（僅 metadata）'}`",
        f"- Formal consumer verified inputs: `{packet.get('formal_ready_input_count', 0)}/{packet.get('formal_input_count', 0)}`",
        f"- Machine verified evidence inputs: `{packet.get('machine_verified_input_count', 0)}/{packet.get('formal_input_count', 0)}`",
        f"- Machine candidate inputs: `{packet.get('machine_candidate_input_count', 0)}/{packet.get('formal_input_count', 0)}`",
        f"- Missing / unknown / invalid inputs: `{packet.get('missing_input_count', 0)}` / `{packet.get('unknown_input_count', 0)}` / `{packet.get('invalid_input_count', 0)}`",
        f"- Evidence required: `{str(bool(packet.get('evidence_required'))).lower()}`",
        "- Formal OOS allowed: `false`",
        "- Candidate only: `true`",
        "- Write performed: `false`",
        "",
        "## Required input review",
        "",
        "| Input | Expected schema | Observed candidates | Packet candidates | Owner decision |",
        "|---|---|---:|---:|---|",
    ]
    for record in packet.get("review_records", []):
        lines.append(
            f"| `{record.get('input', '')}` | `{record.get('expected_schema', '')}` | "
            f"{record.get('candidate_count_observed', 0)} | {record.get('candidate_count_in_packet', 0)} | "
            f"`{record.get('owner_decision', 'pending')}` |"
        )
        lines.extend(
            [
                "",
                f"### {record.get('input', '')}",
                "",
                f"Requirement: {record.get('requirement', '')}",
                f"- Evidence state: `{record.get('evidence_state', 'unknown')}`; formal consumer compatible: `{str(bool(record.get('formal_consumer_compatible'))).lower()}`",
            ]
        )
        machine_verification = record.get("machine_verification")
        if isinstance(machine_verification, Mapping):
            candidate_marker = (
                "candidate-only"
                if machine_verification.get("candidate_only") is True
                else "formal consumer"
            )
            lines.extend(
                [
                    f"- Machine consumer: `{machine_verification.get('status', 'machine_verified')}` ({candidate_marker})",
                    f"- Consumer: `{machine_verification.get('consumer', '')}`",
                    f"- Source: `{machine_verification.get('path', machine_verification.get('receipt_path', machine_verification.get('operational_publication_path', '')))}` — file hash `{machine_verification.get('file_hash', machine_verification.get('receipt_file_hash', machine_verification.get('operational_file_hash', '')))}`",
                    f"- Receipt: `{machine_verification.get('receipt_path', '')}` — "
                    f"`{machine_verification.get('receipt_file_hash', '')}`",
                    f"- Publication: `{machine_verification.get('publication_content_hash', '')}`; "
                    f"rows `{machine_verification.get('row_count', 0)}`; "
                    f"capture `{machine_verification.get('capture_id', '')}`",
                    f"- Source custody / raw rebuild: `{machine_verification.get('source_custody_verified', False)}` / "
                    f"`{machine_verification.get('rows_rebuilt_from_raw', False)}`",
                ]
            )
        candidates = record.get("candidates", [])
        if not candidates:
            lines.append("- No candidate manifest observed for this input.")
        else:
            for candidate in candidates:
                lines.append(
                    f"- `{candidate.get('path', '')}` — `{candidate.get('lane', '')}` — "
                    f"`{candidate.get('reason', '')}` — `{candidate.get('manifest_sha256', '')}`"
                )
        lines.append(
            "- Selected candidate / published formal path / custody id: `not selected by this read-only packet`"
        )
    lines.extend(
        [
            "",
            "## Remaining evidence",
            "",
            "- 狀態由明確來源路徑與正式 consumer 的 loader、PIT、cutoff、hash、chain、custody 驗證決定；owner／reviewer 名字只作 metadata。",
            "- `missing`、`unknown`、`invalid` 會保留具體 evidence blocker；任何名字都不能把它們變成 ready。",
            "- 不得把 research／prospective candidate 改名或複製成正式 input；本 packet 不會自動寫入任何路徑。",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "EXPECTED_INPUTS",
    "FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION",
    "build_formal_input_owner_packet",
    "render_markdown",
    "validate_output_path",
]

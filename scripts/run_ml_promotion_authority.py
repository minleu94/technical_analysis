"""Independent, machine-only authority for a complete ML promotion bundle.

This task never builds model evidence and never decides portfolio weights.  It
only signs an already complete, immutable ``allocation-promotion-v4`` custody
bundle after re-evaluating the deterministic policy.  The signing key is
protected with Windows user-scope DPAPI and is never printed or passed on the
command line.  Missing or incomplete evidence is a successful fail-closed
``skipped`` result, not an authorization.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time as time_module
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
# Windows Defender/indexer/backup scans can transiently hold the status target.
# Keep authority publication fail-closed, but use the same bounded recovery
# window as the Direct/OOC/release chain.
_ATOMIC_REPLACE_RETRY_COUNT = 120
_ATOMIC_REPLACE_RETRY_DELAY_SECONDS = 0.5
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.official_trading_calendar import OfficialTradingCalendar
from ml_module.allocation_validation import (
    AllocationPromotionEvaluator,
    PromotionAuthorizationArtifact,
    file_content_hash,
    load_allocation_promotion_evidence,
)
from runtime.promotion_authority_secret_store import (
    PromotionAuthoritySecretStore,
)


TAIPEI = ZoneInfo("Asia/Taipei")
TASK_NAME = "baldr-ml-promotion-authority-daily"
STATUS_SCHEMA_VERSION = "baldr-ml-promotion-authority-status.v1"
POINTER_SCHEMA_VERSION = "allocation-promotion-evidence-pointer.v1"
AUTHORITY_POINTER_SCHEMA_VERSION = "baldr-promotion-authorization-pointer.v1"
_REQUIRED_CUSTODY_PATH_FIELDS = (
    "model_artifact_path",
    "dataset_manifest_path",
    "oof_bundle_path",
    "shadow_evidence_path",
)


class _Calendar(Protocol):
    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]: ...


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _require_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _require_sha256(value: object, *, label: str) -> str:
    text = _require_text(value, label=label)
    if (
        len(text) != 71
        or not text.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in text[7:])
    ):
        raise ValueError(f"{label} must be a lowercase sha256 value")
    return text


def _parse_aware(value: object, *, label: str) -> datetime:
    text = _require_text(value, label=label)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(TAIPEI)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                    raise
                time_module.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_pointer(path: Path) -> Mapping[str, Any]:
    payload = _require_mapping(
        json.loads(path.read_text(encoding="utf-8")),
        label="promotion evidence pointer",
    )
    if payload.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise ValueError("promotion evidence pointer schema is unsupported")
    if payload.get("authority_required") is not True:
        raise ValueError("promotion evidence pointer must require authority")
    if payload.get("authorization_artifact_created") is not False:
        raise ValueError("evidence builder cannot create authorization")
    pointer_hash = _require_sha256(
        payload.get("pointer_hash"),
        label="pointer_hash",
    )
    body = {
        key: value for key, value in payload.items() if key != "pointer_hash"
    }
    if pointer_hash != _payload_hash(body):
        raise ValueError("promotion evidence pointer hash mismatch")
    return payload


def _trusted_path(value: object, *, release_root: Path, label: str) -> Path:
    path = Path(_require_text(value, label=label)).resolve()
    if not path.is_file():
        raise ValueError(f"{label} is not a file")
    if not path.is_relative_to(release_root):
        raise ValueError(f"{label} is outside the release custody root")
    return path


def _latest_registry_snapshot(
    *,
    registry_database_path: Path,
    output_path: Path,
) -> tuple[str, str]:
    database = registry_database_path.resolve()
    if not database.is_file():
        raise ValueError("engineering gate registry is missing")
    uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        row = connection.execute(
            """
            SELECT payload_json
            FROM engineering_gate_revisions
            WHERE item_id = 'ml:revalidation'
            ORDER BY revision DESC
            LIMIT 1
            """
        ).fetchone()
        total_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM engineering_gate_revisions"
            ).fetchone()[0]
        )
    if row is None:
        raise ValueError("ml:revalidation registry revision is missing")
    item = _require_mapping(
        json.loads(str(row[0])),
        label="ml:revalidation registry payload",
    )
    revision = item.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("registry revision must be a positive integer")
    registry_revision_id = f"ml:revalidation@{revision}"
    snapshot_body: dict[str, object] = {
        "schema_version": "baldr-promotion-registry-snapshot.v1",
        "registry_revision_id": registry_revision_id,
        "source_database_hash": file_content_hash(database),
        "source_row_count": total_rows,
        "item": dict(item),
    }
    snapshot = {
        **snapshot_body,
        "snapshot_hash": _payload_hash(snapshot_body),
    }
    _atomic_write_json(output_path, snapshot)
    return registry_revision_id, file_content_hash(output_path)


def _authorized_decision_at(
    *,
    pointer: Mapping[str, Any],
    now: datetime,
    calendar: _Calendar,
) -> tuple[datetime, str]:
    raw_decision = pointer.get("decision_at")
    if raw_decision is not None:
        candidate = _parse_aware(raw_decision, label="pointer.decision_at")
        if candidate.timetz().replace(tzinfo=None) != time(8, 30):
            raise ValueError("pointer decision_at must be Asia/Taipei 08:30")
        if candidate > now:
            is_open, reason = calendar.is_official_trading_day(
                candidate.date()
            )
            if is_open is True:
                return candidate, reason
            if is_open is None:
                raise ValueError("official trading calendar is unavailable")

    start = now.date()
    for offset in range(0, 15):
        candidate_date = start + timedelta(days=offset)
        candidate = datetime.combine(
            candidate_date,
            time(8, 30),
            tzinfo=TAIPEI,
        )
        if candidate <= now:
            continue
        is_open, reason = calendar.is_official_trading_day(candidate_date)
        if is_open is None:
            raise ValueError("official trading calendar is unavailable")
        if is_open:
            return candidate, reason
    raise ValueError("next official trading decision cannot be resolved")


def _status(
    *,
    status: str,
    now: datetime,
    blockers: tuple[str, ...],
    secret_descriptor: Mapping[str, str],
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "task": TASK_NAME,
        "status": status,
        "generated_at": now.isoformat(timespec="seconds"),
        "blockers": list(blockers),
        "authority": dict(secret_descriptor),
        "authorization_created": status == "authorized",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        **dict(extra or {}),
    }
    return {**body, "status_hash": _payload_hash(body)}


def run(
    *,
    output_root: Path,
    evidence_pointer_path: Path,
    registry_database_path: Path,
    now: datetime | None = None,
    calendar: _Calendar | None = None,
) -> dict[str, object]:
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    release_root = (output_root / "release_v4").resolve()
    authority_root = release_root / "ml_promotion_authority"
    secret_store = PromotionAuthoritySecretStore(
        authority_root / "authority_secret.dpapi.json"
    )
    secret = secret_store.load_or_create()
    descriptor = secret.public_descriptor()
    status_path = authority_root / "latest_status.json"

    if not evidence_pointer_path.is_file():
        result = _status(
            status="skipped_evidence_unavailable",
            now=local_now,
            blockers=("compatible_promotion_evidence_pointer_missing",),
            secret_descriptor=descriptor,
        )
        _atomic_write_json(status_path, result)
        return result

    try:
        pointer = _load_pointer(evidence_pointer_path)
        evidence_path = _trusted_path(
            pointer.get("promotion_evidence_path"),
            release_root=release_root,
            label="promotion_evidence_path",
        )
        custody_paths = {
            field_name: _trusted_path(
                pointer.get(field_name),
                release_root=release_root,
                label=field_name,
            )
            for field_name in _REQUIRED_CUSTODY_PATH_FIELDS
        }
        evidence_file_hash = _require_sha256(
            pointer.get("evidence_file_hash"),
            label="evidence_file_hash",
        )
        if file_content_hash(evidence_path) != evidence_file_hash:
            raise ValueError("promotion evidence physical hash mismatch")
        evidence = load_allocation_promotion_evidence(evidence_path)
        if pointer.get("evidence_hash") != evidence.evidence_hash:
            raise ValueError("promotion evidence logical hash mismatch")
        if (
            file_content_hash(custody_paths["model_artifact_path"])
            != evidence.model_artifact_hash
        ):
            raise ValueError("model artifact custody hash mismatch")
        if (
            file_content_hash(custody_paths["dataset_manifest_path"])
            != evidence.dataset_manifest_file_hash
        ):
            raise ValueError("dataset manifest custody hash mismatch")
        if (
            file_content_hash(custody_paths["oof_bundle_path"])
            != evidence.oof_bundle_hash
        ):
            raise ValueError("OOF bundle custody hash mismatch")
        if (
            file_content_hash(custody_paths["shadow_evidence_path"])
            != evidence.shadow_evidence_hash
        ):
            raise ValueError("shadow evidence custody hash mismatch")

        evaluator = AllocationPromotionEvaluator()
        evaluation = evaluator.evaluate(evidence)
        expected_blockers = ("promotion_authorization_artifact_required",)
        if (
            evaluation.eligible_alpha_bp == 0
            or evaluation.blockers != expected_blockers
        ):
            result = _status(
                status="skipped_machine_evidence_insufficient",
                now=local_now,
                blockers=tuple(evaluation.blockers),
                secret_descriptor=descriptor,
                extra={
                    "eligible_alpha_bp": evaluation.eligible_alpha_bp,
                    "evidence_hash": evidence.evidence_hash,
                },
            )
            _atomic_write_json(status_path, result)
            return result

        decision_at, calendar_reason = _authorized_decision_at(
            pointer=pointer,
            now=local_now,
            calendar=calendar or OfficialTradingCalendar(),
        )
        frozen_at = _parse_aware(
            pointer.get("generated_at"),
            label="pointer.generated_at",
        )
        if frozen_at > local_now:
            raise ValueError("promotion evidence freeze is in the future")
        publication_id = _require_text(
            pointer.get("publication_id"),
            label="publication_id",
        )
        run_identity = hashlib.sha256(
            _canonical_json(
                {
                    "evidence_hash": evidence.evidence_hash,
                    "decision_at": decision_at.isoformat(),
                    "publication_id": publication_id,
                    "key_fingerprint": secret.key_fingerprint,
                    "issued_at": local_now.isoformat(timespec="seconds"),
                }
            ).encode("utf-8")
        ).hexdigest()[:24]
        run_directory = authority_root / "runs" / f"authority-{run_identity}"
        registry_path = run_directory / "registry_revision.json"
        registry_revision_id, registry_revision_hash = (
            _latest_registry_snapshot(
                registry_database_path=registry_database_path,
                output_path=registry_path,
            )
        )
        artifact_id = f"promotion-auth:{run_identity}"
        authorization = PromotionAuthorizationArtifact.create(
            artifact_id=artifact_id,
            registry_revision_id=registry_revision_id,
            registry_revision_hash=registry_revision_hash,
            custody_id=secret.custody_id,
            issuer_id=secret.issuer_id,
            issued_at=local_now.isoformat(timespec="seconds"),
            decision_valid_from=(
                decision_at - timedelta(minutes=30)
            ).isoformat(timespec="seconds"),
            decision_valid_until=(
                decision_at + timedelta(minutes=30)
            ).isoformat(timespec="seconds"),
            freeze_id=publication_id,
            frozen_at=frozen_at.isoformat(timespec="seconds"),
            model_id=evidence.model_id,
            dataset_id=evidence.dataset_id,
            authorized_evidence_hash=evidence.evidence_hash,
            evidence_artifact_hash=evidence_file_hash,
            authorized_policy_hash=evaluator.policy_hash,
            authorized_alpha_bp=evaluation.eligible_alpha_bp,
            model_artifact_hash=evidence.model_artifact_hash,
            dataset_identity_hash=evidence.dataset_identity_hash,
            dataset_manifest_file_hash=evidence.dataset_manifest_file_hash,
            oof_bundle_hash=evidence.oof_bundle_hash,
            shadow_evidence_hash=evidence.shadow_evidence_hash,
            signing_key=secret.signing_key,
        )
        authorization_path = run_directory / "authorization.json"
        _atomic_write_json(authorization_path, authorization.to_dict())
        pointer_body: dict[str, object] = {
            "schema_version": AUTHORITY_POINTER_SCHEMA_VERSION,
            "artifact_id": authorization.artifact_id,
            "authorization_path": str(authorization_path.resolve()),
            "authorization_artifact_hash": authorization.artifact_hash,
            "authorization_file_hash": file_content_hash(authorization_path),
            "evidence_path": str(evidence_path),
            "registry_revision_path": str(registry_path.resolve()),
            "model_artifact_path": str(
                custody_paths["model_artifact_path"]
            ),
            "dataset_manifest_path": str(
                custody_paths["dataset_manifest_path"]
            ),
            "oof_bundle_path": str(custody_paths["oof_bundle_path"]),
            "shadow_evidence_path": str(
                custody_paths["shadow_evidence_path"]
            ),
            "issuer_id": secret.issuer_id,
            "custody_id": secret.custody_id,
            "custody_root": str(release_root),
            "decision_at": decision_at.isoformat(timespec="seconds"),
            "decision_valid_from": authorization.decision_valid_from,
            "decision_valid_until": authorization.decision_valid_until,
            "eligible_alpha_bp": evaluation.eligible_alpha_bp,
            "evidence_hash": evidence.evidence_hash,
            "publication_id": publication_id,
            "calendar_reason": calendar_reason,
        }
        authority_pointer = {
            **pointer_body,
            "pointer_hash": _payload_hash(pointer_body),
        }
        authority_pointer_path = run_directory / "authorization_pointer.json"
        _atomic_write_json(authority_pointer_path, authority_pointer)
        _atomic_write_json(
            authority_root / "latest_authorization_pointer.json",
            authority_pointer,
        )
        result = _status(
            status="authorized",
            now=local_now,
            blockers=(),
            secret_descriptor=descriptor,
            extra={
                "artifact_id": authorization.artifact_id,
                "authorization_artifact_hash": authorization.artifact_hash,
                "authorization_file_hash": file_content_hash(
                    authorization_path
                ),
                "authorization_pointer_path": str(
                    authority_pointer_path.resolve()
                ),
                "authorization_pointer_hash": authority_pointer[
                    "pointer_hash"
                ],
                "authorized_alpha_bp": evaluation.eligible_alpha_bp,
                "authorized_decision_at": decision_at.isoformat(
                    timespec="seconds"
                ),
                "evidence_hash": evidence.evidence_hash,
                "registry_revision_id": registry_revision_id,
                "calendar_reason": calendar_reason,
            },
        )
        _atomic_write_json(status_path, result)
        return result
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        sqlite3.Error,
    ) as exc:
        result = _status(
            status="skipped_invalid_or_incomplete_custody",
            now=local_now,
            blockers=(
                f"promotion_authority_custody_invalid:{type(exc).__name__}",
            ),
            secret_descriptor=descriptor,
            extra={"validation_error": str(exc)},
        )
        _atomic_write_json(status_path, result)
        return result


def build_parser() -> argparse.ArgumentParser:
    data_root = Path(
        os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")
    )
    output_root = Path(
        os.environ.get("OUTPUT_ROOT", str(data_root / "output"))
    )
    parser = argparse.ArgumentParser(
        description=(
            "獨立驗證完整 allocation-promotion-v4 custody，並以 DPAPI "
            "保護的 authority key 為下一個官方交易決策日簽章。"
        )
    )
    parser.add_argument("--output-root", type=Path, default=output_root)
    parser.add_argument(
        "--evidence-pointer",
        type=Path,
        default=(
            output_root
            / "release_v4"
            / "ml_allocation_promotion_evidence"
            / "latest_pointer.json"
        ),
    )
    parser.add_argument(
        "--registry-db",
        type=Path,
        default=(
            output_root
            / "release_v4"
            / "engineering_gate_registry.sqlite"
        ),
    )
    return parser


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = build_parser().parse_args(argv)
    try:
        result = run(
            output_root=args.output_root,
            evidence_pointer_path=args.evidence_pointer,
            registry_database_path=args.registry_db,
        )
    except Exception as exc:  # noqa: BLE001 - status may be unavailable
        print(
            json.dumps(
                {
                    "task": TASK_NAME,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if str(result["status"]).startswith(("authorized", "skipped_")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

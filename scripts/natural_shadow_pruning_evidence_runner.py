"""Publish read-only natural shadow maturity evidence at the daily run boundary.

The ML shadow collector owns the SQLite sidecar.  This module only consumes
that sidecar after a daily orchestration status is about to be published.  It
does not prune, promote, alter the sidecar, or grant a shadow day.  Each
projection is keyed by its evidence hash, so a later collector revision is
published beside the earlier immutable projection instead of replacing it.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from ml_module.natural_shadow_pruning_evidence import (
    NaturalShadowPruningEvidenceError,
    build_natural_shadow_pruning_evidence,
    write_natural_shadow_pruning_evidence,
)


SCHEMA_VERSION = "natural-shadow-pruning-scheduled-status.v1"
_SHA256_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_PENDING_EVIDENCE_STATUSES = frozenset(
    {"pending_maturity", "pending_pruning_metrics"}
)


class NaturalShadowPruningScheduleError(ValueError):
    """The scheduled evidence projection cannot be published safely."""


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


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _parse_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise NaturalShadowPruningScheduleError(
            "as_of_date must be a YYYY-MM-DD date"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise NaturalShadowPruningScheduleError(
            "as_of_date must be a YYYY-MM-DD date"
        ) from error


def _required_hash(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NaturalShadowPruningScheduleError(
            f"{field_name} must be sha256:<64 hex>"
        )
    return value.lower()


def _digest_suffix(value: str) -> str:
    return _required_hash(value, "evidence_hash").split(":", 1)[1]


def _short_digest(value: str) -> str:
    """Keep Windows publication paths bounded; full hash stays in the body."""

    return _digest_suffix(value)[:16]


def _create_only_bytes(path: Path, encoded: bytes) -> str:
    """Create an immutable file, allowing only an exact replay."""

    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() == encoded:
            return "idempotent"
        raise NaturalShadowPruningScheduleError(
            f"immutable evidence status conflict: {output}"
        )
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".nse-",
        suffix=".tmp",
        dir=str(output.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError:
            try:
                if output.read_bytes() == encoded:
                    return "idempotent"
            except OSError:
                pass
            raise NaturalShadowPruningScheduleError(
                f"immutable evidence status conflict: {output}"
            )
    finally:
        if temporary.exists():
            temporary.unlink()
    return "inserted"


def _write_status(path: Path, payload: Mapping[str, object]) -> tuple[str, str]:
    body = dict(payload)
    body.pop("status_hash", None)
    status_hash = _payload_hash(body)
    encoded = (_canonical_json({**body, "status_hash": status_hash}) + "\n").encode(
        "utf-8"
    )
    write_result = _create_only_bytes(
        path.with_name(f"status_{_short_digest(status_hash)}.json"),
        encoded,
    )
    return status_hash, write_result


def _validate_pruning_boundary(evidence: Mapping[str, object]) -> Mapping[str, object]:
    raw_boundary = evidence.get("pruning_boundary")
    if not isinstance(raw_boundary, Mapping):
        raise NaturalShadowPruningScheduleError(
            "natural shadow evidence pruning boundary is missing"
        )
    required = {
        "evidence_only": True,
        "apply_action": False,
        "review_required": True,
        "promotion_eligible": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
    }
    for key, expected in required.items():
        if raw_boundary.get(key) is not expected:
            raise NaturalShadowPruningScheduleError(
                f"natural shadow evidence boundary is unsafe: {key}"
            )
    return dict(raw_boundary)


def _status_body(
    *,
    cutoff: date,
    sidecar: Path,
    source_exists: bool,
    source_hash: str | None,
    evidence: Mapping[str, object] | None,
    evidence_path: Path | None,
    evidence_file_hash: str | None,
    weekly_evidence_path: Path | None,
    weekly_evidence_file_hash: str | None,
    status: str,
    evidence_status: str | None,
    integrity_state: str,
    error: str | None = None,
) -> dict[str, object]:
    evidence_hash = (
        _required_hash(evidence.get("evidence_hash"), "evidence.evidence_hash")
        if evidence is not None
        else None
    )
    boundary = (
        _validate_pruning_boundary(evidence)
        if evidence is not None
        else {
            "evidence_only": True,
            "apply_action": False,
            "review_required": True,
            "promotion_eligible": False,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
        }
    )
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "evidence_status": evidence_status,
        "as_of_date": cutoff.isoformat(),
        "source": {
            "sidecar_database_path": str(sidecar),
            "sidecar_file_hash": source_hash,
            "exists": source_exists,
            "read_only": True,
            "query_only": True,
        },
        "evidence_hash": evidence_hash,
        "evidence_path": (
            str(evidence_path) if evidence_path is not None else None
        ),
        "evidence_file_hash": evidence_file_hash,
        "weekly_evidence_path": (
            str(weekly_evidence_path)
            if weekly_evidence_path is not None
            else None
        ),
        "weekly_evidence_file_hash": weekly_evidence_file_hash,
        "integrity_state": integrity_state,
        "pending_is_normal_wait": status == "pending",
        "pruning_boundary": boundary,
        "pruning_action_performed": False,
        "promotion_action_performed": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "writes_source_database": False,
        "changes_portfolio_state": False,
        "exit_code": 0 if status in {"pending", "ready_for_review"} else 2,
    }
    if error is not None:
        body["error_type"] = "NaturalShadowPruningEvidenceError"
        body["error"] = error
    return body


def _write_daily_and_weekly_status(
    *,
    evidence_root: Path,
    cutoff: date,
    body: Mapping[str, object],
) -> dict[str, object]:
    iso = cutoff.isocalendar()
    week_key = f"{iso.year}-W{iso.week:02d}"
    daily_status_base = (
        evidence_root / "daily" / cutoff.isoformat() / "status.json"
    )
    weekly_status_base = evidence_root / "weekly" / week_key / (
        f"asof_{cutoff.isoformat()}_status.json"
    )
    status_hash, daily_write = _write_status(daily_status_base, body)
    _, weekly_write = _write_status(weekly_status_base, body)
    daily_status_path = daily_status_base.with_name(
        f"status_{_short_digest(status_hash)}.json"
    ).resolve()
    weekly_status_path = weekly_status_base.with_name(
        f"status_{_short_digest(status_hash)}.json"
    ).resolve()
    return {
        **dict(body),
        "status_hash": status_hash,
        "daily_status_path": str(daily_status_path),
        "weekly_status_path": str(weekly_status_path),
        "daily_status_write": daily_write,
        "weekly_status_write": weekly_write,
        "weekly_key": week_key,
    }


def run_natural_shadow_pruning_evidence(
    *,
    sidecar_database_path: Path,
    output_root: Path,
    as_of_date: date | str,
    expected_model_hash: str | None = None,
    expected_dataset_identity_hash: str | None = None,
    expected_policy_hash: str | None = None,
) -> dict[str, object]:
    """Project the exact sidecar at a daily orchestration boundary.

    ``output_root`` is the existing orchestration run root.  No latest-file
    discovery is performed: the sidecar is exactly
    ``output_root/shadow_evidence_collector/shadow_evidence.sqlite`` for a
    scheduled caller.  A missing sidecar means the collector has not supplied
    a source yet and therefore returns a normal pending status.  A malformed
    or changing sidecar is an integrity failure and returns exit code 2.
    """

    cutoff = _parse_date(as_of_date)
    run_root = output_root.expanduser().resolve()
    sidecar = sidecar_database_path.expanduser().resolve()
    evidence_root = run_root / "natural_shadow_pruning_evidence"
    if not sidecar.is_file():
        body = _status_body(
            cutoff=cutoff,
            sidecar=sidecar,
            source_exists=False,
            source_hash=None,
            evidence=None,
            evidence_path=None,
            evidence_file_hash=None,
            weekly_evidence_path=None,
            weekly_evidence_file_hash=None,
            status="pending",
            evidence_status=None,
            integrity_state="awaiting_source",
        )
        return _write_daily_and_weekly_status(
            evidence_root=evidence_root,
            cutoff=cutoff,
            body=body,
        )

    try:
        evidence = build_natural_shadow_pruning_evidence(
            sidecar,
            as_of_date=cutoff,
            expected_model_hash=expected_model_hash,
            expected_dataset_identity_hash=expected_dataset_identity_hash,
            expected_policy_hash=expected_policy_hash,
        )
        evidence_status = evidence.get("status")
        if evidence_status not in _PENDING_EVIDENCE_STATUSES | {
            "ready_for_pruning_review"
        }:
            raise NaturalShadowPruningScheduleError(
                "natural shadow evidence status is unsupported"
            )
        boundary = _validate_pruning_boundary(evidence)
        del boundary
        evidence_hash = _required_hash(
            evidence.get("evidence_hash"),
            "evidence.evidence_hash",
        )
        suffix = _digest_suffix(evidence_hash)
        daily_evidence_path = (
            evidence_root
            / "daily"
            / cutoff.isoformat()
            / f"evidence_{suffix[:16]}.json"
        )
        iso = cutoff.isocalendar()
        week_key = f"{iso.year}-W{iso.week:02d}"
        weekly_evidence_path = (
            evidence_root
            / "weekly"
            / week_key
            / f"asof_{cutoff.isoformat()}_evidence_{suffix[:16]}.json"
        )
        daily_evidence_path.parent.mkdir(parents=True, exist_ok=True)
        weekly_evidence_path.parent.mkdir(parents=True, exist_ok=True)
        daily_write = write_natural_shadow_pruning_evidence(
            daily_evidence_path,
            evidence,
        )
        weekly_write = write_natural_shadow_pruning_evidence(
            weekly_evidence_path,
            evidence,
        )
        source_payload = evidence.get("source")
        if not isinstance(source_payload, Mapping):
            raise NaturalShadowPruningScheduleError(
                "natural shadow evidence source metadata is missing"
            )
        source_hash = _required_hash(
            source_payload.get("sidecar_file_hash"),
            "evidence.source.sidecar_file_hash",
        )
        if source_payload.get("sidecar_database_path") != str(sidecar):
            raise NaturalShadowPruningScheduleError(
                "natural shadow evidence source path differs from requested sidecar"
            )
        body = _status_body(
            cutoff=cutoff,
            sidecar=sidecar,
            source_exists=True,
            source_hash=source_hash,
            evidence=evidence,
            evidence_path=daily_evidence_path,
            evidence_file_hash=_file_hash(daily_evidence_path),
            weekly_evidence_path=weekly_evidence_path,
            weekly_evidence_file_hash=_file_hash(weekly_evidence_path),
            status=(
                "pending"
                if evidence_status in _PENDING_EVIDENCE_STATUSES
                else "ready_for_review"
            ),
            evidence_status=str(evidence_status),
            integrity_state="verified",
        )
        result = _write_daily_and_weekly_status(
            evidence_root=evidence_root,
            cutoff=cutoff,
            body=body,
        )
        result["daily_evidence_write"] = daily_write
        result["weekly_evidence_write"] = weekly_write
        return result
    except (
        NaturalShadowPruningEvidenceError,
        NaturalShadowPruningScheduleError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
    ) as error:
        body = _status_body(
            cutoff=cutoff,
            sidecar=sidecar,
            source_exists=True,
            source_hash=None,
            evidence=None,
            evidence_path=None,
            evidence_file_hash=None,
            weekly_evidence_path=None,
            weekly_evidence_file_hash=None,
            status="blocked_integrity",
            evidence_status=None,
            integrity_state="failed",
            error=str(error),
        )
        return _write_daily_and_weekly_status(
            evidence_root=evidence_root,
            cutoff=cutoff,
            body=body,
        )


__all__ = [
    "SCHEMA_VERSION",
    "NaturalShadowPruningScheduleError",
    "run_natural_shadow_pruning_evidence",
]

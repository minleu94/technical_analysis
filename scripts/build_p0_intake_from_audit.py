"""將既有 P0 machine audit 轉成 owner 可補完的 candidate intake。

這個工具只做資料形狀轉接：把 ``p0-source-evidence-audit.v1`` 中已觀察到的
row counts、payload hash 與 machine status 放入 ``p0-source-intake.v1`` 的
13 列 dossier，並刻意把 source owner、license、publication、available-date、
PIT 與 revision 等需要人或外部權威確認的欄位保留為 ``unverified``／
``requires_review``。它不會建立 decision registry、不會改寫正式資料、也不會
把 candidate 轉成 accepted／limited。

輸出限制在 OS TEMP（或其子目錄），以免把候選 intake 誤寫回 DATA_ROOT。
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from scripts.inspect_p0_intake_readiness import P0_INTAKE_SCHEMA_VERSION
from scripts.run_p0_source_evidence_audit import validate_approved_output_path


AUDIT_SCHEMA_VERSION = "p0-source-evidence-audit.v1"
DOSSIER_SCHEMA_VERSION = "source-acceptance-dossier.v1"
_PRODUCTION_DEFAULT = "D:/Min/Python/Project/FA_Data"

_SAFETY_FLAGS = {
    "read_only": True,
    "writes_allowed": False,
    "formal_oos_allowed": False,
    "production_scheduler_allowed": False,
    "downstream_eligibility": "none",
    "auto_accept_allowed": False,
}

# Machine evidence is deliberately kept at the intake envelope level rather
# than added to ``source-acceptance-dossier.v1``.  The dossier schema is the
# owner-governed decision contract; widening it with probe details would make
# an evidence transport change look like an authority decision.  This allowlist
# also prevents arbitrary probe fields (including a future secret-like field)
# from leaking into the candidate handoff.
_MACHINE_EVIDENCE_FIELDS = (
    "source_id",
    "family",
    "provider",
    "endpoint_or_artifact_type",
    "acquisition_mode",
    "machine_status",
    "pit_status",
    "timestamp_kind",
    "availability",
    "schema_status",
    "probe_outcome",
    "payload_sha256",
    "raw_row_count",
    "accepted_row_count",
    "quarantine_row_count",
    "blocked_row_count",
    "remaining_blocker",
    "endpoint_id",
    "acquisition_route_id",
    "fallback_used",
    "fallback_from_endpoint_id",
    "fallback_from_acquisition_route_id",
    "fallback_attempted",
    "fallback_endpoint_id",
    "fallback_acquisition_route_id",
    "fallback_probe_outcome",
    "fallback_official_status",
    "fallback_http_status",
    "fallback_payload_sha256",
    "fallback_payload_size_bytes",
    "fallback_observation_dates",
    "fallback_requested_date",
    "fallback_quarantine_reasons",
    "fallback_error_type",
    "fallback_error",
    "primary_official_status",
    "timestamp_semantics",
    "acquisition_routes",
)

_SECRET_KEYS = frozenset(
    {"api_key", "authorization", "cookie", "credential", "password", "secret", "token"}
)


def build_candidate_intake(audit: Mapping[str, Any]) -> dict[str, Any]:
    """從 machine audit 建立完整 13 列、仍 fail-closed 的 intake payload。"""

    _validate_audit(audit)
    rows_by_id = {
        str(row["source_id"]): row
        for row in audit["machine_evidence_matrix"]
        if isinstance(row, Mapping)
    }
    audit_hash = _payload_hash(audit)
    decision_date = str(audit.get("decision_date") or "unknown")
    dossiers = [
        _build_dossier(
            source_id,
            rows_by_id[source_id],
            audit_hash=audit_hash,
            decision_date=decision_date,
        )
        for source_id in P0_SOURCE_IDS
    ]
    return {
        "schema_version": P0_INTAKE_SCHEMA_VERSION,
        "safety_flags": dict(_SAFETY_FLAGS),
        "provenance": {
            "builder": "build_p0_intake_from_audit.py",
            "source_audit_schema_version": AUDIT_SCHEMA_VERSION,
            "source_audit_payload_sha256": audit_hash,
            "decision_date": decision_date,
            "machine_evidence_only": True,
            "owner_attestation_required": True,
        },
        # Keep the machine-side route/fallback evidence available to the owner
        # without changing the governed dossier contract.  Every row is
        # allowlisted and recursively redacted before it leaves this builder.
        "machine_evidence_by_source": {
            source_id: _project_machine_evidence(rows_by_id[source_id])
            for source_id in P0_SOURCE_IDS
        },
        "dossiers": dossiers,
    }


def _project_machine_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project only safe, observed probe fields for owner handoff."""

    projected: dict[str, Any] = {}
    for field_name in _MACHINE_EVIDENCE_FIELDS:
        if field_name not in row:
            continue
        # Audit payloads are already redacted, but perform a second boundary
        # pass here because this function is also a public Python entry point.
        projected[field_name] = redact_secrets(row[field_name])
    return projected


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-like keys in machine evidence containers."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SECRET_KEYS else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


def _build_dossier(
    source_id: str,
    row: Mapping[str, Any],
    *,
    audit_hash: str,
    decision_date: str,
) -> dict[str, Any]:
    raw_count = _non_negative_int(row.get("raw_row_count"))
    accepted_count = _non_negative_int(row.get("accepted_row_count"))
    quarantine_count = _non_negative_int(row.get("quarantine_row_count"))
    blocked_count = _non_negative_int(row.get("blocked_row_count"))
    if accepted_count > raw_count:
        # Do not manufacture a valid denominator from malformed audit input.
        coverage_numerator = 0
        coverage_denominator = 0
    else:
        coverage_numerator = accepted_count
        coverage_denominator = raw_count

    payload_hash = str(row.get("payload_sha256") or "").strip()
    evidence_ids = [f"quality:p0-audit:{audit_hash}:{source_id}"]
    if payload_hash:
        evidence_ids.append(f"quality:payload:{payload_hash}")
    if str(row.get("pit_status") or "unavailable") not in {
        "unavailable",
        "missing",
    }:
        evidence_ids.append(f"pit:p0-audit:{audit_hash}:{source_id}")

    source_status = str(row.get("machine_status") or "missing").strip() or "missing"
    availability = str(row.get("availability") or "unknown").strip() or "unknown"
    timestamp_kind = str(row.get("timestamp_kind") or "unavailable").strip() or "unavailable"
    row_counts: dict[str, int] = {}
    for key, field_name in (
        ("raw", "raw_row_count"),
        ("accepted", "accepted_row_count"),
        ("quarantine", "quarantine_row_count"),
        ("blocked", "blocked_row_count"),
    ):
        if field_name in row:
            row_counts[key] = _non_negative_int(row.get(field_name))

    return {
        "schema_version": DOSSIER_SCHEMA_VERSION,
        "source_id": source_id,
        "source_owner_role": "",
        "license_owner_role": "",
        "license_status": "requires_review",
        "license_scope": "research_only",
        "redistribution_policy": "unverified",
        "source_status": f"candidate_{source_status}",
        "publication_time_policy": (
            f"unverified: audit timestamp_kind={timestamp_kind}; "
            "official publication provenance requires owner review"
        ),
        "timezone": "Asia/Taipei",
        "available_date_policy": (
            f"unverified: audit availability={availability}, decision_date={decision_date}; "
            "decision-time availability requires owner review"
        ),
        "revision_policy": "unverified: append-only revision and correction policy requires owner review",
        "pit_coverage_window": (
            f"unverified: bounded audit observed decision_date={decision_date}; "
            "historical PIT window requires owner review"
        ),
        "coverage_numerator": coverage_numerator,
        "coverage_denominator": coverage_denominator,
        "missing_policy": "fail_closed",
        # A missing audit field stays missing; do not turn an absent PIT
        # artifact into a fabricated 0/0 conservation observation.
        "row_conservation_counts": row_counts,
        "quarantine_policy": "unverified: audit counts are observed only; quarantine contract requires owner review",
        "quality_thresholds": {
            "minimum_coverage_bp": 9500,
            "coverage_basis": "accepted_rows_over_raw_rows_from_machine_audit",
            "machine_evidence_only": True,
        },
        "downstream_use_cases": ["research_backtest"],
        "downstream_eligibility": "none",
        "disable_conditions": ["owner_rejection", "license_revoked", "source_outage", "pit_leakage"],
        "rollback_reference": "decision:initial-candidate",
        "evidence_artifact_ids": evidence_ids,
        "reviewer_role": "",
        "decision_timestamp": "",
        "decision_revision_id": "",
    }


def _validate_audit(audit: Mapping[str, Any]) -> None:
    if audit.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported P0 audit schema: {audit.get('schema_version')}"
        )
    matrix = audit.get("machine_evidence_matrix")
    if not isinstance(matrix, list) or len(matrix) != len(P0_SOURCE_IDS):
        raise ValueError("P0 audit machine_evidence_matrix must contain exactly 13 rows")
    source_ids: list[str] = []
    for row in matrix:
        if not isinstance(row, Mapping):
            raise ValueError("P0 audit matrix row must be an object")
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or source_id not in P0_SOURCE_IDS:
            raise ValueError(f"P0 audit row has invalid source_id: {source_id}")
        source_ids.append(source_id)
    if source_ids != list(P0_SOURCE_IDS):
        raise ValueError("P0 audit source denominator/order must remain authoritative 13 rows")
    safety = audit.get("safety_flags")
    if not isinstance(safety, Mapping):
        raise ValueError("P0 audit safety_flags are required")
    for key in (
        "formal_oos_allowed",
        "formal_evidence_credit_authorized",
        "production_allowed",
        "training_allowed",
        "promotion_allowed",
        "scheduler_allowed",
        "unblind_allowed",
    ):
        if safety.get(key) is not False:
            raise ValueError(f"P0 audit safety boundary must remain false: {key}")
    if safety.get("production_blend_alpha_bp") != 0:
        raise ValueError("P0 audit production_blend_alpha_bp must remain zero")
    if safety.get("downstream_eligibility") != "none":
        raise ValueError("P0 audit downstream_eligibility must remain none")


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def _require_candidate_output(path: Path) -> None:
    if not validate_approved_output_path(path):
        raise ValueError("output must remain inside OS TEMP")
    production_root = Path(os.environ.get("DATA_ROOT", _PRODUCTION_DEFAULT)).resolve()
    try:
        path.resolve().relative_to(production_root)
    except ValueError:
        return
    raise ValueError("output must remain outside DATA_ROOT")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True, type=Path, help="既有 p0-source-evidence-audit.v1 JSON")
    parser.add_argument("--output", required=True, type=Path, help="OS TEMP 下的 candidate intake JSON")
    args = parser.parse_args(argv)

    try:
        _require_candidate_output(args.output)
        raw = json.loads(args.audit.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("P0 audit JSON root must be an object")
        payload = build_candidate_intake(raw)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"P0 candidate intake written: {args.output}")
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"P0 candidate intake blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from app_module.evidence_pipeline_runner_dtos import (
    READINESS_DRY_RUN_ONLY,
    READINESS_NOT_READY,
    READINESS_READY_FOR_DESIGN,
    READINESS_READY_FOR_MANUAL_CONFIRM,
)
from app_module.evidence_source_coverage_service import EvidenceSourceCoverageService
from app_module.forward_performance_dashboard_service import ForwardPerformanceDashboardService
from data_module.config import TWStockConfig


READINESS_VALUES = {
    READINESS_NOT_READY,
    READINESS_DRY_RUN_ONLY,
    READINESS_READY_FOR_DESIGN,
    READINESS_READY_FOR_MANUAL_CONFIRM,
}
READINESS_OPERATIONAL_PRODUCTION = "operational_production"
APPROVAL_SCHEMA_VERSION = "evidence-production-scheduler-approval.v1"
_REQUIRED_APPROVAL_CHECKS = (
    "source_coverage_ready",
    "dry_run_passed",
    "working_copy_smoke_passed",
    "diagnostics_reviewed",
    "backup_verified",
    "rollback_verified",
    "recovery_verified",
)


def evaluate_evidence_scheduler_readiness(
    config: TWStockConfig,
    *,
    db_path: str | Path,
    smoke_report_path: str | Path | None = None,
    decision_date: str | None = None,
    result_id: str | None = None,
    approval_artifact_path: str | Path | None = None,
) -> dict[str, Any]:
    config.db_file = Path(db_path)
    source_coverage = EvidenceSourceCoverageService(config, db_path=db_path).inspect(
        decision_date=decision_date,
        result_id=result_id,
    ).to_dict()
    smoke = _load_smoke_report(smoke_report_path)
    blocking_gaps = list(source_coverage["blocking_gaps"])
    smoke_passed = _smoke_passed(smoke)
    latest_smoke_status = "passed" if smoke_passed else ("not_provided" if smoke is None else "failed")
    if not smoke_passed:
        # V4 的正式 wrapper 本身具有 idempotency／timeout／交易日 fail-closed；
        # 舊 working-copy smoke 只保留為補充診斷，不再是人工 scheduler gate。
        smoke_diagnostic = (
            "legacy_working_copy_smoke_not_provided_non_blocking"
            if smoke is None
            else "legacy_working_copy_smoke_failed_non_blocking"
        )
    else:
        smoke_diagnostic = None
    dashboard_available = _dashboard_available()
    if not dashboard_available:
        blocking_gaps.append("forward_dashboard_service_unavailable")

    approval = _load_approval_artifact(approval_artifact_path)
    approval_diagnostic = _approval_diagnostic(approval_artifact_path, approval)
    if approval_diagnostic is not None:
        blocking_gaps.append(approval_diagnostic)

    readiness = source_coverage["scheduler_readiness"]
    production_scheduler_allowed = not blocking_gaps and approval is not None
    if production_scheduler_allowed:
        readiness = READINESS_OPERATIONAL_PRODUCTION
    elif readiness not in READINESS_VALUES:
        readiness = READINESS_NOT_READY

    warnings = list(source_coverage["warnings"])
    if smoke_diagnostic is not None:
        warnings.append(smoke_diagnostic)
    required_manual_checks = []
    if approval_diagnostic is not None:
        required_manual_checks.append(
            "建立並由具名 owner 簽署 evidence-production-scheduler-approval.v1；未通過前不得啟用 production scheduler。"
        )
    return {
        "readiness": readiness,
        "blocking_gaps": sorted(set(blocking_gaps)),
        "warnings": sorted(set(warnings)),
        "required_manual_checks": required_manual_checks,
        "automated_gate_policy": [
            "official_trading_calendar_fail_closed",
            "source_coverage_revalidated_each_run",
            "idempotent_evidence_capture",
            "subprocess_timeout_persisted_as_degraded",
            "insufficient_history_does_not_block_rule_operations",
            "explicit_scheduler_approval_artifact_required",
        ],
        "latest_smoke_status": latest_smoke_status,
        "source_coverage_status": source_coverage,
        "approval_artifact": approval,
        "dashboard_available": dashboard_available,
        "working_copy_confirm_passed": smoke_passed,
        "rule_operational_scheduler_allowed": True,
        "evidence_capture_scheduler_allowed": production_scheduler_allowed,
        "production_scheduler_allowed": production_scheduler_allowed,
        "formal_evidence_credit_allowed": False,
        "ml_nonzero_alpha_allowed": False,
    }


def _load_approval_artifact(
    path: str | Path | None,
) -> dict[str, Any] | None:
    """Read and validate a bounded, owner-supplied approval artifact.

    The evaluator never creates or mutates this file.  A missing or malformed
    artifact is deliberately indistinguishable from an unapproved scheduler
    for the purpose of the write gate, while the returned diagnostic remains
    explicit for operators.
    """

    if path is None:
        return None
    artifact_path = Path(path)
    try:
        raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, Mapping):
        return None
    if raw.get("schema_version") != APPROVAL_SCHEMA_VERSION:
        return None
    if raw.get("approved") is not True:
        return None
    if raw.get("production_scheduler_allowed") is not True:
        return None
    for key in ("approval_id", "owner", "approved_at"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
    scope = raw.get("scope")
    if scope != "evidence_capture_scheduler":
        return None
    checks = raw.get("checks")
    if not isinstance(checks, Mapping):
        return None
    if any(checks.get(key) is not True for key in _REQUIRED_APPROVAL_CHECKS):
        return None
    approved_at = _parse_approval_timestamp(raw.get("approved_at"))
    now = datetime.now(timezone.utc)
    if approved_at is None or approved_at > now:
        return None
    expires_at_raw = raw.get("expires_at")
    expires_at = _parse_approval_timestamp(expires_at_raw)
    if expires_at is None or expires_at <= now or expires_at <= approved_at:
        return None
    return {
        "path": str(artifact_path.expanduser().resolve()),
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "approval_id": raw["approval_id"],
        "owner": raw["owner"],
        "approved_at": raw["approved_at"],
        "expires_at": expires_at_raw,
        "scope": "evidence_capture_scheduler",
        "approved": True,
        "production_scheduler_allowed": True,
        "checks": {key: True for key in _REQUIRED_APPROVAL_CHECKS},
    }


def _approval_diagnostic(
    path: str | Path | None,
    approval: Mapping[str, Any] | None,
) -> str | None:
    if path is None:
        return "production_scheduler_approval_missing"
    if approval is None:
        return "production_scheduler_approval_invalid"
    return None


def _parse_approval_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _load_smoke_report(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    report_path = Path(path)
    if not report_path.exists() or report_path.suffix.lower() != ".json":
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


def _smoke_passed(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return False
    return bool(payload.get("idempotency_check", {}).get("passed")) and not payload.get("blocking_gaps")


def _dashboard_available() -> bool:
    return ForwardPerformanceDashboardService is not None

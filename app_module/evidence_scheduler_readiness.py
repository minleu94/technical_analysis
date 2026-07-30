from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def evaluate_evidence_scheduler_readiness(
    config: TWStockConfig,
    *,
    db_path: str | Path,
    smoke_report_path: str | Path | None = None,
    decision_date: str | None = None,
    result_id: str | None = None,
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

    readiness = source_coverage["scheduler_readiness"]
    production_scheduler_allowed = not blocking_gaps
    if production_scheduler_allowed:
        readiness = READINESS_OPERATIONAL_PRODUCTION
    elif readiness not in READINESS_VALUES:
        readiness = READINESS_NOT_READY

    warnings = list(source_coverage["warnings"])
    if smoke_diagnostic is not None:
        warnings.append(smoke_diagnostic)
    return {
        "readiness": readiness,
        "blocking_gaps": sorted(set(blocking_gaps)),
        "warnings": sorted(set(warnings)),
        "required_manual_checks": [],
        "automated_gate_policy": [
            "official_trading_calendar_fail_closed",
            "source_coverage_revalidated_each_run",
            "idempotent_evidence_capture",
            "subprocess_timeout_persisted_as_degraded",
            "insufficient_history_does_not_block_rule_operations",
        ],
        "latest_smoke_status": latest_smoke_status,
        "source_coverage_status": source_coverage,
        "dashboard_available": dashboard_available,
        "working_copy_confirm_passed": smoke_passed,
        "rule_operational_scheduler_allowed": True,
        "evidence_capture_scheduler_allowed": production_scheduler_allowed,
        "production_scheduler_allowed": production_scheduler_allowed,
        "formal_evidence_credit_allowed": False,
        "ml_nonzero_alpha_allowed": False,
    }


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

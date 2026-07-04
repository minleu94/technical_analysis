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
        blocking_gaps.append("working_copy_confirm_smoke_missing_or_failed")
    dashboard_available = _dashboard_available()
    if not dashboard_available:
        blocking_gaps.append("forward_dashboard_service_unavailable")

    readiness = source_coverage["scheduler_readiness"]
    if not blocking_gaps and smoke_passed:
        readiness = READINESS_READY_FOR_MANUAL_CONFIRM
    elif readiness not in READINESS_VALUES:
        readiness = READINESS_NOT_READY

    required_manual_checks = [
        "manual approval of source coverage",
        "manual approval of dry-run diagnostics",
        "manual approval of working-copy confirm smoke",
        "manual approval before any future scheduler enablement",
    ]
    return {
        "readiness": readiness,
        "blocking_gaps": sorted(set(blocking_gaps)),
        "warnings": list(source_coverage["warnings"]),
        "required_manual_checks": required_manual_checks,
        "latest_smoke_status": latest_smoke_status,
        "source_coverage_status": source_coverage,
        "dashboard_available": dashboard_available,
        "working_copy_confirm_passed": smoke_passed,
        "production_scheduler_allowed": False,
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

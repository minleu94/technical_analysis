from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import section_is_ready
from app_module.evidence_pipeline_runner_dtos import (
    READINESS_DRY_RUN_ONLY,
    READINESS_NOT_READY,
    READINESS_READY_FOR_DESIGN,
    READINESS_READY_FOR_MANUAL_CONFIRM,
)
from app_module.forward_performance_dashboard_service import ForwardPerformanceDashboardService
from app_module.recommendation_repository import RecommendationRepository
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
    source_coverage = _source_coverage(config, decision_date=decision_date, result_id=result_id)
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


def _source_coverage(
    config: TWStockConfig,
    *,
    decision_date: str | None,
    result_id: str | None,
) -> dict[str, Any]:
    recommendation_repository = RecommendationRepository(config)
    recommendation = recommendation_repository.load_result(result_id) if result_id else _latest_recommendation(recommendation_repository)
    snapshot_repository = DecisionDeskSnapshotRepository(config)
    snapshots = snapshot_repository.list_snapshots()
    latest_snapshot = (
        snapshot_repository.latest_before_or_on(decision_date)
        if decision_date
        else (snapshots[0] if snapshots else None)
    )
    recommendation_ready = recommendation is not None
    why_not_ready = _has_payload(getattr(recommendation, "why_not_payload_json", None)) if recommendation else False
    liquidity_ready = _has_payload(getattr(recommendation, "liquidity_gate_payload_json", None)) if recommendation else False
    watchlist_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.watchlist_trigger_json)
    portfolio_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.portfolio_alert_json)
    risk_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.risk_prompt_json)

    gaps: list[str] = []
    warnings: list[str] = []
    if not recommendation_ready:
        gaps.append("recommendation_persisted_missing")
    if latest_snapshot is None:
        gaps.append("decision_desk_snapshot_missing")
    if latest_snapshot is not None and not watchlist_ready:
        gaps.append("watchlist_trigger_snapshot_section_missing")
    if latest_snapshot is not None and not portfolio_ready:
        gaps.append("portfolio_alert_snapshot_section_missing")
    if latest_snapshot is not None and not risk_ready:
        gaps.append("risk_prompt_snapshot_section_missing")
    if not why_not_ready:
        warnings.append("why_not_payload_missing")
    if not liquidity_ready:
        warnings.append("liquidity_gate_payload_missing")

    if not recommendation_ready or latest_snapshot is None or not (watchlist_ready and portfolio_ready and risk_ready):
        readiness = READINESS_NOT_READY
    elif not (why_not_ready and liquidity_ready):
        readiness = READINESS_DRY_RUN_ONLY
    else:
        readiness = READINESS_READY_FOR_DESIGN

    return {
        "recommendation_persisted_available": recommendation_ready,
        "recommendation_exclusion_payload_available": why_not_ready and liquidity_ready,
        "decision_desk_snapshots_count": len(snapshots),
        "latest_decision_desk_snapshot_date": latest_snapshot.decision_date if latest_snapshot is not None else None,
        "watchlist_trigger_capture_ready": watchlist_ready,
        "portfolio_alert_capture_ready": portfolio_ready,
        "risk_prompt_capture_ready": risk_ready,
        "why_not_capture_ready": why_not_ready,
        "liquidity_gate_capture_ready": liquidity_ready,
        "scheduler_readiness": readiness,
        "blocking_gaps": gaps,
        "warnings": warnings,
    }


def _latest_recommendation(repository: RecommendationRepository) -> Any | None:
    rows = repository.list_results()
    if not rows:
        return None
    latest = sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]
    return repository.load_result(str(latest.get("result_id") or ""))


def _has_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    return bool(list(value))


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

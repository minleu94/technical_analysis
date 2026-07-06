from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import section_is_ready
from app_module.evidence_pipeline_runner_dtos import (
    READINESS_DRY_RUN_ONLY,
    READINESS_NOT_READY,
    READINESS_READY_FOR_DESIGN,
)
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig
from data_module.data_source_capability_registry import build_default_data_source_capability_registry


@dataclass(frozen=True)
class EvidenceSourceCoverageInspection:
    recommendation_persisted_available: bool
    recommendation_exclusion_payload_available: bool
    recommendation_screening_matrix_available: bool
    decision_desk_snapshots_count: int
    latest_decision_desk_snapshot_date: str | None
    watchlist_trigger_capture_ready: bool
    portfolio_alert_capture_ready: bool
    risk_prompt_capture_ready: bool
    why_not_capture_ready: bool
    liquidity_gate_capture_ready: bool
    screening_matrix_capture_ready: bool
    scheduler_readiness: str
    blocking_gaps: tuple[str, ...]
    warnings: tuple[str, ...]
    source_capability_status: dict[str, str]
    source_capabilities: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_persisted_available": self.recommendation_persisted_available,
            "recommendation_exclusion_payload_available": self.recommendation_exclusion_payload_available,
            "recommendation_screening_matrix_available": self.recommendation_screening_matrix_available,
            "decision_desk_snapshots_count": self.decision_desk_snapshots_count,
            "latest_decision_desk_snapshot_date": self.latest_decision_desk_snapshot_date,
            "watchlist_trigger_capture_ready": self.watchlist_trigger_capture_ready,
            "portfolio_alert_capture_ready": self.portfolio_alert_capture_ready,
            "risk_prompt_capture_ready": self.risk_prompt_capture_ready,
            "why_not_capture_ready": self.why_not_capture_ready,
            "liquidity_gate_capture_ready": self.liquidity_gate_capture_ready,
            "screening_matrix_capture_ready": self.screening_matrix_capture_ready,
            "scheduler_readiness": self.scheduler_readiness,
            "blocking_gaps": list(self.blocking_gaps),
            "warnings": list(self.warnings),
            "source_capability_status": dict(self.source_capability_status),
            "source_capabilities": {
                source_id: dict(payload) for source_id, payload in self.source_capabilities.items()
            },
        }


class EvidenceSourceCoverageService:
    """Read-only evidence source coverage inspection for V1.5 source gates."""

    def __init__(self, config: TWStockConfig, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)

    def inspect(
        self,
        *,
        decision_date: str | None = None,
        result_id: str | None = None,
    ) -> EvidenceSourceCoverageInspection:
        recommendation_repository = RecommendationRepository(self.config)
        snapshot_repository = DecisionDeskSnapshotRepository(self.config, db_path=self.db_path)
        recommendation = self._latest_recommendation(recommendation_repository, result_id)
        snapshots = snapshot_repository.list_snapshots()
        latest_snapshot = (
            snapshot_repository.latest_before_or_on(decision_date)
            if decision_date
            else (snapshots[0] if snapshots else None)
        )

        recommendation_available = recommendation is not None
        why_not_ready = _has_payload(getattr(recommendation, "why_not_payload_json", None)) if recommendation else False
        liquidity_ready = (
            _has_payload(getattr(recommendation, "liquidity_gate_payload_json", None)) if recommendation else False
        )
        screening_matrix_ready = (
            _has_payload(getattr(recommendation, "screening_matrix_json", None)) if recommendation else False
        )
        watchlist_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.watchlist_trigger_json)
        portfolio_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.portfolio_alert_json)
        risk_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.risk_prompt_json)
        blocking_gaps = self._blocking_gaps(
            recommendation_available=recommendation_available,
            latest_snapshot_available=latest_snapshot is not None,
            watchlist_ready=watchlist_ready,
            portfolio_ready=portfolio_ready,
            risk_ready=risk_ready,
        )
        warnings = self._warnings(
            why_not_ready=why_not_ready,
            liquidity_ready=liquidity_ready,
            screening_matrix_ready=screening_matrix_ready,
        )
        snapshot_ready = latest_snapshot is not None and watchlist_ready and portfolio_ready and risk_ready
        if not recommendation_available or not snapshot_ready:
            readiness = READINESS_NOT_READY
        elif warnings:
            readiness = READINESS_DRY_RUN_ONLY
        else:
            readiness = READINESS_READY_FOR_DESIGN

        source_capabilities = _source_capabilities()
        return EvidenceSourceCoverageInspection(
            recommendation_persisted_available=recommendation_available,
            recommendation_exclusion_payload_available=why_not_ready and liquidity_ready,
            recommendation_screening_matrix_available=screening_matrix_ready,
            decision_desk_snapshots_count=len(snapshots),
            latest_decision_desk_snapshot_date=latest_snapshot.decision_date if latest_snapshot is not None else None,
            watchlist_trigger_capture_ready=watchlist_ready,
            portfolio_alert_capture_ready=portfolio_ready,
            risk_prompt_capture_ready=risk_ready,
            why_not_capture_ready=why_not_ready,
            liquidity_gate_capture_ready=liquidity_ready,
            screening_matrix_capture_ready=screening_matrix_ready,
            scheduler_readiness=readiness,
            blocking_gaps=tuple(blocking_gaps),
            warnings=tuple(warnings),
            source_capability_status={
                source_id: str(payload.get("status") or "unknown")
                for source_id, payload in source_capabilities.items()
            },
            source_capabilities=source_capabilities,
        )

    def _latest_recommendation(self, repository: RecommendationRepository, result_id: str | None) -> Any | None:
        if result_id:
            return repository.load_result(result_id)
        rows = repository.list_results()
        if not rows:
            return None
        latest = sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]
        return repository.load_result(str(latest.get("result_id") or ""))

    def _blocking_gaps(
        self,
        *,
        recommendation_available: bool,
        latest_snapshot_available: bool,
        watchlist_ready: bool,
        portfolio_ready: bool,
        risk_ready: bool,
    ) -> list[str]:
        gaps: list[str] = []
        if not recommendation_available:
            gaps.append("recommendation_persisted_missing")
        if not latest_snapshot_available:
            gaps.append("decision_desk_snapshot_missing")
        if latest_snapshot_available and not watchlist_ready:
            gaps.append("watchlist_trigger_snapshot_section_missing")
        if latest_snapshot_available and not portfolio_ready:
            gaps.append("portfolio_alert_snapshot_section_missing")
        if latest_snapshot_available and not risk_ready:
            gaps.append("risk_prompt_snapshot_section_missing")
        return gaps

    def _warnings(
        self,
        *,
        why_not_ready: bool,
        liquidity_ready: bool,
        screening_matrix_ready: bool,
    ) -> list[str]:
        warnings: list[str] = []
        if not why_not_ready:
            warnings.append("why_not_payload_missing")
        if not liquidity_ready:
            warnings.append("liquidity_gate_payload_missing")
        if not screening_matrix_ready:
            warnings.append("screening_matrix_missing")
        return warnings


def _source_capabilities() -> dict[str, dict[str, Any]]:
    registry = build_default_data_source_capability_registry()
    source_ids = (
        "recommendation.persisted_result",
        "recommendation.screening_matrix",
        "recommendation.exclusion.why_not_payload",
        "recommendation.exclusion.liquidity_gate_payload",
        "decision_desk.snapshot.watchlist_trigger",
        "decision_desk.snapshot.portfolio_alert",
        "decision_desk.snapshot.risk_prompt",
    )
    return {source_id: registry.require(source_id).to_dict() for source_id in source_ids}


def _has_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    try:
        return bool(list(value))
    except TypeError:
        return bool(value)

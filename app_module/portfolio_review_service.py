"""Portfolio Review Dashboard application service for Month 6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.portfolio_feedback_service import (
    LiveResearchGapReport,
    PortfolioFeedbackService,
)
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.strategy_lifecycle_service import (
    GateStatus,
    LifecycleAction,
    LifecycleDecision,
    StrategyDriftReport,
    StrategyLifecycleService,
)


class PortfolioPositionProvider(Protocol):
    def list_positions(self, portfolio_id: str = "default") -> Sequence[PositionDTO]: ...


class ResearchRunProvider(Protocol):
    def get_metadata(self, run_id: str) -> ResearchRunMetadataDTO | None: ...


@dataclass(frozen=True)
class StrategyLifecycleSummary:
    total_runs: int
    promote_candidates: int
    hold_count: int
    demote_count: int
    retire_count: int
    decisions: tuple[LifecycleDecision, ...]


@dataclass(frozen=True)
class PortfolioReviewSnapshot:
    portfolio_id: str
    lifecycle_summary: StrategyLifecycleSummary
    live_research_gap: LiveResearchGapReport
    drift_reports: tuple[StrategyDriftReport, ...]
    quality: GateStatus
    warnings: tuple[str, ...]


class PortfolioReviewService:
    """Build the Month 6 portfolio review dashboard snapshot."""

    def __init__(
        self,
        *,
        lifecycle_service: StrategyLifecycleService | None = None,
        feedback_service: PortfolioFeedbackService | None = None,
    ) -> None:
        self.lifecycle_service = lifecycle_service or StrategyLifecycleService()
        self.feedback_service = feedback_service or PortfolioFeedbackService()

    def build_snapshot(
        self,
        *,
        portfolio_provider: PortfolioPositionProvider,
        candidate_runs: Sequence[ResearchRunMetadataDTO],
        portfolio_id: str = "default",
        condition_results: Mapping[str, Any] | None = None,
        drift_reports_by_stock: Mapping[str, StrategyDriftReport] | None = None,
        expected_regimes_by_strategy: Mapping[str, Sequence[str]] | None = None,
    ) -> PortfolioReviewSnapshot:
        positions = tuple(portfolio_provider.list_positions(portfolio_id))
        decisions = tuple(
            self.lifecycle_service.evaluate_run(
                run,
                expected_regimes=(expected_regimes_by_strategy or {}).get(run.strategy_id),
            )
            for run in candidate_runs
        )
        lifecycle_summary = self._summarize_lifecycle(decisions)
        live_gap = self.feedback_service.build_live_research_gap_report(
            positions,
            condition_results=condition_results,
            drift_reports=drift_reports_by_stock,
            portfolio_id=portfolio_id,
        )
        drift_reports = tuple((drift_reports_by_stock or {}).values())
        warnings = self._warnings(lifecycle_summary, live_gap, drift_reports)
        quality = self._quality(lifecycle_summary, live_gap, drift_reports)
        return PortfolioReviewSnapshot(
            portfolio_id=portfolio_id,
            lifecycle_summary=lifecycle_summary,
            live_research_gap=live_gap,
            drift_reports=drift_reports,
            quality=quality,
            warnings=warnings,
        )

    def _summarize_lifecycle(
        self,
        decisions: Sequence[LifecycleDecision],
    ) -> StrategyLifecycleSummary:
        return StrategyLifecycleSummary(
            total_runs=len(decisions),
            promote_candidates=sum(1 for item in decisions if item.action == LifecycleAction.PROMOTE),
            hold_count=sum(1 for item in decisions if item.action == LifecycleAction.HOLD),
            demote_count=sum(1 for item in decisions if item.action == LifecycleAction.DEMOTE),
            retire_count=sum(1 for item in decisions if item.action == LifecycleAction.RETIRE),
            decisions=tuple(decisions),
        )

    def _warnings(
        self,
        lifecycle: StrategyLifecycleSummary,
        live_gap: LiveResearchGapReport,
        drift_reports: Sequence[StrategyDriftReport],
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if lifecycle.demote_count:
            warnings.append(f"strategy_lifecycle_demote_count:{lifecycle.demote_count}")
        if lifecycle.retire_count:
            warnings.append(f"strategy_lifecycle_retire_count:{lifecycle.retire_count}")
        if live_gap.invalid_count:
            warnings.append(f"portfolio_feedback_invalid_count:{live_gap.invalid_count}")
        if live_gap.warning_count:
            warnings.append(f"portfolio_feedback_warning_count:{live_gap.warning_count}")
        drift_count = sum(1 for report in drift_reports if report.status == GateStatus.FAIL)
        if drift_count:
            warnings.append(f"strategy_drift_count:{drift_count}")
        warnings.extend(live_gap.warnings)
        return tuple(warnings)

    def _quality(
        self,
        lifecycle: StrategyLifecycleSummary,
        live_gap: LiveResearchGapReport,
        drift_reports: Sequence[StrategyDriftReport],
    ) -> GateStatus:
        if lifecycle.retire_count or live_gap.invalid_count:
            return GateStatus.FAIL
        if lifecycle.demote_count or live_gap.warning_count:
            return GateStatus.DEGRADED
        if any(report.status == GateStatus.FAIL for report in drift_reports):
            return GateStatus.DEGRADED
        return GateStatus.PASS

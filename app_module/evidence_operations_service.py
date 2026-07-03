from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable

from app_module.decision_quality_service import DecisionQualityService
from app_module.evidence_operations_dtos import (
    EvidenceOperationsDecisionQuality,
    EvidenceOperationsManualApproval,
    EvidenceOperationsSignalDecay,
    EvidenceOperationsWeeklyReview,
)
from app_module.evidence_scheduler_readiness import evaluate_evidence_scheduler_readiness
from app_module.signal_decay_dtos import SUGGESTION_DEMOTE_CANDIDATE, SUGGESTION_RETIRE_CANDIDATE, SUGGESTION_WATCH
from app_module.signal_decay_service import SignalDecayService
from data_module.config import TWStockConfig


ReadinessEvaluator = Callable[..., dict[str, Any]]


class EvidenceOperationsService:
    """Build V1.3 weekly evidence operations reports without applying actions."""

    def __init__(
        self,
        config: TWStockConfig,
        *,
        db_path: str | Path | None = None,
        readiness_evaluator: ReadinessEvaluator = evaluate_evidence_scheduler_readiness,
        decision_quality_service: DecisionQualityService | None = None,
        signal_decay_service: SignalDecayService | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.readiness_evaluator = readiness_evaluator
        self.decision_quality_service = decision_quality_service or DecisionQualityService(config, db_path=self.db_path)
        self.signal_decay_service = signal_decay_service or SignalDecayService(config, db_path=self.db_path)

    def build_weekly_review(
        self,
        *,
        start_date: str,
        end_date: str,
        smoke_report_path: str | Path | None = None,
        result_id: str | None = None,
    ) -> EvidenceOperationsWeeklyReview:
        readiness_payload = self.readiness_evaluator(
            self.config,
            db_path=self.db_path,
            smoke_report_path=smoke_report_path,
            decision_date=end_date,
            result_id=result_id,
        )
        manual_approval = self._manual_approval(readiness_payload)
        dq_summary = self._decision_quality_summary(start_date=start_date, end_date=end_date)
        decay_summary, candidates = self._signal_decay_summary(start_date=start_date, end_date=end_date)
        status = self._status(manual_approval=manual_approval, decision_quality=dq_summary, signal_decay=decay_summary)
        next_actions = self._next_actions(
            status=status,
            manual_approval=manual_approval,
            decision_quality=dq_summary,
            signal_decay=decay_summary,
        )
        warnings = tuple(sorted(set(manual_approval.warnings + manual_approval.blocking_gaps)))
        return EvidenceOperationsWeeklyReview(
            start_date=start_date,
            end_date=end_date,
            status=status,
            manual_approval=manual_approval,
            decision_quality=dq_summary,
            signal_decay=decay_summary,
            manual_lifecycle_candidates=tuple(candidates),
            next_actions=next_actions,
            warnings=warnings,
            write_performed=False,
        )

    def render_markdown(self, report: EvidenceOperationsWeeklyReview) -> str:
        rows = [
            f"# V1.3 Evidence Operations Weekly Review ({report.start_date} 至 {report.end_date})",
            "",
            f"- status: `{report.status}`",
            f"- scheduler readiness: `{report.manual_approval.readiness}`",
            f"- production scheduler allowed: `{str(report.manual_approval.production_scheduler_allowed).lower()}`",
            f"- decision quality reviews: `{report.decision_quality.reviews_count}`",
            f"- open review items: `{report.decision_quality.open_item_count}`",
            f"- signal decay candidates: `{len(report.manual_lifecycle_candidates)}`",
            "",
            "## Next Actions",
        ]
        rows.extend(f"- `{action}`" for action in report.next_actions)
        rows.extend(["", "## Safety Boundary", "- 本報告只供人工覆盤，不啟用 production scheduler，不自動套用 lifecycle action。"])
        return "\n".join(rows) + "\n"

    @staticmethod
    def _manual_approval(payload: dict[str, Any]) -> EvidenceOperationsManualApproval:
        return EvidenceOperationsManualApproval(
            readiness=str(payload.get("readiness") or "not_ready"),
            production_scheduler_allowed=False,
            blocking_gaps=tuple(str(item) for item in payload.get("blocking_gaps", [])),
            warnings=tuple(str(item) for item in payload.get("warnings", [])),
            required_manual_checks=tuple(str(item) for item in payload.get("required_manual_checks", [])),
            latest_smoke_status=str(payload.get("latest_smoke_status") or ""),
            working_copy_confirm_passed=bool(payload.get("working_copy_confirm_passed")),
        )

    def _decision_quality_summary(self, *, start_date: str, end_date: str) -> EvidenceOperationsDecisionQuality:
        reviews = self.decision_quality_service.list_reviews(start_date=start_date, end_date=end_date)
        review_ids = {review.review_id for review in reviews}
        open_items = [
            item for item in self.decision_quality_service.list_items(status="open") if item.review_id in review_ids
        ]
        actions = []
        for review_id in sorted(review_ids):
            actions.extend(self.decision_quality_service.list_action_items(review_id=review_id))
        return EvidenceOperationsDecisionQuality(
            reviews_count=len(reviews),
            open_item_count=len(open_items),
            action_item_count=len(actions),
            review_status_counts=dict(sorted(Counter(review.review_status for review in reviews).items())),
            item_type_counts=dict(sorted(Counter(item.item_type for item in open_items).items())),
            warnings_count=sum(len(review.warnings_json) for review in reviews),
        )

    def _signal_decay_summary(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> tuple[EvidenceOperationsSignalDecay, list[dict[str, Any]]]:
        rows = [
            row
            for row in self.signal_decay_service.list_decay_observations()
            if start_date <= str(row.observation_date)[:10] <= end_date
        ]
        candidates = [
            {
                "decay_id": row.decay_id,
                "observation_date": row.observation_date,
                "signal_scope_type": row.signal_scope_type,
                "signal_scope_id": row.signal_scope_id,
                "suggested_lifecycle_action": row.suggested_lifecycle_action,
                "confidence": row.confidence,
                "quality": row.quality,
                "apply_action": False,
            }
            for row in rows
            if row.suggested_lifecycle_action in {SUGGESTION_DEMOTE_CANDIDATE, SUGGESTION_RETIRE_CANDIDATE}
        ]
        suggestion_counts = Counter(row.suggested_lifecycle_action for row in rows)
        summary = EvidenceOperationsSignalDecay(
            observations_count=len(rows),
            demote_candidate_count=suggestion_counts[SUGGESTION_DEMOTE_CANDIDATE],
            retire_candidate_count=suggestion_counts[SUGGESTION_RETIRE_CANDIDATE],
            watch_count=suggestion_counts[SUGGESTION_WATCH],
            status_counts=dict(sorted(Counter(row.decay_status for row in rows).items())),
            confidence_counts=dict(sorted(Counter(row.confidence for row in rows).items())),
            warnings_count=sum(len(row.warnings_json) for row in rows),
        )
        return summary, candidates

    @staticmethod
    def _status(
        *,
        manual_approval: EvidenceOperationsManualApproval,
        decision_quality: EvidenceOperationsDecisionQuality,
        signal_decay: EvidenceOperationsSignalDecay,
    ) -> str:
        if decision_quality.reviews_count == 0 and signal_decay.observations_count == 0:
            return "coverage_only"
        if (
            manual_approval.blocking_gaps
            or decision_quality.open_item_count
            or signal_decay.demote_candidate_count
            or signal_decay.retire_candidate_count
        ):
            return "needs_manual_review"
        return "ready_for_weekly_closeout"

    @staticmethod
    def _next_actions(
        *,
        status: str,
        manual_approval: EvidenceOperationsManualApproval,
        decision_quality: EvidenceOperationsDecisionQuality,
        signal_decay: EvidenceOperationsSignalDecay,
    ) -> tuple[str, ...]:
        actions: list[str] = []
        if status == "coverage_only":
            actions.append("collect_more_evidence")
        if manual_approval.blocking_gaps:
            actions.append("resolve_scheduler_blocking_gaps")
        if decision_quality.open_item_count:
            actions.append("review_decision_quality_items")
        if decision_quality.action_item_count:
            actions.append("follow_up_open_action_items")
        if signal_decay.demote_candidate_count or signal_decay.retire_candidate_count:
            actions.append("review_signal_decay_candidate")
        if not actions:
            actions.append("prepare_weekly_closeout_note")
        actions.append("keep_production_scheduler_disabled")
        return tuple(dict.fromkeys(actions))


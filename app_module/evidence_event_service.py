from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any, Iterable
from uuid import uuid4

from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    normalize_data_quality,
    normalize_event_type,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.research_run_dtos import canonical_json as canonical_evidence_json
from app_module.research_run_dtos import EvidenceReviewProposalDTO
from app_module.research_run_service import ResearchRunService


class EvidenceEventService:
    """Application boundary for recording idempotent evidence events."""

    def __init__(self, repository: EvidenceEventRepository) -> None:
        self.repository = repository

    def record_events(self, payloads: Iterable[dict[str, Any]]) -> list[EvidenceEvent]:
        return [self.record_event(**payload) for payload in payloads]

    def record_event(
        self,
        *,
        event_date: str,
        decision_date: str,
        symbol: str | None,
        event_type: EvidenceEventType | str,
        event_family: str,
        source_type: str,
        source_id: str = "",
        source_snapshot_id: str = "",
        strategy_version_id: str = "",
        profile_id: str = "",
        run_id: str = "",
        reason_codes: Iterable[Any] | str | None = (),
        why_not_codes: Iterable[Any] | str | None = (),
        risk_codes: Iterable[Any] | str | None = (),
        score_bp: int | None = None,
        score_percentile_bp: int | None = None,
        regime: str | None = None,
        sector: str | None = None,
        concept_basket: str | None = None,
        liquidity_state: str | None = None,
        data_quality: EvidenceDataQuality | str = EvidenceDataQuality.MISSING,
        warnings: Iterable[Any] | str | None = (),
        as_of_date: str,
        available_date: str,
        source_version: str = "",
        cost_model_id: str = "",
        benchmark_id: str | None = None,
        industry_benchmark_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        evidence_tier: str | None = None,
    ) -> EvidenceEvent:
        normalized_event_type = normalize_event_type(event_type)
        normalized_quality = normalize_data_quality(data_quality)
        normalized_reasons = self._normalize_sequence(reason_codes)
        normalized_why_not = self._normalize_sequence(why_not_codes)
        normalized_risks = self._normalize_sequence(risk_codes)
        normalized_warnings = self._normalize_sequence(warnings)
        normalized_metadata = self._normalize_metadata(metadata)
        if evidence_tier is not None:
            if evidence_tier not in {"replay", "forward", "paper", "live"}:
                raise ValueError("evidence_tier 必須為 replay/forward/paper/live")
            normalized_metadata["evidence_lineage"] = {
                "contract": "evidence-lineage.v1", "declared_tier": evidence_tier,
                "run_id": run_id, "source_snapshot_id": source_snapshot_id,
                "formal_credit_granted": False, "requires_named_review": True,
            }

        self.validate_event(
            event_date=event_date,
            decision_date=decision_date,
            symbol=symbol,
            event_type=normalized_event_type,
            event_family=event_family,
            source_type=source_type,
            data_quality=normalized_quality,
            as_of_date=as_of_date,
            available_date=available_date,
        )

        event_hash = self.build_event_hash(
            event_date=event_date,
            decision_date=decision_date,
            symbol=symbol,
            event_type=normalized_event_type,
            source_type=source_type,
            source_id=source_id,
            source_snapshot_id=source_snapshot_id,
            reason_codes=normalized_reasons,
            why_not_codes=normalized_why_not,
            risk_codes=normalized_risks,
            strategy_version_id=strategy_version_id,
            profile_id=profile_id,
            run_id=run_id,
            metadata=normalized_metadata,
        )
        event = EvidenceEvent(
            event_id=f"evt_{uuid4().hex}",
            event_hash=event_hash,
            event_date=event_date,
            decision_date=decision_date,
            symbol=str(symbol).strip() if symbol is not None else None,
            event_type=normalized_event_type,
            event_family=event_family,
            source_type=source_type,
            source_id=source_id,
            source_snapshot_id=source_snapshot_id,
            strategy_version_id=strategy_version_id,
            profile_id=profile_id,
            run_id=run_id,
            reason_codes=normalized_reasons,
            why_not_codes=normalized_why_not,
            risk_codes=normalized_risks,
            score_bp=score_bp,
            score_percentile_bp=score_percentile_bp,
            regime=regime,
            sector=sector,
            concept_basket=concept_basket,
            liquidity_state=liquidity_state,
            data_quality=normalized_quality,
            warnings=normalized_warnings,
            as_of_date=as_of_date,
            available_date=available_date,
            source_version=source_version,
            cost_model_id=cost_model_id,
            benchmark_id=benchmark_id,
            industry_benchmark_id=industry_benchmark_id,
            metadata=normalized_metadata,
        )
        return self.repository.insert_event(event)

    @staticmethod
    def lineage_for(event: EvidenceEvent) -> dict[str, Any]:
        declared = event.metadata.get("evidence_lineage", {})
        tier = declared.get("declared_tier", "unclassified") if isinstance(declared, dict) else "unclassified"
        if tier not in {"replay", "forward", "paper", "live"}:
            tier = "unclassified"
        return {
            "contract": "evidence-lineage.v1", "declared_tier": tier,
            "event_id": event.event_id, "event_hash": event.event_hash,
            "run_id": event.run_id, "source_id": event.source_id,
            "source_snapshot_id": event.source_snapshot_id,
            "strategy_version_id": event.strategy_version_id,
            "as_of_date": event.as_of_date, "available_date": event.available_date,
            "formal_credit_granted": False, "requires_named_review": True,
        }

    def build_review_proposal(
        self, run_id: str, *, reviewer: str = "", review_notes: str = "",
        next_research_question: str = "",
    ) -> EvidenceReviewProposalDTO:
        """只讀完整研究與事件／outcome，回傳待人工審閱提案，沒有保存或升級副作用。"""
        run = ResearchRunService(self.repository.config).load_run_data(run_id).metadata
        events = self.repository.list_events_for_run(run_id)
        evidence: list[dict[str, Any]] = []
        missing: set[str] = {"formal_evidence_acceptance_not_evaluated"}
        if not reviewer.strip() or not review_notes.strip():
            missing.add("named_review_required")
        if not next_research_question.strip():
            missing.add("next_research_question_required")
        if not events:
            missing.add("linked_evidence_required")
        for event in events:
            lineage = self.lineage_for(event)
            outcomes = self.repository.list_outcomes(event_id=event.event_id)
            if not event.source_snapshot_id:
                missing.add("recommendation_snapshot_lineage_required")
            if lineage["declared_tier"] == "unclassified":
                missing.add("evidence_tier_unclassified")
            if lineage["declared_tier"] != "replay":
                missing.add("real_time_producer_acceptance_required")
            if not outcomes or any(item.outcome_status != "ready" for item in outcomes):
                missing.add("mature_outcomes_required")
            evidence.append({**lineage, "outcomes": [
                {"outcome_id": item.outcome_id, "event_id": item.event_id,
                 "window_days": item.window_days, "status": item.outcome_status,
                 "return_basis": item.return_basis, "data_as_of_date": item.data_as_of_date,
                 "forward_return_bp": item.forward_return_bp,
                 "is_execution_pnl": False}
                for item in outcomes
            ]})
        return EvidenceReviewProposalDTO(
            run_id=run_id, payload_hash=run.payload_hash, execution_contract=run.execution_contract,
            evidence=tuple(evidence), missing_requirements=tuple(sorted(missing)),
            reviewer=reviewer.strip(), review_notes=review_notes.strip(),
            next_research_question=next_research_question.strip(),
        )

    def validate_event(
        self,
        *,
        event_date: str,
        decision_date: str,
        symbol: str | None,
        event_type: EvidenceEventType,
        event_family: str,
        source_type: str,
        data_quality: EvidenceDataQuality,
        as_of_date: str,
        available_date: str,
    ) -> None:
        required = {
            "event_date": event_date,
            "decision_date": decision_date,
            "symbol": symbol,
            "event_type": event_type.value,
            "event_family": event_family,
            "source_type": source_type,
            "data_quality": data_quality.value,
            "as_of_date": as_of_date,
            "available_date": available_date,
        }
        missing = [name for name, value in required.items() if value is None or str(value).strip() == ""]
        if missing:
            raise ValueError(f"missing required evidence event fields: {', '.join(missing)}")

    def build_event_hash(
        self,
        *,
        event_date: str,
        decision_date: str,
        symbol: str | None,
        event_type: EvidenceEventType | str,
        source_type: str,
        source_id: str,
        source_snapshot_id: str,
        reason_codes: Iterable[Any] | str | None,
        why_not_codes: Iterable[Any] | str | None,
        risk_codes: Iterable[Any] | str | None,
        strategy_version_id: str,
        profile_id: str,
        run_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "event_date": event_date,
            "decision_date": decision_date,
            "symbol": symbol,
            "event_type": normalize_event_type(event_type).value,
            "source_type": source_type,
            "source_id": source_id,
            "source_snapshot_id": source_snapshot_id,
            "reason_codes": list(self._normalize_sequence(reason_codes)),
            "why_not_codes": list(self._normalize_sequence(why_not_codes)),
            "risk_codes": list(self._normalize_sequence(risk_codes)),
            "strategy_version_id": strategy_version_id,
            "profile_id": profile_id,
            "run_id": run_id,
            "metadata": self._normalize_metadata(metadata),
        }
        digest = hashlib.sha256(canonical_evidence_json(payload).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _normalize_sequence(self, value: Iterable[Any] | str | None) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        return tuple(str(item) for item in value)

    def _normalize_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be a JSON object")
        return dict(sorted(metadata.items(), key=lambda item: str(item[0])))


def utc_timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()

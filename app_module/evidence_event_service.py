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
    ) -> EvidenceEvent:
        normalized_event_type = normalize_event_type(event_type)
        normalized_quality = normalize_data_quality(data_quality)
        normalized_reasons = self._normalize_sequence(reason_codes)
        normalized_why_not = self._normalize_sequence(why_not_codes)
        normalized_risks = self._normalize_sequence(risk_codes)
        normalized_warnings = self._normalize_sequence(warnings)
        normalized_metadata = self._normalize_metadata(metadata)

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

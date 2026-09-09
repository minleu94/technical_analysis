"""Append-only drift review and rollback simulation for shadow models."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ml_module.drift_champion_comparison import MLFeatureDriftResult
from ml_module.model_lifecycle_registry import ModelLifecycleEvent, ModelLifecycleRegistry


@dataclass(frozen=True)
class ShadowMonitoringActionReport:
    model_id: str
    dataset_id: str
    status: str
    overlay_allowed: bool
    lifecycle_event_ids: tuple[str, ...]
    recommended_human_action: str
    retrain_automatically: bool = False
    auto_promotion_allowed: bool = False
    formal_rule_unchanged: bool = True
    production_action_allowed: bool = False


class ShadowModelMonitoringService:
    def __init__(self, lifecycle_registry: ModelLifecycleRegistry) -> None:
        self._lifecycle_registry = lifecycle_registry

    def apply_drift_review(
        self,
        *,
        model_id: str,
        dataset_id: str,
        evaluated_at: str,
        drift_results: tuple[MLFeatureDriftResult, ...],
    ) -> ShadowMonitoringActionReport:
        if not drift_results:
            raise ValueError("drift_results are required")
        has_major_drift = any(result.status == "major_drift" for result in drift_results)
        lifecycle_status = self._lifecycle_registry.current_status(model_id)
        if lifecycle_status in {"disabled", "superseded"}:
            if lifecycle_status == "disabled" and has_major_drift:
                reason = "major drift requires human review"
                expected_ids = tuple(
                    _event_id(model_id, evaluated_at, reason, event_type)
                    for event_type in ("review_required", "disabled")
                )
                existing_ids = {
                    event.event_id for event in self._lifecycle_registry.list_events(model_id)
                }
                if all(event_id in existing_ids for event_id in expected_ids):
                    return ShadowMonitoringActionReport(
                        model_id=model_id,
                        dataset_id=dataset_id,
                        status="major_drift_disabled",
                        overlay_allowed=False,
                        lifecycle_event_ids=expected_ids,
                        recommended_human_action="review_drift_and_keep_rule_only",
                    )
            return ShadowMonitoringActionReport(
                model_id=model_id,
                dataset_id=dataset_id,
                status=f"lifecycle_{lifecycle_status}",
                overlay_allowed=False,
                lifecycle_event_ids=(),
                recommended_human_action="keep_rule_only_and_review_history",
            )
        if has_major_drift:
            reason = "major drift requires human review"
            event_types = ("review_required", "disabled")
            event_ids = self._append_events(
                model_id=model_id,
                created_at=evaluated_at,
                reason=reason,
                event_types=event_types,
            )
            return ShadowMonitoringActionReport(
                model_id=model_id,
                dataset_id=dataset_id,
                status="major_drift_disabled",
                overlay_allowed=False,
                lifecycle_event_ids=event_ids,
                recommended_human_action="review_drift_and_keep_rule_only",
            )
        moderate = any(result.status == "moderate_drift" for result in drift_results)
        return ShadowMonitoringActionReport(
            model_id=model_id,
            dataset_id=dataset_id,
            status="moderate_drift" if moderate else "stable",
            overlay_allowed=True,
            lifecycle_event_ids=(),
            recommended_human_action=(
                "review_shadow_monitoring" if moderate else "continue_shadow_monitoring"
            ),
        )

    def simulate_rollback(
        self,
        *,
        model_id: str,
        dataset_id: str,
        requested_at: str,
        reason: str,
    ) -> ShadowMonitoringActionReport:
        if not reason:
            raise ValueError("rollback reason is required")
        event_ids = self._append_events(
            model_id=model_id,
            created_at=requested_at,
            reason=reason,
            event_types=("rollback_requested", "disabled"),
        )
        return ShadowMonitoringActionReport(
            model_id=model_id,
            dataset_id=dataset_id,
            status="rollback_simulated_disabled",
            overlay_allowed=False,
            lifecycle_event_ids=event_ids,
            recommended_human_action="inspect_history_and_keep_rule_only",
        )

    def _append_events(
        self,
        *,
        model_id: str,
        created_at: str,
        reason: str,
        event_types: tuple[str, ...],
    ) -> tuple[str, ...]:
        event_ids = tuple(
            _event_id(model_id, created_at, reason, event_type) for event_type in event_types
        )
        events = tuple(
            ModelLifecycleEvent(
                event_id=event_id,
                model_id=model_id,
                event_type=event_type,
                created_at=created_at,
                reason=reason,
            )
            for event_id, event_type in zip(event_ids, event_types)
        )
        if len(events) != 2:
            raise ValueError("shadow monitoring lifecycle action requires an event pair")
        self._lifecycle_registry.append_pair((events[0], events[1]))
        return event_ids


def _event_id(model_id: str, created_at: str, reason: str, event_type: str) -> str:
    payload = "|".join((model_id, created_at, reason, event_type)).encode("utf-8")
    return f"lifecycle:{hashlib.sha256(payload).hexdigest()}"

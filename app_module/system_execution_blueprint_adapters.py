"""跨工作流唯讀投影；只組合 frozen DTO，不改寫任何 domain 決策。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Mapping


_REQUIRED_VISIBILITY_SOURCES = frozenset(
    {
        "fundamental_monthly_revenues",
        "institutional_flows",
        "credit_transactions",
        "tdcc_shareholding",
        "broker_flows",
    }
)
_PENDING_GATES = (
    "forward_evidence",
    "source_acceptance",
    "production_automation",
    "ml_promotion",
)


@dataclass(frozen=True)
class SystemExecutionBlueprintSnapshot:
    evidence_execution: Mapping[str, object]
    dataset_model_prediction_identity: Mapping[str, object]
    dashboard_visibility: Mapping[str, Mapping[str, object]]
    broker_query: Mapping[str, object]
    formal_boundaries: Mapping[str, object]
    external_pending: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_execution",
            MappingProxyType(dict(self.evidence_execution)),
        )
        object.__setattr__(
            self,
            "dataset_model_prediction_identity",
            MappingProxyType(dict(self.dataset_model_prediction_identity)),
        )
        object.__setattr__(
            self,
            "dashboard_visibility",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(value))
                    for key, value in self.dashboard_visibility.items()
                }
            ),
        )
        object.__setattr__(self, "broker_query", MappingProxyType(dict(self.broker_query)))
        object.__setattr__(
            self,
            "formal_boundaries",
            MappingProxyType(dict(self.formal_boundaries)),
        )
        object.__setattr__(self, "external_pending", tuple(self.external_pending))

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_execution": dict(self.evidence_execution),
            "dataset_model_prediction_identity": dict(
                self.dataset_model_prediction_identity
            ),
            "dashboard_visibility": {
                key: dict(value) for key, value in self.dashboard_visibility.items()
            },
            "broker_query": dict(self.broker_query),
            "formal_boundaries": dict(self.formal_boundaries),
            "external_pending": list(self.external_pending),
        }


class SystemExecutionBlueprintAdapter:
    """把 A～F 中立輸出組成可驗證 snapshot，遇到不安全狀態即拒絕。"""

    @staticmethod
    def verify_time_boundaries(payload: Mapping[str, object]) -> None:
        cutoff = date(2024, 12, 31)
        for field_name in (
            "training_end_date",
            "max_train_label_available_date",
            "max_blend_selection_label_available_date",
        ):
            value = date.fromisoformat(str(payload[field_name])[:10])
            if value > cutoff:
                raise ValueError(f"{field_name} must be on or before 2024-12-31")
        oos_start = date.fromisoformat(str(payload["oos_start_date"])[:10])
        oos_end = date.fromisoformat(str(payload["oos_end_date"])[:10])
        if oos_start != date(2025, 1, 1) or oos_end != date(2025, 12, 31):
            raise ValueError("locked OOS must remain 2025-01-01..2025-12-31")

    @classmethod
    def compose(
        cls,
        *,
        evidence_execution: Mapping[str, Any],
        dataset_manifest: Mapping[str, Any],
        dataset_formal_oos_allowed: bool,
        shadow_projection: Any,
        dashboard_visibility: Any,
        broker_query: Mapping[str, Any],
        candidate_source_acceptance: Mapping[str, Any],
        pit_eligibility: Mapping[str, Any],
    ) -> SystemExecutionBlueprintSnapshot:
        execution = _require_mapping(evidence_execution, "execution")
        if execution.get("source_db_opened") is not True:
            raise ValueError("governed source must be opened")
        if execution.get("source_db_write_performed") is not False:
            raise ValueError("governed source must remain zero-write")
        if execution.get("working_copy_created") is not True:
            raise ValueError("Evidence replay requires an isolated working copy")
        if execution.get("working_copy_write_performed") is not True:
            raise ValueError("Evidence replay must write only to the working copy")

        decision_end = date.fromisoformat(str(dataset_manifest["decision_date_end"])[:10])
        if decision_end > date(2024, 12, 31):
            raise ValueError("dataset decision_date_end must be on or before 2024-12-31")
        if dataset_formal_oos_allowed is not False:
            raise ValueError("current corporate-action coverage must keep formal OOS blocked")

        alpha = getattr(shadow_projection, "production_blend_alpha_bp", None)
        formal_unchanged = getattr(shadow_projection, "formal_rule_unchanged", None)
        production_action = getattr(shadow_projection, "production_action_allowed", None)
        if alpha != 0 or formal_unchanged is not True or production_action is not False:
            raise ValueError("ML shadow projection changed the formal decision boundary")

        statuses = {
            status.source_id: status.to_dict()
            for status in tuple(dashboard_visibility.source_statuses)
        }
        missing = _REQUIRED_VISIBILITY_SOURCES.difference(statuses)
        if missing:
            raise ValueError(f"dashboard source statuses missing: {sorted(missing)}")
        for source_id, status in statuses.items():
            if int(status["row_count"]) == 0 and str(status["quality"]).lower() not in {
                "missing",
                "degraded",
            }:
                raise ValueError(f"zero-row source cannot be ready: {source_id}")

        limit = int(broker_query["limit_per_side"])
        if broker_query.get("limit_pushed_down") is not True:
            raise ValueError("broker Top/Bottom limit must be pushed into the query")
        if int(broker_query["top_count"]) > limit or int(broker_query["bottom_count"]) > limit:
            raise ValueError("broker Top/Bottom result exceeded the requested limit")

        if any(
            candidate_source_acceptance.get(flag) is not False
            for flag in (
                "source_accepted",
                "license_accepted",
                "production_scheduler_allowed",
            )
        ):
            raise ValueError("candidate source gates must remain pending")
        if pit_eligibility.get("formal_oos_allowed") is not False:
            raise ValueError("PIT eligibility must keep formal OOS blocked")
        if str(pit_eligibility.get("corporate_coverage")) != "unknown":
            raise ValueError("corporate coverage truth must remain unknown")

        dataset_identity = {
            "dataset_id": dataset_manifest["dataset_id"],
            "dataset_hash": dataset_manifest["content_hash"],
            "model_id": shadow_projection.model_id,
            "prediction_ids": tuple(
                row.prediction_id for row in shadow_projection.predictions
            ),
            "shadow_status": shadow_projection.status,
            "formal_oos_allowed": False,
        }
        return SystemExecutionBlueprintSnapshot(
            evidence_execution={
                "status": evidence_execution.get("status"),
                "source_db_opened": True,
                "source_db_write_performed": False,
                "working_copy_created": True,
                "working_copy_write_performed": True,
                "lineage_status": _require_mapping(
                    evidence_execution, "lineage"
                ).get("status"),
            },
            dataset_model_prediction_identity=dataset_identity,
            dashboard_visibility=statuses,
            broker_query=broker_query,
            formal_boundaries={
                "production_blend_alpha_bp": 0,
                "formal_rule_unchanged": True,
                "production_action_allowed": False,
                "formal_oos_allowed": False,
            },
            external_pending=_PENDING_GATES,
        )


def _require_mapping(payload: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    value = payload.get(field_name)
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} mapping is required")
    return value


__all__ = [
    "SystemExecutionBlueprintAdapter",
    "SystemExecutionBlueprintSnapshot",
]

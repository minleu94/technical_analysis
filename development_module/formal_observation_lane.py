"""Owner-approved, Rule-only formal observation lane contracts.

The lane is a forward-only observation boundary.  It does not grant formal
credit, source acceptance, production use, training, promotion, or trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


RULE_ONLY_SOURCE_IDS = (
    "daily_prices",
    "industry_indices",
    "market_indices",
    "technical_indicators",
)

CANDIDATE_SOURCE_IDS = (
    "corporate_action.ex_dividend_timeline",
    "corporate_action.reduction_split_par_value",
    "credit_transactions",
    "fubon.marketdata",
    "institutional_flows",
    "microstructure.disposition_stock",
    "microstructure.full_delivery",
    "microstructure.limit_lock",
    "microstructure.periodic_call_auction",
    "microstructure.suspended_halt_resume",
    "mops.ezsearch.statement_publication",
    "tdcc_shareholding",
    "tpex.monthly_revenue_announcement",
    "twse.monthly_revenue_announcement",
)


@dataclass(frozen=True)
class FormalObservationLaneDecision:
    """Hash-addressed owner decision for one forward observation lane."""

    decision_id: str
    holdout_id: str
    decided_at: str
    owner_id: str
    first_eligible_session: str
    allowed_source_ids: tuple[str, ...]
    excluded_source_ids: tuple[str, ...]
    rollback_reference: str
    capture_kind: str = "manual_observed"
    binding_policy: str = "first_post_decision_unused_taiwan_trading_session"
    rule_only_formal_path: bool = True
    no_retroactive_credit: bool = True
    formal_oos_allowed: bool = False
    formal_evidence_credit_authorized: bool = False
    production_blend_alpha_bp: int = 0
    production_action_allowed: bool = False
    scheduler_allowed: bool = False
    training_allowed: bool = False
    promotion_allowed: bool = False
    unblind_allowed: bool = False

    def __post_init__(self) -> None:
        _require_text(self.decision_id, "decision_id")
        _require_text(self.holdout_id, "holdout_id")
        _require_text(self.owner_id, "owner_id")
        _require_text(self.rollback_reference, "rollback_reference")
        decided_at = datetime.fromisoformat(self.decided_at.replace("Z", "+00:00"))
        if decided_at.tzinfo is None:
            raise ValueError("decided_at must include a timezone")
        eligible = date.fromisoformat(self.first_eligible_session)
        if eligible < decided_at.date():
            raise ValueError("first_eligible_session cannot precede the owner decision")
        if self.capture_kind != "manual_observed":
            raise ValueError("capture_kind must be manual_observed")
        if self.binding_policy != "first_post_decision_unused_taiwan_trading_session":
            raise ValueError("binding_policy is invalid")
        if tuple(sorted(set(self.allowed_source_ids))) != self.allowed_source_ids:
            raise ValueError("allowed_source_ids must be sorted and unique")
        if tuple(sorted(set(self.excluded_source_ids))) != self.excluded_source_ids:
            raise ValueError("excluded_source_ids must be sorted and unique")
        if not self.allowed_source_ids:
            raise ValueError("allowed_source_ids cannot be empty")
        if set(self.allowed_source_ids) & set(self.excluded_source_ids):
            raise ValueError("allowed and excluded source ids cannot overlap")
        if not set(self.allowed_source_ids).issubset(RULE_ONLY_SOURCE_IDS):
            raise ValueError("allowed_source_ids must remain inside the Rule-only source set")
        if not set(CANDIDATE_SOURCE_IDS).issubset(self.excluded_source_ids):
            raise ValueError("every governed candidate source must remain excluded")
        safety_flags = (
            self.rule_only_formal_path is True,
            self.no_retroactive_credit is True,
            self.formal_oos_allowed is False,
            self.formal_evidence_credit_authorized is False,
            self.production_blend_alpha_bp == 0,
            self.production_action_allowed is False,
            self.scheduler_allowed is False,
            self.training_allowed is False,
            self.promotion_allowed is False,
            self.unblind_allowed is False,
        )
        if not all(safety_flags):
            raise ValueError("formal observation lane safety flags are invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "formal-observation-lane-decision.v1",
            "decision_id": self.decision_id,
            "holdout_id": self.holdout_id,
            "decided_at": self.decided_at,
            "owner_id": self.owner_id,
            "first_eligible_session": self.first_eligible_session,
            "allowed_source_ids": list(self.allowed_source_ids),
            "excluded_source_ids": list(self.excluded_source_ids),
            "capture_kind": self.capture_kind,
            "binding_policy": self.binding_policy,
            "rule_only_formal_path": True,
            "no_retroactive_credit": True,
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_blend_alpha_bp": 0,
            "production_action_allowed": False,
            "scheduler_allowed": False,
            "training_allowed": False,
            "promotion_allowed": False,
            "unblind_allowed": False,
            "rollback_reference": self.rollback_reference,
        }

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FormalObservationLaneDecision":
        if payload.get("schema_version") != "formal-observation-lane-decision.v1":
            raise ValueError("formal observation lane decision schema is invalid")
        decision = cls(
            decision_id=str(payload.get("decision_id", "")),
            holdout_id=str(payload.get("holdout_id", "")),
            decided_at=str(payload.get("decided_at", "")),
            owner_id=str(payload.get("owner_id", "")),
            first_eligible_session=str(payload.get("first_eligible_session", "")),
            allowed_source_ids=_string_tuple(payload, "allowed_source_ids"),
            excluded_source_ids=_string_tuple(payload, "excluded_source_ids"),
            rollback_reference=str(payload.get("rollback_reference", "")),
            capture_kind=str(payload.get("capture_kind", "")),
            binding_policy=str(payload.get("binding_policy", "")),
            rule_only_formal_path=_bool(payload, "rule_only_formal_path"),
            no_retroactive_credit=_bool(payload, "no_retroactive_credit"),
            formal_oos_allowed=_bool(payload, "formal_oos_allowed"),
            formal_evidence_credit_authorized=_bool(
                payload, "formal_evidence_credit_authorized"
            ),
            production_blend_alpha_bp=_int(payload, "production_blend_alpha_bp"),
            production_action_allowed=_bool(payload, "production_action_allowed"),
            scheduler_allowed=_bool(payload, "scheduler_allowed"),
            training_allowed=_bool(payload, "training_allowed"),
            promotion_allowed=_bool(payload, "promotion_allowed"),
            unblind_allowed=_bool(payload, "unblind_allowed"),
        )
        declared_hash = payload.get("content_hash")
        if declared_hash is not None and declared_hash != decision.content_hash:
            raise ValueError("formal observation lane decision content_hash mismatch")
        return decision


def load_formal_observation_lane_decision(
    path: str | Path,
) -> FormalObservationLaneDecision:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("formal observation lane decision must be a JSON object")
    return FormalObservationLaneDecision.from_dict(payload)


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} cannot be empty")


def _string_tuple(payload: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = payload.get(field)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _bool(payload: Mapping[str, Any], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _int(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value

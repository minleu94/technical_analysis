"""Fubon market-data shadow computation authorization contract.

Separate from the formal Wave 2A SourceAcceptanceDecisionRegistry, this contract
authorizes candidate/shadow calculations for score, recommendation, portfolio,
and exit while maintaining hard-coded fail-closed safety flags (zero formal decision
influence, zero formal evidence credit, zero production blend alpha).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any


@dataclass(frozen=True)
class FubonShadowComputationAuthorization:
    """Read-only authorization contract for Fubon shadow decision pipeline."""

    source_id: str = "fubon.marketdata"
    authorization_revision_id: str = "owner:fubon-shadow:20260725-r1"
    authorized_at: str = "2026-07-26T00:56:50+00:00"
    owner_role: str = "Data Governance Owner"
    decision_time_allowed: bool = True
    historical_pit_allowed: bool = True
    candidate_score_allowed: bool = True
    candidate_recommendation_allowed: bool = True
    candidate_portfolio_allowed: bool = True
    candidate_exit_allowed: bool = True
    formal_decision_influence_allowed: bool = False
    formal_evidence_credit_authorized: bool = False
    formal_oos_allowed: bool = False
    production_blend_alpha_bp: int = 0
    rule_only_formal_path: bool = True
    production_action_allowed: bool = False
    broker_execution_allowed: bool = False
    training_allowed: bool = False
    promotion_allowed: bool = False
    scheduler_allowed: bool = False
    rollback_reference: str = "GEMINI-FUBON-MACHINE-GATES-AND-TEST-AUDIT-V2"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Fail-closed validation enforcing immutable governance safety flags."""
        if self.formal_decision_influence_allowed is not False:
            raise ValueError("formal_decision_influence_allowed must be False")
        if self.formal_evidence_credit_authorized is not False:
            raise ValueError("formal_evidence_credit_authorized must be False")
        if self.formal_oos_allowed is not False:
            raise ValueError("formal_oos_allowed must be False")
        if self.production_blend_alpha_bp != 0:
            raise ValueError("production_blend_alpha_bp must be 0")
        if self.rule_only_formal_path is not True:
            raise ValueError("rule_only_formal_path must be True")
        if self.production_action_allowed is not False:
            raise ValueError("production_action_allowed must be False")
        if self.broker_execution_allowed is not False:
            raise ValueError("broker_execution_allowed must be False")
        if self.training_allowed is not False:
            raise ValueError("training_allowed must be False")
        if self.promotion_allowed is not False:
            raise ValueError("promotion_allowed must be False")
        if self.scheduler_allowed is not False:
            raise ValueError("scheduler_allowed must be False")
        if self.source_id != "fubon.marketdata":
            raise ValueError("source_id must be fubon.marketdata")
        if not self.authorization_revision_id.strip():
            raise ValueError("authorization_revision_id cannot be empty")
        try:
            authorized_at = datetime.fromisoformat(self.authorized_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("authorized_at must be a valid ISO-8601 timestamp") from exc
        if authorized_at.tzinfo is None:
            raise ValueError("authorized_at must include a timezone")

    def _dict_for_hash(self) -> dict[str, Any]:
        return {
            "schema_version": "fubon-shadow-computation-authorization.v1",
            "source_id": self.source_id,
            "authorization_revision_id": self.authorization_revision_id,
            "authorized_at": self.authorized_at,
            "owner_role": self.owner_role,
            "decision_time_allowed": self.decision_time_allowed,
            "historical_pit_allowed": self.historical_pit_allowed,
            "candidate_score_allowed": self.candidate_score_allowed,
            "candidate_recommendation_allowed": self.candidate_recommendation_allowed,
            "candidate_portfolio_allowed": self.candidate_portfolio_allowed,
            "candidate_exit_allowed": self.candidate_exit_allowed,
            "formal_decision_influence_allowed": False,
            "formal_evidence_credit_authorized": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "rule_only_formal_path": True,
            "production_action_allowed": False,
            "broker_execution_allowed": False,
            "training_allowed": False,
            "promotion_allowed": False,
            "scheduler_allowed": False,
            "rollback_reference": self.rollback_reference,
        }

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self._dict_for_hash(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        res = self._dict_for_hash()
        res["content_hash"] = self.content_hash
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FubonShadowComputationAuthorization:
        # Enforce safety flag values regardless of input dictionary overrides
        if data.get("formal_decision_influence_allowed") is True:
            raise ValueError("formal_decision_influence_allowed cannot be set to True")
        if data.get("formal_evidence_credit_authorized") is True:
            raise ValueError("formal_evidence_credit_authorized cannot be set to True")
        if data.get("formal_oos_allowed") is True:
            raise ValueError("formal_oos_allowed cannot be set to True")
        if data.get("production_blend_alpha_bp", 0) != 0:
            raise ValueError("production_blend_alpha_bp cannot be non-zero")

        authorization = cls(
            source_id=str(data.get("source_id", "fubon.marketdata")),
            authorization_revision_id=str(
                data.get("authorization_revision_id", "owner:fubon-shadow:20260725-r1")
            ),
            authorized_at=str(data.get("authorized_at", "2026-07-26T00:56:50+00:00")),
            owner_role=str(data.get("owner_role", "Data Governance Owner")),
            decision_time_allowed=_read_bool(data, "decision_time_allowed", True),
            historical_pit_allowed=_read_bool(data, "historical_pit_allowed", True),
            candidate_score_allowed=_read_bool(data, "candidate_score_allowed", True),
            candidate_recommendation_allowed=_read_bool(
                data, "candidate_recommendation_allowed", True
            ),
            candidate_portfolio_allowed=_read_bool(data, "candidate_portfolio_allowed", True),
            candidate_exit_allowed=_read_bool(data, "candidate_exit_allowed", True),
            formal_decision_influence_allowed=False,
            formal_evidence_credit_authorized=False,
            formal_oos_allowed=False,
            production_blend_alpha_bp=0,
            rule_only_formal_path=True,
            production_action_allowed=False,
            broker_execution_allowed=False,
            training_allowed=False,
            promotion_allowed=False,
            scheduler_allowed=False,
            rollback_reference=str(
                data.get(
                    "rollback_reference",
                    "GEMINI-FUBON-MACHINE-GATES-AND-TEST-AUDIT-V2",
                )
            ),
        )
        declared_hash = data.get("content_hash")
        if declared_hash is not None and declared_hash != authorization.content_hash:
            raise ValueError("authorization content_hash mismatch")
        return authorization


def _read_bool(data: dict[str, Any], field_name: str, default: bool) -> bool:
    value = data.get(field_name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value

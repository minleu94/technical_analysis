"""Fail-closed V3 pruning proposals; never applies strategy changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


VALID_ACTIONS = frozenset({"retain", "restrict", "downweight", "retire", "defer"})


@dataclass(frozen=True)
class PruningProposal:
    slice_id: str
    action: str
    reason_codes: tuple[str, ...]
    apply_action: bool = False
    review_required: bool = True

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"unsupported pruning action: {self.action}")
        if self.apply_action:
            raise ValueError("V3 pruning proposals cannot apply actions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "action": self.action,
            "reason_codes": list(self.reason_codes),
            "apply_action": self.apply_action,
            "review_required": self.review_required,
        }


class V3PruningDecisionService:
    def __init__(self, *, minimum_sample: int = 30) -> None:
        if minimum_sample <= 0:
            raise ValueError("minimum_sample must be positive")
        self._minimum_sample = minimum_sample

    def propose(
        self,
        *,
        slice_id: str,
        metrics: Mapping[str, Any],
        manual_validation_status: str = "NOT_REQUIRED",
    ) -> PruningProposal:
        sample_count = int(metrics.get("sample_count", metrics.get("ready_count", 0)))
        if sample_count < self._minimum_sample:
            return self._proposal(slice_id, "defer", "insufficient_sample")
        if manual_validation_status not in {"COMPLETED", "NOT_REQUIRED"}:
            return self._proposal(slice_id, "defer", "manual_validation_pending")

        hit_rate = metrics.get("hit_rate_bp")
        monotonic = metrics.get("score_monotonic")
        payoff = metrics.get("payoff_ratio_bp")
        if hit_rate is None or monotonic is None:
            return self._proposal(slice_id, "defer", "required_metric_missing")
        if bool(monotonic) and int(hit_rate) >= 5500 and payoff is not None and int(payoff) >= 10000:
            return self._proposal(slice_id, "retain", "stable_positive_signal")
        if not bool(monotonic) and int(hit_rate) < 4000:
            return self._proposal(slice_id, "restrict", "weak_non_monotonic_signal")
        if int(hit_rate) < 5000:
            return self._proposal(slice_id, "downweight", "below_neutral_hit_rate")
        return self._proposal(slice_id, "defer", "mixed_evidence")

    @staticmethod
    def _proposal(slice_id: str, action: str, *reasons: str) -> PruningProposal:
        return PruningProposal(slice_id=slice_id, action=action, reason_codes=tuple(reasons))

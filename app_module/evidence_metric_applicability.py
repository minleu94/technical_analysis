"""Evidence event family 與 effectiveness metric 的適用性契約。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricApplicability:
    score_requirement: str
    supported_metrics: tuple[str, ...]


class EvidenceMetricApplicability:
    """避免把不適用 TotalScore 的 evidence 誤報為 score 缺失。"""

    def classify(self, event_family: str, event_type: str) -> MetricApplicability:
        family = str(event_family or "").strip().lower()
        event = str(event_type or "").strip().lower()
        if family == "recommendation" or event == "recommendation_included":
            return MetricApplicability(
                score_requirement="required",
                supported_metrics=(
                    "score",
                    "forward_return",
                    "precision_at_k",
                ),
            )
        if family in {"risk_prompt", "decision_quality"}:
            return MetricApplicability(
                score_requirement="not_applicable",
                supported_metrics=("alert_quality",),
            )
        return MetricApplicability(
            score_requirement="optional",
            supported_metrics=("forward_return",),
        )

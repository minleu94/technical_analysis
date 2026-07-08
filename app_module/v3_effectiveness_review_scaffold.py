"""V3.0 signal / alert / gate manual review scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_module.v3_effectiveness_dtos import V3EffectivenessReport


CATEGORY_BY_FAMILY = {
    "recommendation": "signal",
    "watchlist": "signal",
    "portfolio_alert": "alert",
    "risk_prompt": "alert",
    "why_not": "gate",
    "liquidity": "gate",
    "screening_matrix": "gate",
    "decision_quality": "dashboard",
}


@dataclass(frozen=True)
class V3ReviewScaffoldItem:
    review_id: str
    event_family: str
    event_type: str
    review_category: str
    sample_sufficiency_label: str
    confidence_label: str
    review_question: str
    manual_validation_status: str
    apply_lifecycle_action: bool
    auto_trading: bool
    source_trace: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "event_family": self.event_family,
            "event_type": self.event_type,
            "review_category": self.review_category,
            "sample_sufficiency_label": self.sample_sufficiency_label,
            "confidence_label": self.confidence_label,
            "review_question": self.review_question,
            "manual_validation_status": self.manual_validation_status,
            "apply_lifecycle_action": self.apply_lifecycle_action,
            "auto_trading": self.auto_trading,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class V3ReviewScaffold:
    active_milestone: str
    items: tuple[V3ReviewScaffoldItem, ...]
    manual_validation_status: str
    production_scheduler_allowed: bool
    auto_trading: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_milestone": self.active_milestone,
            "manual_validation_status": self.manual_validation_status,
            "production_scheduler_allowed": self.production_scheduler_allowed,
            "auto_trading": self.auto_trading,
            "items": [item.to_dict() for item in self.items],
        }


class V3ReviewScaffoldBuilder:
    def build(self, report: V3EffectivenessReport) -> V3ReviewScaffold:
        items = tuple(
            self._build_item(index=index + 1, item=item)
            for index, item in enumerate(report.slices)
        )
        return V3ReviewScaffold(
            active_milestone=report.active_milestone,
            items=items,
            manual_validation_status="PENDING_MANUAL_VALIDATION",
            production_scheduler_allowed=False,
            auto_trading=False,
        )

    def _build_item(self, *, index: int, item: Any) -> V3ReviewScaffoldItem:
        category = CATEGORY_BY_FAMILY.get(item.event_family, "dashboard")
        return V3ReviewScaffoldItem(
            review_id=f"V3-REVIEW-{index:03d}",
            event_family=item.event_family,
            event_type=item.event_type,
            review_category=category,
            sample_sufficiency_label=item.sample_sufficiency_label,
            confidence_label=item.confidence_label,
            review_question=self._review_question(
                event_family=item.event_family,
                event_type=item.event_type,
                category=category,
            ),
            manual_validation_status="PENDING_MANUAL_VALIDATION",
            apply_lifecycle_action=False,
            auto_trading=False,
            source_trace=self._source_trace(item),
        )

    def _review_question(
        self, *, event_family: str, event_type: str, category: str
    ) -> str:
        return (
            f"人工覆盤：{event_family}/{event_type} 作為 {category} 類證據時，"
            "樣本、缺口與文案是否足以進入 V3 engineering candidate？"
        )

    def _source_trace(self, item: Any) -> str | None:
        traces = sorted(
            {
                gap.source_trace
                for gap in item.gap_classifications
                if gap.source_trace
            }
        )
        return ";".join(traces) if traces else None

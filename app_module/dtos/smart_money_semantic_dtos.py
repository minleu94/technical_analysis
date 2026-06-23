from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping


@dataclass(frozen=True)
class SmartMoneyWindowStats:
    window_days: int
    net_qty: int
    buy_qty: int
    sell_qty: int
    direction: str
    continuous_buy_days: int
    continuous_sell_days: int
    top_n: int
    top_concentration_bp: int | None
    observed_count: int
    estimated_count: int
    unavailable_count: int
    usable_coverage_bp: int
    top_group_concentration_bp: int | None = None


@dataclass(frozen=True)
class SmartMoneySemanticSummary:
    stock_code: str
    stock_name: str
    decision_date: date
    as_of_date: date | None = None
    net_qty: int = 0
    dominant_side: str = "neutral"
    primary_state: str = "中性"
    semantic_flags: tuple[str, ...] = ()
    confidence_bp: int = 0
    status: str = "neutral"
    quality: str = "missing"
    warnings: tuple[str, ...] = ()
    evidence_lines: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    source_quality_counts: Mapping[str, int] = field(default_factory=dict)
    window_5: SmartMoneyWindowStats | None = None
    window_20: SmartMoneyWindowStats | None = None
    window_60: SmartMoneyWindowStats | None = None
    price_position_bp: int | None = None
    distance_to_60d_high_bp: int | None = None

    def __post_init__(self) -> None:
        if self.as_of_date is None:
            object.__setattr__(self, "as_of_date", self.decision_date)
        if self.evidence_lines and not self.reasons:
            object.__setattr__(self, "reasons", self.evidence_lines)
        elif self.reasons and not self.evidence_lines:
            object.__setattr__(self, "evidence_lines", self.reasons)


@dataclass(frozen=True)
class SmartMoneyDashboardSummary:
    decision_date: date
    as_of_date: date
    priority_summaries: tuple[SmartMoneySemanticSummary, ...]
    risk_summaries: tuple[SmartMoneySemanticSummary, ...]
    quality: str
    warnings: tuple[str, ...] = ()

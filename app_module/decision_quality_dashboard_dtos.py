from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DecisionQualityDashboardRequest:
    review_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    symbol: str | None = None
    portfolio_id: str | None = None
    item_type: str | None = None
    severity: str | None = None
    status: str | None = None
    min_score: int | None = None


@dataclass(frozen=True)
class DecisionQualityDashboardCards:
    decision_quality_score: int = 0
    process_adherence_score: int = 0
    evidence_usage_score: int = 0
    risk_discipline_score: int = 0
    review_completeness_score: int = 0
    open_items: int = 0
    reviewed_items: int = 0
    dismissed_items: int = 0
    warnings_count: int = 0


@dataclass(frozen=True)
class DecisionQualityDashboardRow:
    item_type: str
    symbol: str = ""
    event_date: str = ""
    source_type: str = ""
    severity: str = "medium"
    status: str = "open"
    suggested_review_question: str = ""
    reason_codes: tuple[str, ...] = ()
    related_gap_id: str = ""
    related_decay_id: str = ""
    quality: str = "observed"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionQualityDashboardResult:
    request: DecisionQualityDashboardRequest
    cards: DecisionQualityDashboardCards
    rows: tuple[DecisionQualityDashboardRow, ...] = ()
    empty_state_message: str = ""
    limitations: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    quality_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)

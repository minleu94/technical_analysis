from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


REVIEW_STATUS_NO_DATA = "no_data"
REVIEW_STATUS_INCOMPLETE = "incomplete"
REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
REVIEW_STATUS_READY = "ready"

ITEM_STATUS_OPEN = "open"
ITEM_STATUS_REVIEWED = "reviewed"
ITEM_STATUS_DISMISSED = "dismissed"

ITEM_IGNORED_PORTFOLIO_ALERT = "ignored_portfolio_alert"
ITEM_MANUAL_OVERRIDE_WITHOUT_EVIDENCE = "manual_override_without_evidence"
ITEM_TRADE_WITHOUT_SOURCE_TRACE = "trade_without_source_trace"
ITEM_MISSED_HIGH_QUALITY_SIGNAL = "missed_high_quality_signal"
ITEM_UNREVIEWED_SIGNAL_DECAY = "unreviewed_signal_decay"
ITEM_LARGE_LIVE_RESEARCH_GAP = "large_live_research_gap"
ITEM_LOW_QUALITY_DATA_USED = "low_quality_data_used"
ITEM_REGIME_PROFILE_MISMATCH = "regime_profile_mismatch"


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("JSON payload must be an object")
    return dict(value)


@dataclass(frozen=True)
class DecisionQualityDiagnostic:
    code: str
    severity: str = "warning"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionQualityMetricSet:
    process_adherence_score_bp: int = 0
    evidence_usage_score_bp: int = 0
    risk_discipline_score_bp: int = 0
    review_completeness_score_bp: int = 0
    decision_quality_score_bp: int = 0
    metrics_json: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "process_adherence_score_bp",
            "evidence_usage_score_bp",
            "risk_discipline_score_bp",
            "review_completeness_score_bp",
            "decision_quality_score_bp",
        ):
            value = max(0, min(10000, int(getattr(self, field_name))))
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "metrics_json", _dict(self.metrics_json))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionQualityItem:
    item_id: str
    review_id: str
    item_type: str
    symbol: str = ""
    event_date: str = ""
    decision_date: str = ""
    source_type: str = ""
    source_id: str = ""
    related_trade_id: str = ""
    related_position_id: str = ""
    related_evidence_event_id: str = ""
    related_gap_id: str = ""
    related_decay_id: str = ""
    severity: str = "medium"
    status: str = ITEM_STATUS_OPEN
    reason_codes_json: list[Any] = field(default_factory=list)
    evidence_json: dict[str, Any] = field(default_factory=dict)
    suggested_review_question: str = ""
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes_json", _list(self.reason_codes_json))
        object.__setattr__(self, "evidence_json", _dict(self.evidence_json))
        object.__setattr__(self, "metadata_json", _dict(self.metadata_json))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionQualityActionItem:
    action_item_id: str
    review_id: str
    item_id: str
    description: str
    status: str = "open"
    owner: str = ""
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata_json", _dict(self.metadata_json))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionQualityReview:
    review_id: str
    review_hash: str
    review_period_start: str
    review_period_end: str
    review_type: str
    portfolio_mode_counts_json: dict[str, Any] = field(default_factory=dict)
    evidence_event_count: int = 0
    trade_count: int = 0
    journal_entry_count: int = 0
    portfolio_alert_count: int = 0
    ignored_alert_count: int = 0
    manual_override_count: int = 0
    missed_high_quality_signal_count: int = 0
    unreviewed_decay_candidate_count: int = 0
    unlinked_trade_count: int = 0
    decision_quality_score_bp: int = 0
    process_adherence_score_bp: int = 0
    evidence_usage_score_bp: int = 0
    risk_discipline_score_bp: int = 0
    review_completeness_score_bp: int = 0
    review_status: str = REVIEW_STATUS_NO_DATA
    quality: str = "missing"
    warnings_json: list[Any] = field(default_factory=list)
    diagnostics_json: list[Any] = field(default_factory=list)
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "portfolio_mode_counts_json", _dict(self.portfolio_mode_counts_json))
        object.__setattr__(self, "warnings_json", _list(self.warnings_json))
        object.__setattr__(self, "diagnostics_json", _list(self.diagnostics_json))
        object.__setattr__(self, "metadata_json", _dict(self.metadata_json))
        for field_name in (
            "evidence_event_count",
            "trade_count",
            "journal_entry_count",
            "portfolio_alert_count",
            "ignored_alert_count",
            "manual_override_count",
            "missed_high_quality_signal_count",
            "unreviewed_decay_candidate_count",
            "unlinked_trade_count",
            "decision_quality_score_bp",
            "process_adherence_score_bp",
            "evidence_usage_score_bp",
            "risk_discipline_score_bp",
            "review_completeness_score_bp",
        ):
            object.__setattr__(self, field_name, int(getattr(self, field_name)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionQualitySaveResult:
    review: DecisionQualityReview
    saved: bool
    skipped_duplicate: bool = False
    items_created: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "review": self.review.to_dict(),
            "saved": self.saved,
            "skipped_duplicate": self.skipped_duplicate,
            "items_created": self.items_created,
        }


@dataclass(frozen=True)
class DecisionQualitySummary:
    reviews_count: int = 0
    item_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    review_status_counts: dict[str, int] = field(default_factory=dict)
    average_decision_quality_score_bp: int | None = None
    warnings_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_counts", _dict(self.item_counts))
        object.__setattr__(self, "status_counts", _dict(self.status_counts))
        object.__setattr__(self, "review_status_counts", _dict(self.review_status_counts))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
class LiveResearchGapSourceTrace:
    source_type: str = ""
    source_id: str = ""
    research_run_id: str = ""
    strategy_version_id: str = ""
    recommendation_result_id: str = ""
    evidence_event_id: str = ""
    evidence_outcome_id: str = ""
    match_confidence: str = "none"
    candidate_evidence_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "candidate_evidence_event_ids": list(self.candidate_evidence_event_ids),
        }


@dataclass(frozen=True)
class LiveResearchGapAttribution:
    category: str
    confidence: str = "low"
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveResearchGapDiagnostic:
    code: str
    severity: str = "warning"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveResearchGapLink:
    evidence_event_id: str = ""
    evidence_outcome_id: str = ""
    match_confidence: str = "none"
    candidate_evidence_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_event_id": self.evidence_event_id,
            "evidence_outcome_id": self.evidence_outcome_id,
            "match_confidence": self.match_confidence,
            "candidate_evidence_event_ids": list(self.candidate_evidence_event_ids),
        }


@dataclass(frozen=True)
class LiveResearchGapObservation:
    gap_id: str
    gap_hash: str
    observation_date: str
    position_id: str
    symbol: str
    portfolio_mode: str
    source_type: str
    source_id: str
    research_run_id: str = ""
    strategy_version_id: str = ""
    recommendation_result_id: str = ""
    evidence_event_id: str = ""
    evidence_outcome_id: str = ""
    entry_date: str = ""
    entry_price: str = ""
    current_price_date: str = ""
    current_price: str = ""
    holding_days: int | None = None
    portfolio_return_bp: int | None = None
    research_expected_return_bp: int | None = None
    forward_evidence_return_bp: int | None = None
    benchmark_excess_bp: int | None = None
    industry_excess_bp: int | None = None
    gap_vs_research_bp: int | None = None
    gap_vs_forward_evidence_bp: int | None = None
    gap_vs_benchmark_bp: int | None = None
    condition_status: str = ""
    chip_risk_level: str = ""
    regime_at_entry: str = ""
    regime_current: str = ""
    data_quality: str = "missing"
    warnings_json: list[Any] = field(default_factory=list)
    attribution_json: list[Any] = field(default_factory=list)
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings_json", _list(self.warnings_json))
        object.__setattr__(self, "attribution_json", _list(self.attribution_json))
        object.__setattr__(self, "metadata_json", _dict(self.metadata_json))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveResearchGapSaveResult:
    observation: LiveResearchGapObservation
    saved: bool
    skipped_duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.to_dict(),
            "saved": self.saved,
            "skipped_duplicate": self.skipped_duplicate,
        }


@dataclass(frozen=True)
class LiveResearchGapSummary:
    group_by: str
    group_key: str
    sample_size: int
    mean_portfolio_return_bp: int | None = None
    median_portfolio_return_bp: int | None = None
    mean_gap_vs_research_bp: int | None = None
    mean_gap_vs_forward_evidence_bp: int | None = None
    mean_gap_vs_benchmark_bp: int | None = None
    positive_gap_rate_bp: int | None = None
    negative_gap_rate_bp: int | None = None
    missing_source_trace_count: int = 0
    missing_evidence_count: int = 0
    quality_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)
    summary_status: str = "INSUFFICIENT_SAMPLE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LiveResearchGapDashboardRequest:
    observation_date: str | None = None
    symbol: str | None = None
    portfolio_id: str | None = None
    source_type: str | None = None
    strategy_version_id: str | None = None
    portfolio_mode: str | None = None
    attribution_category: str | None = None
    data_quality: str | None = None


@dataclass(frozen=True)
class LiveResearchGapDashboardCards:
    positions_seen: int = 0
    positions_linked: int = 0
    missing_source_trace: int = 0
    missing_research_run: int = 0
    missing_evidence_event: int = 0
    missing_evidence_outcome: int = 0
    simulated_count: int = 0
    unknown_count: int = 0
    large_gap_count: int = 0
    warnings_count: int = 0


@dataclass(frozen=True)
class LiveResearchGapDashboardRow:
    symbol: str = ""
    portfolio_mode: str = ""
    source_type: str = ""
    source_id: str = ""
    strategy_version_id: str = ""
    entry_date: str = ""
    holding_days: int | None = None
    portfolio_return_bp: int | None = None
    forward_evidence_return_bp: int | None = None
    benchmark_excess_bp: int | None = None
    gap_vs_research_bp: int | None = None
    gap_vs_forward_evidence_bp: int | None = None
    gap_vs_benchmark_bp: int | None = None
    condition_status: str = ""
    chip_risk_level: str = ""
    regime_at_entry: str = ""
    regime_current: str = ""
    attribution_categories: tuple[str, ...] = ()
    match_confidence: str = "none"
    quality: str = "missing"
    warnings: tuple[str, ...] = ()
    evidence_event_id: str = ""
    evidence_outcome_id: str = ""
    research_run_id: str = ""


@dataclass(frozen=True)
class LiveResearchGapDashboardResult:
    request: LiveResearchGapDashboardRequest
    cards: LiveResearchGapDashboardCards
    rows: tuple[LiveResearchGapDashboardRow, ...] = ()
    empty_state_message: str = ""
    limitations: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    quality_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignalDecayDashboardRequest:
    observation_date: str | None = None
    scope_type: str | None = None
    scope_id: str | None = None
    event_type: str | None = None
    event_family: str | None = None
    strategy_version_id: str | None = None
    profile_id: str | None = None
    decay_status: str | None = None
    suggested_lifecycle_action: str | None = None
    confidence: str | None = None
    min_sample_size: int = 10


@dataclass(frozen=True)
class SignalDecayDashboardCards:
    scopes_evaluated: int = 0
    stable_count: int = 0
    watch_count: int = 0
    decaying_count: int = 0
    severe_decay_count: int = 0
    demote_candidate_count: int = 0
    retire_candidate_count: int = 0
    insufficient_sample_count: int = 0
    low_confidence_count: int = 0
    warnings_count: int = 0


@dataclass(frozen=True)
class SignalDecayDashboardRow:
    signal_scope_type: str = ""
    signal_scope_id: str = ""
    sample_size_short: int = 0
    sample_size_long: int = 0
    forward_excess_short_bp: int | None = None
    forward_excess_long_bp: int | None = None
    win_rate_short_bp: int | None = None
    win_rate_long_bp: int | None = None
    mae_short_bp: int | None = None
    mae_long_bp: int | None = None
    live_gap_short_bp: int | None = None
    live_gap_long_bp: int | None = None
    decay_score_bp: int = 0
    decay_status: str = ""
    suggested_lifecycle_action: str = ""
    confidence: str = ""
    quality: str = "missing"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SignalDecayDashboardResult:
    request: SignalDecayDashboardRequest
    cards: SignalDecayDashboardCards
    rows: tuple[SignalDecayDashboardRow, ...] = ()
    empty_state_message: str = ""
    limitations: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    quality_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)

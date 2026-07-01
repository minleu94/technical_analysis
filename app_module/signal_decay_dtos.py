from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DECAY_STATUS_NO_DATA = "no_data"
DECAY_STATUS_INSUFFICIENT_SAMPLE = "insufficient_sample"
DECAY_STATUS_STABLE = "stable"
DECAY_STATUS_WATCH = "watch"
DECAY_STATUS_DECAYING = "decaying"
DECAY_STATUS_SEVERE_DECAY = "severe_decay"

SUGGESTION_NONE = "none"
SUGGESTION_HOLD = "hold"
SUGGESTION_WATCH = "watch"
SUGGESTION_DEMOTE_CANDIDATE = "demote_candidate"
SUGGESTION_RETIRE_CANDIDATE = "retire_candidate"


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
class SignalDecayWindow:
    name: str
    mode: str
    requested_size: int
    actual_size: int
    start_date: str = ""
    end_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalDecayMetricSet:
    mean_benchmark_excess_bp: int | None = None
    median_benchmark_excess_bp: int | None = None
    win_vs_benchmark_rate_bp: int | None = None
    mean_industry_excess_bp: int | None = None
    mean_mae_bp: int | None = None
    mean_live_gap_vs_forward_bp: int | None = None
    mean_live_gap_vs_benchmark_bp: int | None = None
    quality_degraded_ratio_bp: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalDecayDiagnostic:
    code: str
    severity: str = "warning"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalDecaySuggestion:
    action: str = SUGGESTION_NONE
    reason: str = ""
    confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalDecayObservation:
    decay_id: str
    decay_hash: str
    observation_date: str
    signal_scope_type: str
    signal_scope_id: str
    strategy_version_id: str = ""
    profile_id: str = ""
    event_type: str = ""
    event_family: str = ""
    factor_name: str = ""
    window_short: int = 30
    window_long: int = 120
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
    decay_status: str = DECAY_STATUS_NO_DATA
    suggested_lifecycle_action: str = SUGGESTION_NONE
    confidence: str = "low"
    evidence_event_count: int = 0
    gap_observation_count: int = 0
    quality: str = "missing"
    warnings_json: list[Any] = field(default_factory=list)
    diagnostics_json: list[Any] = field(default_factory=list)
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_short", int(self.window_short))
        object.__setattr__(self, "window_long", int(self.window_long))
        object.__setattr__(self, "sample_size_short", int(self.sample_size_short))
        object.__setattr__(self, "sample_size_long", int(self.sample_size_long))
        object.__setattr__(self, "decay_score_bp", int(self.decay_score_bp))
        object.__setattr__(self, "evidence_event_count", int(self.evidence_event_count))
        object.__setattr__(self, "gap_observation_count", int(self.gap_observation_count))
        object.__setattr__(self, "warnings_json", _list(self.warnings_json))
        object.__setattr__(self, "diagnostics_json", _list(self.diagnostics_json))
        object.__setattr__(self, "metadata_json", _dict(self.metadata_json))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalDecaySaveResult:
    observation: SignalDecayObservation
    saved: bool
    skipped_duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.to_dict(),
            "saved": self.saved,
            "skipped_duplicate": self.skipped_duplicate,
        }


@dataclass(frozen=True)
class SignalDecaySummary:
    observations_count: int
    status_counts: dict[str, int] = field(default_factory=dict)
    suggestion_counts: dict[str, int] = field(default_factory=dict)
    confidence_counts: dict[str, int] = field(default_factory=dict)
    quality_counts: dict[str, int] = field(default_factory=dict)
    warnings_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


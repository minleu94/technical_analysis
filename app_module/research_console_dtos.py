"""Research Console 的唯讀、fail-closed application DTO。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping

from app_module.p0_source_control_center import P0SourceControlCenterDTO


@dataclass(frozen=True)
class ResearchConsoleBoundaryDTO:
    formal_oos_allowed: Literal[False] = field(default=False, init=False)
    production_blend_alpha_bp: Literal[0] = field(default=0, init=False)
    production_ml_enabled: Literal[False] = field(default=False, init=False)
    formal_rule_unchanged: Literal[True] = field(default=True, init=False)
    recommendation_path: Literal["rule_only"] = field(default="rule_only", init=False)
    portfolio_path: Literal["rule_only"] = field(default="rule_only", init=False)
    promotion_allowed: Literal[False] = field(default=False, init=False)
    retrain_allowed: Literal[False] = field(default=False, init=False)
    scheduler_allowed: Literal[False] = field(default=False, init=False)
    trading_allowed: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True)
class ResearchPipelineRowDTO:
    component_id: str
    label: str
    identity: str
    status: str
    cutoff: str | None = None
    feature_interval: str | None = None
    label_maturity: str | None = None
    row_count: int | None = None
    eligible_count: int | None = None
    feature_count: int | None = None
    generated_at: str | None = None
    artifact_path: str | None = None
    artifact_hash: str | None = None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.component_id or not self.label or not self.identity or not self.status:
            raise ValueError("pipeline identity, label, and status are required")
        for name in ("row_count", "eligible_count", "feature_count"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")


@dataclass(frozen=True)
class ResearchGateCardDTO:
    gate_id: str
    label: str
    status: str
    detail: str
    artifact_citation: str | None = None


@dataclass(frozen=True)
class ResearchSourceRowDTO:
    source_id: str
    label: str
    lane: Literal["p0", "broker"]
    status: str
    allowed_use: str
    observed_rows: int | None = None
    revision: str | None = None
    owner: str | None = None
    degraded_reason: str | None = None

    def __post_init__(self) -> None:
        if self.observed_rows is not None and (
            isinstance(self.observed_rows, bool)
            or not isinstance(self.observed_rows, int)
            or self.observed_rows < 0
        ):
            raise ValueError("observed_rows must be a non-negative integer or None")


@dataclass(frozen=True)
class ResearchArtifactRowDTO:
    artifact_type: str
    artifact_id: str
    status: str
    citation: str


@dataclass(frozen=True)
class ResearchConsoleDTO:
    overall_status: str
    source_reference: str
    boundary: ResearchConsoleBoundaryDTO
    pipeline: tuple[ResearchPipelineRowDTO, ...] = ()
    gates: tuple[ResearchGateCardDTO, ...] = ()
    sources: tuple[ResearchSourceRowDTO, ...] = ()
    artifacts: tuple[ResearchArtifactRowDTO, ...] = ()
    source_control_center: P0SourceControlCenterDTO | None = None
    frozen_metrics: Mapping[str, object] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.overall_status or not self.source_reference:
            raise ValueError("console status and source reference are required")
        object.__setattr__(self, "frozen_metrics", _freeze_mapping(self.frozen_metrics))


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value

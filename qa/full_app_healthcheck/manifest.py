from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HealthcheckMode(str, Enum):
    QUICK = "quick"
    FULL = "full"
    HIGH_RISK_DRY_RUN = "high-risk-dry-run"


class RiskLevel(str, Enum):
    READ_ONLY = "read-only"
    UI_ONLY = "ui-only"
    DRY_RUN_ONLY = "dry-run-only"
    HIGH_RISK_CANCEL_ONLY = "high-risk-cancel-only"
    WRITES_DATA = "writes-data"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class HealthcheckStep:
    id: str
    title: str
    mode: HealthcheckMode
    workspace: str
    action: str
    risk: RiskLevel = RiskLevel.UI_ONLY
    expected: str = ""
    evidence_kind: str = "text"


@dataclass(frozen=True)
class HealthcheckManifest:
    id: str
    title: str
    modes: tuple[HealthcheckMode, ...]
    steps: tuple[HealthcheckStep, ...]

    def steps_for_mode(self, mode: HealthcheckMode) -> tuple[HealthcheckStep, ...]:
        return tuple(step for step in self.steps if step.mode == mode)

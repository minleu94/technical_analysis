"""Maturity-aware exit effectiveness read model using integer basis points."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ExitEffectivenessObservation:
    event_id: str
    reason_code: str
    maturity_status: str
    action_stage: str
    realized_return_bp: int | None
    post_exit_return_bp: int | None

    def __post_init__(self) -> None:
        if not self.event_id or not self.reason_code:
            raise ValueError("event_id and reason_code are required")
        if self.maturity_status not in {"ready", "pending"}:
            raise ValueError("unsupported maturity_status")
        if self.action_stage not in {"proposal", "human_approved", "closed"}:
            raise ValueError("unsupported action_stage")
        if self.maturity_status == "ready" and self.post_exit_return_bp is None:
            raise ValueError("ready outcome requires post_exit_return_bp")
        for name in ("realized_return_bp", "post_exit_return_bp"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError(f"{name} must be integer bp or None")


@dataclass(frozen=True)
class ExitEffectivenessSlice:
    reason_code: str
    observation_count: int
    ready_count: int
    pending_count: int
    avoided_loss_count: int
    avoided_loss_average_bp: int | None
    early_exit_regret_count: int
    early_exit_regret_average_bp: int | None
    avoided_loss_precision_bp: int | None
    average_realized_return_bp: int | None


@dataclass(frozen=True)
class ExitEffectivenessReport:
    slices: tuple[ExitEffectivenessSlice, ...]
    research_only: bool = True
    investment_effectiveness_claim: bool = False
    auto_exit_allowed: bool = False


class ExitEffectivenessReadModel:
    def build(
        self, *, observations: Iterable[ExitEffectivenessObservation]
    ) -> ExitEffectivenessReport:
        grouped: dict[str, list[ExitEffectivenessObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.reason_code].append(observation)
        slices = tuple(
            self._slice(reason, tuple(grouped[reason])) for reason in sorted(grouped)
        )
        return ExitEffectivenessReport(slices=slices)

    @staticmethod
    def _slice(
        reason_code: str, rows: tuple[ExitEffectivenessObservation, ...]
    ) -> ExitEffectivenessSlice:
        ready = tuple(row for row in rows if row.maturity_status == "ready")
        post_exit_returns = tuple(
            row.post_exit_return_bp
            for row in ready
            if row.post_exit_return_bp is not None
        )
        avoided = tuple(-value for value in post_exit_returns if value < 0)
        regret = tuple(value for value in post_exit_returns if value > 0)
        realized = tuple(row.realized_return_bp for row in ready if row.realized_return_bp is not None)
        return ExitEffectivenessSlice(
            reason_code=reason_code,
            observation_count=len(rows),
            ready_count=len(ready),
            pending_count=len(rows) - len(ready),
            avoided_loss_count=len(avoided),
            avoided_loss_average_bp=sum(avoided) // len(avoided) if avoided else None,
            early_exit_regret_count=len(regret),
            early_exit_regret_average_bp=sum(regret) // len(regret) if regret else None,
            avoided_loss_precision_bp=len(avoided) * 10000 // len(ready) if ready else None,
            average_realized_return_bp=sum(realized) // len(realized) if realized else None,
        )

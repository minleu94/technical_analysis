"""Read-only exit effectiveness projection.

Exit health transitions are proposals.  A proposal is a counterfactual
observation until an append-only Paper ledger proves that the position was
actually closed.  Keeping that distinction in this small read model prevents
research-only proposals from being reported as realised exit performance.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_EXIT_HORIZON_TRADING_DAYS = 5


@dataclass(frozen=True)
class ExitEffectivenessObservation:
    """One immutable exit observation.

    The first six fields are retained for compatibility with the original
    read model. ``post_exit_return_bp`` is the realised exit outcome for a
    ``closed`` row. For a proposal it is interpreted as the legacy spelling
    of ``counterfactual_post_exit_return_bp`` and is never included in actual
    closed metrics.
    """

    event_id: str
    reason_code: str
    maturity_status: str
    action_stage: str
    realized_return_bp: int | None
    post_exit_return_bp: int | None
    counterfactual_post_exit_return_bp: int | None = None
    horizon_trading_days: int = DEFAULT_EXIT_HORIZON_TRADING_DAYS
    policy_id: str = "legacy-unversioned"
    position_id: str | None = None
    stock_code: str | None = None
    decision_date: str | None = None
    exit_date: str | None = None
    outcome_date: str | None = None
    execution_status: str = ""
    limitation_codes: tuple[str, ...] = ()
    transition_hash: str | None = None
    paper_ledger_rows_hash: str | None = None
    price_source_hash: str | None = None
    calendar_source_hash: str | None = None
    observation_hash: str | None = None
    transition_reasons: tuple[str, ...] = ()
    entry_fill_id: str | None = None
    exit_fill_id: str | None = None
    entry_evidence_hash: str | None = None
    exit_evidence_hash: str | None = None
    realized_return_basis: str = "unspecified"

    def __post_init__(self) -> None:
        if not self.event_id or not self.reason_code:
            raise ValueError("event_id and reason_code are required")
        if self.maturity_status not in {"ready", "pending"}:
            raise ValueError("unsupported maturity_status")
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("policy_id is required")
        if self.action_stage not in {"proposal", "human_approved", "closed"}:
            raise ValueError("unsupported action_stage")
        if (
            isinstance(self.horizon_trading_days, bool)
            or not isinstance(self.horizon_trading_days, int)
            or self.horizon_trading_days <= 0
        ):
            raise ValueError("horizon_trading_days must be a positive integer")
        if self.maturity_status == "ready" and (
            self.post_exit_return_bp is None
            and self.counterfactual_post_exit_return_bp is None
        ):
            raise ValueError("ready outcome requires post_exit_return_bp or counterfactual_post_exit_return_bp")
        for name in (
            "realized_return_bp",
            "post_exit_return_bp",
            "counterfactual_post_exit_return_bp",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError(f"{name} must be integer bp or None")
        if self.action_stage == "closed" and self.counterfactual_post_exit_return_bp is not None:
            raise ValueError("closed observation cannot carry a counterfactual return")
        if self.action_stage != "closed" and self.realized_return_bp is not None:
            raise ValueError("non-closed observation cannot carry realised return")
        if self.maturity_status == "pending" and (
            self.post_exit_return_bp is not None
            or self.counterfactual_post_exit_return_bp is not None
        ):
            raise ValueError("pending observation cannot carry a mature return")
        execution_status = self.execution_status
        if not execution_status:
            execution_status = "closed" if self.action_stage == "closed" else "not_executed"
            object.__setattr__(self, "execution_status", execution_status)
        if execution_status not in {
            "not_executed",
            "partially_filled",
            "closed",
            "rejected",
            "ambiguous",
        }:
            raise ValueError("unsupported execution_status")
        if self.action_stage == "closed" and execution_status != "closed":
            raise ValueError("closed observation requires closed execution_status")
        if self.action_stage != "closed" and execution_status == "closed":
            raise ValueError("non-closed observation cannot claim closed execution")
        if not isinstance(self.limitation_codes, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.limitation_codes
        ):
            raise ValueError("limitation_codes must be a tuple of non-empty strings")
        if not isinstance(self.transition_reasons, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.transition_reasons
        ):
            raise ValueError("transition_reasons must be a tuple of non-empty strings")
        if not isinstance(self.realized_return_basis, str) or not self.realized_return_basis.strip():
            raise ValueError("realized_return_basis is required")

    @property
    def is_actual_closed(self) -> bool:
        """Whether this row may contribute to realised metrics."""

        return (
            self.maturity_status == "ready"
            and self.action_stage == "closed"
            and self.execution_status == "closed"
            and not self.limitation_codes
        )

    @property
    def counterfactual_return_bp(self) -> int | None:
        if self.counterfactual_post_exit_return_bp is not None:
            return self.counterfactual_post_exit_return_bp
        if self.action_stage != "closed":
            return self.post_exit_return_bp
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "reason_code": self.reason_code,
            "maturity_status": self.maturity_status,
            "action_stage": self.action_stage,
            "realized_return_bp": self.realized_return_bp,
            "post_exit_return_bp": self.post_exit_return_bp,
            "counterfactual_post_exit_return_bp": self.counterfactual_post_exit_return_bp,
            "horizon_trading_days": self.horizon_trading_days,
            "policy_id": self.policy_id,
            "position_id": self.position_id,
            "stock_code": self.stock_code,
            "decision_date": self.decision_date,
            "exit_date": self.exit_date,
            "outcome_date": self.outcome_date,
            "execution_status": self.execution_status,
            "limitation_codes": list(self.limitation_codes),
            "transition_hash": self.transition_hash,
            "paper_ledger_rows_hash": self.paper_ledger_rows_hash,
            "price_source_hash": self.price_source_hash,
            "calendar_source_hash": self.calendar_source_hash,
            "observation_hash": self.observation_hash,
            "transition_reasons": list(self.transition_reasons),
            "entry_fill_id": self.entry_fill_id,
            "exit_fill_id": self.exit_fill_id,
            "entry_evidence_hash": self.entry_evidence_hash,
            "exit_evidence_hash": self.exit_evidence_hash,
            "realized_return_basis": self.realized_return_basis,
        }


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
    horizon_trading_days: int = DEFAULT_EXIT_HORIZON_TRADING_DAYS
    policy_id: str = "legacy-unversioned"
    actual_closed_count: int = 0
    counterfactual_proposal_count: int = 0
    counterfactual_ready_count: int = 0
    counterfactual_avoided_loss_count: int = 0
    counterfactual_avoided_loss_average_bp: int | None = None
    counterfactual_early_exit_regret_count: int = 0
    counterfactual_early_exit_regret_average_bp: int | None = None
    counterfactual_avoided_loss_precision_bp: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "observation_count": self.observation_count,
            "ready_count": self.ready_count,
            "pending_count": self.pending_count,
            "avoided_loss_count": self.avoided_loss_count,
            "avoided_loss_average_bp": self.avoided_loss_average_bp,
            "early_exit_regret_count": self.early_exit_regret_count,
            "early_exit_regret_average_bp": self.early_exit_regret_average_bp,
            "avoided_loss_precision_bp": self.avoided_loss_precision_bp,
            "average_realized_return_bp": self.average_realized_return_bp,
            "horizon_trading_days": self.horizon_trading_days,
            "policy_id": self.policy_id,
            "actual_closed_count": self.actual_closed_count,
            "counterfactual_proposal_count": self.counterfactual_proposal_count,
            "counterfactual_ready_count": self.counterfactual_ready_count,
            "counterfactual_avoided_loss_count": self.counterfactual_avoided_loss_count,
            "counterfactual_avoided_loss_average_bp": self.counterfactual_avoided_loss_average_bp,
            "counterfactual_early_exit_regret_count": self.counterfactual_early_exit_regret_count,
            "counterfactual_early_exit_regret_average_bp": self.counterfactual_early_exit_regret_average_bp,
            "counterfactual_avoided_loss_precision_bp": self.counterfactual_avoided_loss_precision_bp,
        }


@dataclass(frozen=True)
class ExitEffectivenessReport:
    slices: tuple[ExitEffectivenessSlice, ...]
    research_only: bool = True
    investment_effectiveness_claim: bool = False
    auto_exit_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "slices": [item.to_dict() for item in self.slices],
            "research_only": self.research_only,
            "investment_effectiveness_claim": self.investment_effectiveness_claim,
            "auto_exit_allowed": self.auto_exit_allowed,
        }


class ExitEffectivenessReadModel:
    """Build deterministic, explicitly separated actual/counterfactual slices."""

    def build(
        self, *, observations: Iterable[ExitEffectivenessObservation]
    ) -> ExitEffectivenessReport:
        grouped: dict[tuple[str, int, str], list[ExitEffectivenessObservation]] = defaultdict(list)
        seen: set[tuple[str, int]] = set()
        for observation in observations:
            key = (observation.event_id, observation.horizon_trading_days)
            if key in seen:
                raise ValueError(
                    "duplicate exit observation for event/horizon: "
                    f"{observation.event_id}/{observation.horizon_trading_days}"
                )
            seen.add(key)
            grouped[
                (
                    observation.reason_code,
                    observation.horizon_trading_days,
                    observation.policy_id,
                )
            ].append(
                observation
            )
        slices = tuple(
            self._slice(reason, horizon, policy_id, tuple(grouped[(reason, horizon, policy_id)]))
            for reason, horizon, policy_id in sorted(grouped)
        )
        return ExitEffectivenessReport(slices=slices)

    @staticmethod
    def _slice(
        reason_code: str,
        horizon: int,
        policy_id: str,
        rows: tuple[ExitEffectivenessObservation, ...],
    ) -> ExitEffectivenessSlice:
        actual_ready = tuple(row for row in rows if row.is_actual_closed)
        pending = tuple(row for row in rows if row.maturity_status == "pending")
        counterfactual_ready = tuple(
            row
            for row in rows
            if row.maturity_status == "ready"
            and row.action_stage in {"proposal", "human_approved"}
            and row.counterfactual_return_bp is not None
            and not row.limitation_codes
        )
        actual_returns = tuple(
            row.post_exit_return_bp
            for row in actual_ready
            if row.post_exit_return_bp is not None
        )
        actual_realized_returns = tuple(
            row.realized_return_bp
            for row in actual_ready
            if row.realized_return_bp is not None
        )
        counterfactual_returns = tuple(
            row.counterfactual_return_bp
            for row in counterfactual_ready
            if row.counterfactual_return_bp is not None
        )
        avoided = tuple(-value for value in actual_returns if value < 0)
        regret = tuple(value for value in actual_returns if value > 0)
        cf_avoided = tuple(-value for value in counterfactual_returns if value < 0)
        cf_regret = tuple(value for value in counterfactual_returns if value > 0)
        return ExitEffectivenessSlice(
            reason_code=reason_code,
            observation_count=len(rows),
            ready_count=len(actual_ready),
            pending_count=len(pending),
            avoided_loss_count=len(avoided),
            avoided_loss_average_bp=sum(avoided) // len(avoided) if avoided else None,
            early_exit_regret_count=len(regret),
            early_exit_regret_average_bp=sum(regret) // len(regret) if regret else None,
            avoided_loss_precision_bp=(
                len(avoided) * 10000 // len(actual_ready) if actual_ready else None
            ),
            average_realized_return_bp=(
                sum(actual_realized_returns) // len(actual_realized_returns)
                if actual_realized_returns
                else None
            ),
            horizon_trading_days=horizon,
            policy_id=policy_id,
            actual_closed_count=len(actual_ready),
            counterfactual_proposal_count=sum(
                1 for row in rows if row.action_stage in {"proposal", "human_approved"}
            ),
            counterfactual_ready_count=len(counterfactual_ready),
            counterfactual_avoided_loss_count=len(cf_avoided),
            counterfactual_avoided_loss_average_bp=(
                sum(cf_avoided) // len(cf_avoided) if cf_avoided else None
            ),
            counterfactual_early_exit_regret_count=len(cf_regret),
            counterfactual_early_exit_regret_average_bp=(
                sum(cf_regret) // len(cf_regret) if cf_regret else None
            ),
            counterfactual_avoided_loss_precision_bp=(
                len(cf_avoided) * 10000 // len(counterfactual_ready)
                if counterfactual_ready
                else None
            ),
        )

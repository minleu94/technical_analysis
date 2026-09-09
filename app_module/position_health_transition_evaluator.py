"""Daily, proposal-only position health transition evaluation.

這個模組是 baseline 與既有 health 元件之間的薄 adapter。它不產生
investment thesis、不讀 UI cache、不修改 Paper／Formal／D 槽來源，也不會
自動核准或執行 transition。缺少受治理的 thesis、PIT condition 或 metric 時，
它只會產生可追溯的 WATCH proposal 與 degraded 結果。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app_module.portfolio_condition_monitor import (
    PortfolioConditionResult,
    PortfolioCurrentSnapshot,
)
from app_module.position_health_service import (
    PositionHealthService,
    PositionHealthState,
)
from app_module.position_health_state_machine import (
    PositionHealthMetric,
    PositionHealthStateMachine,
)
from app_module.position_health_transition_repository import (
    PositionHealthTransitionRecord,
    PositionHealthTransitionRepository,
)
from app_module.position_thesis_contract import PositionThesisContract
from app_module.strategy_lifecycle_service import GateStatus


SCHEMA_VERSION = "position-health-transition-evaluation.v1"
DEFAULT_POLICY_HASH = (
    "sha256:" + hashlib.sha256(b"position-health-transition-policy.v1").hexdigest()
)
TAIPEI = ZoneInfo("Asia/Taipei")
_HEALTH_FIELDS = (
    "entry_thesis",
    "invalidation",
    "holding_horizon",
    "review_date",
)
_VERIFIED_LINEAGE_STATUSES = frozenset(
    {
        "same_snapshot_verified",
        "ledger_continuous_no_trade",
        "natural_entry_verified",
        "carried_verified",
    }
)
_STATE_PRIORITY = {
    PositionHealthState.HEALTHY: 0,
    PositionHealthState.WATCH: 1,
    PositionHealthState.REDUCE_CANDIDATE: 2,
    PositionHealthState.EXIT_CANDIDATE: 3,
    PositionHealthState.CLOSED: 4,
}
_VALID_CONDITION_STATUSES = frozenset({"valid", "warning", "invalid"})

@dataclass(frozen=True)
class PITConditionObservation:
    """A condition result plus the source custody needed by a daily evaluator."""

    result: PortfolioConditionResult | None
    current_snapshot: PortfolioCurrentSnapshot | None
    source_id: str
    source_snapshot_hash: str
    as_of_date: str
    available_at: str
    quality: str = "observed"
    source_trace: tuple[str, ...] = ()


@dataclass(frozen=True)
class DailyPositionHealthTransitionRequest:
    """All inputs to one deterministic, proposal-only daily evaluation."""

    decision_date: str
    observed_at: datetime | str
    positions: Sequence[Mapping[str, Any]]
    previous_positions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    thesis_by_position: Mapping[str, PositionThesisContract | None] = field(
        default_factory=dict
    )
    conditions_by_position: Mapping[str, PITConditionObservation | None] = field(
        default_factory=dict
    )
    metrics_by_position: Mapping[str, Sequence[PositionHealthMetric]] = field(
        default_factory=dict
    )
    forward_binding_by_position: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    feedback_status_by_position: Mapping[str, GateStatus | None] = field(
        default_factory=dict
    )
    trading_dates: Sequence[str] | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    policy_hash: str = DEFAULT_POLICY_HASH


class DailyPositionHealthTransitionEvaluator:
    """Combine existing health services without applying any state transition."""

    def __init__(
        self,
        *,
        health_service: PositionHealthService | None = None,
        state_machine: PositionHealthStateMachine | None = None,
        transition_repository: PositionHealthTransitionRepository | None = None,
        policy_hash: str = DEFAULT_POLICY_HASH,
    ) -> None:
        self.health_service = health_service or PositionHealthService()
        self.state_machine = state_machine or PositionHealthStateMachine()
        self.transition_repository = transition_repository
        self.policy_hash = policy_hash

    def evaluate(self, request: DailyPositionHealthTransitionRequest) -> dict[str, Any]:
        """Evaluate one request and return a JSON-serializable receipt.

        Request-level clock or schema failures are ``blocked``. Missing per-position
        evidence is ``degraded`` and remains a WATCH proposal, while preserving a
        previously known more severe state.
        """

        if not isinstance(request, DailyPositionHealthTransitionRequest):
            raise TypeError("request must be DailyPositionHealthTransitionRequest")

        global_blockers: list[str] = []
        global_warnings: list[str] = []
        decision = _parse_date(request.decision_date, "decision_date", global_blockers)
        observed = _parse_observed_at(request.observed_at, global_blockers)
        if observed is not None:
            now = datetime.now(timezone.utc)
            if observed > now:
                global_blockers.append("observed_at_in_future")
            if decision is not None and decision > observed.astimezone(TAIPEI).date():
                global_blockers.append("decision_date_after_observed_date")

        if not isinstance(request.positions, Sequence) or isinstance(
            request.positions, (str, bytes)
        ):
            global_blockers.append("positions_not_sequence")
            positions: tuple[Mapping[str, Any], ...] = ()
        else:
            positions = tuple(
                item for item in request.positions if isinstance(item, Mapping)
            )
            if len(positions) != len(request.positions):
                global_blockers.append("position_payload_not_object")

        if not isinstance(request.provenance, Mapping):
            global_blockers.append("provenance_not_object")
            provenance: Mapping[str, Any] = {}
        else:
            provenance = request.provenance

        policy_hash = str(request.policy_hash or self.policy_hash).strip()
        if not policy_hash:
            global_blockers.append("policy_hash_missing")
            policy_hash = self.policy_hash

        provenance_warnings = _provenance_warnings(provenance)
        global_warnings.extend(provenance_warnings)
        provider_warnings = _string_tuple(provenance.get("source_provider_warnings"))
        global_warnings.extend(provider_warnings)
        provider_blockers = _string_tuple(provenance.get("source_provider_blockers"))
        global_blockers.extend(
            f"input_source_provider_blocked:{item}" for item in provider_blockers
        )

        if global_blockers:
            return self._blocked_result(
                request=request,
                decision_date=request.decision_date,
                observed_at=_iso_observed(observed, request.observed_at),
                blockers=global_blockers,
                warnings=global_warnings,
                provenance=provenance,
            )

        assert decision is not None
        assert observed is not None

        result_positions: list[dict[str, Any]] = []
        any_degraded = bool(global_warnings)
        persistence_blockers: list[str] = []
        for raw_position in positions:
            row, degraded, blockers = self._evaluate_position(
                request=request,
                position=raw_position,
                decision=decision,
                observed=observed,
                provenance=provenance,
                policy_hash=policy_hash,
            )
            result_positions.append(row)
            any_degraded = any_degraded or degraded
            persistence_blockers.extend(blockers)

        if persistence_blockers:
            global_blockers.extend(dict.fromkeys(persistence_blockers))

        status = "blocked" if global_blockers else "degraded" if any_degraded else "passed"
        output: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "decision_date": request.decision_date,
            "observed_at": _iso_observed(observed, request.observed_at),
            "policy_hash": policy_hash,
            "positions_count": len(result_positions),
            "transition_proposals_count": sum(
                1 for item in result_positions if item.get("transition_event") is not None
            ),
            "research_only": True,
            "apply_transition": False,
            "auto_action_allowed": False,
            "broker_execution": False,
            "formal_credit": False,
            "provenance": _jsonable(dict(provenance)),
            "warnings": list(dict.fromkeys(global_warnings)),
            "blockers": list(dict.fromkeys(global_blockers)),
            "positions": result_positions,
        }
        return output

    def _evaluate_position(
        self,
        *,
        request: DailyPositionHealthTransitionRequest,
        position: Mapping[str, Any],
        decision: date,
        observed: datetime,
        provenance: Mapping[str, Any],
        policy_hash: str,
    ) -> tuple[dict[str, Any], bool, list[str]]:
        code = str(position.get("stock_code") or "").strip()
        position_id = _stable_position_id(position)
        lookup_key = position_id or code
        reasons: list[str] = []
        warnings: list[str] = []
        blockers: list[str] = []
        required_human_fields: list[str] = []
        degraded = False

        if not code:
            blockers.append("position_stock_code_missing")
            code = ""
        if not position_id:
            reasons.append("position_identity_missing")
            degraded = True

        lineage_status = str(position.get("entry_lineage_status") or "").strip()
        if lineage_status not in _VERIFIED_LINEAGE_STATUSES:
            reasons.append("position_entry_lineage_unproven")
            degraded = True

        prior_payload = _lookup_mapping(request.previous_positions, lookup_key, code)
        previous_state, previous_state_reason = _read_state(
            prior_payload.get("state") if prior_payload else position.get("state")
        )
        if previous_state_reason:
            reasons.append(previous_state_reason)
            degraded = True

        historical_state = str(
            (prior_payload or {}).get("historical_prior_state")
            or position.get("historical_prior_state")
            or ""
        ).strip()
        if historical_state:
            reasons.append(f"historical_prior_state:{historical_state}")

        # CLOSED is never projected onto an active quantity. Keep the prior state
        # in the audit payload, but evaluate the live row from WATCH.
        if previous_state is PositionHealthState.CLOSED:
            reasons.append("closed_state_with_active_quantity")
            previous_state = PositionHealthState.WATCH
            degraded = True

        source_trace = _string_tuple(position.get("source_trace"))
        snapshot_id = _provenance_snapshot_id(provenance)
        if not source_trace and snapshot_id:
            source_trace = (f"paper_snapshot:{snapshot_id}",)

        forward_binding = _lookup_mapping(
            request.forward_binding_by_position,
            lookup_key,
            code,
        )
        if forward_binding is not None:
            binding_status = str(forward_binding.get("status") or "unknown").strip()
            if binding_status == "bound":
                binding_hash = str(forward_binding.get("binding_file_sha256") or "").strip()
                if binding_hash:
                    source_trace = tuple(
                        dict.fromkeys(
                            (
                                *source_trace,
                                f"forward_position_thesis_binding:{binding_hash}",
                            )
                        )
                    )
            else:
                reasons.append(f"forward_position_thesis_binding_{binding_status}")
                degraded = True

        condition = _lookup_value(request.conditions_by_position, lookup_key, code)
        condition_result: PortfolioConditionResult | None = None
        condition_ready = False
        if condition is None:
            reasons.append("condition_observation_missing")
            degraded = True
        elif not isinstance(condition, PITConditionObservation):
            reasons.append("condition_observation_invalid")
            degraded = True
        else:
            condition_reasons, condition_ready = _validate_condition(
                condition,
                stock_code=code,
                decision=decision,
                observed=observed,
            )
            reasons.extend(condition_reasons)
            blockers.extend(
                _integrity_blockers(
                    condition_reasons,
                    prefixes=(
                        "condition_source_future_dated",
                        "condition_stock_code_mismatch",
                        "condition_status_invalid",
                        "condition_observation_invalid",
                    ),
                )
            )
            if not condition_ready:
                degraded = True
            else:
                condition_result = condition.result
                if condition_result is not None and str(
                    condition_result.status or ""
                ).lower() != "valid":
                    reasons.append(
                        f"condition:{str(condition_result.status or 'unknown').lower()}"
                    )
                source_trace = tuple(
                    dict.fromkeys(
                        (
                            *source_trace,
                            *condition.source_trace,
                            f"condition_source:{condition.source_id}",
                            f"condition_hash:{condition.source_snapshot_hash}",
                        )
                    )
                )

        feedback_status = _lookup_value(
            request.feedback_status_by_position, lookup_key, code
        )
        if feedback_status is not None and not isinstance(feedback_status, GateStatus):
            reasons.append("feedback_status_invalid")
            degraded = True
            feedback_status = None

        try:
            health_result = self.health_service.evaluate(
                stock_code=code,
                condition_result=condition_result,
                feedback_status=feedback_status,
                source_trace=source_trace,
            )
        except (TypeError, ValueError) as exc:
            blockers.append(f"health_service_input_invalid:{type(exc).__name__}")
            health_result = None

        if health_result is not None:
            reasons.extend(health_result.reasons)

        thesis = _lookup_value(request.thesis_by_position, lookup_key, code)
        thesis_ready = False
        thesis_source_type: str | None = None
        thesis_source_actor: str | None = None
        if thesis is None:
            reasons.append("thesis_contract_missing")
            required_human_fields.extend(_HEALTH_FIELDS)
            degraded = True
        elif not isinstance(thesis, PositionThesisContract):
            reasons.append("thesis_contract_unverified")
            required_human_fields.extend(_HEALTH_FIELDS)
            degraded = True
        else:
            thesis_reasons, thesis_ready = _validate_thesis(
                thesis,
                position_id=position_id,
                stock_code=code,
                decision=decision,
            )
            reasons.extend(thesis_reasons)
            blockers.extend(
                _integrity_blockers(
                    thesis_reasons,
                    prefixes=(
                        "thesis_position_id_mismatch",
                        "thesis_stock_code_mismatch",
                        "thesis_future_dated",
                        "thesis_date_invalid",
                    ),
                )
            )
            if not thesis_ready:
                required_human_fields.extend(_HEALTH_FIELDS)
                degraded = True
            else:
                thesis_source_type = thesis.source_type
                thesis_source_actor = thesis.source_actor
                source_trace = tuple(dict.fromkeys((*source_trace, *thesis.source_trace)))

        metrics_value = _lookup_value(request.metrics_by_position, lookup_key, code)
        metrics, metric_reasons, metrics_ready = _validate_metrics(
            metrics_value,
            thesis=thesis if thesis_ready else None,
            decision=decision,
        )
        reasons.extend(metric_reasons)
        blockers.extend(
            _integrity_blockers(
                metric_reasons,
                prefixes=(
                    "metrics_invalid",
                    "metric_unverified",
                    "metric_duplicate:",
                    "metric_date_invalid:",
                    "metric_future_dated:",
                ),
            )
        )
        if not metrics_ready:
            degraded = True

        trading_dates, calendar_reasons, calendar_ready = _validate_calendar(
            request.trading_dates,
            thesis=thesis if thesis_ready else None,
            decision=decision,
        )
        reasons.extend(calendar_reasons)
        blockers.extend(
            _integrity_blockers(
                calendar_reasons,
                prefixes=("official_calendar_invalid",),
            )
        )
        if not calendar_ready:
            degraded = True

        machine_proposal = None
        if thesis_ready:
            try:
                machine_proposal = self.state_machine.evaluate(
                    current_state=previous_state,
                    thesis=thesis,
                    decision_date=request.decision_date,
                    metrics=metrics,
                    trading_dates=trading_dates,
                )
                reasons.extend(machine_proposal.reasons)
                if "time_stop_calendar_incomplete" in machine_proposal.reasons:
                    degraded = True
            except (TypeError, ValueError) as exc:
                blockers.append(f"state_machine_input_invalid:{type(exc).__name__}")

        candidates = [previous_state]
        if health_result is not None:
            candidates.append(health_result.state)
        if machine_proposal is not None:
            candidates.append(machine_proposal.proposed_state)
        # Missing evidence is a watch-level candidate. It must never suppress a
        # known EXIT/REDUCE candidate already returned by another governed source.
        if degraded:
            candidates.append(PositionHealthState.WATCH)
        proposed_state = max(candidates, key=lambda item: _STATE_PRIORITY[item])
        reasons = list(dict.fromkeys(reason for reason in reasons if reason))
        if not reasons and proposed_state is PositionHealthState.HEALTHY:
            reasons.append("position_health_transition_evaluated")

        input_payload = {
            "position": _jsonable(dict(position)),
            "previous": _jsonable(dict(prior_payload or {})),
            "thesis": _jsonable(thesis.to_dict()) if thesis_ready and thesis else None,
            "condition": _jsonable(condition),
            "feedback_status": _jsonable(feedback_status),
            "metrics": _jsonable(metrics),
            "forward_position_thesis_binding": _jsonable(forward_binding),
            "trading_dates": _jsonable(trading_dates),
            "provenance": _jsonable(dict(provenance)),
            "decision_date": decision.isoformat(),
            "policy_hash": policy_hash,
        }
        input_hash = _sha256_json(input_payload)
        transition_event: dict[str, Any] | None = None
        if position_id:
            event_id = _proposal_event_id(
                position_id=position_id,
                decision_date=decision.isoformat(),
                policy_hash=policy_hash,
                input_hash=input_hash,
            )
            transition_event = {
                "event_id": event_id,
                "decision_kind": "proposal",
                "recorded_state": previous_state.value,
                "previous_state": previous_state.value,
                "proposed_state": proposed_state.value,
                "input_hash": input_hash,
                "policy_hash": policy_hash,
                "persistence": "not_requested",
            }
            if self.transition_repository is not None and not blockers:
                try:
                    transition_event["persistence"] = self._persist_proposal(
                        event_id=event_id,
                        position_id=position_id,
                        decision_date=decision.isoformat(),
                        previous_state=previous_state,
                        proposed_state=proposed_state,
                        reasons=tuple(reasons),
                    )
                except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                    blockers.append(f"transition_proposal_persistence_blocked:{type(exc).__name__}")
                    transition_event["persistence"] = "blocked"

        if blockers:
            degraded = True

        row: dict[str, Any] = {
            "position_id": position_id or None,
            "stock_code": code,
            "previous_state": previous_state.value,
            "proposed_state": proposed_state.value,
            "condition_status": (
                "unknown"
                if condition_result is None
                else str(condition_result.status or "unknown").lower()
            ),
            "reasons": reasons,
            "required_human_fields": list(dict.fromkeys(required_human_fields)),
            "thesis_source_type": thesis_source_type,
            "thesis_source_actor": thesis_source_actor,
            # Machine policy contracts can make a proposal deterministic, but
            # they never stand in for a human approval event or enable action.
            "human_approval_required": True,
            "metrics_evidence": [_metric_to_dict(item) for item in metrics],
            "entry_lineage_status": lineage_status or "unproven",
            "forward_position_thesis_binding": (
                None if forward_binding is None else _jsonable(dict(forward_binding))
            ),
            "source_trace": list(source_trace),
            "review_required": bool(
                degraded or proposed_state is not previous_state
            ),
            "transition_event": transition_event,
            "blockers": list(dict.fromkeys(blockers)),
            "warnings": warnings,
            "auto_action_allowed": False,
        }
        return row, degraded, blockers

    def _persist_proposal(
        self,
        *,
        event_id: str,
        position_id: str,
        decision_date: str,
        previous_state: PositionHealthState,
        proposed_state: PositionHealthState,
        reasons: tuple[str, ...],
    ) -> str:
        assert self.transition_repository is not None
        return self.transition_repository.append_proposal_idempotent(
            PositionHealthTransitionRecord.proposal(
                event_id=event_id,
                position_id=position_id,
                decision_date=decision_date,
                previous_state=previous_state,
                proposed_state=proposed_state,
                reasons=reasons,
            )
        )

    @staticmethod
    def _blocked_result(
        *,
        request: DailyPositionHealthTransitionRequest,
        decision_date: str,
        observed_at: str,
        blockers: Sequence[str],
        warnings: Sequence[str],
        provenance: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "decision_date": decision_date,
            "observed_at": observed_at,
            "policy_hash": str(request.policy_hash or DEFAULT_POLICY_HASH),
            "positions_count": 0,
            "transition_proposals_count": 0,
            "research_only": True,
            "apply_transition": False,
            "auto_action_allowed": False,
            "broker_execution": False,
            "formal_credit": False,
            "provenance": _jsonable(dict(provenance)),
            "warnings": list(dict.fromkeys(str(item) for item in warnings)),
            "blockers": list(dict.fromkeys(str(item) for item in blockers)),
            "positions": [],
        }


def evaluate_baseline_file(
    *,
    baseline_path: str | Path,
    output_dir: str | Path,
    observed_at: datetime | str,
    decision_date: str | None = None,
    transition_repository_path: str | Path | None = None,
    policy_hash: str = DEFAULT_POLICY_HASH,
    thesis_registry_path: str | Path | None = None,
    forward_binding_path: str | Path | None = None,
    condition_source_path: str | Path | None = None,
    metrics_source_path: str | Path | None = None,
    policy_source_path: str | Path | None = None,
    calendar_cache_path: str | Path | None = None,
    temporary_closure_path: str | Path | None = None,
    calendar_db_path: str | Path | None = None,
    calendar_start_date: str | None = None,
) -> dict[str, Any]:
    """Evaluate a Paper health baseline through governed optional source adapters.

    It reads the baseline bytes once, verifies the same bytes after parsing, and
    writes only derived evaluator receipts under ``output_dir``.  Optional source
    paths are loaded by ``position_health_source_providers``; absent sources remain
    degraded and supplied integrity failures are blocked before proposal persistence.
    """

    source = Path(baseline_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    try:
        raw = source.read_bytes()
        source_hash = _sha256_bytes(raw)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("health baseline payload must be an object")
        if source.read_bytes() != raw:
            raise ValueError("health baseline changed during read")
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "decision_date": decision_date or "",
            "observed_at": _iso_observed(None, observed_at),
            "policy_hash": policy_hash,
            "positions_count": 0,
            "transition_proposals_count": 0,
            "research_only": True,
            "apply_transition": False,
            "auto_action_allowed": False,
            "broker_execution": False,
            "formal_credit": False,
            "provenance": {"baseline_path": str(source)},
            "warnings": [],
            "blockers": [f"baseline_read_blocked:{type(exc).__name__}"],
            "positions": [],
        }
        return _persist_evaluation_result(result, output=output, decision_date=decision_date)

    effective_date = decision_date or str(
        payload.get("as_of_date") or payload.get("decision_date") or ""
    )
    positions = payload.get("positions")
    if not isinstance(positions, list):
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "decision_date": effective_date,
            "observed_at": _iso_observed(None, observed_at),
            "policy_hash": policy_hash,
            "positions_count": 0,
            "transition_proposals_count": 0,
            "research_only": True,
            "apply_transition": False,
            "auto_action_allowed": False,
            "broker_execution": False,
            "formal_credit": False,
            "provenance": {"baseline_path": str(source), "baseline_sha256": source_hash},
            "warnings": [],
            "blockers": ["health_baseline_positions_missing"],
            "positions": [],
        }
        return _persist_evaluation_result(result, output=output, decision_date=effective_date)

    repository: PositionHealthTransitionRepository | None = None
    if transition_repository_path is not None:
        repository = PositionHealthTransitionRepository(transition_repository_path)
    provenance = dict(payload)
    provenance.update(
        {
            "baseline_path": str(source),
            "baseline_sha256": source_hash,
            "snapshot_id": payload.get("source_snapshot_id"),
            "snapshot_rows_sha256": payload.get("source_snapshot_rows_sha256"),
        }
    )
    request = DailyPositionHealthTransitionRequest(
        decision_date=effective_date,
        observed_at=observed_at,
        positions=tuple(positions),
        thesis_by_position={},
        conditions_by_position={},
        metrics_by_position={},
        trading_dates=None,
        provenance=provenance,
        policy_hash=policy_hash,
    )
    source_bundle = None
    source_paths_configured = any(
        item is not None
        for item in (
            thesis_registry_path,
            forward_binding_path,
            condition_source_path,
            metrics_source_path,
            policy_source_path,
            calendar_cache_path,
        )
    )
    if source_paths_configured:
        from app_module.position_health_source_providers import (
            build_position_health_source_bundle,
        )

        observed_parsed = _parse_observed_at(observed_at, [])
        if observed_parsed is None:
            result = {
                "schema_version": SCHEMA_VERSION,
                "status": "blocked",
                "decision_date": effective_date,
                "observed_at": _iso_observed(None, observed_at),
                "policy_hash": policy_hash,
                "positions_count": 0,
                "transition_proposals_count": 0,
                "research_only": True,
                "apply_transition": False,
                "auto_action_allowed": False,
                "broker_execution": False,
                "formal_credit": False,
                "provenance": provenance,
                "warnings": [],
                "blockers": ["observed_at_invalid_or_naive"],
                "positions": [],
            }
            return _persist_evaluation_result(
                result, output=output, decision_date=effective_date
            )
        source_bundle = build_position_health_source_bundle(
            positions=tuple(positions),
            decision_date=effective_date,
            decision_at=observed_parsed.astimezone(TAIPEI),
            observed_at=observed_parsed,
            thesis_registry_path=thesis_registry_path,
            forward_binding_path=forward_binding_path,
            condition_source_path=condition_source_path,
            metrics_source_path=metrics_source_path,
            policy_source_path=policy_source_path,
            calendar_cache_path=calendar_cache_path,
            temporary_closure_path=temporary_closure_path,
            calendar_db_path=calendar_db_path,
            calendar_start_date=calendar_start_date,
        )
        provenance.update(dict(source_bundle.provenance))
        request = DailyPositionHealthTransitionRequest(
            decision_date=effective_date,
            observed_at=observed_at,
            positions=tuple(positions),
            thesis_by_position=source_bundle.thesis_by_position,
            conditions_by_position=source_bundle.conditions_by_position,
            metrics_by_position=source_bundle.metrics_by_position,
            forward_binding_by_position=source_bundle.forward_binding_by_position,
            trading_dates=source_bundle.trading_dates,
            provenance=provenance,
            # The Health transition policy is a separate identity from the
            # Formal Rule ranking policy.  The latter is retained in source
            # provenance/input_hash and must never silently replace the Health
            # state-machine policy hash.
            policy_hash=policy_hash,
        )
    # ``source_bundle`` is intentionally kept in scope only for the request
    # construction above; the evaluator remains the single status authority.
    result = DailyPositionHealthTransitionEvaluator(
        transition_repository=(
            None
            if source_bundle is not None and source_bundle.blockers
            else repository
        ),
        policy_hash=(
            request.policy_hash
            if source_bundle is not None
            else policy_hash
        ),
    ).evaluate(request)
    result["baseline_path"] = str(source)
    result["baseline_sha256"] = source_hash
    return _persist_evaluation_result(result, output=output, decision_date=effective_date)


def _persist_evaluation_result(
    result: dict[str, Any],
    *,
    output: Path,
    decision_date: str | None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    date_key = str(decision_date or result.get("decision_date") or "unknown").replace("-", "")
    encoded = _canonical_json(result).encode("utf-8")
    dated = output / f"transition_{date_key}.json"
    if dated.exists() and dated.read_bytes() != encoded:
        suffix = hashlib.sha256(encoded).hexdigest()[:16]
        dated = output / f"transition_{date_key}_{suffix}.json"
    if not dated.exists():
        dated.write_bytes(encoded)
    latest = output / "latest.json"
    _atomic_write(latest, result)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "producer": "app_module.position_health_transition_evaluator",
        "status": result.get("status", "blocked"),
        "decision_date": result.get("decision_date"),
        "baseline_path": result.get("baseline_path"),
        "baseline_sha256": result.get("baseline_sha256"),
        "result_path": str(dated),
        "latest_path": str(latest),
        "result_sha256": _sha256_bytes(encoded),
        "warnings": list(result.get("warnings") or []),
        "blockers": list(result.get("blockers") or []),
        "research_only": True,
        "apply_transition": False,
        "auto_action_allowed": False,
        "broker_execution": False,
        "formal_credit": False,
    }
    _atomic_write(output / "latest_status.json", receipt)
    result["result_path"] = str(dated)
    result["latest_path"] = str(latest)
    result["receipt_path"] = str(output / "latest_status.json")
    return result


def _validate_condition(
    condition: PITConditionObservation,
    *,
    stock_code: str,
    decision: date,
    observed: datetime,
) -> tuple[list[str], bool]:
    reasons: list[str] = []
    if not isinstance(condition.result, PortfolioConditionResult) or not isinstance(
        condition.current_snapshot, PortfolioCurrentSnapshot
    ):
        reasons.append("condition_observation_invalid")
    if not str(condition.source_id or "").strip() or not str(
        condition.source_snapshot_hash or ""
    ).strip():
        reasons.append("condition_source_missing")
    if not str(condition.as_of_date or "").strip():
        reasons.append("condition_source_missing")
    else:
        try:
            if date.fromisoformat(str(condition.as_of_date)[:10]) > decision:
                reasons.append("condition_source_future_dated")
        except ValueError:
            reasons.append("condition_observation_invalid")
    try:
        available = _parse_aware_datetime(condition.available_at)
        if available > observed:
            reasons.append("condition_source_future_dated")
    except (TypeError, ValueError):
        reasons.append("condition_observation_invalid")
    if str(condition.quality or "").lower() not in {"observed", "verified"}:
        reasons.append("condition_source_quality_not_observed")
    if isinstance(condition.result, PortfolioConditionResult):
        if condition.result.stock_code != stock_code:
            reasons.append("condition_stock_code_mismatch")
        if str(condition.result.status or "").lower() not in _VALID_CONDITION_STATUSES:
            reasons.append("condition_status_invalid")
    unique = list(dict.fromkeys(reasons))
    return unique, not unique


def _validate_thesis(
    thesis: PositionThesisContract,
    *,
    position_id: str,
    stock_code: str,
    decision: date,
) -> tuple[list[str], bool]:
    reasons: list[str] = []
    if not position_id:
        reasons.append("position_identity_missing")
    elif thesis.position_id != position_id:
        reasons.append("thesis_position_id_mismatch")
    if thesis.stock_code != stock_code:
        reasons.append("thesis_stock_code_mismatch")
    try:
        if date.fromisoformat(thesis.decision_date[:10]) > decision:
            reasons.append("thesis_future_dated")
        if date.fromisoformat(thesis.available_date[:10]) > decision:
            reasons.append("thesis_future_dated")
    except (TypeError, ValueError):
        reasons.append("thesis_date_invalid")
    return list(dict.fromkeys(reasons)), not reasons


def _validate_metrics(
    raw_metrics: object,
    *,
    thesis: PositionThesisContract | None,
    decision: date,
) -> tuple[tuple[PositionHealthMetric, ...], list[str], bool]:
    if thesis is None:
        return (), [], False
    if raw_metrics is None:
        return (), ["metrics_missing"], False
    if not isinstance(raw_metrics, Sequence) or isinstance(raw_metrics, (str, bytes)):
        return (), ["metrics_invalid"], False
    metrics: list[PositionHealthMetric] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for item in raw_metrics:
        if not isinstance(item, PositionHealthMetric):
            reasons.append("metric_unverified")
            continue
        if item.metric_id in seen:
            reasons.append(f"metric_duplicate:{item.metric_id}")
            continue
        seen.add(item.metric_id)
        try:
            available = date.fromisoformat(item.available_date[:10])
        except (TypeError, ValueError):
            reasons.append(f"metric_date_invalid:{item.metric_id}")
            continue
        if available > decision:
            reasons.append(f"metric_future_dated:{item.metric_id}")
        metrics.append(item)
    required = {rule.metric_id for rule in thesis.invalidation_rules}
    if not required.issubset({item.metric_id for item in metrics}):
        reasons.append("metric_missing")
    if any("future_dated" in reason for reason in reasons):
        return tuple(metrics), list(dict.fromkeys(reasons)), False
    return tuple(metrics), list(dict.fromkeys(reasons)), not reasons


def _validate_calendar(
    raw_dates: Sequence[str] | None,
    *,
    thesis: PositionThesisContract | None,
    decision: date,
) -> tuple[tuple[str, ...] | None, list[str], bool]:
    if thesis is None:
        return None, [], False
    if raw_dates is None:
        return None, ["official_calendar_missing"], False
    if isinstance(raw_dates, (str, bytes)):
        return None, ["official_calendar_invalid"], False
    parsed: list[str] = []
    reasons: list[str] = []
    for value in raw_dates:
        try:
            parsed.append(date.fromisoformat(str(value)[:10]).isoformat())
        except (TypeError, ValueError):
            reasons.append("official_calendar_invalid")
    if not parsed:
        reasons.append("official_calendar_invalid")
    # The state machine performs the endpoint coverage check and emits its own
    # reason. Here we only validate that the supplied values are dates.
    del decision
    return tuple(sorted(set(parsed))), list(dict.fromkeys(reasons)), not reasons


def _stable_position_id(position: Mapping[str, Any]) -> str:
    for key in ("position_id", "entry_lineage_id", "lineage_id"):
        value = str(position.get(key) or "").strip()
        if value:
            return value
    return ""


def _read_state(value: object) -> tuple[PositionHealthState, str | None]:
    try:
        return PositionHealthState(str(value).strip().upper()), None
    except (TypeError, ValueError):
        return PositionHealthState.WATCH, "previous_state_invalid"


def _lookup_value(mapping: Mapping[str, Any], primary: str, secondary: str) -> Any:
    if primary and primary in mapping:
        return mapping[primary]
    if secondary and secondary in mapping:
        return mapping[secondary]
    return None


def _lookup_mapping(
    mapping: Mapping[str, Mapping[str, Any]], primary: str, secondary: str
) -> Mapping[str, Any] | None:
    value = _lookup_value(mapping, primary, secondary)
    return value if isinstance(value, Mapping) else None


def _provenance_snapshot_id(provenance: Mapping[str, Any]) -> str:
    return str(
        provenance.get("snapshot_id") or provenance.get("source_snapshot_id") or ""
    ).strip()


def _provenance_warnings(provenance: Mapping[str, Any]) -> list[str]:
    snapshot_id = _provenance_snapshot_id(provenance)
    rows_hash = str(
        provenance.get("snapshot_rows_sha256")
        or provenance.get("source_snapshot_rows_sha256")
        or ""
    ).strip()
    return ["provenance_missing"] if not snapshot_id or not rows_hash else []


def _proposal_event_id(
    *,
    position_id: str,
    decision_date: str,
    policy_hash: str,
    input_hash: str,
) -> str:
    payload = {
        "position_id": position_id,
        "decision_date": decision_date,
        "policy_hash": policy_hash,
        "input_hash": input_hash,
    }
    return "position-health-proposal-" + _sha256_json(payload)[:32]


def _metric_to_dict(metric: PositionHealthMetric) -> dict[str, str]:
    return {
        "metric_id": metric.metric_id,
        "value": str(metric.value),
        "available_date": metric.available_date,
    }


def _integrity_blockers(reasons: Iterable[str], *, prefixes: Sequence[str]) -> list[str]:
    """Promote malformed/future evidence to a blocked result.

    Missing evidence remains a safe degraded WATCH result; a supplied evidence
    item that is malformed, future-dated, or contradicts the live identity is an
    integrity failure and must not produce a proposal for persistence.
    """

    return [
        f"input_integrity_blocked:{reason}"
        for reason in reasons
        if any(reason == prefix or reason.startswith(prefix) for prefix in prefixes)
    ]


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _parse_date(value: object, field_name: str, blockers: list[str]) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        blockers.append(f"{field_name}_invalid")
        return None


def _parse_observed_at(value: datetime | str, blockers: list[str]) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else _parse_aware_datetime(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        blockers.append("observed_at_invalid_or_naive")
        return None


def _parse_aware_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso_observed(parsed: datetime | None, original: object) -> str:
    if parsed is not None:
        return parsed.isoformat()
    return str(original or "")


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _canonical_json(value: object) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonable(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, PositionHealthState):
        return value.value
    if isinstance(value, GateStatus):
        return value.value
    if isinstance(value, PITConditionObservation):
        return {
            "result": _jsonable(value.result),
            "current_snapshot": _jsonable(value.current_snapshot),
            "source_id": value.source_id,
            "source_snapshot_hash": value.source_snapshot_hash,
            "as_of_date": value.as_of_date,
            "available_at": value.available_at,
            "quality": value.quality,
            "source_trace": list(value.source_trace),
        }
    if isinstance(value, PositionHealthMetric):
        return _metric_to_dict(value)
    if isinstance(value, PositionThesisContract):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonable(vars(value))
    return value


def _atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{id(payload)}.tmp")
    try:
        temporary.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


# Imported lazily at the bottom to keep the module import graph clear for mypy
# and to allow the persistence exception tuple to name sqlite3 without widening
# the public API.
import sqlite3  # noqa: E402  (used only in the persistence boundary)

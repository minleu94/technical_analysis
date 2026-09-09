from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

from app_module.portfolio_condition_monitor import (
    PortfolioConditionResult,
    PortfolioCurrentSnapshot,
)
from app_module.position_health_service import PositionHealthState
from app_module.position_health_state_machine import PositionHealthMetric
from app_module.position_health_transition_evaluator import (
    DailyPositionHealthTransitionEvaluator,
    DailyPositionHealthTransitionRequest,
    PITConditionObservation,
    evaluate_baseline_file,
)
from app_module.position_health_transition_repository import (
    PositionHealthTransitionRepository,
)
from app_module.position_thesis_contract import (
    PositionInvalidationRule,
    PositionThesisContract,
)
from app_module.strategy_lifecycle_service import GateStatus


TAIPEI = ZoneInfo("Asia/Taipei")


def _observed() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _request_date(observed: datetime) -> str:
    return observed.astimezone(TAIPEI).date().isoformat()


def _position(*, state: str = "WATCH", position_id: str = "position-2330") -> dict[str, object]:
    return {
        "position_id": position_id,
        "stock_code": "2330",
        "paper_shares": 1_000,
        "state": state,
        "entry_lineage_status": "same_snapshot_verified",
        "source_trace": ["paper_snapshot:paper-main-20260908"],
    }


def _provenance() -> dict[str, str]:
    return {
        "snapshot_id": "paper-main-20260908",
        "snapshot_rows_sha256": "sha256:rows",
        "baseline_sha256": "sha256:baseline",
    }


def _thesis(decision_date: str, *, action: str = "exit") -> PositionThesisContract:
    return PositionThesisContract(
        position_id="position-2330",
        stock_code="2330",
        entry_date=decision_date,
        decision_date=decision_date,
        available_date=decision_date,
        entry_thesis="Human-authored thesis",
        holding_horizon_trading_days=5,
        next_review_date=decision_date,
        source_trace=("manual_thesis:position-2330",),
        invalidation_rules=(
            PositionInvalidationRule(
                metric_id="drawdown_pct",
                operator="gt",
                threshold=Decimal("10"),
                action=action,
            ),
        ),
    )


def _condition(observed: datetime, *, status: str = "valid") -> PITConditionObservation:
    result = PortfolioConditionResult(
        stock_code="2330",
        status=status,
        label="condition",
        source_label="verified-current-condition",
    )
    return PITConditionObservation(
        result=result,
        current_snapshot=PortfolioCurrentSnapshot(
            current_regime="bull",
            current_total_score=Decimal("90"),
            current_price=None,
        ),
        source_id="condition-20260908",
        source_snapshot_hash="sha256:condition",
        as_of_date=observed.astimezone(TAIPEI).date().isoformat(),
        available_at=observed.isoformat(),
        quality="observed",
        source_trace=("condition_observation:20260908",),
    )


def _complete_request(
    *,
    observed: datetime | None = None,
    condition_status: str = "valid",
    metric_value: str = "1",
    action: str = "exit",
    previous_state: str = "HEALTHY",
    repository: PositionHealthTransitionRepository | None = None,
) -> tuple[DailyPositionHealthTransitionEvaluator, DailyPositionHealthTransitionRequest]:
    observed = observed or _observed()
    decision_date = _request_date(observed)
    position = _position(state=previous_state)
    request = DailyPositionHealthTransitionRequest(
        decision_date=decision_date,
        observed_at=observed,
        positions=(position,),
        previous_positions={"position-2330": {"state": previous_state}},
        thesis_by_position={"position-2330": _thesis(decision_date, action=action)},
        conditions_by_position={
            "position-2330": _condition(observed, status=condition_status)
        },
        metrics_by_position={
            "position-2330": (
                PositionHealthMetric(
                    metric_id="drawdown_pct",
                    value=Decimal(metric_value),
                    available_date=decision_date,
                ),
            )
        },
        feedback_status_by_position={"position-2330": GateStatus.PASS},
        trading_dates=(decision_date,),
        provenance=_provenance(),
    )
    return DailyPositionHealthTransitionEvaluator(
        transition_repository=repository
    ), request


def test_complete_inputs_write_proposal_and_are_idempotent(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "transitions.sqlite")
    evaluator, request = _complete_request(repository=repository)

    first = evaluator.evaluate(request)
    second = evaluator.evaluate(request)

    assert first["status"] == "passed"
    assert first["positions"][0]["proposed_state"] == PositionHealthState.HEALTHY.value
    assert first["positions"][0]["transition_event"]["persistence"] == "written"
    assert second["status"] == "passed"
    assert second["positions"][0]["transition_event"]["persistence"] == "idempotent"
    assert len(repository.list_for_position("position-2330")) == 1


def test_machine_policy_thesis_is_traceable_but_remains_proposal_only() -> None:
    evaluator, request = _complete_request()
    machine = replace(
        request.thesis_by_position["position-2330"],
        entry_thesis="machine_policy_candidate:fixture; source-bound observation; no human investment rationale supplied",
        source_type="machine_policy",
        source_actor="forward_position_policy_producer",
    )
    result = evaluator.evaluate(
        replace(request, thesis_by_position={"position-2330": machine})
    )
    row = result["positions"][0]
    assert result["status"] == "passed"
    assert row["thesis_source_type"] == "machine_policy"
    assert row["thesis_source_actor"] == "forward_position_policy_producer"
    assert row["human_approval_required"] is True
    assert row["auto_action_allowed"] is False
    assert row["transition_event"]["decision_kind"] == "proposal"


def test_same_identity_different_input_is_rejected(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "transitions.sqlite")
    evaluator, request = _complete_request(repository=repository, metric_value="1")
    assert evaluator.evaluate(request)["status"] == "passed"

    changed_evaluator, changed = _complete_request(
        repository=repository,
        metric_value="2",
    )
    result = changed_evaluator.evaluate(changed)

    assert result["status"] == "blocked"
    assert "transition_proposal_persistence_blocked:ValueError" in result["blockers"]
    assert result["positions"][0]["transition_event"]["persistence"] == "blocked"
    assert len(repository.list_for_position("position-2330")) == 1


def test_feedback_status_changes_input_hash_and_event_id(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "transitions.sqlite")
    evaluator, request = _complete_request(repository=repository)
    first = evaluator.evaluate(request)

    changed = DailyPositionHealthTransitionRequest(
        **{
            **request.__dict__,
            "feedback_status_by_position": {"position-2330": GateStatus.FAIL},
        }
    )
    result = DailyPositionHealthTransitionEvaluator(
        transition_repository=repository
    ).evaluate(changed)

    first_event = first["positions"][0]["transition_event"]
    changed_event = result["positions"][0]["transition_event"]
    assert first_event["input_hash"] != changed_event["input_hash"]
    assert first_event["event_id"] != changed_event["event_id"]
    assert result["status"] == "blocked"
    assert "transition_proposal_persistence_blocked:ValueError" in result["blockers"]


def test_concurrent_same_payload_is_idempotent(tmp_path: Path) -> None:
    repository_path = tmp_path / "transitions.sqlite"
    _, request = _complete_request(
        repository=PositionHealthTransitionRepository(repository_path)
    )

    def run_once() -> dict[str, object]:
        return DailyPositionHealthTransitionEvaluator(
            transition_repository=PositionHealthTransitionRepository(repository_path)
        ).evaluate(request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: run_once(), (0, 1)))

    assert {item["status"] for item in results} == {"passed"}
    assert {
        item["positions"][0]["transition_event"]["persistence"]
        for item in results
    } == {"written", "idempotent"}
    assert len(
        PositionHealthTransitionRepository(repository_path).list_for_position(
            "position-2330"
        )
    ) == 1


def test_concurrent_different_payload_same_identity_is_rejected(tmp_path: Path) -> None:
    repository_path = tmp_path / "transitions.sqlite"
    _, request_one = _complete_request(metric_value="1")
    _, request_two = _complete_request(metric_value="2")

    def run_once(request: DailyPositionHealthTransitionRequest) -> dict[str, object]:
        return DailyPositionHealthTransitionEvaluator(
            transition_repository=PositionHealthTransitionRepository(repository_path)
        ).evaluate(request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run_once, (request_one, request_two)))

    assert sorted(item["status"] for item in results) == ["blocked", "passed"]
    assert len(
        PositionHealthTransitionRepository(repository_path).list_for_position(
            "position-2330"
        )
    ) == 1


def test_exit_condition_has_priority_over_reduce_candidate() -> None:
    evaluator, request = _complete_request(
        condition_status="invalid",
        metric_value="11",
        action="reduce",
    )

    result = evaluator.evaluate(request)
    row = result["positions"][0]

    assert result["status"] == "passed"
    assert row["proposed_state"] == PositionHealthState.EXIT_CANDIDATE.value
    assert any("condition" in reason for reason in row["reasons"])
    assert "invalidation_triggered:drawdown_pct" in row["reasons"]


def test_missing_thesis_and_condition_is_degraded_watch(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "transitions.sqlite")
    observed = _observed()
    decision_date = _request_date(observed)
    request = DailyPositionHealthTransitionRequest(
        decision_date=decision_date,
        observed_at=observed,
        positions=(_position(state="HEALTHY"),),
        previous_positions={"position-2330": {"state": "HEALTHY"}},
        provenance=_provenance(),
    )
    result = DailyPositionHealthTransitionEvaluator(
        transition_repository=repository
    ).evaluate(request)
    row = result["positions"][0]

    assert result["status"] == "degraded"
    assert row["proposed_state"] == PositionHealthState.WATCH.value
    assert "condition_observation_missing" in row["reasons"]
    assert "thesis_contract_missing" in row["reasons"]
    assert row["transition_event"]["persistence"] == "written"
    assert row["review_required"] is True


def test_known_exit_is_not_suppressed_by_missing_evidence() -> None:
    evaluator, request = _complete_request(previous_state="EXIT_CANDIDATE")
    request = DailyPositionHealthTransitionRequest(
        **{
            **request.__dict__,
            "thesis_by_position": {},
            "conditions_by_position": {},
            "metrics_by_position": {},
            "trading_dates": None,
        }
    )

    row = evaluator.evaluate(request)["positions"][0]
    assert row["previous_state"] == PositionHealthState.EXIT_CANDIDATE.value
    assert row["proposed_state"] == PositionHealthState.EXIT_CANDIDATE.value


def test_future_condition_is_blocked_and_not_persisted(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "transitions.sqlite")
    evaluator, request = _complete_request(repository=repository)
    future_date = (date.fromisoformat(request.decision_date) + timedelta(days=1)).isoformat()
    condition = _condition(request.observed_at if isinstance(request.observed_at, datetime) else _observed())
    future_condition = PITConditionObservation(
        result=condition.result,
        current_snapshot=condition.current_snapshot,
        source_id=condition.source_id,
        source_snapshot_hash=condition.source_snapshot_hash,
        as_of_date=future_date,
        available_at=condition.available_at,
        quality=condition.quality,
        source_trace=condition.source_trace,
    )
    changed = DailyPositionHealthTransitionRequest(
        **{**request.__dict__, "conditions_by_position": {"position-2330": future_condition}}
    )

    result = evaluator.evaluate(changed)
    assert result["status"] == "blocked"
    assert result["positions"][0]["transition_event"]["persistence"] == "not_requested"
    assert repository.list_for_position("position-2330") == ()


def test_future_metric_is_blocked() -> None:
    evaluator, request = _complete_request()
    future_date = (date.fromisoformat(request.decision_date) + timedelta(days=1)).isoformat()
    changed = DailyPositionHealthTransitionRequest(
        **{
            **request.__dict__,
            "metrics_by_position": {
                "position-2330": (
                    PositionHealthMetric(
                        metric_id="drawdown_pct",
                        value=Decimal("1"),
                        available_date=future_date,
                    ),
                )
            },
        }
    )

    result = evaluator.evaluate(changed)
    assert result["status"] == "blocked"
    assert "input_integrity_blocked:metric_future_dated:drawdown_pct" in result["blockers"]


def test_missing_position_identity_is_degraded_without_event() -> None:
    evaluator, request = _complete_request()
    changed_position = dict(request.positions[0])
    changed_position.pop("position_id")
    changed = DailyPositionHealthTransitionRequest(
        **{**request.__dict__, "positions": (changed_position,)}
    )

    result = evaluator.evaluate(changed)
    row = result["positions"][0]
    assert result["status"] == "degraded"
    assert row["position_id"] is None
    assert row["transition_event"] is None
    assert "position_identity_missing" in row["reasons"]


def test_baseline_file_bridge_is_executable_and_degraded_without_sources(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        '{"as_of_date":"2026-09-08","source_snapshot_id":"snapshot-1",'
        '"source_snapshot_rows_sha256":"sha256:rows",'
        '"positions":[{"position_id":"p1","stock_code":"2330",'
        '"paper_shares":1000,"state":"WATCH",'
        '"entry_lineage_status":"same_snapshot_verified"}]}',
        encoding="utf-8",
    )
    output = tmp_path / "transition-output"

    result = evaluate_baseline_file(
        baseline_path=baseline,
        output_dir=output,
        observed_at=_observed(),
        decision_date="2026-09-08",
        transition_repository_path=output / "position_health_transitions.sqlite",
    )

    assert result["status"] == "degraded"
    assert result["positions"][0]["proposed_state"] == PositionHealthState.WATCH.value
    assert (output / "latest.json").exists()
    assert (output / "latest_status.json").exists()
    assert result["positions"][0]["transition_event"]["persistence"] == "written"

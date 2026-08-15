"""Prospective shadow observation and maturity-gate custody.

PFS-08 only audits observations that were captured after a frozen prospective
clock activation.  It never creates observations from historical data, fills a
missing horizon, replays a date, or changes the production calibration.  All
monetary/return values use integer basis points; no floating-point portfolio
calculation is performed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    canonical_json,
    file_sha256,
    payload_hash,
)
from data_module.prospective_formal_clock_activation import (
    DAILY_CAPTURE_SEQUENCE,
    ProspectiveClockActivation,
)


PROSPECTIVE_SHADOW_OBSERVATION_SCHEMA_VERSION = (
    "prospective-formal-shadow-observation.v1"
)
PROSPECTIVE_SHADOW_MATURITY_SCHEMA_VERSION = (
    "prospective-formal-shadow-maturity-report.v1"
)
SHADOW_MATURITY_HORIZONS = (5, 10, 20, 60)
MINIMUM_SHADOW_DAYS = 20
MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON = 20
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")

_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "mode",
        "capture_only",
        "clock_id",
        "clock_manifest_hash",
        "activation_manifest_hash",
        "capture_date",
        "decision_timestamp",
        "previous_trading_day",
        "input_state_date",
        "pit_publication_hash",
        "rule_snapshot_hash",
        "portfolio_transition_hash",
        "inference_artifact_hash",
        "source_lineage_hash",
        "scheduled_sequence",
        "outcome_rows",
        "future_teacher_target_used",
        "same_day_advice_used",
        "replayed",
        "backfilled",
        "synthetic_outcomes_used",
        "secret_values_emitted",
        "observation_hash",
    }
)
_OUTCOME_FIELDS = frozenset(
    {
        "horizon_trading_days",
        "outcome_date",
        "matured_at",
        "realized_return_bp",
        "rebalance_worthwhile",
        "outcome_source_hash",
    }
)


class ProspectiveShadowMaturityError(ValueError):
    """Shadow observation／maturity report 不符合 strict contract。"""


def build_prospective_shadow_observation(
    *,
    activation: ProspectiveClockActivation,
    capture_date: str,
    decision_timestamp: str,
    previous_trading_day: str,
    input_state_date: str,
    pit_publication_hash: str,
    rule_snapshot_hash: str,
    portfolio_transition_hash: str,
    inference_artifact_hash: str,
    source_lineage_hash: str,
    outcome_rows: Sequence[Mapping[str, object]],
    now: datetime,
) -> dict[str, object]:
    """建立一筆 activation 後 complete observation；不接受 future target。"""

    _validate_now(now)
    if not isinstance(activation, ProspectiveClockActivation):
        raise ProspectiveShadowMaturityError("validated activation is required")
    capture_day = _parse_date(capture_date, "capture_date")
    now_taipei = _parse_now(now).astimezone(TAIPEI_TIMEZONE)
    if capture_day < activation.activation_trading_day:
        raise ProspectiveShadowMaturityError("capture_date precedes activation")
    if capture_day > now_taipei.date():
        raise ProspectiveShadowMaturityError("capture_date is in the future")
    decision = _parse_taipei_timestamp(decision_timestamp, "decision_timestamp")
    if decision.date() != capture_day or decision > now_taipei:
        raise ProspectiveShadowMaturityError("decision_timestamp is outside capture boundary")
    if decision.timetz().replace(tzinfo=None) != _clock_decision_time(activation):
        raise ProspectiveShadowMaturityError("decision_timestamp does not match clock decision_time")
    previous = _parse_date(previous_trading_day, "previous_trading_day")
    input_day = _parse_date(input_state_date, "input_state_date")
    if input_day != previous or input_day >= capture_day:
        raise ProspectiveShadowMaturityError("input state must be the T-1 trading day")
    for field_name, value in (
        ("pit_publication_hash", pit_publication_hash),
        ("rule_snapshot_hash", rule_snapshot_hash),
        ("portfolio_transition_hash", portfolio_transition_hash),
        ("inference_artifact_hash", inference_artifact_hash),
        ("source_lineage_hash", source_lineage_hash),
    ):
        _required_hash(value, field_name)
    if not isinstance(outcome_rows, Sequence) or isinstance(outcome_rows, (str, bytes)):
        raise ProspectiveShadowMaturityError("outcome_rows must be an array")
    outcomes = _normalize_outcomes(outcome_rows, capture_day=capture_day, decision=decision, now=now)
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_SHADOW_OBSERVATION_SCHEMA_VERSION,
        "status": "complete",
        "mode": "prospective_formal_simulation",
        "capture_only": True,
        "clock_id": activation.clock_id,
        "clock_manifest_hash": str(activation.payload["clock_manifest_hash"]),
        "activation_manifest_hash": activation.activation_manifest_hash,
        "capture_date": capture_day.isoformat(),
        "decision_timestamp": decision.isoformat(),
        "previous_trading_day": previous.isoformat(),
        "input_state_date": input_day.isoformat(),
        "pit_publication_hash": pit_publication_hash,
        "rule_snapshot_hash": rule_snapshot_hash,
        "portfolio_transition_hash": portfolio_transition_hash,
        "inference_artifact_hash": inference_artifact_hash,
        "source_lineage_hash": source_lineage_hash,
        "scheduled_sequence": list(DAILY_CAPTURE_SEQUENCE),
        "outcome_rows": outcomes,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
        "replayed": False,
        "backfilled": False,
        "synthetic_outcomes_used": False,
        "secret_values_emitted": False,
    }
    observation = {**body, "observation_hash": payload_hash(body)}
    validate_prospective_shadow_observation(observation, activation=activation, now=now)
    return observation


def validate_prospective_shadow_observation(
    observation: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    now: datetime,
) -> tuple[date, tuple[Mapping[str, object], ...]]:
    """驗證單日 observation 的 clock、T-1、outcome 與 no-replay flags。"""

    if set(observation) != _OBSERVATION_FIELDS:
        raise ProspectiveShadowMaturityError("shadow observation fields are invalid")
    if observation.get("schema_version") != PROSPECTIVE_SHADOW_OBSERVATION_SCHEMA_VERSION:
        raise ProspectiveShadowMaturityError("shadow observation schema_version is invalid")
    for field_name, expected in (
        ("status", "complete"),
        ("mode", "prospective_formal_simulation"),
        ("capture_only", True),
        ("clock_id", activation.clock_id),
        ("clock_manifest_hash", activation.payload["clock_manifest_hash"]),
        ("activation_manifest_hash", activation.activation_manifest_hash),
        ("scheduled_sequence", list(DAILY_CAPTURE_SEQUENCE)),
        ("future_teacher_target_used", False),
        ("same_day_advice_used", False),
        ("replayed", False),
        ("backfilled", False),
        ("synthetic_outcomes_used", False),
        ("secret_values_emitted", False),
    ):
        if observation.get(field_name) is not expected if isinstance(expected, bool) else observation.get(field_name) != expected:
            raise ProspectiveShadowMaturityError(
                f"shadow observation {field_name} is unsafe"
            )
    capture_day = _parse_date(observation.get("capture_date"), "capture_date")
    now_taipei = _parse_now(now).astimezone(TAIPEI_TIMEZONE)
    if capture_day < activation.activation_trading_day:
        raise ProspectiveShadowMaturityError("shadow observation precedes activation")
    if capture_day > now_taipei.date():
        raise ProspectiveShadowMaturityError("shadow observation is in the future")
    decision = _parse_taipei_timestamp(observation.get("decision_timestamp"), "decision_timestamp")
    if decision.date() != capture_day or decision > now_taipei:
        raise ProspectiveShadowMaturityError("shadow observation decision boundary is invalid")
    if decision.timetz().replace(tzinfo=None) != _clock_decision_time(activation):
        raise ProspectiveShadowMaturityError("shadow observation decision_time mismatch")
    previous = _parse_date(observation.get("previous_trading_day"), "previous_trading_day")
    input_day = _parse_date(observation.get("input_state_date"), "input_state_date")
    if input_day != previous or input_day >= capture_day:
        raise ProspectiveShadowMaturityError("shadow observation input state is not T-1")
    for field_name in (
        "pit_publication_hash",
        "rule_snapshot_hash",
        "portfolio_transition_hash",
        "inference_artifact_hash",
        "source_lineage_hash",
    ):
        _required_hash(observation.get(field_name), field_name)
    rows = observation.get("outcome_rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ProspectiveShadowMaturityError("shadow observation outcome_rows are invalid")
    outcomes = _normalize_outcomes(rows, capture_day=capture_day, decision=decision, now=now)
    supplied_hash = _required_hash(observation.get("observation_hash"), "observation_hash")
    body = dict(observation)
    body.pop("observation_hash", None)
    if payload_hash(body) != supplied_hash:
        raise ProspectiveShadowMaturityError("shadow observation hash mismatch")
    return capture_day, tuple(outcomes)


def build_prospective_shadow_maturity_report(
    *,
    activation: ProspectiveClockActivation,
    observations: Sequence[Mapping[str, object]],
    now: datetime,
) -> dict[str, object]:
    """彙總 elapsed shadow days 與 matured horizons，缺件時只回報 waiting。"""

    _validate_now(now)
    if not isinstance(activation, ProspectiveClockActivation):
        raise ProspectiveShadowMaturityError("validated activation is required")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise ProspectiveShadowMaturityError("observations must be an array")
    dates: list[str] = []
    observation_hashes: list[str] = []
    maturity: dict[str, dict[str, object]] = {
        str(horizon): {
            "matured_observation_count": 0,
            "matured_capture_dates": [],
            "rebalance_worthwhile_class_counts": {"0": 0, "1": 0},
        }
        for horizon in SHADOW_MATURITY_HORIZONS
    }
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise ProspectiveShadowMaturityError("observation item must be an object")
        capture_day, outcomes = validate_prospective_shadow_observation(
            observation,
            activation=activation,
            now=now,
        )
        capture_text = capture_day.isoformat()
        if dates and capture_text <= dates[-1]:
            raise ProspectiveShadowMaturityError(
                "observations must be unique and sorted by capture_date"
            )
        dates.append(capture_text)
        observation_hashes.append(_required_hash(observation.get("observation_hash"), "observation_hash"))
        for outcome in outcomes:
            horizon = _required_int(
                outcome.get("horizon_trading_days"), "horizon_trading_days"
            )
            target = maturity[str(horizon)]
            target_dates = target["matured_capture_dates"]
            if not isinstance(target_dates, list):  # pragma: no cover - local literal guard
                raise AssertionError("target dates must be a list")
            target_dates.append(capture_text)
            target["matured_observation_count"] = _required_int(
                target.get("matured_observation_count"),
                "matured_observation_count",
            ) + 1
            class_counts = target["rebalance_worthwhile_class_counts"]
            if not isinstance(class_counts, dict):  # pragma: no cover
                raise AssertionError("class counts must be a dict")
            class_key = "1" if outcome["rebalance_worthwhile"] is True else "0"
            class_counts[class_key] = _required_int(
                class_counts.get(class_key), f"class_count_{class_key}"
            ) + 1
    blockers: list[str] = []
    if len(dates) < MINIMUM_SHADOW_DAYS:
        blockers.append(f"shadow_days_insufficient:{len(dates)}/{MINIMUM_SHADOW_DAYS}")
    for horizon in SHADOW_MATURITY_HORIZONS:
        detail = maturity[str(horizon)]
        count = _required_int(
            detail.get("matured_observation_count"), "matured_observation_count"
        )
        if count < MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON:
            blockers.append(
                f"matured_horizon_insufficient:h{horizon}:{count}/{MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON}"
            )
        classes = detail["rebalance_worthwhile_class_counts"]
        if (
            not isinstance(classes, Mapping)
            or _required_int(classes.get("0", 0), "class_count_0") <= 0
            or _required_int(classes.get("1", 0), "class_count_1") <= 0
        ):
            blockers.append(f"rebalance_worthwhile_class_coverage_missing:h{horizon}")
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_SHADOW_MATURITY_SCHEMA_VERSION,
        "status": "maturity_gate_ready_shadow_only" if not blockers else "waiting_for_maturity",
        "mode": "prospective_formal_simulation",
        "capture_only": True,
        "clock_id": activation.clock_id,
        "clock_manifest_hash": str(activation.payload["clock_manifest_hash"]),
        "activation_manifest_hash": activation.activation_manifest_hash,
        "observed_capture_dates": dates,
        "observed_day_count": len(dates),
        "minimum_shadow_days": MINIMUM_SHADOW_DAYS,
        "minimum_matured_observations_per_horizon": MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON,
        "observation_hashes": observation_hashes,
        "horizon_maturity": maturity,
        "blockers": blockers,
        "maturity_gate_pass": not blockers,
        "replay_used": False,
        "backfilled": False,
        "synthetic_outcomes_used": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    return {**body, "report_hash": payload_hash(body)}


def write_immutable_shadow_observation(
    output_path: Path,
    observation: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存單日 observation。"""

    _validate_hash_shape(observation, "observation_hash", "shadow observation")
    return _write_immutable_json(output_path, observation, "observation")


def write_immutable_shadow_maturity_report(
    output_path: Path,
    report: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 maturity report。"""

    _validate_hash_shape(report, "report_hash", "maturity report")
    return _write_immutable_json(output_path, report, "maturity report")


def _normalize_outcomes(
    rows: Sequence[Mapping[str, object]],
    *,
    capture_day: date,
    decision: datetime,
    now: datetime,
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[int] = set()
    now_taipei = _parse_now(now).astimezone(TAIPEI_TIMEZONE)
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _OUTCOME_FIELDS:
            raise ProspectiveShadowMaturityError("outcome row fields are invalid")
        horizon = row.get("horizon_trading_days")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon not in SHADOW_MATURITY_HORIZONS:
            raise ProspectiveShadowMaturityError("outcome horizon is invalid")
        if horizon in seen:
            raise ProspectiveShadowMaturityError("outcome horizon is duplicated")
        seen.add(horizon)
        outcome_day = _parse_date(row.get("outcome_date"), "outcome_date")
        if outcome_day <= capture_day or outcome_day > now_taipei.date():
            raise ProspectiveShadowMaturityError("outcome_date is outside matured boundary")
        matured_at = _parse_taipei_timestamp(row.get("matured_at"), "matured_at")
        if matured_at < decision or matured_at > now_taipei:
            raise ProspectiveShadowMaturityError("matured_at is outside capture boundary")
        realized = row.get("realized_return_bp")
        if isinstance(realized, bool) or not isinstance(realized, int):
            raise ProspectiveShadowMaturityError("realized_return_bp must be an integer")
        worthwhile = row.get("rebalance_worthwhile")
        if not isinstance(worthwhile, bool):
            raise ProspectiveShadowMaturityError("rebalance_worthwhile must be boolean")
        source_hash = _required_hash(row.get("outcome_source_hash"), "outcome_source_hash")
        normalized.append(
            {
                "horizon_trading_days": horizon,
                "outcome_date": outcome_day.isoformat(),
                "matured_at": matured_at.isoformat(),
                "realized_return_bp": realized,
                "rebalance_worthwhile": worthwhile,
                "outcome_source_hash": source_hash,
            }
        )
    return normalized


def _write_immutable_json(output_path: Path, value: Mapping[str, object], label: str) -> str:
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveShadowMaturityError(f"{label} output parent directory must exist")
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(value)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveShadowMaturityError(f"{label} output already exists") from error
    return file_sha256(output)


def _validate_hash_shape(value: Mapping[str, object], field_name: str, label: str) -> None:
    supplied = _required_hash(value.get(field_name), field_name)
    body = dict(value)
    body.pop(field_name, None)
    if payload_hash(body) != supplied:
        raise ProspectiveShadowMaturityError(f"{label} hash mismatch")


def _clock_decision_time(activation: ProspectiveClockActivation) -> time:
    value = activation.payload.get("decision_time")
    if not isinstance(value, str):
        raise ProspectiveShadowMaturityError("clock decision_time is invalid")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveShadowMaturityError("clock decision_time is invalid") from error
    return parsed


def _parse_taipei_timestamp(value: object, field_name: str) -> datetime:
    parsed = _parse_aware_datetime(value, field_name)
    return parsed.astimezone(TAIPEI_TIMEZONE)


def _parse_aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ProspectiveShadowMaturityError(f"{field_name} is invalid") from error
    else:
        raise ProspectiveShadowMaturityError(f"{field_name} must include timezone")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveShadowMaturityError(f"{field_name} must include timezone")
    return parsed


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProspectiveShadowMaturityError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveShadowMaturityError(f"{field_name} is invalid") from error
    if parsed.isoformat() != value:
        raise ProspectiveShadowMaturityError(f"{field_name} must use YYYY-MM-DD")
    return parsed


def _parse_now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveShadowMaturityError("now must include timezone")
    return value


def _validate_now(value: datetime) -> None:
    _parse_now(value)


def _required_hash(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in value[7:]
    ):
        raise ProspectiveShadowMaturityError(f"{field_name} must be sha256")
    return value


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveShadowMaturityError(f"{field_name} must be an integer")
    return value

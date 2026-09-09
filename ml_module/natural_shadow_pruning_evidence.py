"""Read-only natural shadow evidence projection for pruning review.

This module consumes the existing ML shadow sidecar without creating a second
registry or invoking a pruning/promotion action.  It selects the latest
revision for each decision date and observation outcome, counts only complete
natural observations, and emits a hash-bound pending/ready projection that a
review consumer can inspect later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from zoneinfo import ZoneInfo
from data_module.prospective_shadow_maturity import (
    MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON,
    MINIMUM_SHADOW_DAYS,
)


NATURAL_SHADOW_PRUNING_EVIDENCE_SCHEMA_VERSION = (
    "v4-natural-shadow-pruning-evidence.v1"
)
MATURED_HORIZONS = (5, 10, 20, 60)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
_SHA256_PREFIX = "sha256:"
_PRUNING_METRIC_FIELDS = (
    "sample_count",
    "hit_rate_bp",
    "score_monotonic",
    "payoff_ratio_bp",
)


class NaturalShadowPruningEvidenceError(ValueError):
    """Shadow sidecar evidence cannot be safely projected."""


def build_natural_shadow_pruning_evidence(
    sidecar_database_path: Path,
    *,
    as_of_date: date | str,
    expected_model_hash: str | None = None,
    expected_dataset_identity_hash: str | None = None,
    expected_policy_hash: str | None = None,
) -> dict[str, object]:
    """Build a read-only, idempotently reproducible pruning-review projection.

    The sidecar is opened with SQLite ``mode=ro`` and ``query_only``.  A
    record is creditable only when its latest outcome covers all current
    horizons, its observation explicitly allows natural credit, and no replay,
    backfill, or synthetic flag is present.  Missing or partial evidence stays
    in ``pending_observations`` and never becomes a pruning input.
    """

    cutoff = _parse_date(as_of_date, "as_of_date")
    cutoff_instant = _as_of_cutoff_instant(cutoff)
    for field_name, value in (
        ("expected_model_hash", expected_model_hash),
        ("expected_dataset_identity_hash", expected_dataset_identity_hash),
        ("expected_policy_hash", expected_policy_hash),
    ):
        if value is not None:
            _required_hash(value, field_name)
    sidecar = sidecar_database_path.expanduser().resolve()
    if not sidecar.is_file():
        raise NaturalShadowPruningEvidenceError(
            f"shadow sidecar does not exist: {sidecar}"
        )
    source_hash_before = _file_hash(sidecar)
    observations = _read_records(sidecar, "shadow_observations")
    outcomes = _read_records(sidecar, "shadow_outcomes")
    source_hash_after = _file_hash(sidecar)
    if source_hash_before != source_hash_after:
        raise NaturalShadowPruningEvidenceError(
            "shadow sidecar changed during readback"
        )

    latest_observations, unavailable_observations = _latest_by_as_of(
        observations,
        key_name="decision_date",
        label="observation",
        cutoff_instant=cutoff_instant,
    )
    latest_outcomes, unavailable_outcomes = _latest_by_as_of(
        outcomes,
        key_name="observation_hash",
        label="outcome",
        cutoff_instant=cutoff_instant,
    )
    selected_observations = tuple(
        record
        for record in latest_observations.values()
        if _parse_date(record["decision_date"], "observation.decision_date") <= cutoff
    )
    selected_observations = tuple(
        sorted(
            selected_observations,
            key=lambda record: str(record["decision_date"]),
        )
    )
    selected_hashes = tuple(
        _required_hash(record.get("record_hash"), "observation.record_hash")
        for record in selected_observations
    )

    pending: list[dict[str, object]] = []
    matured: list[dict[str, object]] = []
    for observation in selected_observations:
        observation_hash = _required_hash(
            observation.get("record_hash"), "observation.record_hash"
        )
        reasons: list[str] = []
        observation_availability_reason = unavailable_observations.get(
            str(observation["decision_date"])
        )
        if observation_availability_reason == "record_availability_missing":
            reasons.append("observation_available_at_missing")
        elif observation_availability_reason == "record_available_after_as_of_date":
            reasons.append("observation_not_available_at_as_of_date")
        if observation.get("promotion_day_credit_allowed") is not True:
            reasons.append("natural_day_credit_not_allowed")
        for flag_name in ("replayed", "backfilled", "synthetic_outcomes_used"):
            if observation.get(flag_name) is True:
                reasons.append(f"unsafe_{flag_name}")
        identity = _source_identity(observation)
        if identity is None:
            reasons.append("source_model_dataset_policy_identity_missing")
        else:
            model_hash, dataset_hash, policy_hash = identity
            if expected_model_hash is not None and model_hash != expected_model_hash:
                reasons.append("source_model_identity_mismatch")
            if (
                expected_dataset_identity_hash is not None
                and dataset_hash != expected_dataset_identity_hash
            ):
                reasons.append("source_dataset_identity_mismatch")
            if expected_policy_hash is not None and policy_hash != expected_policy_hash:
                reasons.append("source_policy_identity_mismatch")

        outcome = latest_outcomes.get(observation_hash)
        outcome_summary: dict[str, object] | None = None
        if outcome is None:
            reasons.append("matured_outcome_missing")
        else:
            outcome_summary, outcome_reasons = _maturity_summary(
                outcome,
                cutoff=cutoff,
                cutoff_instant=cutoff_instant,
                observation_hash=observation_hash,
            )
            reasons.extend(outcome_reasons)
            outcome_availability_reason = unavailable_outcomes.get(observation_hash)
            if outcome_availability_reason == "record_availability_missing":
                reasons.append("outcome_available_at_missing")
            elif outcome_availability_reason == "record_available_after_as_of_date":
                reasons.append("outcome_not_available_at_as_of_date")

        compact = {
            "decision_date": str(observation["decision_date"]),
            "observation_hash": observation_hash,
            "observation_revision": _required_revision(
                observation.get("revision"), "observation.revision"
            ),
            "custody_hash": _required_hash(
                observation.get("custody_hash"), "observation.custody_hash"
            ),
            "outcome_hash": (
                str(outcome.get("record_hash"))
                if outcome is not None
                else None
            ),
            "reasons": sorted(set(reasons)),
        }
        if outcome_summary is not None:
            compact["horizon_summary"] = outcome_summary
        if reasons:
            pending.append(compact)
            continue
        if outcome_summary is None:  # pragma: no cover - guarded above
            raise AssertionError("matured outcome summary is required")
        compact["model_hash"] = identity[0] if identity is not None else None
        compact["dataset_identity_hash"] = (
            identity[1] if identity is not None else None
        )
        compact["policy_hash"] = identity[2] if identity is not None else None
        compact["pruning_lanes"] = _pruning_lanes(observation)
        matured.append(compact)

    # A pruning review is a single frozen cohort.  Never combine observations
    # from different model/dataset/policy identities merely because each one
    # is individually complete.  Callers may pin an expected identity; when
    # they do not, exactly one identity must still be present.
    matured_identity_keys = {
        (
            str(item["model_hash"]),
            str(item["dataset_identity_hash"]),
            str(item["policy_hash"]),
        )
        for item in matured
    }
    if len(matured_identity_keys) > 1:
        mixed = list(matured)
        matured = []
        for item in mixed:
            pending_item = dict(item)
            pending_item.pop("horizon_summary", None)
            pending_item.pop("model_hash", None)
            pending_item.pop("dataset_identity_hash", None)
            pending_item.pop("policy_hash", None)
            pending_item.pop("pruning_lanes", None)
            pending_item["reasons"] = ["source_identity_cohort_mixed"]
            pending.append(pending_item)

    horizon_counts = {str(horizon): 0 for horizon in MATURED_HORIZONS}
    class_counts = {
        str(horizon): {"0": 0, "1": 0} for horizon in MATURED_HORIZONS
    }
    for item in matured:
        summary = item.get("horizon_summary")
        if not isinstance(summary, Mapping):
            continue
        for horizon in MATURED_HORIZONS:
            detail = summary.get(str(horizon))
            if not isinstance(detail, Mapping) or detail.get("complete") is not True:
                continue
            horizon_counts[str(horizon)] += 1
            classes = detail.get("actual_downside_class_counts")
            if isinstance(classes, Mapping):
                for class_key in ("0", "1"):
                    class_counts[str(horizon)][class_key] += _required_nonnegative_int(
                        classes.get(class_key, 0),
                        f"class_count_{horizon}_{class_key}",
                    )

    maturity_blockers: list[str] = []
    if len(matured) < MINIMUM_SHADOW_DAYS:
        maturity_blockers.append(
            f"natural_shadow_days_insufficient:{len(matured)}/{MINIMUM_SHADOW_DAYS}"
        )
    for horizon in MATURED_HORIZONS:
        count = horizon_counts[str(horizon)]
        if count < MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON:
            maturity_blockers.append(
                f"matured_horizon_insufficient:h{horizon}:{count}/"
                f"{MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON}"
            )
        classes = class_counts[str(horizon)]
        if classes["0"] <= 0 or classes["1"] <= 0:
            maturity_blockers.append(
                f"actual_downside_class_coverage_missing:h{horizon}"
            )

    pending_slices, review_inputs = _build_pruning_projection(matured)
    blockers = [*maturity_blockers]
    for item in pending:
        raw_reasons = item.get("reasons")
        if not isinstance(raw_reasons, Sequence) or isinstance(raw_reasons, (str, bytes)):
            raise AssertionError("pending observation reasons must be a sequence")
        blockers.extend(
            f"{item['decision_date']}:{reason}"
            for reason in raw_reasons
        )
    if maturity_blockers:
        status = "pending_maturity"
    elif pending_slices:
        status = "pending_pruning_metrics"
        blockers.append("pruning_metrics_incomplete")
    else:
        status = "ready_for_pruning_review"

    latest_outcome_hashes = tuple(
        _required_hash(item.get("record_hash"), "outcome.record_hash")
        for item in latest_outcomes.values()
        if _required_hash(item.get("observation_hash"), "outcome.observation_hash")
        in selected_hashes
    )
    body: dict[str, object] = {
        "schema_version": NATURAL_SHADOW_PRUNING_EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "as_of_date": cutoff.isoformat(),
        "source": {
            "sidecar_database_path": str(sidecar),
            "sidecar_file_hash": source_hash_after,
            "read_only": True,
            "query_only": True,
            "latest_observation_count": len(selected_observations),
            "latest_outcome_count": len(latest_outcome_hashes),
            "source_record_digest": _payload_hash(
                {
                    "observation_hashes": list(selected_hashes),
                    "outcome_hashes": sorted(latest_outcome_hashes),
                }
            ),
        },
        "observation_count": len(selected_observations),
        "matured_observation_count": len(matured),
        "pending_observation_count": len(pending),
        "matured_observation_hashes": [item["observation_hash"] for item in matured],
        "pending_observations": pending,
        "matured_horizon_counts": horizon_counts,
        "actual_downside_class_counts": class_counts,
        "minimum_natural_shadow_days": MINIMUM_SHADOW_DAYS,
        "minimum_matured_observations_per_horizon": (
            MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON
        ),
        "maturity_blockers": sorted(set(maturity_blockers)),
        "pending_pruning_slices": pending_slices,
        "pruning_review_inputs": review_inputs,
        "pruning_boundary": {
            "evidence_only": True,
            "apply_action": False,
            "review_required": True,
            "promotion_eligible": False,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
        },
    }
    return {**body, "evidence_hash": _payload_hash(body)}


def write_natural_shadow_pruning_evidence(
    output_path: Path,
    evidence: Mapping[str, object],
) -> str:
    """Create-only write; an exact replay is idempotent, a changed replay fails."""

    _validate_evidence_hash(evidence)
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise NaturalShadowPruningEvidenceError(
            "pruning evidence output parent directory must exist"
        )
    encoded = _canonical_json(dict(evidence)).encode("utf-8")
    if output.exists():
        if output.read_bytes() == encoded:
            return "idempotent"
        raise NaturalShadowPruningEvidenceError(
            "pruning evidence output conflict"
        )
    # Stage and fsync the complete bytes before publishing a hard link.  A
    # process crash during the write therefore leaves only an orphaned temp
    # file, never a partial immutable destination that would poison retries.
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".nse-",
        suffix=".tmp",
        dir=str(output.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError:
            if output.read_bytes() == encoded:
                return "idempotent"
            raise NaturalShadowPruningEvidenceError(
                "pruning evidence output conflict"
            )
    finally:
        if temporary.exists():
            temporary.unlink()
    return "inserted"


def _build_pruning_projection(
    matured: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_slice: dict[str, list[dict[str, object]]] = {}
    missing_lane_observations: list[dict[str, object]] = []
    for observation in matured:
        decision_date = str(observation["decision_date"])
        observation_hash = str(observation["observation_hash"])
        lanes = observation.get("pruning_lanes")
        if not isinstance(lanes, Sequence) or isinstance(lanes, (str, bytes)):
            missing_lane_observations.append(
                {
                    "slice_id": f"observation:{observation_hash}",
                    "matured_observation_count": 1,
                    "reason": "pruning_lanes_missing_or_invalid",
                }
            )
            continue
        valid_lane_count = 0
        for lane in lanes:
            if not isinstance(lane, Mapping):
                continue
            slice_id = str(lane.get("slice_id", ""))
            if not slice_id:
                continue
            valid_lane_count += 1
            metrics = lane.get("metrics")
            entry: dict[str, object] = {
                "decision_date": decision_date,
                "observation_hash": observation_hash,
                "metrics": dict(metrics) if isinstance(metrics, Mapping) else None,
                "metrics_complete": _metrics_complete(metrics),
            }
            by_slice.setdefault(slice_id, []).append(entry)
        if valid_lane_count == 0:
            missing_lane_observations.append(
                {
                    "slice_id": f"observation:{observation_hash}",
                    "matured_observation_count": 1,
                    "reason": "pruning_lanes_missing_or_invalid",
                }
            )

    pending: list[dict[str, object]] = list(missing_lane_observations)
    review_inputs: list[dict[str, object]] = []
    for slice_id in sorted(by_slice):
        entries = by_slice[slice_id]
        complete = all(bool(entry["metrics_complete"]) for entry in entries)
        summary = {
            "slice_id": slice_id,
            "matured_observation_count": len(entries),
            "metrics_complete": complete,
            "observations": entries,
        }
        if complete:
            review_inputs.append(summary)
        else:
            pending.append(
                {
                    "slice_id": slice_id,
                    "matured_observation_count": len(entries),
                    "reason": "pruning_metrics_missing_or_invalid",
                }
            )
    return pending, review_inputs


def _pruning_lanes(observation: Mapping[str, object]) -> list[dict[str, object]]:
    raw_lanes = observation.get("lanes")
    if not isinstance(raw_lanes, Sequence) or isinstance(raw_lanes, (str, bytes)):
        return []
    result: list[dict[str, object]] = []
    for index, raw_lane in enumerate(raw_lanes):
        if not isinstance(raw_lane, Mapping):
            continue
        alpha = raw_lane.get("alpha_bp")
        slice_id = raw_lane.get("slice_id")
        if slice_id is None and isinstance(alpha, int) and not isinstance(alpha, bool):
            slice_id = f"alpha:{alpha}"
        if slice_id is None:
            slice_id = f"lane:{index}"
        metrics = raw_lane.get("pruning_metrics", raw_lane.get("lane_metrics"))
        result.append(
            {
                "slice_id": str(slice_id),
                "alpha_bp": alpha,
                "metrics": dict(metrics) if isinstance(metrics, Mapping) else None,
            }
        )
    return result


def _maturity_summary(
    outcome: Mapping[str, object],
    *,
    cutoff: date,
    cutoff_instant: datetime,
    observation_hash: str,
) -> tuple[dict[str, object], list[str]]:
    """Summarise the current outcome contract without manufacturing labels.

    The live collector stores one ``downside_outcomes`` row per symbol and
    horizon.  Older fixtures used one row per horizon with ``matured_at`` and
    ``rebalance_worthwhile``; accepting that shape keeps replay tests useful,
    while the emitted summary names the current ``actual_downside`` label.
    """

    reasons: list[str] = []
    if outcome.get("observation_hash") != observation_hash:
        reasons.append("outcome_observation_identity_mismatch")
    if outcome.get("status") != "matured_all_horizons":
        reasons.append("outcome_not_matured_all_horizons")
    completed = outcome.get("completed_horizons_trading_sessions")
    if not isinstance(completed, Sequence) or isinstance(completed, (str, bytes)):
        reasons.append("completed_horizons_missing")
        completed_values: set[int] = set()
    else:
        completed_values = {
            value
            for value in completed
            if isinstance(value, int) and not isinstance(value, bool)
        }
        if tuple(completed) != MATURED_HORIZONS:
            reasons.append("completed_horizons_incomplete")

    summary: dict[str, object] = {}
    raw_rows = outcome.get("downside_outcomes", ())
    rows = (
        raw_rows
        if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes))
        else ()
    )
    by_horizon: dict[int, list[Mapping[str, object]]] = {}
    seen_symbol_horizons: set[tuple[str, int]] = set()
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            reasons.append("outcome_row_invalid")
            continue
        horizon = raw_row.get("horizon_trading_sessions")
        if (
            not isinstance(horizon, int)
            or isinstance(horizon, bool)
            or horizon not in MATURED_HORIZONS
        ):
            reasons.append("outcome_horizon_invalid")
            continue
        symbol = raw_row.get("symbol")
        if isinstance(symbol, str) and symbol:
            identity = (symbol, horizon)
            if identity in seen_symbol_horizons:
                reasons.append(f"outcome_symbol_horizon_duplicated:{symbol}:h{horizon}")
            seen_symbol_horizons.add(identity)
        by_horizon.setdefault(horizon, []).append(raw_row)

    for horizon in MATURED_HORIZONS:
        horizon_rows = by_horizon.get(horizon, [])
        if not horizon_rows:
            reasons.append(f"outcome_horizon_missing:h{horizon}")
            summary[str(horizon)] = {
                "complete": False,
                "row_count": 0,
                "actual_downside_class_counts": {"0": 0, "1": 0},
            }
            continue
        classes = {"0": 0, "1": 0}
        horizon_valid = True
        available_at_values: list[datetime] = []
        for row in horizon_rows:
            try:
                available_at = _outcome_row_available_at(
                    row,
                    f"outcome.h{horizon}.available_at",
                )
            except NaturalShadowPruningEvidenceError:
                raise
            available_at_values.append(available_at)
            if available_at.astimezone(timezone.utc) > cutoff_instant:
                reasons.append(f"outcome_matures_after_as_of_date:h{horizon}")
                horizon_valid = False
            actual_downside = row.get("actual_downside")
            if (
                isinstance(actual_downside, bool)
                or not isinstance(actual_downside, int)
                or actual_downside not in {0, 1}
            ):
                worthwhile = row.get("rebalance_worthwhile")
                if isinstance(worthwhile, bool):
                    actual_downside = 0 if worthwhile else 1
                else:
                    reasons.append(f"outcome_class_invalid:h{horizon}")
                    horizon_valid = False
                    continue
            classes[str(actual_downside)] += 1
        complete = (
            horizon in completed_values
            and horizon_valid
            and bool(available_at_values)
        )
        summary[str(horizon)] = {
            "complete": complete,
            "row_count": len(horizon_rows),
            "available_at": max(available_at_values).isoformat(),
            "actual_downside_class_counts": classes,
        }
    latest_used_date = outcome.get("latest_used_date")
    if latest_used_date is not None:
        if _parse_date(latest_used_date, "outcome.latest_used_date") > cutoff:
            reasons.append("outcome_latest_used_date_after_as_of_date")
    return summary, sorted(set(reasons))


def _read_records(path: Path, table_name: str) -> tuple[dict[str, object], ...]:
    if table_name not in {"shadow_observations", "shadow_outcomes"}:
        raise AssertionError("unsupported sidecar table")
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            cursor = connection.execute(
                f"SELECT * FROM {table_name} ORDER BY rowid"  # noqa: S608
            )
            rows = cursor.fetchall()
            columns = tuple(description[0] for description in cursor.description or ())
    except sqlite3.OperationalError as error:
        raise NaturalShadowPruningEvidenceError(
            f"shadow sidecar table unavailable: {table_name}"
        ) from error
    records: list[dict[str, object]] = []
    for row in rows:
        row_map = dict(zip(columns, row))
        raw_payload = row_map.get("payload_json")
        if not isinstance(raw_payload, str):
            raise NaturalShadowPruningEvidenceError(
                f"{table_name} payload_json is invalid"
            )
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as error:
            raise NaturalShadowPruningEvidenceError(
                f"{table_name} payload_json is not JSON"
            ) from error
        if not isinstance(payload, dict):
            raise NaturalShadowPruningEvidenceError(
                f"{table_name} payload must be an object"
            )
        _validate_record_hash(payload, f"{table_name}.record_hash")
        for field_name in ("record_hash", "revision", "custody_hash"):
            if str(payload.get(field_name)) != str(row_map.get(field_name)):
                raise NaturalShadowPruningEvidenceError(
                    f"{table_name} row metadata mismatch: {field_name}"
                )
        identity_field = (
            "decision_date" if table_name == "shadow_observations" else "observation_hash"
        )
        if str(payload.get(identity_field)) != str(row_map.get(identity_field)):
            raise NaturalShadowPruningEvidenceError(
                f"{table_name} row metadata mismatch: {identity_field}"
            )
        records.append(payload)
    return tuple(records)


def _latest_by_as_of(
    records: Sequence[Mapping[str, object]],
    *,
    key_name: str,
    label: str,
    cutoff_instant: datetime,
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    """Select the highest revision that was available at the as-of cutoff.

    A later revision must not retroactively replace an earlier revision when
    the later bytes were emitted after the requested cutoff.  If a key has no
    verifiably available revision, the latest record is returned with its key
    in ``unavailable`` so the caller can retain it as pending evidence.
    """

    grouped: dict[str, list[dict[str, object]]] = {}
    for raw_record in records:
        record = dict(raw_record)
        key = record.get(key_name)
        if not isinstance(key, str) or not key:
            raise NaturalShadowPruningEvidenceError(
                f"{label}.{key_name} is invalid"
            )
        _required_revision(record.get("revision"), f"{label}.revision")
        grouped.setdefault(key, []).append(record)

    latest: dict[str, dict[str, object]] = {}
    unavailable: dict[str, str] = {}
    for key, candidates in grouped.items():
        by_revision: dict[int, dict[str, object]] = {}
        for record in candidates:
            revision = _required_revision(
                record.get("revision"), f"{label}.revision"
            )
            existing = by_revision.get(revision)
            if existing is not None and record.get("record_hash") != existing.get(
                "record_hash"
            ):
                raise NaturalShadowPruningEvidenceError(
                    f"{label} has contradictory same-revision records: {key}"
                )
            by_revision[revision] = record
        eligible_records: list[dict[str, object]] = []
        for record in by_revision.values():
            available_at = _record_available_at(record, label=label)
            if (
                available_at is not None
                and available_at.astimezone(timezone.utc) <= cutoff_instant
            ):
                eligible_records.append(record)
        eligible = tuple(eligible_records)
        if eligible:
            latest[key] = max(
                eligible,
                key=lambda record: _required_revision(
                    record.get("revision"), f"{label}.revision"
                ),
            )
        else:
            latest[key] = max(
                by_revision.values(),
                key=lambda record: _required_revision(
                    record.get("revision"), f"{label}.revision"
                ),
            )
            unavailable[key] = (
                "record_available_after_as_of_date"
                if any(
                    _record_available_at(record, label=label) is not None
                    for record in by_revision.values()
                )
                else "record_availability_missing"
            )
    return latest, unavailable


def _record_available_at(
    record: Mapping[str, object],
    *,
    label: str,
) -> datetime | None:
    """Return the record's persisted availability clock when one exists."""

    values: list[datetime] = []
    for field_name in ("emitted_at", "available_at"):
        value = record.get(field_name)
        if value is not None:
            values.append(_parse_datetime(value, f"{label}.{field_name}"))
    if label == "outcome":
        raw_rows = record.get("downside_outcomes", ())
        rows = (
            raw_rows
            if isinstance(raw_rows, Sequence)
            and not isinstance(raw_rows, (str, bytes))
            else ()
        )
        for row in rows:
            if not isinstance(row, Mapping):
                raise NaturalShadowPruningEvidenceError(
                    "outcome downside row is invalid"
                )
            values.append(
                _outcome_row_available_at(
                    row,
                    "outcome.available_at",
                )
            )
    return max(values) if values else None


def _outcome_row_available_at(
    row: Mapping[str, object],
    field_name: str,
) -> datetime:
    value = row.get("available_at")
    if value is None:
        value = row.get("matured_at")
    return _parse_datetime(value, field_name)


def _as_of_cutoff_instant(cutoff: date) -> datetime:
    """Use the inclusive end of the explicit Asia/Taipei as-of date."""

    return datetime.combine(
        cutoff,
        time.max,
        tzinfo=TAIPEI_TIMEZONE,
    ).astimezone(timezone.utc)


def _source_identity(record: Mapping[str, object]) -> tuple[str, str, str] | None:
    custody = record.get("custody")
    if not isinstance(custody, Mapping):
        return None
    model_hash = custody.get("model_hash")
    dataset_hash = custody.get("dataset_identity_hash")
    policy_hash = custody.get("policy_hash")
    if (
        not _is_sha256(model_hash)
        or not _is_sha256(dataset_hash)
        or not _is_sha256(policy_hash)
    ):
        return None
    return str(model_hash), str(dataset_hash), str(policy_hash)


def _metrics_complete(metrics: object) -> bool:
    if not isinstance(metrics, Mapping):
        return False
    if set(metrics) < set(_PRUNING_METRIC_FIELDS):
        return False
    sample_count = metrics.get("sample_count")
    hit_rate = metrics.get("hit_rate_bp")
    payoff = metrics.get("payoff_ratio_bp")
    return (
        isinstance(sample_count, int)
        and not isinstance(sample_count, bool)
        and sample_count > 0
        and isinstance(hit_rate, int)
        and not isinstance(hit_rate, bool)
        and isinstance(metrics.get("score_monotonic"), bool)
        and isinstance(payoff, int)
        and not isinstance(payoff, bool)
    )


def _validate_record_hash(record: Mapping[str, object], field_name: str) -> str:
    supplied = _required_hash(record.get("record_hash"), field_name)
    body = dict(record)
    body.pop("record_hash", None)
    if _payload_hash(body) != supplied:
        raise NaturalShadowPruningEvidenceError(f"{field_name} does not match payload")
    return supplied


def _validate_evidence_hash(evidence: Mapping[str, object]) -> str:
    supplied = _required_hash(evidence.get("evidence_hash"), "evidence_hash")
    body = dict(evidence)
    body.pop("evidence_hash", None)
    if _payload_hash(body) != supplied:
        raise NaturalShadowPruningEvidenceError("pruning evidence hash mismatch")
    return supplied


def _parse_date(value: object, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise NaturalShadowPruningEvidenceError(f"{field_name} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise NaturalShadowPruningEvidenceError(f"{field_name} is invalid") from error


def _parse_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise NaturalShadowPruningEvidenceError(f"{field_name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise NaturalShadowPruningEvidenceError(f"{field_name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NaturalShadowPruningEvidenceError(f"{field_name} must include timezone")
    return parsed


def _required_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NaturalShadowPruningEvidenceError(f"{field_name} must be non-negative integer")
    return value


def _required_revision(value: object, field_name: str) -> int:
    revision = _required_nonnegative_int(value, field_name)
    if revision < 1:
        raise NaturalShadowPruningEvidenceError(f"{field_name} must be positive integer")
    return revision


def _required_hash(value: object, field_name: str) -> str:
    if not _is_sha256(value):
        raise NaturalShadowPruningEvidenceError(f"{field_name} must be sha256")
    return str(value)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == len(_SHA256_PREFIX) + 64
        and value.startswith(_SHA256_PREFIX)
        and all(char in "0123456789abcdef" for char in value[len(_SHA256_PREFIX) :])
    )


def _file_hash(path: Path) -> str:
    return f"{_SHA256_PREFIX}{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _payload_hash(value: object) -> str:
    return f"{_SHA256_PREFIX}{hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "MATURED_HORIZONS",
    "NATURAL_SHADOW_PRUNING_EVIDENCE_SCHEMA_VERSION",
    "NaturalShadowPruningEvidenceError",
    "build_natural_shadow_pruning_evidence",
    "write_natural_shadow_pruning_evidence",
]

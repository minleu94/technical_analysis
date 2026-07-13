"""Historical replay 的唯讀 rehearsal artifact 投影。"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Mapping

from app_module.evidence_rehearsal_dtos import RehearsalArtifact


def canonical_payload_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class HistoricalReplayRehearsalAdapter:
    """將既有 historical replay 結果投影為不可變的 rehearsal metadata。"""

    def project(
        self,
        replay_summary: Mapping[str, object],
        *,
        decision_date: str,
        rollback_reference: str,
    ) -> tuple[RehearsalArtifact, ...]:
        projection_date = _require_date(decision_date, "decision_date")
        if not rollback_reference.strip():
            raise ValueError("rollback_reference must not be empty")
        days = replay_summary.get("days", ())
        if not isinstance(days, list):
            raise ValueError("replay_summary.days must be a list")
        return tuple(
            self._project_day(
                replay_summary,
                day,
                projection_date=projection_date,
                rollback_reference=rollback_reference,
            )
            for day in days
            if isinstance(day, Mapping)
        )

    def _project_day(
        self,
        replay_summary: Mapping[str, object],
        day: Mapping[str, object],
        *,
        projection_date: date,
        rollback_reference: str,
    ) -> RehearsalArtifact:
        decision_date = str(day.get("decision_date") or projection_date.isoformat())
        if _require_date(decision_date, "day.decision_date") != projection_date:
            raise ValueError("day.decision_date must match decision_date")
        as_of_date = _optional_string(day, replay_summary, "as_of_date")
        available_date = _optional_string(day, replay_summary, "available_date")
        if as_of_date is not None:
            _require_date(as_of_date, "as_of_date")
        available = _require_date(available_date, "available_date") if available_date is not None else None
        parent_ids = _parent_ids(day)
        diagnostics = _diagnostics(day)
        future_blocked = available is not None and available > projection_date
        missing_state = "missing" if any("missing" in item for item in diagnostics) else None
        canonical_payload: dict[str, object] = {
            "replay_run_id": str(replay_summary.get("replay_run_id") or ""),
            "decision_date": decision_date,
        }
        for field_name, value in (
            ("as_of_date", as_of_date),
            ("available_date", available_date),
            ("source_version", _optional_string(day, replay_summary, "source_version")),
            ("data_quality", _optional_string(day, replay_summary, "data_quality")),
            ("missing_state", missing_state),
        ):
            if value is not None:
                canonical_payload[field_name] = value
        if parent_ids:
            canonical_payload["parent_artifact_ids"] = parent_ids
        if diagnostics:
            canonical_payload["diagnostics"] = diagnostics
        for field_name in ("score_effectiveness_rows", "benchmark_diagnostics"):
            if field_name in day:
                canonical_payload[field_name] = day[field_name]
        content_hash = canonical_payload_hash(canonical_payload)
        return RehearsalArtifact(
            artifact_id=f"historical-replay:{canonical_payload['replay_run_id']}:{decision_date}",
            decision_date=decision_date,
            available_date=decision_date if future_blocked or available_date is None else available_date,
            tier="historical_replay_candidate",
            as_of_date=as_of_date,
            parent_artifact_ids=parent_ids,
            source_version=_optional_string(day, replay_summary, "source_version"),
            data_quality=_optional_string(day, replay_summary, "data_quality"),
            missing_state=missing_state,
            content_hash=content_hash,
            current_status="future_blocked" if future_blocked else "projected",
            effectiveness_denominator_included=not future_blocked,
            diagnostics=diagnostics,
            canonical_payload=canonical_payload,
            rollback_reference=rollback_reference,
        )


def _parent_ids(day: Mapping[str, object]) -> tuple[str, ...]:
    values: list[object] = []
    for key in ("source_ids", "sources"):
        value = day.get(key, ())
        if isinstance(value, (list, tuple)):
            values.extend(value)
    selected = day.get("selected_recommendation_result_id")
    if selected:
        values.append(selected)
    evidence_ids = day.get("evidence_ids", ())
    if isinstance(evidence_ids, (list, tuple)):
        values.extend(evidence_ids)
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _diagnostics(day: Mapping[str, object]) -> tuple[str, ...]:
    values: list[object] = []
    for key in ("diagnostics", "benchmark_diagnostics"):
        value = day.get(key, ())
        if isinstance(value, (list, tuple)):
            values.extend(value)
    return tuple(str(value) for value in values if str(value))


def _optional_string(
    day: Mapping[str, object],
    replay_summary: Mapping[str, object],
    field_name: str,
) -> str | None:
    value = day.get(field_name, replay_summary.get(field_name))
    if value is None or not str(value):
        return None
    return str(value)


def _require_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an ISO date") from error

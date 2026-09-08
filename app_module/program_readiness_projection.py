"""唯讀載入 ``program-readiness.v1`` 的 UI 投影。

整體 readiness 報告由 ``scripts/inspect_program_readiness.py`` 產生，這個
模組只接受呼叫端明確指定的 artifact 路徑，並把各 lane 的摘要投影給 UI。
它不掃描資料目錄、不呼叫網路、不建立 SQLite，也不會因為顯示狀態而授予
任何 scheduler、formal 或 broker 權限。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any, cast


PROGRAM_READINESS_SCHEMA = "program-readiness.v1"
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024

PROGRAM_READINESS_LANE_ORDER: tuple[str, ...] = (
    "p0",
    "evidence",
    "paper",
    "formal_ml",
    "runtime",
    "performance",
    "update_history",
)

PROGRAM_READINESS_LANE_LABELS: dict[str, str] = {
    "p0": "P0 來源",
    "evidence": "Evidence",
    "paper": "Paper Portfolio",
    "formal_ml": "Formal／ML",
    "runtime": "Runtime",
    "performance": "效能／容量",
    "update_history": "更新歷史",
}

_ROUTE_PROBE_STATUS_TOKENS = frozenset(
    {
        "observed",
        "failed",
        "official_no_data",
        "date_mismatch",
        "no_accepted_rows",
        "schema_mismatch",
        "not_usable",
        "not_attempted",
    }
)

_BOUNDARY_DEFAULTS: dict[str, bool] = {
    "read_only": True,
    "writes_allowed": False,
    "broker_order_allowed": False,
    "formal_oos_allowed": False,
    "production_scheduler_allowed": False,
    "historical_replay_backfill_allowed": False,
}


def load_program_readiness(
    path: Path | None,
    *,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    freshness_reference_paths: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Load and safely project one explicit readiness artifact.

    Missing or malformed artifacts are returned as visible fail-closed payloads
    rather than raising into the whole Data Update page.  A valid artifact is
    deliberately reduced to lane-level fields; arbitrary nested ``details``
    are not copied into the UI model.
    """

    if path is None:
        return _empty_payload("not_configured", "program_readiness_path_not_configured")

    resolved_path = Path(path).expanduser().resolve()
    if not resolved_path.is_file():
        return _empty_payload(
            "missing", f"program_readiness_artifact_missing:{resolved_path}"
        )

    try:
        safe_max_bytes = max(1, int(max_bytes))
    except (TypeError, ValueError):
        safe_max_bytes = MAX_ARTIFACT_BYTES
    try:
        if resolved_path.stat().st_size > safe_max_bytes:
            raise ValueError("program readiness artifact exceeds bounded size")
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _empty_payload(
            "invalid",
            f"program_readiness_artifact_invalid:{type(exc).__name__}:{exc}",
            path=resolved_path,
        )

    if not isinstance(raw, Mapping):
        return _empty_payload(
            "invalid",
            "program_readiness_artifact_root_not_object",
            path=resolved_path,
        )
    if raw.get("schema_version") != PROGRAM_READINESS_SCHEMA:
        return _empty_payload(
            "invalid",
            f"program_readiness_schema_unsupported:{raw.get('schema_version')}",
            path=resolved_path,
        )
    projected = _project_payload(raw, resolved_path)
    projected["diagnostics"] = _append_staleness_diagnostics(
        projected.get("diagnostics"),
        readiness_path=resolved_path,
        freshness_reference_paths=freshness_reference_paths,
    )
    return projected


def _append_staleness_diagnostics(
    diagnostics: object,
    *,
    readiness_path: Path,
    freshness_reference_paths: Sequence[Path] | None,
) -> list[str]:
    """Expose an older explicit readiness artifact without auto-selecting another.

    The Data Update UI can supply only the status artifacts it already reads.
    A newer reference mtime is a bounded hint that the readiness projection may
    be historical; it never changes lane status and never triggers discovery or
    replacement of the configured artifact.
    """

    result = [str(item).strip() for item in diagnostics if str(item).strip()] if isinstance(diagnostics, list) else []
    if not freshness_reference_paths:
        return result[:8]
    try:
        readiness_mtime = readiness_path.stat().st_mtime
    except OSError:
        return result[:8]
    for raw_reference in freshness_reference_paths:
        try:
            reference_path = Path(raw_reference).expanduser().resolve()
            if not reference_path.is_file():
                continue
            if reference_path.stat().st_mtime > readiness_mtime + 1.0:
                label = reference_path.name or str(reference_path)
                result.append(f"program_readiness_artifact_older_than_reference:{label}")
        except (OSError, TypeError, ValueError):
            continue
    return list(dict.fromkeys(result))[:8]


def _empty_payload(
    status: str,
    diagnostic: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": PROGRAM_READINESS_SCHEMA,
        "status": str(status or "invalid").strip().lower() or "invalid",
        "path": str(path) if path is not None else None,
        "generated_at": None,
        "workstreams": {},
        "lane_order": list(PROGRAM_READINESS_LANE_ORDER),
        "boundary": dict(_BOUNDARY_DEFAULTS),
        "diagnostics": [str(diagnostic)],
        "read_only": True,
        "writes_allowed": False,
    }


def _project_payload(payload: Mapping[str, Any], path: Path) -> dict[str, Any]:
    raw_workstreams = payload.get("workstreams")
    workstreams = raw_workstreams if isinstance(raw_workstreams, Mapping) else {}
    raw_order = payload.get("execution_order")
    execution_rows = (
        raw_order if isinstance(raw_order, list) else []
    )

    projected_workstreams: dict[str, dict[str, Any]] = {}
    for lane in PROGRAM_READINESS_LANE_ORDER:
        raw_lane = workstreams.get(lane)
        if isinstance(raw_lane, Mapping):
            projected_workstreams[lane] = _project_lane(lane, raw_lane)

    # Older artifacts may only contain the ordered execution list.  Keep the
    # lane visible without treating a missing workstream as healthy.
    for raw_lane in execution_rows:
        if not isinstance(raw_lane, Mapping):
            continue
        lane = str(raw_lane.get("lane") or "").strip()
        if lane not in PROGRAM_READINESS_LANE_ORDER or lane in projected_workstreams:
            continue
        projected_workstreams[lane] = _project_lane(lane, raw_lane)

    boundary = dict(_BOUNDARY_DEFAULTS)
    raw_boundary = payload.get("boundary")
    if isinstance(raw_boundary, Mapping):
        for key in boundary:
            if isinstance(raw_boundary.get(key), bool):
                boundary[key] = bool(raw_boundary[key])

    diagnostics = _string_list(payload.get("diagnostics"), limit=8)
    return {
        "schema_version": PROGRAM_READINESS_SCHEMA,
        "status": _status_token(payload.get("status")),
        "path": str(path),
        "generated_at": str(payload.get("generated_at") or "").strip() or None,
        "workstreams": projected_workstreams,
        "lane_order": list(PROGRAM_READINESS_LANE_ORDER),
        "boundary": boundary,
        "diagnostics": diagnostics,
        "read_only": True,
        "writes_allowed": False,
    }


def _project_lane(lane: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "status": _status_token(payload.get("status")),
        "blockers": _string_list(payload.get("blockers"), limit=8),
        "next_actions": _string_list(payload.get("next_actions"), limit=3),
        "external_input_required": payload.get("external_input_required") is True,
    }
    metrics = _project_lane_metrics(lane, payload)
    if metrics:
        projected["metrics"] = metrics
    return projected


def _project_lane_metrics(lane: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a tiny allowlisted progress summary for the UI.

    The readiness artifact contains large diagnostic payloads.  The UI should
    still be able to answer "how far along is this lane?" without receiving
    arbitrary nested details or paths.  Only bounded counters/status tokens are
    copied here; this projection never changes gate decisions.
    """

    details = payload.get("details")
    if not isinstance(details, Mapping):
        return {}
    metrics: dict[str, Any] = {}

    if lane == "p0":
        _copy_nonnegative_int(details, "source_count", metrics)
        _copy_nonnegative_int(details, "accepted_count", metrics)
        _copy_nonnegative_int(details, "limited_count", metrics)
        projection = details.get("projection")
        if isinstance(projection, Mapping):
            _copy_nonnegative_int(projection, "p0_source_count", metrics)
            _copy_nonnegative_int(projection, "accepted_count", metrics)
            _copy_nonnegative_int(projection, "limited_count", metrics)
            machine_counts = projection.get("machine_status_counts")
            if isinstance(machine_counts, Mapping):
                for raw_name in ("verified", "degraded", "failed", "missing"):
                    value = machine_counts.get(raw_name)
                    if _is_nonnegative_int(value):
                        metrics[f"machine_{raw_name}_count"] = cast(int, value)
            rows = projection.get("rows")
            if isinstance(rows, (list, tuple)):
                route_count = 0
                route_attempted = 0
                route_status_counts: dict[str, int] = {}
                for row in rows:
                    if not isinstance(row, Mapping):
                        continue
                    route_statuses = row.get("route_probe_statuses")
                    if not isinstance(route_statuses, (list, tuple)):
                        continue
                    for route in route_statuses:
                        if not isinstance(route, Mapping):
                            continue
                        if route_count >= 4096:
                            break
                        route_count += 1
                        status = str(route.get("status") or "unknown").strip().lower()
                        if status not in _ROUTE_PROBE_STATUS_TOKENS:
                            status = "unknown"
                        if status != "not_attempted":
                            route_attempted += 1
                        route_status_counts[status] = route_status_counts.get(status, 0) + 1
                if route_count:
                    metrics["route_count"] = route_count
                    metrics["route_attempted_count"] = route_attempted
                    for status, count in sorted(route_status_counts.items()):
                        metrics[f"route_{status}_count"] = count

    elif lane == "evidence":
        readiness = details.get("readiness")
        if isinstance(readiness, Mapping):
            items = readiness.get("items")
            if isinstance(items, (list, tuple)):
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    item_id = str(item.get("item_id") or "").strip()
                    if item_id == "weekly_history":
                        _copy_nonnegative_int(item, "observed_count", metrics, "weekly_observed_count")
                        _copy_nonnegative_int(item, "required_count", metrics, "weekly_required_count")
                        evidence = item.get("evidence")
                        if isinstance(evidence, Mapping):
                            pending_periods = evidence.get("pending_collection_periods")
                            if isinstance(pending_periods, (list, tuple)):
                                # 只投影 bounded 計數，不把 sidecar 期別、路徑或任意
                                # nested payload 帶進 UI；pending 不會被當成 Gate credit。
                                pending_count = sum(
                                    1
                                    for pending in pending_periods[:4096]
                                    if isinstance(pending, Mapping)
                                )
                                metrics["weekly_pending_count"] = pending_count
                    elif item_id == "multi_day_dry_run":
                        _copy_nonnegative_int(item, "observed_count", metrics, "dry_run_observed_count")
                        _copy_nonnegative_int(item, "required_count", metrics, "dry_run_required_count")
            if isinstance(readiness.get("formal_credit_authorized"), bool):
                metrics["formal_credit_authorized"] = bool(readiness["formal_credit_authorized"])

    elif lane == "paper":
        readiness = details.get("readiness")
        if isinstance(readiness, Mapping):
            for key in (
                "snapshot_count",
                "benchmark_observation_count",
                "cost_record_count",
                "filled_event_count",
                "partial_fill_event_count",
                "rejected_event_count",
                "override_event_count",
            ):
                _copy_nonnegative_int(readiness, key, metrics)
            for key in ("weekly_report_status", "cost_ledger_status", "latest_status"):
                _copy_short_status(readiness, key, metrics)

    elif lane == "formal_ml":
        readiness = details.get("readiness")
        if isinstance(readiness, Mapping):
            for key in (
                "ready_input_count",
                "machine_verified_input_count",
                "machine_candidate_input_count",
                "formal_consumer_compatible_count",
                "missing_input_count",
                "unknown_input_count",
                "invalid_input_count",
                "input_count",
            ):
                _copy_nonnegative_int(readiness, key, metrics)
            _copy_short_status(readiness, "ready_input_ratio", metrics)
            _copy_short_status(readiness, "status", metrics, "readiness_status")

    elif lane == "runtime":
        readiness = details.get("readiness")
        if isinstance(readiness, Mapping):
            _copy_short_status(readiness, "overall_state", metrics)
            _copy_short_status(readiness, "write_probe", metrics)

    elif lane == "performance":
        for key in ("parallelism_enabled", "single_writer_required"):
            value = details.get(key)
            if isinstance(value, bool):
                metrics[key] = bool(value)
        owner_packet = details.get("owner_packet")
        if isinstance(owner_packet, Mapping):
            _copy_short_status(owner_packet, "status", metrics, "owner_packet_status")
            for key in ("review_lane_count", "pending_lane_count", "observed_lane_count"):
                _copy_nonnegative_int(owner_packet, key, metrics)
            for key in ("owner_role_present", "reviewer_role_present", "candidate_only", "write_performed", "destructive_action_performed"):
                value = owner_packet.get(key)
                if isinstance(value, bool):
                    metrics[key] = bool(value)
        artifacts = details.get("artifacts")
        if isinstance(artifacts, Mapping):
            for artifact_name in (
                "technical",
                "technical_batch",
                "technical_write",
                "technical_worker",
                "broker",
                "ml_direct_chain",
                "technical_canary",
            ):
                artifact = artifacts.get(artifact_name)
                if isinstance(artifact, Mapping):
                    _copy_short_status(artifact, "status", metrics, f"{artifact_name}_status")

    elif lane == "update_history":
        for key in ("terminal_record_count", "unique_run_count", "size_bytes"):
            _copy_nonnegative_int(details, key, metrics)
        for key in ("retention_status", "freshness_status"):
            _copy_short_status(details, key, metrics)
        scheduler = details.get("scheduled_task_status")
        if isinstance(scheduler, Mapping):
            _copy_nonnegative_int(scheduler, "available_count", metrics, "scheduled_available_count")
            _copy_nonnegative_int(scheduler, "task_count", metrics, "scheduled_task_count")

    return metrics


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _copy_nonnegative_int(
    source: Mapping[str, Any],
    source_key: str,
    target: dict[str, Any],
    target_key: str | None = None,
) -> None:
    value = source.get(source_key)
    if _is_nonnegative_int(value):
        target[target_key or source_key] = cast(int, value)


def _copy_short_status(
    source: Mapping[str, Any],
    source_key: str,
    target: dict[str, Any],
    target_key: str | None = None,
) -> None:
    value = source.get(source_key)
    if isinstance(value, str):
        text = value.strip()
        if text and len(text) <= 96:
            target[target_key or source_key] = text


def _status_token(value: Any) -> str:
    return str(value or "unknown").strip().lower() or "unknown"


def _string_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
        if len(result) >= max(0, int(limit)):
            break
    return result


__all__ = [
    "MAX_ARTIFACT_BYTES",
    "PROGRAM_READINESS_LANE_LABELS",
    "PROGRAM_READINESS_LANE_ORDER",
    "PROGRAM_READINESS_SCHEMA",
    "load_program_readiness",
]

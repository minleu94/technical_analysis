"""唯讀載入 ``program-readiness.v1`` 的 UI 投影。

整體 readiness 報告由 ``scripts/inspect_program_readiness.py`` 產生，這個
模組只接受呼叫端明確指定的 artifact 路徑，並把各 lane 的摘要投影給 UI。
它不掃描資料目錄、不呼叫網路、不建立 SQLite，也不會因為顯示狀態而授予
任何 scheduler、formal 或 broker 權限。
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any


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
    return _project_payload(raw, resolved_path)


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
            projected_workstreams[lane] = _project_lane(raw_lane)

    # Older artifacts may only contain the ordered execution list.  Keep the
    # lane visible without treating a missing workstream as healthy.
    for raw_lane in execution_rows:
        if not isinstance(raw_lane, Mapping):
            continue
        lane = str(raw_lane.get("lane") or "").strip()
        if lane not in PROGRAM_READINESS_LANE_ORDER or lane in projected_workstreams:
            continue
        projected_workstreams[lane] = _project_lane(raw_lane)

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


def _project_lane(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": _status_token(payload.get("status")),
        "blockers": _string_list(payload.get("blockers"), limit=8),
        "next_actions": _string_list(payload.get("next_actions"), limit=3),
        "external_input_required": payload.get("external_input_required") is True,
    }


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

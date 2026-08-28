"""資料更新排程的 append-only 狀態歷史。

``latest_status.json`` 只適合提供目前 read model；這個模組另外保存每次排程
嘗試的 bounded JSONL record，讓 UI 可以區分「本輪」與「歷史曾經成功」。
它不讀取網路、不修改市場資料，也不會把檔案 mtime 當成執行完成時間。
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


UPDATE_STATUS_HISTORY_SCHEMA = "data-update-status-history.v1"
MAX_STATUS_HISTORY_BYTES = 8 * 1024 * 1024
DEFAULT_STATUS_HISTORY_LIMIT = 32

_FAILURE_STATUSES = {"failed", "failure", "error", "blocked"}


def _normalise_status(value: Any) -> str:
    return str(value or "unknown").strip().lower() or "unknown"


def _text(value: Any, *, limit: int = 512) -> str:
    return str(value or "").strip()[:limit]


def _bounded_text_list(value: Any, *, limit: int = 16) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value[:limit] if _text(item)]


def _normalise_steps(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    steps: list[dict[str, str]] = []
    for raw_step in value[:64]:
        if not isinstance(raw_step, Mapping):
            continue
        steps.append(
            {
                "name": _text(raw_step.get("name"), limit=160) or "未命名步驟",
                "status": _normalise_status(raw_step.get("status")),
                "message": _text(raw_step.get("message")),
            }
        )
    return steps


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_update_status_history_record(
    payload: Mapping[str, Any],
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """從一筆排程 status payload 建立 bounded、可雜湊的歷史 record。"""

    if not isinstance(payload, Mapping):
        raise TypeError("update status payload must be an object")
    try:
        canonical_payload = _canonical_json(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"update status payload is not JSON-safe: {exc}") from exc

    run_id = _text(payload.get("run_id"), limit=200)
    if not run_id:
        raise ValueError("update status payload requires run_id")

    steps = _normalise_steps(payload.get("steps"))
    status = _normalise_status(payload.get("status"))
    raw_warnings = payload.get("warnings")
    raw_errors = payload.get("errors")
    record: dict[str, Any] = {
        "schema_version": UPDATE_STATUS_HISTORY_SCHEMA,
        "record_type": "data_update_attempt",
        "run_id": run_id,
        "status": status,
        "started_at": _text(payload.get("started_at"), limit=80) or None,
        "completed_at": _text(
            payload.get("completed_at") or payload.get("checked_at"), limit=80
        )
        or None,
        "start_date": _text(payload.get("start_date"), limit=32) or None,
        "end_date": _text(payload.get("end_date") or payload.get("target_date"), limit=32)
        or None,
        "step_count": len(steps),
        "failed_step_count": sum(
            1 for step in steps if step["status"] in _FAILURE_STATUSES
        ),
        "warning_count": len(raw_warnings) if isinstance(raw_warnings, list) else 0,
        "error_count": len(raw_errors) if isinstance(raw_errors, list) else 0,
        "warnings": _bounded_text_list(raw_warnings),
        "errors": _bounded_text_list(raw_errors),
        "steps": steps,
        "captured_at": captured_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "payload_sha256": hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
    }
    record_hash = hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()
    record["record_id"] = f"duh_{record_hash[:24]}"
    return record


def _invalid_history(
    path: Path | None,
    diagnostics: list[str],
    *,
    configured: bool,
    available: bool = False,
    records: list[dict[str, Any]] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    safe_records = records or []
    return {
        "schema_version": UPDATE_STATUS_HISTORY_SCHEMA,
        "configured": configured,
        "available": available,
        "path": str(path) if path is not None else None,
        "status": status or ("invalid" if diagnostics else "empty"),
        "record_count": len(safe_records),
        "records": safe_records,
        "latest": safe_records[-1] if safe_records else None,
        "diagnostics": list(dict.fromkeys(diagnostics)),
    }


def read_update_status_history(
    path: Path | None,
    *,
    limit: int = DEFAULT_STATUS_HISTORY_LIMIT,
) -> dict[str, Any]:
    """讀取明確指定的 JSONL history；檔案異常時保留可見 diagnostics。"""

    if path is None:
        return _invalid_history(None, [], configured=False, status="not_configured")
    if not path.is_file():
        return _invalid_history(
            path,
            [f"history_artifact_missing:{path}"],
            configured=True,
            status="missing",
        )
    try:
        if path.stat().st_size > MAX_STATUS_HISTORY_BYTES:
            return _invalid_history(
                path,
                [f"history_artifact_too_large:{path}"],
                configured=True,
            )
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:  # noqa: BLE001
        return _invalid_history(
            path,
            [f"history_artifact_unreadable:{type(exc).__name__}:{exc}"],
            configured=True,
        )

    diagnostics: list[str] = []
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.append(f"history_invalid_json_line:{line_number}:{exc.msg}")
            continue
        if not isinstance(raw, dict):
            diagnostics.append(f"history_record_not_object:{line_number}")
            continue
        if raw.get("schema_version") != UPDATE_STATUS_HISTORY_SCHEMA:
            diagnostics.append(f"history_schema_mismatch:{line_number}")
            continue
        record_id = _text(raw.get("record_id"), limit=100)
        run_id = _text(raw.get("run_id"), limit=200)
        if not record_id or not run_id:
            diagnostics.append(f"history_record_identity_missing:{line_number}")
            continue
        if record_id in seen_ids:
            diagnostics.append(f"history_duplicate_record:{record_id}")
        seen_ids.add(record_id)
        records.append(raw)

    safe_limit = max(1, int(limit))
    selected = records[-safe_limit:]
    result = _invalid_history(
        path,
        diagnostics,
        configured=True,
        available=True,
        records=selected,
    )
    result["record_count"] = len(records)
    result["latest"] = records[-1] if records else None
    if not diagnostics and records:
        result["status"] = "current"
    return result


def append_update_status_history(
    path: Path,
    payload: Mapping[str, Any],
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """append 一筆 status record；相同 record hash 會保持 idempotent。"""

    if path.exists() and not path.is_file():
        raise ValueError(f"history path is not a file: {path}")
    record = build_update_status_history_record(payload, captured_at=captured_at)
    existing = read_update_status_history(path, limit=10_000)
    if existing["status"] == "invalid":
        raise ValueError(
            "history artifact is invalid; refusing to append: "
            + ";".join(str(item) for item in existing["diagnostics"])
        )
    existing_ids = {
        str(item.get("record_id"))
        for item in existing.get("records", [])
        if isinstance(item, Mapping)
    }
    if record["record_id"] in existing_ids:
        return {
            "appended": False,
            "duplicate": True,
            "record_id": record["record_id"],
            "path": str(path),
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "appended": True,
        "duplicate": False,
        "record_id": record["record_id"],
        "path": str(path),
    }


__all__ = [
    "DEFAULT_STATUS_HISTORY_LIMIT",
    "MAX_STATUS_HISTORY_BYTES",
    "UPDATE_STATUS_HISTORY_SCHEMA",
    "append_update_status_history",
    "build_update_status_history_record",
    "read_update_status_history",
]

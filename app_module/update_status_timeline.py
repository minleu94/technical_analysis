"""唯讀資料更新時間軸投影。

這個模組只接受呼叫端明確提供的 status artifact 路徑，不掃描目錄、不呼叫
網路，也不會為了顯示狀態寫回任何檔案。它把更新流程的最後一次嘗試、最後一
次成功完成時間、步驟結果與 freshness 檢查組成 UI/CLI 可共用的 read model。
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
import json
from pathlib import Path
from typing import Any, Mapping

from app_module.update_status_history import read_update_status_history


UPDATE_STATUS_TIMELINE_SCHEMA = "data-update-timeline.v1"
DEFAULT_STALE_AFTER_SECONDS = 7 * 24 * 60 * 60
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024

_SUCCESS_STATUSES = {"passed", "success", "succeeded", "done", "ok", "completed"}
_FAILURE_STATUSES = {"failed", "failure", "error", "blocked"}
_RUNNING_STATUSES = {"running", "in_progress", "started"}


def _normalise_status(value: Any) -> str:
    return str(value or "unknown").strip().lower() or "unknown"


def _bounded_text(value: Any, *, max_length: int = 128) -> str:
    """Keep status projections readable even when an artifact field is malformed."""

    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _date_key(value: Any) -> str | None:
    """Normalize common YYYY-MM-DD／YYYYMMDD values for consistency checks."""

    text = _bounded_text(value, max_length=32).replace("-", "").replace("/", "")
    if len(text) == 8 and text.isdigit():
        return text
    return None


def _freshness_consistency_diagnostics(
    update: Mapping[str, Any],
    freshness: Mapping[str, Any],
) -> list[str]:
    """Compare freshness observations with the quick-run target date.

    Missing optional fields remain compatible with older artifacts.  Once a
    field is supplied, a mismatch is explicit and degrades the timeline rather
    than allowing a top-level ``status=passed`` to hide stale data.
    """

    target_key = _date_key(update.get("target_date"))
    if target_key is None:
        return []
    diagnostics: list[str] = []
    # ``data_update_quick_checked_date`` is the calendar date on which the
    # freshness probe observed the quick-run artifact.  It is not the latest
    # trading/data date and therefore must not be compared for equality with
    # the quick run's ``end_date`` (a weekend check of Friday's data would be
    # falsely degraded).  It is checked separately against the expected date
    # below; the data-bearing fields remain strict equality checks.
    comparisons = (
        ("data_update_quick_expected_date", "quick_expected_date"),
        ("daily_prices_latest_date", "daily_prices_latest_date"),
        ("technical_indicators_latest_date", "technical_indicators_latest_date"),
    )
    for field_name, diagnostic_name in comparisons:
        value = freshness.get(field_name)
        if value in (None, ""):
            continue
        observed_key = _date_key(value)
        if observed_key is None:
            diagnostics.append(f"freshness:{diagnostic_name}_invalid:{value}")
        elif observed_key != target_key:
            diagnostics.append(
                f"freshness:{diagnostic_name}_mismatch:{value}:target={update.get('target_date')}"
            )

    checked_key = _date_key(freshness.get("data_update_quick_checked_date"))
    expected_key = _date_key(freshness.get("data_update_quick_expected_date"))
    if checked_key is not None and expected_key is not None and checked_key < expected_key:
        diagnostics.append(
            "freshness:quick_checked_date_before_expected:"
            f"{freshness.get('data_update_quick_checked_date')}:"
            f"expected={freshness.get('data_update_quick_expected_date')}"
        )

    quick_status = _normalise_status(freshness.get("data_update_quick_status"))
    if quick_status not in {"unknown", "", *_SUCCESS_STATUSES}:
        diagnostics.append(f"freshness:quick_status_not_success:{quick_status}")
    for field_name, diagnostic_name in (
        (
            "twse_daily_price_file_exists_for_latest_date",
            "twse_daily_price_file_missing",
        ),
        (
            "tpex_daily_price_file_exists_for_latest_date",
            "tpex_daily_price_file_missing",
        ),
    ):
        if freshness.get(field_name) is False:
            diagnostics.append(f"freshness:{diagnostic_name}")
    return diagnostics


def _local_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_timestamp(value: Any, *, default_tz: tzinfo) -> tuple[datetime | None, str | None]:
    """解析 ISO timestamp；無 timezone 時接受但明確回報 warning。"""

    raw = str(value or "").strip()
    if not raw:
        return None, None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None, f"invalid_timestamp:{raw}"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
        return parsed, f"timestamp_without_timezone:{raw}"
    return parsed, None


def _read_artifact(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, [f"{label}_path_not_configured"]
    if not path.is_file():
        return None, [f"{label}_artifact_missing:{path}"]
    try:
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            return None, [f"{label}_artifact_too_large"]
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"{label}_artifact_invalid:{type(exc).__name__}:{exc}"]
    if not isinstance(payload, dict):
        return None, [f"{label}_artifact_root_not_object"]
    return payload, []


def _artifact_projection(
    payload: Mapping[str, Any] | None,
    path: Path | None,
    *,
    label: str,
    now: datetime,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    if payload is None:
        return {
            "configured": path is not None,
            "available": False,
            "path": str(path) if path is not None else None,
            "status": "missing" if path is not None else "not_configured",
        }, diagnostics

    default_tz = now.tzinfo or _local_timezone()
    raw_status = _normalise_status(payload.get("status"))
    started_at, started_warning = _parse_timestamp(payload.get("started_at"), default_tz=default_tz)
    completed_at, completed_warning = _parse_timestamp(
        payload.get("completed_at") or payload.get("checked_at") or payload.get("updated_at"),
        default_tz=default_tz,
    )
    completed_utc = completed_at.astimezone(timezone.utc) if completed_at else None
    now_utc = now.astimezone(timezone.utc)
    age_seconds: int | None = None
    if completed_utc is not None:
        age_seconds = int((now_utc - completed_utc).total_seconds())
        if age_seconds < 0:
            diagnostics.append(f"{label}:timestamp_in_future")
            age_seconds = None

    projected: dict[str, Any] = {
        "configured": True,
        "available": True,
        "path": str(path) if path is not None else None,
        "status": raw_status,
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at") or payload.get("checked_at") or payload.get("updated_at"),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("end_date") or payload.get("target_date"),
        "age_seconds": age_seconds,
    }
    timestamp_warnings = [
        warning
        for warning in (started_warning, completed_warning)
        if warning and warning.startswith("timestamp_without_timezone:")
    ]
    if timestamp_warnings:
        projected["timestamp_warnings"] = timestamp_warnings
    for warning in (started_warning, completed_warning):
        if warning and not warning.startswith("timestamp_without_timezone:"):
            diagnostics.append(f"{label}:{warning}")
    if label == "update":
        raw_steps = payload.get("steps")
        steps: list[dict[str, Any]] = []
        if isinstance(raw_steps, list):
            for raw_step in raw_steps[:64]:
                if not isinstance(raw_step, Mapping):
                    continue
                steps.append(
                    {
                        "name": str(raw_step.get("name") or "未命名步驟"),
                        "status": _normalise_status(raw_step.get("status")),
                        "message": str(raw_step.get("message") or ""),
                    }
                )
        projected["steps"] = steps
        projected["step_count"] = len(steps)
        projected["failed_step_count"] = sum(
            1 for step in steps if _normalise_status(step.get("status")) in _FAILURE_STATUSES
        )
        projected["warning_count"] = len(payload.get("warnings") or []) if isinstance(payload.get("warnings"), list) else 0
        projected["error_count"] = len(payload.get("errors") or []) if isinstance(payload.get("errors"), list) else 0
    else:
        projected["warnings"] = list(payload.get("warnings") or [])[:8]
        projected["errors"] = list(payload.get("errors") or [])[:8]
        if label == "freshness":
            checks = payload.get("checks")
            if isinstance(checks, Mapping):
                for key in (
                    "daily_prices_latest_date",
                    "daily_price_latest_date_key",
                    "technical_indicators_latest_date",
                    "data_update_quick_status",
                    "data_update_quick_checked_date",
                    "data_update_quick_expected_date",
                ):
                    value = checks.get(key)
                    if value is not None:
                        projected[key] = _bounded_text(value)
                for key in (
                    "daily_prices_age_days",
                    "technical_indicators_age_days",
                ):
                    value = checks.get(key)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        projected[key] = value
                for key in (
                    "twse_daily_price_file_exists_for_latest_date",
                    "tpex_daily_price_file_exists_for_latest_date",
                ):
                    value = checks.get(key)
                    if isinstance(value, bool):
                        projected[key] = value
    return projected, diagnostics


def load_data_update_timeline(
    *,
    update_status_path: Path | None,
    freshness_status_path: Path | None = None,
    tpex_status_path: Path | None = None,
    history_path: Path | None = None,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    """讀取明確指定的更新 artifact 並回傳 fail-closed 時間軸。

    ``update_status_path`` 是主要來源；freshness/TPEX/history 路徑若未設定只會
    被標為 ``not_configured``，不會偷偷搜尋其他檔案。所有 elapsed 數值以整數秒表示。
    """

    reference_now = now or datetime.now().astimezone()
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=_local_timezone())
    safe_stale_after = max(0, int(stale_after_seconds))
    artifacts: dict[str, dict[str, Any]] = {}
    diagnostics: list[str] = []

    for label, path in (
        ("update", update_status_path),
        ("freshness", freshness_status_path),
        ("tpex", tpex_status_path),
    ):
        payload, read_diagnostics = _read_artifact(path, label=label)
        diagnostics.extend(read_diagnostics)
        projected, projection_diagnostics = _artifact_projection(
            payload,
            path,
            label=label,
            now=reference_now,
        )
        diagnostics.extend(projection_diagnostics)
        artifacts[label] = projected

    update = artifacts["update"]
    freshness = artifacts["freshness"]
    tpex = artifacts["tpex"]
    history = read_update_status_history(history_path)
    diagnostics.extend(f"history:{item}" for item in history.get("diagnostics", []))
    update_status = _normalise_status(update.get("status"))
    update_age = update.get("age_seconds")
    has_future_timestamp = any(item == "update:timestamp_in_future" for item in diagnostics)
    freshness_consistency = (
        _freshness_consistency_diagnostics(update, freshness)
        if freshness.get("available")
        else []
    )
    diagnostics.extend(freshness_consistency)

    if not update.get("available"):
        status = "missing" if update.get("configured") else "not_configured"
    elif has_future_timestamp:
        status = "invalid"
    elif update_status in _FAILURE_STATUSES:
        status = "failed"
    elif update_status in _RUNNING_STATUSES:
        status = "running"
    elif update_status not in _SUCCESS_STATUSES:
        status = "invalid"
        diagnostics.append(f"update:unsupported_status:{update_status}")
    elif update_age is None:
        status = "invalid"
        diagnostics.append("update:completed_timestamp_unavailable")
    elif int(update_age) > safe_stale_after:
        status = "stale"
    elif freshness.get("configured") and not freshness.get("available"):
        status = "partial"
    elif (
        freshness.get("available")
        and isinstance(freshness.get("age_seconds"), int)
        and int(freshness["age_seconds"]) > safe_stale_after
    ):
        status = "degraded"
    elif freshness.get("available") and _normalise_status(freshness.get("status")) in _FAILURE_STATUSES:
        status = "degraded"
    elif freshness_consistency:
        status = "degraded"
    elif freshness.get("available") and _normalise_status(freshness.get("status")) not in _SUCCESS_STATUSES:
        status = "partial"
    else:
        status = "current"

    last_success_at = update.get("completed_at") if status in {"current", "partial", "degraded", "stale"} else None
    result: dict[str, Any] = {
        "schema_version": UPDATE_STATUS_TIMELINE_SCHEMA,
        "status": status,
        "source": "scheduled_data_update",
        "last_success_at": last_success_at,
        "last_attempt_at": update.get("completed_at") or update.get("started_at"),
        "age_seconds": update_age if isinstance(update_age, int) else None,
        "stale_after_seconds": safe_stale_after,
        "run_id": update.get("run_id"),
        "target_date": update.get("target_date"),
        "artifacts": artifacts,
        "history": history,
        "steps": update.get("steps", []),
        "step_count": int(update.get("step_count") or 0),
        "failed_step_count": int(update.get("failed_step_count") or 0),
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "boundary": {
            "read_only": True,
            "writes_allowed": False,
            "network_allowed": False,
            "explicit_paths_only": True,
        },
    }
    # A running/failed artifact must never expose a previous-looking success time.
    if status not in {"current", "partial", "degraded", "stale"}:
        result["last_success_at"] = None
    return result


__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "MAX_ARTIFACT_BYTES",
    "UPDATE_STATUS_TIMELINE_SCHEMA",
    "load_data_update_timeline",
]

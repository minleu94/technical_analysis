"""唯讀彙整每日排程產物，供 Owner 營運監控使用。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Callable

from app_module.dtos.runtime_dtos import (
    ScheduledOperationStatusDTO,
    ScheduledOperationsSnapshotDTO,
)
from app_module.runtime_services.event_time import parse_runtime_event_timestamp


_CORE_JOBS: tuple[tuple[str, str], ...] = (
    ("data_update_quick", "每日資料更新"),
    ("data_freshness", "資料新鮮度"),
    ("recommendation_snapshot", "推薦快照"),
    ("evidence_pipeline_dry_run", "證據 dry-run"),
    ("decision_evidence_capture", "決策證據擷取"),
    ("paper_portfolio_daily", "Paper Portfolio"),
)
_SAFETY_JOBS: tuple[tuple[str, str], ...] = (
    ("official_market_events", "官方市場事件"),
    ("ml_promotion_evidence", "ML Promotion 證據"),
    ("ml_allocation_copilot", "ML Shadow Co-pilot"),
)
_JOB_LABELS = dict(_CORE_JOBS + _SAFETY_JOBS)
_SUCCESS_STATUSES = frozenset({"passed", "published"})


class ScheduledOperationsStatusService:
    """只讀 ``scheduled/*/latest_status.json``，不呼叫也不修改 Windows Task Scheduler。"""

    def __init__(
        self,
        scheduled_root: Path,
        *,
        now_provider: Callable[[], datetime] | None = None,
        freshness_window: timedelta = timedelta(hours=36),
    ) -> None:
        self._scheduled_root = Path(scheduled_root)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._freshness_window = freshness_window

    def get_snapshot(self) -> ScheduledOperationsSnapshotDTO:
        now = _as_utc(self._now_provider())
        known_job_ids = tuple(job_id for job_id, _label in (_CORE_JOBS + _SAFETY_JOBS))
        discovered_job_ids = self._discover_job_ids()
        job_ids = known_job_ids + tuple(
            job_id for job_id in discovered_job_ids if job_id not in known_job_ids
        )
        operations = tuple(self._read_operation(job_id, now) for job_id in job_ids)
        core_operations = tuple(item for item in operations if item.lane == "core")
        core_ready_count = sum(
            item.state in {"operational", "guarded"} for item in core_operations
        )
        overall_state = "operational" if core_ready_count == len(core_operations) else "attention"
        return ScheduledOperationsSnapshotDTO(
            overall_state=overall_state,
            core_ready_count=core_ready_count,
            core_job_count=len(core_operations),
            operations=operations,
            observed_at=now,
            scheduled_root=str(self._scheduled_root),
        )

    def build_unavailable_snapshot(
        self,
        diagnostic: str,
    ) -> ScheduledOperationsSnapshotDTO:
        """讀取協調器失敗時供 UI 使用的 fail-closed 投影。"""
        now = _as_utc(self._now_provider())
        operations = tuple(
            ScheduledOperationStatusDTO(
                job_id=job_id,
                label=label,
                raw_status="unreadable",
                state="attention" if _lane_for_job(job_id) == "core" else "unavailable",
                updated_at=None,
                lane=_lane_for_job(job_id),
                source_path=str(self._scheduled_root / job_id / "latest_status.json"),
                read_state="service_error",
                diagnostic=diagnostic,
            )
            for job_id, label in (_CORE_JOBS + _SAFETY_JOBS)
        )
        return ScheduledOperationsSnapshotDTO(
            overall_state="attention",
            core_ready_count=0,
            core_job_count=len(_CORE_JOBS),
            operations=operations,
            observed_at=now,
            scheduled_root=str(self._scheduled_root),
        )

    def _discover_job_ids(self) -> tuple[str, ...]:
        if not self._scheduled_root.is_dir():
            return ()
        try:
            return tuple(
                path.name
                for path in sorted(self._scheduled_root.iterdir(), key=lambda item: item.name)
                if path.is_dir() and (path / "latest_status.json").is_file()
            )
        except OSError:
            return ()

    def _read_operation(
        self,
        job_id: str,
        now: datetime,
    ) -> ScheduledOperationStatusDTO:
        status_path = self._scheduled_root / job_id / "latest_status.json"
        lane = _lane_for_job(job_id)
        is_core_job = lane == "core"
        label = _JOB_LABELS.get(job_id, job_id)
        if not status_path.is_file():
            return ScheduledOperationStatusDTO(
                job_id=job_id,
                label=label,
                raw_status="missing",
                state="attention" if is_core_job else "unavailable",
                updated_at=None,
                lane=lane,
                source_path=str(status_path),
                read_state="missing",
                diagnostic="latest_status_missing",
            )

        try:
            raw_payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ScheduledOperationStatusDTO(
                job_id=job_id,
                label=label,
                raw_status="unreadable",
                state="attention" if is_core_job else "unavailable",
                updated_at=None,
                lane=lane,
                source_path=str(status_path),
                read_state="unreadable",
                diagnostic=f"latest_status_unreadable:{type(exc).__name__}",
            )

        if not isinstance(raw_payload, dict):
            return ScheduledOperationStatusDTO(
                job_id=job_id,
                label=label,
                raw_status="invalid",
                state="attention" if is_core_job else "unavailable",
                updated_at=None,
                lane=lane,
                source_path=str(status_path),
                read_state="invalid_payload",
                diagnostic="latest_status_payload_not_object",
            )

        try:
            updated_at = datetime.fromtimestamp(status_path.stat().st_mtime, tz=timezone.utc)
        except OSError as exc:
            return ScheduledOperationStatusDTO(
                job_id=job_id,
                label=label,
                raw_status="unreadable",
                state="attention" if is_core_job else "unavailable",
                updated_at=None,
                lane=lane,
                source_path=str(status_path),
                read_state="unreadable",
                diagnostic=f"latest_status_stat_failed:{type(exc).__name__}",
            )

        raw_status = str(raw_payload.get("status", "unknown")).strip().lower() or "unknown"
        state, diagnostic = self._classify(job_id, raw_status, raw_payload, is_core_job)
        updated_at, observed_at_raw, observed_at_source, timestamp_diagnostic = _status_timestamp(
            raw_payload,
            file_mtime=updated_at,
            now=now,
        )
        if timestamp_diagnostic:
            diagnostic = timestamp_diagnostic if not diagnostic else f"{diagnostic};{timestamp_diagnostic}"
        if updated_at > now + timedelta(minutes=5):
            state = "attention" if is_core_job else "unavailable"
            diagnostic = (
                "latest_status_timestamp_future"
                if not diagnostic
                else f"{diagnostic};latest_status_timestamp_future"
            )
        elif now - updated_at > self._freshness_window:
            state = "attention" if is_core_job else "unavailable"
            diagnostic = "latest_status_stale" if not diagnostic else f"{diagnostic};latest_status_stale"

        return ScheduledOperationStatusDTO(
            job_id=job_id,
            label=label,
            raw_status=raw_status,
            state=state,
            updated_at=updated_at,
            lane=lane,
            observed_at_raw=observed_at_raw,
            observed_at_source=observed_at_source,
            source_path=str(status_path),
            read_state="observed",
            diagnostic=diagnostic,
        )

    @staticmethod
    def _classify(
        job_id: str,
        raw_status: str,
        payload: dict[str, object],
        is_core_job: bool,
    ) -> tuple[str, str]:
        if raw_status in _SUCCESS_STATUSES:
            return "operational", ""
        if job_id == "evidence_pipeline_dry_run" and raw_status == "degraded":
            if _is_expected_evidence_degradation(payload):
                return "guarded", "natural_maturity_or_nonblocking_degradation"
            return "attention", "evidence_pipeline_degradation_requires_review"
        if job_id == "ml_promotion_evidence" and raw_status == "blocked":
            return "guarded", "ml_promotion_safety_gate_active"
        if job_id == "ml_allocation_copilot" and raw_status == "passed_rule_only":
            return "guarded", "ml_shadow_rule_only"
        if is_core_job:
            return "attention", f"unexpected_core_status:{raw_status}"
        return "attention", f"unexpected_status:{raw_status}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lane_for_job(job_id: str) -> str:
    if job_id in dict(_CORE_JOBS):
        return "core"
    if job_id in dict(_SAFETY_JOBS):
        return "safety"
    return "other"


def _status_timestamp(
    payload: dict[str, object],
    *,
    file_mtime: datetime,
    now: datetime,
) -> tuple[datetime, str | None, str, str]:
    diagnostics: list[str] = []
    invalid_raw_value: str | None = None
    # ``decision_at`` and ``as_of_date`` describe a market decision/effective
    # date.  They are deliberately not task-completion timestamps: using them
    # here could show a future time and silently defeat stale-artifact checks.
    for key in ("checked_at", "generated_at"):
        raw_value = payload.get(key)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        parsed = parse_runtime_event_timestamp(raw_value)
        if parsed is None:
            diagnostics.append(f"invalid_status_timestamp:{key}")
            invalid_raw_value = raw_value
            continue
        if parsed > now + timedelta(minutes=5):
            diagnostics.append(f"future_status_timestamp:{key}")
            invalid_raw_value = raw_value
            continue
        return parsed, raw_value, key, ";".join(diagnostics)
    return file_mtime, invalid_raw_value, "file_mtime", ";".join(diagnostics)


def _is_expected_evidence_degradation(payload: dict[str, object]) -> bool:
    """只接受明確證明為 natural-maturity 的 dry-run degradation。"""
    required_values = {
        "natural_maturity_only": True,
        "manual_action_required": False,
        "pipeline_summary_available": True,
        "freshness_status": "passed",
        "pipeline_errors_count": 0,
        "pipeline_actionable_warning_count": 0,
    }
    if any(payload.get(key) != expected for key, expected in required_values.items()):
        return False

    for key in (
        "pipeline_blocking_gaps",
        "source_coverage_blocking_gaps",
        "pipeline_diagnostic_codes",
    ):
        value = payload.get(key)
        if not isinstance(value, list) or value:
            return False
    return True

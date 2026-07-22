"""Scheduler Observability & Health Contract for TWStock.

Read-only inspection of scheduled task status, freshness, execution ordering,
write intent, and production evidence boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from data_module.config import TWStockConfig


SCHEDULED_TASK_ORDERING = (
    "daily_data_update_quick",
    "daily_data_freshness_check",
    "scheduled_recommendation_snapshot",
    "scheduled_evidence_pipeline_dry_run",
    "v2_2_weekly_collection",
)

# Explicit mapping between logical task names and candidate relative status file paths.
TASK_RELATIVE_PATHS: Dict[str, Tuple[str, ...]] = {
    "daily_data_update_quick": (
        "scheduled/data_update_quick/latest_status.json",
        "data_update_quick/latest_status.json",
        "scheduled/data_update_quick_latest_status.json",
        "data_update_quick_latest_status.json",
    ),
    "daily_data_freshness_check": (
        "scheduled/data_freshness/latest_status.json",
        "data_freshness/latest_status.json",
        "scheduled/data_freshness_latest_status.json",
        "data_freshness_latest_status.json",
    ),
    "scheduled_recommendation_snapshot": (
        "scheduled/recommendation_snapshot/latest_status.json",
        "recommendation_snapshot/latest_status.json",
        "scheduled/recommendation_snapshot_latest_status.json",
        "recommendation_snapshot_latest_status.json",
    ),
    "scheduled_evidence_pipeline_dry_run": (
        "scheduled/evidence_pipeline_dry_run/latest_status.json",
        "evidence_pipeline_dry_run/latest_status.json",
        "scheduled/evidence_pipeline_dry_run_latest_status.json",
        "evidence_pipeline_dry_run_latest_status.json",
    ),
    "v2_2_weekly_collection": (
        "scheduled/v2_2_weekly_collection/latest_status.json",
        "v2_2_weekly_collection/latest_status.json",
        "scheduled/v2_2_weekly_collection_latest_status.json",
        "v2_2_weekly_collection_latest_status.json",
    ),
}


@dataclass(frozen=True)
class TaskStatusItem:
    task_name: str
    expected_order_index: int
    last_run_timestamp: Optional[str]
    status: str  # SUCCESS, PASSED_WITH_WARNINGS, DEGRADED, FAILED, STALE, MISSING
    write_intent: str  # MARKET_DATA_UPDATE_WRITE, DRY_RUN_NO_WRITE, PENDING_REVIEW_WRITE, FORMAL_EVIDENCE_PROHIBITED
    status_json_path: str
    failure_reason: Optional[str] = None


@dataclass(frozen=True)
class SchedulerHealthReport:
    audited_at: str
    overall_health: str  # HEALTHY, WARNING, CRITICAL
    production_scheduler_allowed: bool  # ALWAYS False
    ordering_valid: bool
    tasks: Tuple[TaskStatusItem, ...]
    advisory_notes: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audited_at": self.audited_at,
            "overall_health": self.overall_health,
            "production_scheduler_allowed": self.production_scheduler_allowed,
            "ordering_valid": self.ordering_valid,
            "tasks": [
                {
                    "task_name": item.task_name,
                    "expected_order_index": item.expected_order_index,
                    "last_run_timestamp": item.last_run_timestamp,
                    "status": item.status,
                    "write_intent": item.write_intent,
                    "status_json_path": item.status_json_path,
                    "failure_reason": item.failure_reason,
                }
                for item in self.tasks
            ],
            "advisory_notes": list(self.advisory_notes),
        }


class SchedulerHealthService:
    """Read-only scheduler health inspector."""

    def __init__(self, config: Optional[TWStockConfig] = None) -> None:
        self.config = config or TWStockConfig()

    @staticmethod
    def _resolve_status_file(
        *,
        base_root: Path,
        task_name: str,
        candidate_rel_paths: Tuple[str, ...],
    ) -> Optional[Path]:
        """解析邏輯任務對應的最新狀態檔，不修改任何排程產物。"""
        for relative_path in candidate_rel_paths:
            candidate = (base_root / relative_path).resolve()
            if candidate.exists() and candidate.is_file():
                return candidate

        if task_name != "v2_2_weekly_collection":
            return None

        collection_dir = (base_root / "scheduled" / "v2_2_weekly_collection").resolve()
        dated_artifacts = sorted(
            path
            for path in collection_dir.glob("v2_2_weekly_collection_*.json")
            if path.is_file()
        )
        return dated_artifacts[-1] if dated_artifacts else None

    def audit_scheduler_health(self) -> SchedulerHealthReport:
        audited_at = datetime.now().isoformat()
        advisory: List[str] = []

        base_search_roots = [
            self.config.output_root,
            self.config.data_root,
            Path("output"),
            Path("."),
        ]

        task_items: List[TaskStatusItem] = []

        task_write_intents = {
            "daily_data_update_quick": "MARKET_DATA_UPDATE_WRITE",
            "daily_data_freshness_check": "DRY_RUN_NO_WRITE",
            "scheduled_recommendation_snapshot": "DRY_RUN_NO_WRITE",
            "scheduled_evidence_pipeline_dry_run": "DRY_RUN_NO_WRITE",
            "v2_2_weekly_collection": "PENDING_REVIEW_WRITE",
        }

        for idx, task_name in enumerate(SCHEDULED_TASK_ORDERING):
            found_file: Optional[Path] = None
            candidate_rel_paths = TASK_RELATIVE_PATHS.get(task_name, ())

            for b_root in base_search_roots:
                found_file = self._resolve_status_file(
                    base_root=b_root,
                    task_name=task_name,
                    candidate_rel_paths=candidate_rel_paths,
                )
                if found_file:
                    break

            intent = task_write_intents.get(task_name, "DRY_RUN_NO_WRITE")

            if found_file is None:
                task_items.append(
                    TaskStatusItem(
                        task_name=task_name,
                        expected_order_index=idx,
                        last_run_timestamp=None,
                        status="MISSING",
                        write_intent=intent,
                        status_json_path="N/A",
                        failure_reason="Status JSON file not found in standard output directories",
                    )
                )
                advisory.append(f"排程任務 {task_name} 尚未執行或缺少狀態紀錄檔 ({candidate_rel_paths[0]})")
                continue

            try:
                payload = json.loads(found_file.read_text(encoding="utf-8"))
                collection_record = payload.get("collection_record")
                if not isinstance(collection_record, dict):
                    collection_record = {}
                run_ts = (
                    payload.get("timestamp")
                    or payload.get("run_timestamp")
                    or payload.get("last_run")
                    or payload.get("created_at")
                    or payload.get("date")
                    or collection_record.get("created_at")
                )
                if not run_ts:
                    # Fallback to file mtime format YYYY-MM-DDTHH:MM:SS
                    mtime = datetime.fromtimestamp(found_file.stat().st_mtime)
                    run_ts = mtime.isoformat()

                raw_status = str(
                    payload.get("status") or payload.get("collection_status") or ""
                ).lower()
                success_flag = payload.get("success", False)

                err_msg = payload.get("error") or payload.get("message")

                if raw_status in ("passed", "success", "ok") or (success_flag and not raw_status):
                    status_str = "SUCCESS"
                elif raw_status in ("passed_with_warnings", "ready_with_advisories", "ready_for_manual_confirm", "ready"):
                    status_str = "PASSED_WITH_WARNINGS"
                elif raw_status == "pending_human_review":
                    status_str = "PENDING_HUMAN_REVIEW"
                elif raw_status == "degraded":
                    status_str = "DEGRADED"
                else:
                    status_str = "FAILED"
                    if not err_msg:
                        err_msg = f"Task status indicated '{raw_status or 'failed'}'"

                task_items.append(
                    TaskStatusItem(
                        task_name=task_name,
                        expected_order_index=idx,
                        last_run_timestamp=run_ts,
                        status=status_str,
                        write_intent=intent,
                        status_json_path=str(found_file),
                        failure_reason=err_msg if status_str == "FAILED" else None,
                    )
                )
            except Exception as e:
                task_items.append(
                    TaskStatusItem(
                        task_name=task_name,
                        expected_order_index=idx,
                        last_run_timestamp=None,
                        status="FAILED",
                        write_intent=intent,
                        status_json_path=str(found_file),
                        failure_reason=f"Status JSON parsing error: {e}",
                    )
                )

        # Check sequence order timestamps
        ordering_valid = True
        daily_timestamps = [
            item.last_run_timestamp
            for item in task_items
            if item.task_name != "v2_2_weekly_collection" and item.last_run_timestamp
        ]
        if len(daily_timestamps) >= 2:
            for i in range(len(daily_timestamps) - 1):
                if daily_timestamps[i] > daily_timestamps[i + 1]:
                    ordering_valid = False
                    advisory.append("排程任務執行時間戳記未遵循標準相依性順序")
                    break

        # Check overall health
        has_failed = any(t.status == "FAILED" for t in task_items)
        has_missing = any(t.status == "MISSING" for t in task_items)
        has_advisory = any(
            t.status in ("PASSED_WITH_WARNINGS", "DEGRADED", "PENDING_HUMAN_REVIEW")
            for t in task_items
        )

        if has_failed:
            overall = "CRITICAL"
        elif has_missing or has_advisory or not ordering_valid:
            overall = "WARNING"
        else:
            overall = "HEALTHY"

        advisory.append(
            "提示：`production_scheduler_allowed=false` 為正式 DB 寫入限制，不影響 daily_data_update_quick 之市場價格更新。"
        )

        return SchedulerHealthReport(
            audited_at=audited_at,
            overall_health=overall,
            production_scheduler_allowed=False,  # ALWAYS False
            ordering_valid=ordering_valid,
            tasks=tuple(task_items),
            advisory_notes=tuple(advisory),
        )

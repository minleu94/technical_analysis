"""只讀投影治理狀態；不把遺失、無法讀取或未知狀態當成閒置。"""

from collections.abc import Callable
from typing import Any

from runtime.interfaces.store_interface import IRuntimeStore
from app_module.dtos.runtime_dtos import RuntimeState, RuntimeStateSnapshotDTO


class RuntimeSnapshotService:
    def __init__(self, store: IRuntimeStore):
        self.store = store

    def get_snapshot(self) -> RuntimeStateSnapshotDTO:
        task, task_state, task_diagnostics = _read_mapping(self.store.read_current_task, "task")
        context, context_state, context_diagnostics = _read_mapping(self.store.read_runtime_context, "context")
        diagnostics = [*task_diagnostics, *context_diagnostics]
        raw_status = str(task.get("status", ""))
        status = raw_status if raw_status in RuntimeState.__members__ else "UNKNOWN"
        if task and status == "UNKNOWN":
            task_state = "degraded"
            diagnostics.append("runtime_task_status_unknown")

        active_files = context.get("active_files", [])
        if not isinstance(active_files, list) or not all(isinstance(item, str) for item in active_files):
            active_files = []
            context_state = "degraded"
            diagnostics.append("runtime_context_active_files_invalid")

        objective = task.get("objective", "No task assigned")
        if not isinstance(objective, str):
            objective = "治理目標無法判讀"
            task_state = "degraded"
            diagnostics.append("runtime_task_objective_invalid")
        return RuntimeStateSnapshotDTO(
            task_objective=objective,
            task_status=status,
            active_context_files=list(active_files),
            task_read_state=task_state,
            context_read_state=context_state,
            raw_task_status=raw_status,
            diagnostics=tuple(diagnostics),
        )


def _read_mapping(reader: Callable[[], Any], label: str) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    try:
        value = reader()
    except Exception as exc:
        return {}, "unavailable", (f"runtime_{label}_read_failed:{type(exc).__name__}",)
    if not isinstance(value, dict):
        return {}, "degraded", (f"runtime_{label}_payload_invalid",)
    if not value:
        # 既有 store 將不存在與讀取錯誤都回傳 {}；不在 app 層猜原因或再開檔。
        return {}, "missing_or_unreadable", (f"runtime_{label}_missing_or_unreadable",)
    return value, "observed", ()

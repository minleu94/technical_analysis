"""Runtime Observatory 的 Qt composition coordinator。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_module.runtime_services.environment_readiness_service import (
    EnvironmentReadinessService,
)


@dataclass(frozen=True)
class RuntimeUiComposition:
    controller: Any
    bridge: Any
    view: Any
    timer: Any


def build_runtime_ui_composition(
    *,
    project_root: Path,
    parent: Any,
    dependencies: dict[str, Any],
    scheduled_output_root: Path | None = None,
    environment_roots: tuple[Path, Path] | None = None,
) -> RuntimeUiComposition:
    controller_kwargs: dict[str, Any] = {
        "scheduled_output_root": scheduled_output_root,
    }
    if environment_roots is not None:
        service_factory = dependencies.get(
            "EnvironmentReadinessService",
            EnvironmentReadinessService,
        )
        controller_kwargs["environment_readiness_service"] = service_factory(
            environment_roots[0],
            environment_roots[1],
        )
    controller = dependencies["RuntimeController"](
        str(project_root / "runtime"),
        **controller_kwargs,
    )
    bridge = dependencies["QtRuntimeBridge"](controller.event_bus, parent)
    view = dependencies["RuntimeView"](parent=parent)
    bridge.state_updated.connect(view.on_state_updated)
    bridge.health_updated.connect(view.on_health_updated)
    bridge.event_received.connect(view.on_event_received)
    bridge.scheduled_operations_updated.connect(view.on_scheduled_operations_updated)
    environment_signal = getattr(bridge, "environment_readiness_updated", None)
    environment_slot = getattr(view, "on_environment_readiness_updated", None)
    if environment_signal is not None and callable(environment_slot):
        environment_signal.connect(environment_slot)
    timer = dependencies["QTimer"](parent)
    timer.timeout.connect(controller.poll_updates)
    # 首次 render 不能等待 1 秒 timer，否則 Runtime 初始畫面會把所有唯讀
    # readiness 狀態顯示成「尚未讀取」。poll_updates 只發布已存在的 snapshot，
    # 不會建立目錄、probe 檔或初始化 SQLite。
    controller.poll_updates()
    timer.start(1000)
    return RuntimeUiComposition(
        controller=controller,
        bridge=bridge,
        view=view,
        timer=timer,
    )

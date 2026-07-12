"""Runtime Observatory 的 Qt composition coordinator。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeUiComposition:
    controller: Any
    bridge: Any
    view: Any
    timer: Any


def build_runtime_ui_composition(
    *, project_root: Path, parent: Any, dependencies: dict[str, Any]
) -> RuntimeUiComposition:
    controller = dependencies["RuntimeController"](str(project_root / "runtime"))
    bridge = dependencies["QtRuntimeBridge"](controller.event_bus, parent)
    view = dependencies["RuntimeView"](parent=parent)
    bridge.state_updated.connect(view.on_state_updated)
    bridge.health_updated.connect(view.on_health_updated)
    bridge.event_received.connect(view.on_event_received)
    timer = dependencies["QTimer"](parent)
    timer.timeout.connect(controller.poll_updates)
    timer.start(1000)
    return RuntimeUiComposition(
        controller=controller,
        bridge=bridge,
        view=view,
        timer=timer,
    )

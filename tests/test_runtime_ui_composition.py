from ui_qt.runtime_composition import build_runtime_ui_composition


class _Signal:
    def __init__(self):
        self.targets = []

    def connect(self, target):
        self.targets.append(target)


class _Controller:
    def __init__(
        self,
        runtime_dir,
        *,
        scheduled_output_root=None,
        environment_readiness_service=None,
    ):
        self.runtime_dir = runtime_dir
        self.scheduled_output_root = scheduled_output_root
        self.environment_readiness_service = environment_readiness_service
        self.event_bus = object()
        self.poll_count = 0

    def poll_updates(self):
        self.poll_count += 1


class _Bridge:
    def __init__(self, event_bus, parent):
        self.event_bus = event_bus
        self.parent = parent
        self.state_updated = _Signal()
        self.health_updated = _Signal()
        self.event_received = _Signal()
        self.scheduled_operations_updated = _Signal()
        self.environment_readiness_updated = _Signal()


class _View:
    def __init__(self, parent):
        self.parent = parent

    def on_state_updated(self):
        pass

    def on_health_updated(self):
        pass

    def on_event_received(self):
        pass

    def on_scheduled_operations_updated(self):
        pass

    def on_environment_readiness_updated(self):
        pass


class _Timeout(_Signal):
    pass


class _Timer:
    def __init__(self, parent):
        self.parent = parent
        self.timeout = _Timeout()
        self.interval = None

    def start(self, interval):
        self.interval = interval


def test_runtime_composition_wires_bridge_view_and_poll_timer(tmp_path) -> None:
    parent = object()
    result = build_runtime_ui_composition(
        project_root=tmp_path,
        parent=parent,
        dependencies={
            "RuntimeController": _Controller,
            "QtRuntimeBridge": _Bridge,
            "RuntimeView": _View,
            "QTimer": _Timer,
        },
        scheduled_output_root=tmp_path / "output" / "scheduled",
        environment_roots=(tmp_path / "data", tmp_path / "output"),
    )

    assert result.controller.runtime_dir == str(tmp_path / "runtime")
    assert result.controller.scheduled_output_root == tmp_path / "output" / "scheduled"
    assert result.controller.environment_readiness_service is not None
    assert result.bridge.state_updated.targets == [result.view.on_state_updated]
    assert result.bridge.health_updated.targets == [result.view.on_health_updated]
    assert result.bridge.event_received.targets == [result.view.on_event_received]
    assert result.bridge.scheduled_operations_updated.targets == [
        result.view.on_scheduled_operations_updated
    ]
    assert result.bridge.environment_readiness_updated.targets == [
        result.view.on_environment_readiness_updated
    ]
    assert result.timer.timeout.targets == [result.controller.poll_updates]
    assert result.timer.interval == 1000
    assert result.controller.poll_count == 1

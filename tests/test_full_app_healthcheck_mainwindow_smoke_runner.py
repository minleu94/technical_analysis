from __future__ import annotations

from pathlib import Path

from qa.full_app_healthcheck.mainwindow_smoke import EXPECTED_MAINWINDOW_TAB_LABELS
from qa.full_app_healthcheck.mainwindow_smoke_runner import (
    MainWindowSmokeOptions,
    run_mainwindow_smoke,
)


class FakeApp:
    def __init__(self):
        self.process_events_count = 0

    def processEvents(self):
        self.process_events_count += 1


class FakeSize:
    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakePixmap:
    def __init__(self, *, null: bool = False):
        self.null = null

    def isNull(self):
        return self.null

    def save(self, path):
        Path(path).write_bytes(b"fake png")
        return True


class FakeTabWidget:
    def __init__(self, labels):
        self.labels = list(labels)
        self.current_index = 0
        self.widgets = [FakeUpdateView()] + [object() for _ in labels[1:]]

    def count(self):
        return len(self.labels)

    def tabText(self, index):
        return self.labels[index]

    def setCurrentIndex(self, index):
        self.current_index = index

    def widget(self, index):
        return self.widgets[index]


class FakeUpdateView:
    def __init__(self):
        self.force_merge_executed = False

    def _execute_force_merge(self):
        return None

    def _do_merge(self, force_all=False):
        self.force_merge_executed = True


class FakeMainWindow:
    def __init__(self):
        self.tab_widget = FakeTabWidget(EXPECTED_MAINWINDOW_TAB_LABELS)
        self.resize_calls: list[tuple[int, int]] = []
        self.closed = False
        self.shown = False
        self._width = 1400
        self._height = 800

    def windowTitle(self):
        return "baldr"

    def show(self):
        self.shown = True

    def close(self):
        self.closed = True

    def resize(self, width, height):
        self.resize_calls.append((width, height))
        self._width = width
        self._height = height

    def size(self):
        return FakeSize(self._width, self._height)

    def grab(self):
        return FakePixmap()


def test_run_mainwindow_smoke_switches_tabs_captures_screenshots_and_resizes(tmp_path):
    app = FakeApp()
    window = FakeMainWindow()
    options = MainWindowSmokeOptions(
        output_dir=tmp_path,
        switch_tabs=True,
        capture_screenshots=True,
        resize_viewports=("800x600", "390x844"),
        dialog_cancel=False,
    )

    evidence = run_mainwindow_smoke(
        options,
        app_factory=lambda: app,
        window_factory=lambda: window,
    )

    assert window.shown is True
    assert window.closed is True
    assert app.process_events_count >= 1
    assert evidence["missing_tabs"] == []
    assert evidence["switched_tabs"] == list(EXPECTED_MAINWINDOW_TAB_LABELS)
    assert [item["viewport"] for item in evidence["resize_evidence"]] == ["800x600", "390x844"]
    assert [item["requested_size"] for item in evidence["resize_evidence"]] == ["800x600", "390x844"]
    assert all(item["matches_requested"] is True for item in evidence["resize_evidence"])
    assert all(item["constrained_by_minimum"] is False for item in evidence["resize_evidence"])
    assert window.resize_calls == [(800, 600), (390, 844)]
    assert evidence["screenshots"]
    for screenshot in evidence["screenshots"]:
        assert Path(screenshot["path"]).exists()


def test_run_mainwindow_smoke_can_skip_optional_operations(tmp_path):
    window = FakeMainWindow()
    options = MainWindowSmokeOptions(
        output_dir=tmp_path,
        switch_tabs=False,
        capture_screenshots=False,
        resize_viewports=(),
        dialog_cancel=False,
    )

    evidence = run_mainwindow_smoke(
        options,
        app_factory=FakeApp,
        window_factory=lambda: window,
    )

    assert evidence["switched_tabs"] == []
    assert evidence["screenshots"] == []
    assert evidence["resize_evidence"] == []
    assert window.resize_calls == []


def test_run_mainwindow_smoke_records_dialog_cancel_probe(tmp_path):
    window = FakeMainWindow()
    options = MainWindowSmokeOptions(
        output_dir=tmp_path,
        switch_tabs=False,
        capture_screenshots=False,
        resize_viewports=(),
        dialog_cancel=True,
    )

    evidence = run_mainwindow_smoke(
        options,
        app_factory=FakeApp,
        window_factory=lambda: window,
    )

    assert evidence["dialog_cancel_evidence"] == [
        {
            "dialog": "update_force_merge_daily_price",
            "available": True,
            "cancelled": True,
            "destructive_action_called": False,
        }
    ]
    assert evidence["forbidden_actions_invoked"] == []

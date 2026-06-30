from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from qa.full_app_healthcheck.mainwindow_smoke import (
    build_mainwindow_smoke_evidence,
    collect_mainwindow_smoke_evidence,
    parse_viewport_spec,
)


@dataclass(frozen=True)
class MainWindowSmokeOptions:
    output_dir: Path
    switch_tabs: bool = False
    capture_screenshots: bool = False
    resize_viewports: tuple[str, ...] = ()
    dialog_cancel: bool = False


def run_mainwindow_smoke_in_subprocess(
    options: MainWindowSmokeOptions,
    *,
    python_executable: str | None = None,
    cwd: Path | None = None,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    output_dir = Path(options.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "evidence.json"
    project_root = cwd or Path(__file__).resolve().parents[2]
    command = [
        python_executable or sys.executable,
        "-m",
        "qa.full_app_healthcheck.mainwindow_smoke_child",
        "--output-dir",
        str(output_dir),
    ]
    if options.switch_tabs:
        command.append("--switch-tabs")
    if options.capture_screenshots:
        command.append("--screenshot")
    for viewport in options.resize_viewports:
        command.extend(("--resize", viewport))
    if options.dialog_cancel:
        command.append("--dialog-cancel")

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        command,
        cwd=str(project_root),
        env=env,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "MainWindow UI smoke subprocess failed "
            f"(returncode={completed.returncode}). stdout_tail={completed.stdout[-2000:]!r} "
            f"stderr_tail={completed.stderr[-2000:]!r}"
        )
    if not evidence_path.exists():
        raise AssertionError(f"MainWindow UI smoke subprocess did not write evidence: {evidence_path}")
    return json.loads(evidence_path.read_text(encoding="utf-8"))


def run_mainwindow_smoke(
    options: MainWindowSmokeOptions,
    *,
    app_factory: Callable[[], Any] | None = None,
    window_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    app = app_factory() if app_factory is not None else _ensure_qapplication()
    window = window_factory() if window_factory is not None else _create_mainwindow()
    options.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        window.show()
        _process_events(app)
        evidence = collect_mainwindow_smoke_evidence(window, switch_tabs=options.switch_tabs)
        if evidence["missing_tabs"]:
            raise AssertionError(f"MainWindow missing tabs: {evidence['missing_tabs']}")

        screenshots: list[dict[str, Any]] = []
        if options.capture_screenshots:
            screenshots.append(_capture_screenshot(window, options.output_dir, "startup"))

        resize_evidence: list[dict[str, Any]] = []
        for viewport_spec in options.resize_viewports:
            viewport = parse_viewport_spec(viewport_spec)
            window.resize(viewport.width, viewport.height)
            _process_events(app)
            actual_label = _window_size_label(window)
            matches_requested = actual_label == viewport.label
            resize_evidence.append({
                "viewport": viewport.label,
                "requested_size": viewport.label,
                "actual_size": actual_label,
                "matches_requested": matches_requested,
                "constrained_by_minimum": not matches_requested,
            })
            if options.capture_screenshots:
                screenshots.append(_capture_screenshot(window, options.output_dir, f"resize_{viewport.label}"))

        dialog_cancel_evidence: list[dict[str, Any]] = []
        forbidden_actions_invoked: list[str] = []
        if options.dialog_cancel:
            dialog_cancel_evidence.append(_probe_update_force_merge_cancel(window))
            if dialog_cancel_evidence[-1].get("destructive_action_called"):
                forbidden_actions_invoked.append("update_force_merge_daily_price")

        if forbidden_actions_invoked:
            raise AssertionError(f"Forbidden UI smoke actions invoked: {forbidden_actions_invoked}")

        return build_mainwindow_smoke_evidence(
            window_title=evidence["window_title"],
            tab_labels=evidence["tab_labels"],
            missing_tabs=evidence["missing_tabs"],
            switched_tabs=evidence["switched_tabs"],
            screenshots=screenshots,
            resize_evidence=resize_evidence,
            dialog_cancel_evidence=dialog_cancel_evidence,
            forbidden_actions_invoked=forbidden_actions_invoked,
        )
    finally:
        close = getattr(window, "close", None)
        if callable(close):
            close()
        _process_events(app)
        _quit_app(app)
        _process_events(app)


def _ensure_qapplication() -> Any:
    import sys

    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def _create_mainwindow() -> Any:
    from ui_qt.main import MainWindow, apply_app_theme

    app = _ensure_qapplication()
    apply_app_theme(app)
    return MainWindow()


def _process_events(app: Any) -> None:
    process_events = getattr(app, "processEvents", None)
    if callable(process_events):
        process_events()


def _quit_app(app: Any) -> None:
    quit_app = getattr(app, "quit", None)
    if callable(quit_app):
        quit_app()


def _capture_screenshot(window: Any, output_dir: Path, label: str) -> dict[str, Any]:
    screenshot_dir = output_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    path = screenshot_dir / f"{label}.png"
    pixmap = window.grab()
    if pixmap.isNull():
        raise AssertionError(f"Screenshot failed for {label}: pixmap is null")
    saved = pixmap.save(str(path))
    if saved is False:
        raise AssertionError(f"Screenshot failed for {label}: save returned False")
    return {"label": label, "path": str(path)}


def _window_size_label(window: Any) -> str:
    size = window.size()
    return f"{int(size.width())}x{int(size.height())}"


def _probe_update_force_merge_cancel(window: Any) -> dict[str, Any]:
    update_view = _find_update_view(window)
    if update_view is None or not callable(getattr(update_view, "_execute_force_merge", None)):
        return {
            "dialog": "update_force_merge_daily_price",
            "available": False,
            "cancelled": False,
            "destructive_action_called": False,
        }

    destructive_action_called = False
    original_do_merge = getattr(update_view, "_do_merge", None)

    def blocking_do_merge(*args: Any, **kwargs: Any) -> None:
        nonlocal destructive_action_called
        destructive_action_called = True

    if callable(original_do_merge):
        setattr(update_view, "_do_merge", blocking_do_merge)

    update_view_module = None
    original_message_box = None
    try:
        import ui_qt.views.update_view as update_view_module  # type: ignore[no-redef]

        original_message_box = update_view_module.QMessageBox
        update_view_module.QMessageBox = _build_cancel_message_box(original_message_box)
        update_view._execute_force_merge()
    finally:
        if callable(original_do_merge):
            setattr(update_view, "_do_merge", original_do_merge)
        if update_view_module is not None and original_message_box is not None:
            update_view_module.QMessageBox = original_message_box

    return {
        "dialog": "update_force_merge_daily_price",
        "available": True,
        "cancelled": not destructive_action_called,
        "destructive_action_called": destructive_action_called,
    }


def _find_update_view(window: Any) -> Any | None:
    direct = getattr(window, "update_view", None)
    if direct is not None:
        return direct
    for attr_name in ("tabs", "tab_widget"):
        tabs = getattr(window, attr_name, None)
        widget = getattr(tabs, "widget", None)
        if callable(widget):
            try:
                return widget(0)
            except Exception:
                continue
    return None


def _build_cancel_message_box(base_message_box: Any) -> type:
    class CancelMessageBox(base_message_box):  # type: ignore[misc, valid-type]
        def exec(self) -> Any:
            self._clicked_button = None
            for button in self.buttons():
                if "取消" in button.text():
                    self._clicked_button = button
                    break
            return getattr(base_message_box, "Cancel", 0)

        def clickedButton(self) -> Any:
            return getattr(self, "_clicked_button", None)

    return CancelMessageBox

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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
            resize_evidence.append({
                "viewport": viewport.label,
                "actual_size": actual_label,
            })
            if options.capture_screenshots:
                screenshots.append(_capture_screenshot(window, options.output_dir, f"resize_{viewport.label}"))

        return build_mainwindow_smoke_evidence(
            window_title=evidence["window_title"],
            tab_labels=evidence["tab_labels"],
            missing_tabs=evidence["missing_tabs"],
            switched_tabs=evidence["switched_tabs"],
            screenshots=screenshots,
            resize_evidence=resize_evidence,
            dialog_cancel_evidence=[],
            forbidden_actions_invoked=[],
        )
    finally:
        close = getattr(window, "close", None)
        if callable(close):
            close()
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
